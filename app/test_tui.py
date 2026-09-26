import importlib.util
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
        self.assertLessEqual(tv.display_width(row.split("\t")[1]), 68)
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

    def test_channel_names_and_links_share_the_same_validation(self):
        for value in [" Alpha ", "@Alpha", "https://twitch.tv/Alpha?ref=share", "https://www.twitch.tv/Alpha/", "twitch.tv/Alpha", "HTTPS://TWITCH.TV/Alpha"]:
            self.assertEqual(tv.normalize_channel(value), "alpha")
        for value in ["", "invalid name", "https://example.com/alpha", "alpha/other", "https://twitch.tv/"]:
            with self.assertRaises(ValueError):
                tv.normalize_channel(value)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
