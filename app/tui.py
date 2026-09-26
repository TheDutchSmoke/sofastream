#!/usr/bin/env python3
"""Render tv menu rows with public Twitch metadata (no personal token needed).

Twitch's web GraphQL endpoint is also used by Streamlink, but isn't a stable
public API contract. If it changes or is unreachable, keep the menu usable.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from urllib.parse import urlsplit


ENDPOINT = "https://gql.twitch.tv/gql"
# Public web client identifier, also used by Streamlink's Twitch plugin.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
CACHE_SECONDS = 30
ACTIONS = (
    ("action:other", "↗", "Andere streamer openen"),
    ("action:add", "+", "Favoriet toevoegen"),
    ("action:remove", "−", "Kanaal uit tv verwijderen"),
    ("action:import", "↓", "GUI-follows importeren"),
    ("action:status", "●", "Apple TV-stream: status"),
    ("action:stop", "■", "Apple TV-stream stoppen"),
    ("action:log", "≡", "Streamlog bekijken"),
    ("action:pair", "⌘", "Automatisch starten koppelen (pincode op tv)"),
)
COLORS = {"purple": 141, "green": 84, "gold": 220, "muted": 245,
          "white": 255, "cyan": 117}


def clean(value):
    """Keep remote text on one terminal row, with no control sequences."""
    text = "".join(c if not unicodedata.category(c).startswith("C") else " "
                   for c in str(value))
    return " ".join(text.split())


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
    if result.returncode or not result.stdout.strip().startswith(("http://", "https://")):
        raise ValueError(f"{login} is offline of niet bereikbaar. Je huidige stream blijft ongewijzigd.")


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
                and (item.get("game") is None or isinstance(item.get("game"), str))}
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


def fetch_status(channels):
    fields = " ".join(
        f"c{i}: user(login: {json.dumps(login)}) "
        "{ stream { type viewersCount game { name } } }"
        for i, login in enumerate(channels)
    )
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--connect-timeout", "2",
         "--max-time", "6", ENDPOINT, "-H", f"Client-ID: {CLIENT_ID}",
         "-H", "Content-Type: application/json", "--data-binary", "@-"],
        input=json.dumps({"query": "query { " + fields + " }"}),
        text=True, capture_output=True, timeout=7, check=True,
    )
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("Twitch query failed")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Twitch response has no data")
    statuses = {}
    for i, login in enumerate(channels):
        key = f"c{i}"
        if key not in data:
            continue
        user = data[key]
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
    return cache


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
        return (f"Verversen niet volledig gelukt: {failed} kanalen zonder actuele status.\n"
                "Bekijk Status onbekend of probeer later opnieuw.")
    return f"Status bijgewerkt om {time.strftime('%H:%M:%S')}."


def display_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def fit(text, width, right=False):
    text = clean(text)
    if display_width(text) > width:
        clipped = ""
        for char in text:
            if display_width(clipped + char) > width - 1:
                break
            clipped += char
        text = clipped + "…"
    padding = " " * max(0, width - display_width(text))
    return padding + text if right else text + padding


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


def menu_rows(channels, statuses, priority=(), view="live", columns=100, color=False, notice=""):
    priority = set(priority)
    groups = grouped_channels(channels, statuses, priority)
    paint = lambda value, name: f"\033[38;5;{COLORS[name]}m{value}\033[0m" if color else value
    stars_count = len(priority.intersection(channels))
    stars_label = "favoriet" if stars_count == 1 else "favorieten"
    summary = (paint(f"● {len(groups['live'])} live", "green") + "   "
               + paint(f"○ {len(groups['offline'])} offline", "muted") + "   "
               + paint(f"★ {stars_count} {stars_label}", "gold"))
    if groups["unknown"]:
        summary += "   " + paint(f"? {len(groups['unknown'])} onbekend", "muted")
    yield "header\t" + summary
    notice = notice or "Kies een kanaal om af te spelen op Apple TV."
    for line in (notice.splitlines() + [""])[:2]:
        yield "header\t" + paint(fit(line, max(20, columns - 12)).rstrip(), "purple")
    visible = groups.get(view, [])
    channel_width = min(22, max(14, max((len(login) for login in visible), default=14)))
    game_width = max(12, min(46, columns - 12 - channel_width - 21))
    if view == "manage":
        yield "header\t" + paint("BEHEER   /   Kanalen en Apple TV", "purple")
        for key, symbol, label in ACTIONS:
            yield f"{key}\t{paint(symbol, 'purple')}  {label}"
    else:
        heading = ("   " + fit("KANAAL", channel_width) + "  "
                   + fit("GAME" if view == "live" else "STATUS", game_width)
                   + "  " + fit("KIJKERS", 11, right=True))
        yield "header\t" + paint(heading, "muted")
        for login in visible:
            item = statuses.get(login, {})
            star = "★" if login in priority else "·"
            if view == "live":
                detail = item.get("game") or "—"
                count = item.get("viewers")
                viewers = f"{count:,}".replace(",", ".") if type(count) is int and count >= 0 else "—"
            else:
                detail = ("Offline" if view == "offline" else
                          "Verouderde status" if item.get("stale") else
                          "Kanaal niet gevonden" if item.get("status") == "missing" else "Niet beschikbaar")
                viewers = "—"
            display = (paint(star, "gold" if login in priority else "muted") + "  "
                       + paint(fit(login, channel_width), "white") + "  "
                       + paint(fit(detail, game_width), "cyan" if view == "live" else "muted") + "  "
                       + paint(fit(viewers, 11, right=True), "green" if view == "live" else "muted"))
            yield f"channel:{login}\t{display}"
        if not visible:
            empty = "Er zijn nu geen live kanalen." if view == "live" else "Geen kanalen in dit overzicht."
            yield "noop\t" + paint(empty, "muted")
    if view != "live":
        yield "view:live\t" + paint("‹  Terug naar live", "purple")
    else:
        offline_count = len(groups['offline'])
        offline_label = "kanaal" if offline_count == 1 else "kanalen"
        yield f"view:offline\t{paint('○  Offline', 'muted')}  ·  {offline_count} {offline_label}  ›"
        if groups["unknown"]:
            yield f"view:unknown\t{paint('?  Status onbekend', 'muted')}  ·  {len(groups['unknown'])} kanalen  ›"
        yield "view:manage\t" + paint("≡  Beheer & Apple TV  ›", "purple")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Refresh status now")
    parser.add_argument("--favorites", type=Path,
                        default=Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv")) / "favorites")
    parser.add_argument("--cache", type=Path,
                        default=Path(os.environ.get("TV_CACHE_DIR", Path.home() / ".cache/tv")) / "stream-status.json")
    parser.add_argument("--priority", type=Path,
                        default=Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv")) / "priority-favorites")
    parser.add_argument("--view", choices=("live", "offline", "unknown", "manage"), default="live")
    parser.add_argument("--color", action="store_true")
    parser.add_argument("--render-after-action", action="store_true")
    parser.add_argument("--columns", type=int,
                        default=int(os.environ.get("TV_TUI_COLUMNS", shutil.get_terminal_size().columns)))
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--toggle-key")
    actions.add_argument("--add")
    actions.add_argument("--remove")
    actions.add_argument("--normalize-channel")
    actions.add_argument("--check-playable")
    args = parser.parse_args()
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
    for operation, value in (("toggle", args.toggle_key), ("add", args.add), ("remove", args.remove)):
        if value is not None:
            try:
                notice = update_channel(args.favorites, args.priority, operation, value)
            except (OSError, ValueError) as error:
                if not args.render_after_action:
                    parser.exit(1, f"{error}\n")
                notice = str(error)
            if not args.render_after_action:
                if notice:
                    print(notice)
                return
    channels = read_favorites(args.favorites)
    # Star changes should remain instant, even if Twitch is slow or unavailable.
    cached_only = args.render_after_action or (args.view == "manage" and not args.force)
    statuses = read_cache(args.cache) if cached_only else get_statuses(channels, args.cache, args.force)
    priority = read_favorites(args.priority)
    if args.force:
        notice = refresh_notice(channels, statuses)
    print("\n".join(menu_rows(channels, statuses, priority, args.view, args.columns, args.color, notice)))


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
