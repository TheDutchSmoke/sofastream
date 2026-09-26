"""Exercise the real zsh/fzf menu in an isolated PTY; never control playback."""

import codecs
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unicodedata


class Screen:
    """Small ANSI screen reader for locating visible fzf controls in this test."""

    def __init__(self, rows=32, columns=110):
        self.rows, self.columns = rows, columns
        self.cells = [[" "] * columns for _ in range(rows)]
        self.row = self.column = 0
        self.saved = (0, 0)
        self.pending = ""
        self.report_cursor = None
        self.mouse_enabled = False

    def feed(self, text):
        self.pending += text
        while self.pending:
            c = self.pending[0]
            if c == "\x1b":
                if len(self.pending) < 2:
                    return
                if self.pending[1] == "[":
                    match = re.match(r"\x1b\[([0-?]*)([ -/]*)([@-~])", self.pending)
                    if not match:
                        return
                    self.pending = self.pending[match.end():]
                    self.csi(match[1], match[3])
                    continue
                if self.pending[1] == "]":
                    match = re.match(r"\x1b\].*?(?:\x07|\x1b\\)", self.pending, re.S)
                    if not match:
                        return
                    self.pending = self.pending[match.end():]
                    continue
                count = 3 if self.pending[1] in "()" else 2
                if len(self.pending) < count:
                    return
                if self.pending[1] == "7":
                    self.saved = self.row, self.column
                elif self.pending[1] == "8":
                    self.row, self.column = self.saved
                self.pending = self.pending[count:]
                continue
            self.pending = self.pending[1:]
            if c == "\r":
                self.column = 0
            elif c == "\n":
                if self.row == self.rows - 1:
                    self.cells.pop(0)
                    self.cells.append([" "] * self.columns)
                else:
                    self.row += 1
            elif c == "\b":
                self.column = max(0, self.column - 1)
            elif ord(c) >= 32 and not unicodedata.combining(c):
                if self.column < self.columns:
                    self.cells[self.row][self.column] = c
                self.column = min(self.columns, self.column +
                                  (2 if unicodedata.east_asian_width(c) in "WF" else 1))

    def csi(self, arguments, command):
        if arguments == "?1000":
            self.mouse_enabled = command == "h"
        if arguments.startswith(("?", ">")):
            return
        args = [int(x or 0) for x in arguments.split(";")] if arguments else [0]
        n = args[0] or 1
        if command == "n" and args[0] == 6 and self.report_cursor:
            self.report_cursor(self.row + 1, self.column + 1)
        elif command == "A":
            self.row = max(0, self.row - n)
        elif command in ("B", "e"):
            self.row = min(self.rows - 1, self.row + n)
        elif command in ("C", "a"):
            self.column = min(self.columns - 1, self.column + n)
        elif command == "D":
            self.column = max(0, self.column - n)
        elif command in ("G", "`"):
            self.column = min(self.columns - 1, n - 1)
        elif command in ("H", "f"):
            self.row = min(self.rows - 1, n - 1)
            self.column = min(self.columns - 1, (args[1] or 1) - 1 if len(args) > 1 else 0)
        elif command == "K":
            start = self.column if args[0] == 0 else 0
            end = self.column + 1 if args[0] == 1 else self.columns
            self.cells[self.row][start:end] = [" "] * (end - start)
        elif command == "J":
            if args[0] in (2, 3):
                self.cells = [[" "] * self.columns for _ in range(self.rows)]
            elif args[0] == 0:
                self.cells[self.row][self.column:] = [" "] * (self.columns - self.column)
                for row in range(self.row + 1, self.rows):
                    self.cells[row] = [" "] * self.columns

    def lines(self):
        return ["".join(row) for row in self.cells]

    def locate(self, text):
        matches = [(row, line) for row, line in enumerate(self.lines())
                   if line.lstrip().startswith("│") and text in line]
        # A result message may repeat the channel/menu name. Click the list row.
        for row, line in sorted(matches, key=lambda item: not ('▸' in item[1] or '▌' in item[1])):
            return line.index(text) + 2, row + 1
        raise AssertionError(f"Control not visible: {text}\n" + "\n".join(self.lines()))


def main():
    home = Path.home()
    actual = Path(__file__).with_name("tui.py")
    source = Path(__file__).with_name("tv.zsh").read_text()
    menu = source[source.index("_tv_menu() {"):source.index("\ntv() {")]
    with tempfile.TemporaryDirectory(prefix="tv-interaction-") as directory:
        root = Path(directory)
        favorites, priority = root / "favorites", root / "priority"
        favorites.write_text("alpha\nbeta\nstar\nsleeper\n")
        priority.write_text("star\n")
        wrapper = root / "tui.py"
        offline_marker = root / 'network-failed'
        wrapper.write_text(f"""import importlib.util, sys
from pathlib import Path
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('tv_tui', {str(actual)!r})
tv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tv)
data = {{'alpha': {{'status':'live','viewers':15000,'game':'Minecraft'}}, 'beta': {{'status':'live','viewers':700,'game':'Chess'}}, 'star': {{'status':'live','viewers':100,'game':'Art'}}, 'sleeper': {{'status':'offline'}}}}
def fetch(channels):
    if Path({str(offline_marker)!r}).exists():
        raise OSError('Test: network unavailable')
    return {{login: data[login] for login in channels if login in data}}
tv.fetch_status = fetch
sys.argv += ['--favorites', {str(favorites)!r}, '--priority', {str(priority)!r}, '--cache', {str(root / 'cache')!r}]
tv.main()
""")
        menu = menu.replace('$TV_APP_DIR/tui.py', str(wrapper))
        menu = menu.replace('$TV_CONFIG_DIR/favorites', str(favorites))
        log = root / "stream.log"
        menu = menu.replace('/tmp/streamlink-tv.log', str(log))
        menu = menu.replace('/tmp/streamlink-tv.err', str(root / 'stream.err'))
        menu = menu.replace('node "$TV_APP_DIR/stream-status.mjs" --watch {q}', 'printf "Test: lokale streamstatus"')
        started = root / "started"
        script = root / "menu.zsh"
        profile = ""
        script.write_text(profile + menu + f"""
_tv_start() {{
    print -r -- "$1" >> {shlex.quote(str(started))}
    if [[ "$1" == beta ]]; then
        echo 'Test: starten mislukt.'
        return 1
    fi
    echo "Test: $1 gestart voor Apple TV."
}}
tv() {{
    case "$1" in
        status) print -r -- $'Test: streamstatus actief.\nTest: TV afspelen onbekend.';;
        stop) echo 'Test: stream gestopt.';;
        fav) echo 'Test: follows geimporteerd.';;
        *) return 1;;
    esac
}}
_tv_menu
""")
        master, slave = pty.openpty()
        columns = 80 if '--narrow' in sys.argv else 110
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, columns, 0, 0))
        env = {**os.environ, "TERM": "xterm-256color", "TV_APP_DIR": str(actual.parent), "TV_CONFIG_DIR": str(root), "TV_STREAM_LOG": str(log), "TV_STREAM_ERR": str(root/"stream.err"), "FZF_DEFAULT_OPTS": "--expect=enter --print-query --bind=enter:abort", "FZF_DEFAULT_OPTS_FILE": ""}
        process = subprocess.Popen(["/bin/zsh", "-f", str(script)], stdin=slave,
                                   stdout=slave, stderr=slave, env=env, start_new_session=True)
        os.close(slave)
        screen = Screen(columns=columns)
        screen.report_cursor = lambda row, col: os.write(master, f"\x1b[{row};{col}R".encode())
        decoder = codecs.getincrementaldecoder("utf-8")("replace")

        def pump(duration=0.25):
            until = time.monotonic() + duration
            while time.monotonic() < until:
                if select.select([master], [], [], max(0, until - time.monotonic()))[0]:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        return
                    screen.feed(decoder.decode(data))

        def visible(text, timeout=5):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                pump(0.1)
                if any(text in line for line in screen.lines()):
                    pump(0.15)
                    return
                if process.poll() is not None:
                    break
            raise AssertionError(f"Missing visible result: {text}\n" + "\n".join(screen.lines()))

        def click(text, button=0):
            x, y = screen.locate(text)
            os.write(master, f"\x1b[<{button};{x};{y}M".encode())
            pump(0.1)
            if screen.mouse_enabled:
                os.write(master, f"\x1b[<{button};{x};{y}m".encode())
            pump()

        try:
            visible("Minecraft")
            os.write(master, b"doesnotexist123\r")
            visible("Geen resultaten")
            assert process.poll() is None
            os.write(master, b"\x1b")
            visible("Minecraft")
            os.write(master, b"Beheer\r")
            visible("Andere streamer openen")
            click("Andere streamer openen")
            visible("Kanaal ›")
            os.write(master, b"partial\x1b")
            visible("Invoer geannuleerd.")
            assert not started.exists()
            click("Favoriet toevoegen")
            visible("Kanaal ›")
            os.write(master, b"\x03")
            visible("Invoer geannuleerd.")
            click("Favoriet toevoegen")
            visible("Kanaal ›")
            os.write(master, b"\r")
            visible("Invoer geannuleerd.")
            click("Favoriet toevoegen")
            visible("Kanaal ›")
            os.write(master, b"invalid name\r")
            visible("Gebruik een geldige Twitch-kanaalnaam")
            assert priority.read_text() == "star\n"
            click("Streamlog bekijken")
            visible("Nog geen Streamlink-log.")
            log.write_text('TEST_STREAM_LOG\n')
            click("Streamlog bekijken")
            visible("TEST_STREAM_LOG")
            os.write(master, b"q")
            visible("Andere streamer openen")
            os.write(master, b"Terug naar live\r")
            visible("Minecraft")
            os.write(master, b"Offline\n")
            visible("sleeper")
            os.write(master, b"\x1b")
            visible("Minecraft")
            click("alpha")
            visible("Test: alpha gestart voor Apple TV.")
            assert started.read_text().splitlines() == ["alpha"]

            click("star ", button=2)
            pump(0.5)
            assert priority.read_text() == "", priority.read_text()
            assert started.read_text().splitlines() == ["alpha"]
            click("[Favoriet]")
            pump(0.5)
            assert priority.read_text() == "star\n", priority.read_text() + '\n' + '\n'.join(screen.lines())
            click("[Verversen]")
            visible("Status bijgewerkt om")

            click("Offline")
            visible("sleeper")
            click("sleeper")
            visible("sleeper is offline.")
            assert started.read_text().splitlines() == ["alpha"]
            click("[Terug]")
            visible("Minecraft")

            click("Beheer & Apple TV")
            visible("Apple TV-stream: status")
            click("Apple TV-stream: status")
            visible("Test: streamstatus actief.")
            visible("Test: TV afspelen onbekend.")
            click("Apple TV-stream stoppen")
            visible("Test: stream gestopt.")
            click("GUI-follows importeren")
            visible("Test: follows geimporteerd.")
            click("Terug naar live")
            visible("Minecraft")

            click("beta")
            visible("Test: starten mislukt.")
            assert process.poll() is None

            os.write(master, b"star\r")
            visible("Test: star gestart voor Apple TV.")
            os.write(master, b"\x06")
            pump(0.5)
            assert priority.read_text() == ""
            os.write(master, b"\x12")
            visible("Status bijgewerkt om")
            click("Beheer & Apple TV")
            visible("Favoriet toevoegen")
            click("Favoriet toevoegen")
            visible("Kanaal ›")
            os.write(master, b"https://twitch.tv/BETA?ref=test\r")
            visible("beta als favoriet opgeslagen.")
            assert priority.read_text() == "beta\n"
            click("Favoriet toevoegen")
            visible("Kanaal ›")
            os.write(master, b"beta\r")
            visible("beta staat al bij je favorieten.")
            click("Kanaal uit tv verwijderen")
            visible("KANAAL VERWIJDEREN")
            os.write(master, b"\x1b")
            visible("BEHEER & APPLE TV")
            assert "beta" in favorites.read_text().splitlines()
            click("Kanaal uit tv verwijderen")
            visible("KANAAL VERWIJDEREN")
            click("beta")
            visible("beta verwijderd.")
            assert "beta" not in favorites.read_text().splitlines()
            assert priority.read_text() == ""
            os.write(master, b"\x1b")
            visible("Minecraft")
            offline_marker.touch()
            os.write(master, b"\x12")
            visible("Verversen niet volledig gelukt")
            click("?  Status onbekend")
            visible("Verouderde status")
            offline_marker.unlink()
            os.write(master, b"\x12")
            visible("Status bijgewerkt om")
            click("[Terug]")
            visible("Minecraft")
            favorites.write_text('')
            priority.write_text('')
            os.write(master, b"\x12")
            visible("Er zijn nu geen live kanalen.")
            os.write(master, b"\r")
            visible("Geen kanaal geselecteerd.")
            click("Beheer & Apple TV")
            visible("Kanaal uit tv verwijderen")
            click("Kanaal uit tv verwijderen")
            visible("Er zijn geen kanalen om te verwijderen.")
            click("[Terug]")
            visible("Er zijn nu geen live kanalen.")
            click("[Sluiten]")
            process.wait(timeout=4)
            assert process.returncode == 0
            print(f"PASS ({columns} columns): keyboard/mouse, cancelled/invalid input, empty search/list, favorites, refresh failure/recovery, navigation, status/stop/import, logs, closing.")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=4)
            os.close(master)


if __name__ == "__main__":
    main()
