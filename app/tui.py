#!/usr/bin/env python3
"""Render tv menu rows with public Twitch metadata (no personal token needed).

Twitch's web GraphQL endpoint is also used by Streamlink, but isn't a stable
public API contract. If it changes or is unreachable, keep the menu usable.
"""

import argparse
import calendar
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page import (CYAN, GREEN, RED, TEAL, WHITE, YELLOW, band, clean, clean_title,  # noqa: E402,F401
                  column_head, display_width, fit, leaders, nav_row, notice_rows, number, paint, plural, uptime)


ENDPOINT = "https://gql.twitch.tv/gql"
# Public web client identifier, also used by Streamlink's Twitch plugin.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
CACHE_SECONDS = 30
# Key, label and the page number you type to find the row (20x channels, 21x the TV stream).
ACTIONS = (
    ("action:other", "Andere streamer openen", 201),
    ("action:add", "Favoriet toevoegen", 202),
    ("action:remove", "Kanaal uit tv verwijderen", 203),
    ("action:import", "GUI-follows importeren", 204),
    ("action:status", "Apple TV-stream: status", 210),
    ("action:stop", "Apple TV-stream stoppen", 211),
    ("action:log", "Streamlog bekijken", 212),
    ("action:pair", "Koppelen voor automatisch starten (pincode op tv)", 220),
    ("action:settings", "Instellingen · Apple TV kiezen", 300),
)
TITLES = {"live": "LIVE NU", "offline": "OFFLINE", "unknown": "STATUS ONBEKEND", "manage": "BEHEER & APPLE TV",
          "remove": "KANAAL VERWIJDEREN", "other": "ANDERE STREAMER OPENEN", "add": "FAVORIET TOEVOEGEN"}
HINTS = {"live": "Kies een kanaal om af te spelen op Apple TV.",
         "offline": "Nu offline. Ctrl-F zet een ster aan of uit.",
         "unknown": "Geen actuele Twitch-status. Ctrl-R probeert het opnieuw.",
         "manage": "Beheer je kanalen, de tv-stream en de instellingen."}
ON_AIR = re.compile(r"NAAR TV\s+([a-z0-9_]{1,25})")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def normalize_channel(value):
    value = value.strip()
    if re.match(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/", value, re.I):
        url = urlsplit(value if "://" in value else "https://" + value)
        if url.hostname not in ("twitch.tv", "www.twitch.tv", "m.twitch.tv") or url.username:
            raise ValueError("Gebruik een Twitch-kanaalnaam of een Twitch-kanaallink.")
        value = url.path.strip("/").split("/", 1)[0]
    login = value.removeprefix("@").lower()
    if not re.fullmatch(r"[a-z0-9_]{1,25}", login):
        raise ValueError("Gebruik een geldige Twitch-kanaalnaam of Twitch-link.")
    return login


def check_playable(login):
    streamlink = shutil.which("streamlink")
    if not streamlink:
        raise ValueError("Streamlink niet gevonden.")
    try:
        result = subprocess.run([streamlink, "--loglevel", "none", "--stream-url", "--twitch-low-latency",
                                 f"https://www.twitch.tv/{login}", "best"],
                                capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        raise ValueError("Twitch reageert te traag. Je huidige stream blijft ongewijzigd.") from None
    if not result.returncode and result.stdout.strip().startswith(("http://", "https://")):
        return
    kept = "Je huidige stream blijft ongewijzigd."
    # Even with --loglevel none, Streamlink ends with one 'error: …' line.
    error = next((line.strip()[len("error:"):].strip()
                  for line in (result.stdout + "\n" + result.stderr).splitlines()
                  if line.strip().startswith("error:")), "")
    if "Unauthorized" in error:
        # check_playable passes no login, so this one comes from the user's own Streamlink config.
        raise ValueError("Twitch weigert de login uit je Streamlink-config (config.twitch): verlopen of ongeldig. "
                         f"Vernieuw of verwijder de regel twitch-api-header. {kept}")
    if error and "No playable streams" not in error:
        raise ValueError(f"Streamlink: {clean(error)} {kept}")
    raise ValueError(f"{login} is offline of niet bereikbaar. {kept}")


def read_favorites(path):
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    return list(dict.fromkeys(line.strip().lower() for line in lines
                             if re.fullmatch(r"[A-Za-z0-9_]{1,25}", line.strip())))


def read_cache(path):
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {}
        return {login: item for login, item in data.items()
                if isinstance(item, dict)
                and item.get("status") in ("live", "offline", "missing", "unknown")
                and isinstance(item.get("checked_at"), (int, float))
                and (item.get("viewers") is None
                     or type(item.get("viewers")) is int)
                and (item.get("game") is None or isinstance(item.get("game"), str))
                and (item.get("title") is None or isinstance(item.get("title"), str))
                and (item.get("started") is None or type(item.get("started")) in (int, float))}
    except (OSError, ValueError):
        return {}


def write_cache(path, data):
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                         prefix=".status-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
        os.replace(temporary, path)
    except OSError:
        pass  # A read-only cache must not prevent playback or menu actions.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def parse_time(value):
    """Twitch's createdAt (2026-11-19T19:03:12Z, UTC) as epoch seconds, or None."""
    if not isinstance(value, str):
        return None
    try:
        return calendar.timegm(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def fetch_status(channels):
    # One root field for the whole batch: Twitch rejects queries with more than
    # 15 aliased root fields, which made every channel "unknown".
    query = ("query($logins: [String!]) { users(logins: $logins) "
             "{ login stream { type viewersCount title createdAt game { name } } } }")
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--connect-timeout", "2",
         "--max-time", "6", ENDPOINT, "-H", f"Client-ID: {CLIENT_ID}",
         "-H", "Content-Type: application/json", "--data-binary", "@-"],
        input=json.dumps({"query": query, "variables": {"logins": list(channels)}}),
        text=True, capture_output=True, timeout=7, check=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("Twitch query failed")
    data = payload.get("data")
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, list):
        raise ValueError("Twitch response has no data")
    found = {user["login"].lower(): user for user in users
             if isinstance(user, dict) and isinstance(user.get("login"), str)}
    # Unknown logins come back as null in their own position.
    aligned = len(users) == len(channels)
    statuses = {}
    for i, login in enumerate(channels):
        if login in found:
            user = found[login]
        elif aligned and users[i] is None:
            user = None
        else:
            continue
        if user is None:
            statuses[login] = {"status": "missing"}
        elif isinstance(user, dict) and "stream" in user:
            stream = user["stream"]
            if stream is None:
                statuses[login] = {"status": "offline"}
            elif isinstance(stream, dict) and stream.get("type") == "live":
                viewers = stream.get("viewersCount")
                game = stream.get("game")
                statuses[login] = {
                    "status": "live",
                    "viewers": viewers if type(viewers) is int and viewers >= 0 else None,
                    "game": clean(game.get("name") or "—") if isinstance(game, dict) else "—",
                }
                # Only what Twitch sent: a reply without these gives the same dict as before.
                if isinstance(stream.get("title"), str):
                    statuses[login]["title"] = clean_title(stream["title"])
                started = parse_time(stream.get("createdAt"))
                if started is not None:
                    statuses[login]["started"] = started
    return statuses


def get_statuses(channels, cache_path, force=False):
    cache = read_cache(cache_path)
    now = time.time()
    pending = [login for login in channels
               if force or login not in cache
               or not 0 <= now - cache[login]["checked_at"] < CACHE_SECONDS]
    for offset in range(0, len(pending), 50):
        batch = pending[offset:offset + 50]
        try:
            fetched = fetch_status(batch)
        except (OSError, ValueError, subprocess.SubprocessError):
            fetched = {}
        for login in batch:
            if login in fetched:
                cache[login] = {**fetched[login], "checked_at": now, "stale": False}
            else:
                cache[login] = {**cache.get(login, {"status": "unknown"}),
                                "checked_at": now, "stale": True}
    if pending:
        write_cache(cache_path, {login: cache[login] for login in channels})
        if any(not cache[login]["stale"] for login in pending):
            write_stand(cache_path.parent / "tui-stand", now)
    return cache


def write_stand(path, moment):
    """The time of the Twitch snapshot, shown as 'stand HH:MM' on the search row."""
    try:
        path.write_text(time.strftime("%H:%M", time.localtime(moment)) + "\n")
    except OSError:
        pass


def save_channels(path, channels):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent,
                                         prefix=".channels-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write("".join(login + "\n" for login in sorted(set(channels))))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_channel(favorites, priority, operation, value):
    if operation == "toggle":
        if not value.startswith("channel:"):
            return "Selecteer eerst een kanaal om een ster aan of uit te zetten."
        value = value.removeprefix("channel:")
    login = normalize_channel(value)
    channels = set(read_favorites(favorites))
    stars = set(read_favorites(priority))
    if operation == "toggle":
        if login not in channels:
            return
        stars.symmetric_difference_update({login})
    elif operation == "add":
        if login in channels and login in stars:
            return f"★ {login} staat al bij je favorieten."
        channels.add(login)
        stars.add(login)
        save_channels(favorites, channels)
    elif operation == "remove":
        if login not in channels and login not in stars:
            return f"{login} staat niet in tv."
        channels.discard(login)
        stars.discard(login)
        save_channels(favorites, channels)
    else:
        raise ValueError("Onbekende kanaalactie.")
    save_channels(priority, stars)
    if operation == "add":
        return f"★ {login} als favoriet opgeslagen."
    if operation == "remove":
        return f"✓ {login} verwijderd."
    return f"★ {login}: favoriet {'aan' if login in stars else 'uit'}."


def refresh_notice(channels, statuses):
    failed = sum(bool(statuses.get(login, {}).get("stale")) for login in channels)
    if failed:
        return (f"Verversen niet volledig gelukt: {failed} kanalen zonder actuele status. "
                "Bekijk Status onbekend of probeer later opnieuw.")
    return f"Status bijgewerkt om {time.strftime('%H:%M:%S')}."


def grouped_channels(channels, statuses, priority):
    groups = {"live": [], "offline": [], "unknown": []}
    for login in channels:
        item = statuses.get(login, {})
        state = item.get("status")
        group = state if state in ("live", "offline") and not item.get("stale") else "unknown"
        groups[group].append(login)
    for group, logins in groups.items():
        def order(login):
            viewers = statuses.get(login, {}).get("viewers")
            count = viewers if type(viewers) is int and viewers >= 0 else -1
            return (login not in priority, -count if group == "live" else 0, login)
        logins.sort(key=order)
    return groups


def on_air_channel(label):
    """The channel the Mac sends to the TV, read from the stream row fzf shows."""
    match = ON_AIR.search(ANSI.sub("", label or ""))
    return match[1] if match else ""


def summary_forms(groups, stars):
    live, offline, unknown = (len(groups[name]) for name in ("live", "offline", "unknown"))
    word = "favoriet" if stars == 1 else "favorieten"
    tail = f"  ? {unknown} onbekend" if unknown else ""
    return [f"● {live} live  ○ {offline} offline  ★ {stars} {word}{tail}",
            f"● {live} live  ○ {offline} offline  ★ {stars}{tail}",
            f"● {live}  ○ {offline}  ★ {stars}" + (f"  ? {unknown}" if unknown else "")]


def channel_width(logins, width):
    cap = 14 if width < 58 else 18 if width < 70 else 22
    return min(cap, max(12, max((len(login) for login in logins), default=12)))


def live_geometry(width, logins, counts):
    """Column widths for the live list (DESIGN.md, Channel row). `width` is T."""
    cw = channel_width(logins, width)
    vw = max(7, max((len(count) for count in counts), default=7))
    wide, xwide = width >= 98, width >= 118
    middle = width - 5 - cw - 2 - 1 - vw - (8 if xwide else 0)
    gw = (44 if width >= 148 else 28 if xwide else 24) if wide else max(4, middle)
    tw = max(4, middle - gw - 2) if wide else 0
    return cw, vw, gw, tw, wide, xwide


def menu_rows(channels, statuses, priority=(), view="live", columns=100, color=False, notice="",
              kind=None, on_air="", notice_count=None, dev=False, now=None):
    """Rows for fzf: band, notice, column heads, then the list. `columns` is fzf's width."""
    width = max(20, columns - 2)
    now = time.time() if now is None else now
    priority = set(priority)
    groups = grouped_channels(channels, statuses, priority)
    stars = len(priority.intersection(channels))
    if view == "manage":
        word = "favoriet" if stars == 1 else "favorieten"
        right = [f"{len(channels)} {plural(len(channels))} in tv  ★ {stars} {word}",
                 f"{len(channels)} {plural(len(channels))}  ★ {stars}"]
    else:
        right = summary_forms(groups, stars)
    yield "header\t" + band(TITLES[view], right, width, color, dev=dev)
    hint = not notice
    if hint:
        notice = HINTS[view]
        if view == "live" and not channels:
            notice = "Nog geen kanalen. Voeg er een toe of importeer je follows."
        elif view == "live" and not groups["live"]:
            notice = "Er is nu niemand live. Ctrl-R ververst de Twitch-status."
    for line in notice_rows(notice, kind, width, color, notice_count, hint):
        yield "header\t" + line

    back = "view:live\t" + nav_row("‹", "Terug naar live", 101, width, color, glyph_fg=CYAN)
    if view == "manage":
        yield "header\t" + column_head("     " + fit("ACTIE", width - 11) + "PAGINA", color)
        for key, label, page in ACTIONS:
            yield f"{key}\t" + nav_row(" ", label, page, width, color)
        yield back
        return

    visible = groups[view]
    star = lambda login: paint("★", YELLOW, color) if login in priority else " "
    if view == "live":
        items = [statuses.get(login, {}) for login in visible]
        counts = [number(item.get("viewers")) for item in items]
        cw, vw, gw, tw, wide, xwide = live_geometry(width, visible, counts)
        head = "     " + fit("KANAAL", cw) + "  " + fit("GAME", gw)
        if wide:
            head += "  " + fit("TITEL", tw)
        head += " " + (fit("DUUR", 6, right=True) + "  " if xwide else "") + fit("KIJKERS", vw, right=True)
        yield "header\t" + column_head(head, color)
        for login, item, count in zip(visible, items, counts):
            playing = login == on_air
            row = (paint("▶", GREEN, color) if playing else " ") + " " + star(login) + "  "
            row += paint(fit(login, cw), WHITE, color, bold=playing) + "  "
            if wide:
                row += paint(fit(item.get("game") or "—", gw), CYAN, color) + "  "
                row += leaders(clean_title(item.get("title") or "") or "—", tw, WHITE, color)
            else:
                row += leaders(item.get("game") or "—", gw, CYAN, color)
            row += " "
            if xwide:
                started = item.get("started")
                minutes = int(now - started) // 60 if type(started) in (int, float) and started <= now else None
                row += paint(fit(uptime(minutes), 6, right=True), CYAN, color) + "  "
            yield f"channel:{login}\t" + row + paint(fit(count, vw, right=True), YELLOW, color)
        if not visible:
            yield "noop\t     " + paint("Er zijn nu geen live kanalen.", WHITE, color)
            if not channels:
                yield "action:add\t" + nav_row("+", "Favoriet toevoegen", 202, width, color, glyph_fg=CYAN)
                yield "action:import\t" + nav_row("↓", "GUI-follows importeren", 204, width, color, glyph_fg=CYAN)
        offline = len(groups["offline"])
        yield "view:offline\t" + nav_row("○", f"Offline · {offline} {plural(offline)}", 102, width, color)
        if groups["unknown"]:
            unknown = len(groups["unknown"])
            yield "view:unknown\t" + nav_row("?", f"Status onbekend · {unknown} {plural(unknown)}", 103, width, color)
        yield "view:manage\t" + nav_row("≡", "Beheer & Apple TV", 200, width, color)
        return

    cw = channel_width(visible, width)
    yield "header\t" + column_head("     " + (fit("KANAAL", cw) + "  STATUS" if view == "unknown" else "KANAAL"), color)
    for login in visible:
        row = "  " + star(login) + "  " + paint(fit(login, cw), WHITE, color)
        if view == "unknown":
            item = statuses.get(login, {})
            detail = ("Verouderde status" if item.get("stale") else
                      "Kanaal niet gevonden" if item.get("status") == "missing" else "Niet beschikbaar")
            row += "  " + paint(detail, CYAN, color)
        yield f"channel:{login}\t" + row.rstrip()
    if not visible:
        yield "noop\t     " + paint("Geen kanalen in dit overzicht.", WHITE, color)
    yield back


def remove_rows(channels, statuses, priority=(), columns=100, color=False, dev=False):
    """Page 203: the first field stays the bare login, as the picker returns it."""
    width = max(20, columns - 2)
    priority = set(priority)
    total = f"{len(channels)} {plural(len(channels))} in tv"
    yield "header\t" + band(TITLES["remove"], [total], width, color, danger=True, dev=dev)
    yield "header\t" + paint(fit("Enter of klik verwijdert het kanaal en zijn ster uit tv.", width).rstrip(), WHITE, color)
    yield "header\t" + paint(fit("Je Twitch-follows veranderen niet.", width).rstrip(), TEAL, color)
    cw = channel_width(channels, width)
    yield "header\t" + column_head("     " + fit("KANAAL", cw) + "  STATUS", color)
    for login in sorted(channels):
        item = statuses.get(login, {})
        state = item.get("status")
        word = "onbekend" if item.get("stale") or state not in ("live", "offline") else state
        yield (f"{login}\t  " + (paint("★", YELLOW, color) if login in priority else " ") + "  "
               + paint(fit(login, cw), WHITE, color) + "  " + paint(word, CYAN if word == "live" else TEAL, color))


def dialog_header(dialog, query="", columns=100, color=False, dev=False):
    """Pages 201 and 202: band, instruction and a live check of what the input becomes."""
    width = max(20, columns - 2)
    lines = [band(TITLES[dialog], [], width, color, dev=dev),
             paint("Typ een Twitch-kanaalnaam of plak een Twitch-link.", WHITE, color)]
    if not query.strip():
        lines.append("")
    else:
        try:
            login = normalize_channel(query)
            lines.append(paint("→ twitch.tv/", TEAL, color) + paint(login, GREEN, color, bold=True))
        except ValueError:
            lines.append(paint("✕ Geen geldige kanaalnaam of Twitch-link.", RED, color))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Refresh status now")
    parser.add_argument("--favorites", type=Path,
                        default=Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv")) / "favorites")
    parser.add_argument("--cache", type=Path,
                        default=Path(os.environ.get("TV_CACHE_DIR", Path.home() / ".cache/tv")) / "stream-status.json")
    parser.add_argument("--priority", type=Path,
                        default=Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv")) / "priority-favorites")
    parser.add_argument("--view", choices=("live", "offline", "unknown", "manage", "remove"), default="live")
    parser.add_argument("--color", action="store_true")
    parser.add_argument("--render-after-action", action="store_true")
    # fzf passes its own width ($FZF_COLUMNS); an empty value falls back to the first-render width.
    parser.add_argument("--columns", default="")
    parser.add_argument("--dialog", choices=("other", "add"))
    parser.add_argument("--query", default="")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--toggle-key")
    actions.add_argument("--add")
    actions.add_argument("--remove")
    actions.add_argument("--normalize-channel")
    actions.add_argument("--check-playable")
    args = parser.parse_args()
    columns = next((int(value) for value in (args.columns, os.environ.get("TV_TUI_COLUMNS", ""))
                    if value.isdigit() and int(value) > 0), shutil.get_terminal_size().columns)
    dev = os.environ.get("TV_DEV_MODE") == "1"
    color = args.color and not os.environ.get("NO_COLOR")  # https://no-color.org
    if args.dialog:
        print(dialog_header(args.dialog, args.query, columns, color, dev))
        return
    if args.normalize_channel is not None or args.check_playable is not None:
        try:
            login = normalize_channel(args.normalize_channel if args.normalize_channel is not None else args.check_playable)
            if args.check_playable is not None:
                check_playable(login)
            else:
                print(login)
        except (OSError, ValueError) as error:
            parser.exit(1, f"{error}\n")
        return
    notice = os.environ.get("TV_TUI_NOTICE", "")
    kind = os.environ.get("TV_TUI_NOTICE_KIND") or None
    kind = kind if kind in ("ok", "error", "info") else None
    for operation, value in (("toggle", args.toggle_key), ("add", args.add), ("remove", args.remove)):
        if value is not None:
            kind = None  # a fresh result replaces the previous message and its kind
            try:
                notice = update_channel(args.favorites, args.priority, operation, value) or ""
            except (OSError, ValueError) as error:
                if not args.render_after_action:
                    parser.exit(1, f"{error}\n")
                notice, kind = str(error), "error"
            if not args.render_after_action:
                if notice:
                    print(notice)
                return
    channels = read_favorites(args.favorites)
    # Star changes should remain instant, even if Twitch is slow or unavailable.
    cached_only = args.render_after_action or (args.view in ("manage", "remove") and not args.force)
    statuses = read_cache(args.cache) if cached_only else get_statuses(channels, args.cache, args.force)
    priority = read_favorites(args.priority)
    if args.view == "remove":
        print("\n".join(remove_rows(channels, statuses, priority, columns, color, dev)))
        return
    if args.force:
        notice = refresh_notice(channels, statuses)
        kind = "error" if "niet volledig" in notice else "info"
    rows = os.environ.get("TV_TUI_NOTICE_ROWS", "")
    count = min(4, max(2, int(rows))) if rows.isdigit() else None
    on_air = on_air_channel(os.environ.get("FZF_INPUT_LABEL", ""))
    print("\n".join(menu_rows(channels, statuses, priority, args.view, columns, color, notice,
                              kind, on_air, count, dev)))


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
