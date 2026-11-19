import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("tv_tui", Path(__file__).with_name("tui.py"))
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)


class TuiTests(unittest.TestCase):
    def setUp(self):
        self.channels = ["low", "high", "star", "offline", "stale", "unknown"]
        self.statuses = {
            "low": {"status": "live", "viewers": 10, "game": "Chess"},
            "high": {"status": "live", "viewers": 9999, "game": "Minecraft"},
            "star": {"status": "live", "viewers": 0, "game": "Art"},
            "offline": {"status": "offline"},
            "stale": {"status": "live", "viewers": 20000, "stale": True},
        }

    def keys(self, view="live", stars=("star",)):
        return [row.split("\t")[0] for row in tv.menu_rows(self.channels, self.statuses, stars, view)]

    def test_live_priority_then_viewer_count(self):
        live = [key for key in self.keys() if key.startswith("channel:")]
        self.assertEqual(live, ["channel:star", "channel:high", "channel:low"])
        without_stars = [key for key in self.keys(stars=()) if key.startswith("channel:")]
        self.assertEqual(without_stars, ["channel:high", "channel:low", "channel:star"])

    def test_offline_and_unverified_have_separate_views(self):
        self.assertIn("view:offline", self.keys())
        self.assertNotIn("channel:offline", self.keys())
        self.assertEqual([k for k in self.keys("offline") if k.startswith("channel:")], ["channel:offline"])
        self.assertEqual([k for k in self.keys("unknown") if k.startswith("channel:")], ["channel:stale", "channel:unknown"])
        self.assertIn("view:live", self.keys("offline"))

    def test_offline_star_never_displaces_live_channels(self):
        self.assertNotIn("channel:offline", self.keys(stars=("offline",)))
        self.assertEqual(tv.grouped_channels(self.channels, self.statuses, {"offline"})["live"], ["high", "low", "star"])

    def test_toggling_a_star_preserves_followed_channels(self):
        with tempfile.TemporaryDirectory() as directory:
            favorites, priority = Path(directory) / "favorites", Path(directory) / "priority"
            favorites.write_text("one\ntwo\n")
            tv.update_channel(favorites, priority, "toggle", "channel:two")
            self.assertEqual(tv.read_favorites(priority), ["two"])
            self.assertEqual(favorites.read_text(), "one\ntwo\n")
            tv.update_channel(favorites, priority, "toggle", "channel:two")
            self.assertEqual(tv.read_favorites(priority), [])
            self.assertEqual(favorites.read_text(), "one\ntwo\n")
            tv.update_channel(favorites, priority, "toggle", "view:offline")
            self.assertEqual(tv.read_favorites(priority), [])

    def test_add_remove_and_reimport_do_not_star_every_follow(self):
        with tempfile.TemporaryDirectory() as directory:
            favorites, priority = Path(directory) / "favorites", Path(directory) / "priority"
            tv.update_channel(favorites, priority, "add", "https://www.twitch.tv/One/")
            self.assertEqual(tv.read_favorites(favorites), ["one"])
            self.assertEqual(tv.read_favorites(priority), ["one"])
            # Imports only update the followed-channel file.
            tv.save_channels(favorites, ["one", "two"])
            self.assertEqual(tv.read_favorites(priority), ["one"])
            tv.update_channel(favorites, priority, "remove", "one")
            self.assertEqual(tv.read_favorites(favorites), ["two"])
            self.assertEqual(tv.read_favorites(priority), [])

    def test_alignment_and_remote_text_are_safe(self):
        self.statuses["high"]["game"] = "長いゲーム\t\n\x1b[2J" * 10
        row = next(row for row in tv.menu_rows(self.channels, self.statuses, columns=80) if row.startswith("channel:high\t"))
        self.assertEqual(row.count("\t"), 1)
        self.assertNotIn("\x1b", row)
        # Rows are fzf's width minus the two pointer columns; there is no frame any more.
        self.assertLessEqual(tv.display_width(row.split("\t")[1]), 78)
        self.assertIn("9.999", row)

    def test_real_fzf_preserves_keys_and_priority_order(self):
        rows = "\n".join(tv.menu_rows(self.channels, self.statuses, ["star"], color=True))
        result = subprocess.run(["fzf", "--ansi", "--no-sort", "--header-lines=4", "--delimiter=\t", "--with-nth=2..", "--accept-nth=1", "--filter=Minecraft"], input=rows, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout, "channel:high\n")

    def test_stream_and_tv_status_remain_separately_visible(self):
        notice = "Streamlink: actief · star · PID 123.\nApple TV: afspelen onbekend · VLC-bediening niet bereikbaar."
        rows = list(tv.menu_rows(self.channels, self.statuses, notice=notice, columns=80))
        self.assertEqual(rows[1], "header\t" + notice.splitlines()[0])
        self.assertEqual(rows[2], "header\t" + notice.splitlines()[1])
        self.assertEqual(sum(row.startswith("header\t") for row in rows), 4)

    def test_playable_check_names_streamlink_failures(self):
        """Streamlink 8.6.3 prints its fatal error as one 'error: …' line on stdout, also with --loglevel none."""
        cases = [
            ('print -r -- "https://video.example/playlist.m3u8"', 0, None),
            ('print -r -- "error: No playable streams found on this URL: https://www.twitch.tv/star"', 1, "star is offline"),
            ('print -r -- \'error: Unauthorized: The "Authorization" token is invalid.\'', 1, "login uit je Streamlink-config"),
            ('print -r -- "error: unrecognized arguments: --twitch-low-latency"', 2, "Streamlink: unrecognized arguments"),
            ('print -r -- "error: Unable to open URL: https://gql.twitch.tv (Connection refused)" >&2', 1, "Streamlink: Unable to open URL"),
            ('exit 1', 1, "star is offline"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            fake = Path(folder) / "streamlink"
            for body, code, expected in cases:
                fake.write_text(f"#!/bin/zsh -f\n{body}\nexit {code}\n")
                fake.chmod(0o755)
                with self.subTest(body=body), patch.dict("os.environ", {"PATH": f"{folder}:/usr/bin:/bin"}):
                    if expected is None:
                        tv.check_playable("star")
                        continue
                    with self.assertRaises(ValueError) as caught:
                        tv.check_playable("star")
                    self.assertIn(expected, str(caught.exception))
                    self.assertIn("Je huidige stream blijft ongewijzigd.", str(caught.exception))

    def test_channel_names_and_links_share_the_same_validation(self):
        for value in [" Alpha ", "@Alpha", "https://twitch.tv/Alpha?ref=share", "https://www.twitch.tv/Alpha/", "twitch.tv/Alpha", "HTTPS://TWITCH.TV/Alpha"]:
            self.assertEqual(tv.normalize_channel(value), "alpha")
        for value in ["", "invalid name", "https://example.com/alpha", "alpha/other", "https://twitch.tv/"]:
            with self.assertRaises(ValueError):
                tv.normalize_channel(value)

    def test_input_check_in_sh_matches_normalize_channel(self):
        """The page 201/202 check runs on every keystroke in sh; it must agree with Python."""
        values = [" Alpha ", "@Alpha", "https://twitch.tv/Alpha?ref=share", "https://www.twitch.tv/Alpha/",
                  "twitch.tv/Alpha", "HTTPS://TWITCH.TV/Alpha", "m.twitch.tv/al_pha#x", "twitch.tv/@alpha",
                  "invalid name", "https://example.com/alpha", "alpha/other", "https://twitch.tv/",
                  "http://alpha", "a" * 25, "a" * 26, "ålpha", "twitch.tv.evil.com/alpha"]
        for value in values:
            with self.subTest(value=value):
                result = subprocess.run(["sh", str(Path(__file__).with_name("tui-check.sh"))], text=True,
                                        capture_output=True, check=True,
                                        env={"FZF_QUERY": value, "TV_TUI_DIALOG_HEAD": "head", "NO_COLOR": "1",
                                             "PATH": "/usr/bin:/bin"})
                head, check = result.stdout.split("\n", 1)
                self.assertEqual(head, "head")
                try:
                    expected = "→ twitch.tv/" + tv.normalize_channel(value)
                except ValueError:
                    expected = "✕ Geen geldige kanaalnaam of Twitch-link."
                self.assertEqual(check, expected)

    def test_failed_refresh_preserves_previous_data_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            tv.write_cache(cache, {"star": {"status": "live", "viewers": 100, "checked_at": 0}})
            with patch.object(tv, "fetch_status", side_effect=OSError("offline")):
                statuses = tv.get_statuses(["star"], cache, force=True)
            self.assertEqual(statuses["star"]["viewers"], 100)
            self.assertTrue(statuses["star"]["stale"])
            self.assertIn("niet volledig gelukt", tv.refresh_notice(["star"], statuses))
            self.assertNotIn("bijgewerkt", tv.refresh_notice(["star"], statuses))
            self.assertEqual(tv.grouped_channels(["star"], statuses, ())['unknown'], ["star"])

    def test_star_toggle_never_waits_for_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'favorites').write_text("star\n")
            tv.write_cache(root / 'cache', {"star": {"status": "live", "viewers": 100, "checked_at": 0}})
            argv = ['tui.py', '--favorites', str(root/'favorites'), '--priority', str(root/'priority'), '--cache', str(root/'cache'), '--toggle-key', 'channel:star', '--render-after-action']
            with patch.object(sys, 'argv', argv), patch.object(tv, 'fetch_status', side_effect=AssertionError('Network used')), redirect_stdout(io.StringIO()) as output:
                tv.main()
            self.assertIn("favoriet aan", output.getvalue())
            self.assertEqual((root/'priority').read_text(), 'star\n')

    def twitch_reply(self, users):
        return subprocess.CompletedProcess([], 0, json.dumps({"data": {"users": users}}), "")

    def test_status_query_uses_one_root_field_for_a_full_batch(self):
        # Twitch rejects more than 15 aliased root fields; a batch of 50 must be one field.
        channels = [f"channel{i}" for i in range(50)]
        users = [{"login": login, "stream": None} for login in channels]
        with patch.object(tv.subprocess, "run", return_value=self.twitch_reply(users)) as run:
            statuses = tv.fetch_status(channels)
        request = json.loads(run.call_args.kwargs["input"])
        self.assertNotRegex(request["query"], r"\w+\s*:\s*users?\s*\(")  # no aliases
        self.assertEqual(request["query"].count("users("), 1)
        self.assertEqual(request["variables"]["logins"], channels)
        self.assertEqual({item["status"] for item in statuses.values()}, {"offline"})
        self.assertEqual(len(statuses), 50)

    def test_status_reply_maps_live_offline_and_missing(self):
        users = [{"login": "Live", "stream": {"type": "live", "viewersCount": 42, "game": {"name": "Chess\n"}}},
                 None,
                 {"login": "off", "stream": None}]
        with patch.object(tv.subprocess, "run", return_value=self.twitch_reply(users)):
            statuses = tv.fetch_status(["live", "gone", "off"])
        self.assertEqual(statuses["live"], {"status": "live", "viewers": 42, "game": "Chess"})
        self.assertEqual(statuses["gone"], {"status": "missing"})
        self.assertEqual(statuses["off"], {"status": "offline"})

    def test_title_and_start_are_kept_without_emoji(self):
        users = [{"login": "live", "stream": {"type": "live", "viewersCount": 1, "game": None,
                                              "title": "Major 🎉\tplayoffs ✨ nu", "createdAt": "2026-11-19T18:00:00Z"}}]
        with patch.object(tv.subprocess, "run", return_value=self.twitch_reply(users)):
            statuses = tv.fetch_status(["live"])
        self.assertEqual(statuses["live"]["title"], "Major playoffs nu")
        self.assertEqual(statuses["live"]["started"], 1795111200)

    def test_rows_never_exceed_the_width_fzf_gives_them(self):
        self.statuses["high"].update(title="Een heel lange titel " * 8, started=0)
        ansi = __import__("re").compile(r"\x1b\[[0-9;]*m")
        for columns in (60, 64, 88, 100, 120, 150):
            for view in ("live", "offline", "unknown", "manage"):
                for color in (False, True):
                    with self.subTest(columns=columns, view=view, color=color):
                        for row in tv.menu_rows(self.channels, self.statuses, ["star"], view, columns, color,
                                                "Een melding die zo lang is dat ze over meer regels moet " * 3,
                                                now=7200):
                            self.assertEqual(row.count("\t"), 1)
                            self.assertLessEqual(tv.display_width(ansi.sub("", row.split("\t")[1])), columns - 2)

    def test_wide_layouts_add_title_and_duration(self):
        self.statuses["high"].update(title="Speedrun", started=7200 - 134 * 60)
        row = lambda columns: next(r for r in tv.menu_rows(self.channels, self.statuses, columns=columns, now=7200)
                                   if r.startswith("channel:high\t"))
        self.assertNotIn("Speedrun", row(80))
        self.assertIn("Speedrun", row(100))
        self.assertNotIn("2u14", row(100))
        self.assertIn("2u14", row(120))

    def test_on_air_marker_follows_the_stream_row(self):
        label = "\x1b[38;5;46m▷ NAAR TV  \x1b[0m\x1b[1;38;5;231mhigh\x1b[0m\x1b[38;5;51m · 1080p60\x1b[0m "
        self.assertEqual(tv.on_air_channel(label), "high")
        self.assertEqual(tv.on_air_channel("■ GEEN STREAM "), "")
        rows = {r.split("\t")[0]: r.split("\t")[1] for r in tv.menu_rows(self.channels, self.statuses, on_air="high")
                if r.startswith("channel:")}
        self.assertTrue(rows["channel:high"].startswith("▶"))
        self.assertEqual([key for key, row in rows.items() if "▶" in row], ["channel:high"])

    def test_notice_kinds_wrap_without_losing_the_advice(self):
        message = ("VLC is nog niet klaar. Staat de profielkeuze in beeld? Zet op Apple TV onder Instellingen → "
                   "Profielen en accounts 'Kies profiel bij uitschakelen sluimerstand' uit. Controleer ook "
                   "Afspelen op afstand in VLC.")
        rows = [r.split("\t")[1] for r in tv.menu_rows(self.channels, self.statuses, notice=message, kind="error",
                                                       columns=64) if r.startswith("header\t")]
        self.assertEqual(len(rows), 6)  # band, four notice rows, column heads
        self.assertTrue(rows[1].startswith("✕ VLC is nog niet klaar."))
        self.assertIn("in VLC.", rows[4])
        self.assertEqual(tv.menu_rows(self.channels, self.statuses, notice="❌ Wisselen mislukt.", kind="error").__next__(),
                         next(tv.menu_rows(self.channels, self.statuses)))
        self.assertEqual(list(tv.menu_rows(self.channels, self.statuses, notice="❌ Wisselen mislukt.", kind="error"))[1],
                         "header\t✕ Wisselen mislukt.")

    def test_misaligned_status_reply_never_guesses_missing(self):
        with patch.object(tv.subprocess, "run", return_value=self.twitch_reply([None, {"login": "b", "stream": None}])):
            statuses = tv.fetch_status(["a", "b", "c"])
        self.assertEqual(statuses, {"b": {"status": "offline"}})

    def test_status_errors_keep_the_previous_cache(self):
        reply = subprocess.CompletedProcess([], 0, json.dumps({"errors": [{"message": "limit"}]}), "")
        with patch.object(tv.subprocess, "run", return_value=reply):
            with self.assertRaises(ValueError):
                tv.fetch_status(["a"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
