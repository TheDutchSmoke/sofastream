#!/usr/bin/env python3
"""SofaStream relay: one endless MPEG-TS stream for VLC on the Apple TV.

VLC on tvOS (3.0.24) opens a network URL with a short probe connection and then
connects again; it also does not recover once an item has ended. Streamlink's own
HTTP server accepted a single connection, so VLC's real connection found a closed
port. The relay serves any number of connections and keeps one stream running
while someone watches. A channel switch replaces the source inside that stream:

    stream.zsh (Streamlink: ad filtering, optional 2K login) -> ffmpeg -c copy to
    MPEG-TS -> PAT/PMT version per source, so VLC sets up the new codec -> viewers

The old source keeps playing until the new one delivers data. Without viewers the
relay ends (VLC closed the video), like the one-shot server did.

  relay.py serve --listen ADDR --port N --control SOCKET --stream-script PATH
                 --streamlink PATH --ffmpeg PATH --service NAME --channel C --hq 0|1
  relay.py send SOCKET status | switch CHANNEL HQ | stop
  relay.py query SOCKET          -> "channel pending viewers"
  relay.py wait SOCKET CHANNEL [SECONDS]
"""
import argparse
import collections
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PACKET = 188
CHUNK = PACKET * 64
BUFFER = 1_500_000  # about a second of 1440p60: a (re)connecting viewer gets it at once
PAT_PID, PMT_PID, VIDEO_PID = 0, 0x1000, 0x100  # ffmpeg's mpegts defaults; video is mapped first
CHANNEL = re.compile(r"[a-z0-9_]{1,25}")
QUALITY = re.compile(r"Opening stream: (\S+) \(")


def out(message):
    """The launchd job's stdout is the stream log; tv.zsh and the TUI read it."""
    print(message, flush=True)


def mpeg_crc32(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def pid_of(packets, start):
    return ((packets[start + 1] & 0x1F) << 8) | packets[start + 2]


def scan(packets):
    """The last video keyframe offset (random_access_indicator; ffmpeg also marks every
    audio frame, so only the video PID counts) and the last PAT and PMT packets."""
    keyframe = pat = pmt = None
    for start in range(0, len(packets) - PACKET + 1, PACKET):
        if packets[start] != 0x47:
            continue
        pid = pid_of(packets, start)
        if pid == VIDEO_PID and packets[start + 3] & 0x20 and packets[start + 4] and packets[start + 5] & 0x40:
            keyframe = start
        elif pid == PAT_PID and packets[start + 1] & 0x40:
            pat = packets[start:start + PACKET]
        elif pid == PMT_PID and packets[start + 1] & 0x40:
            pmt = packets[start:start + PACKET]
    return keyframe, pat, pmt


def set_table_version(packets, version):
    """Every ffmpeg starts PAT/PMT at version 0; after a switch a demuxer would keep the
    old codec (H.265 decoder fed H.264). Give each source its own table version, as
    broadcasters do when a programme changes, and fix the section CRC."""
    out_ = bytearray(packets)
    view = memoryview(out_)
    for start in range(0, len(out_) - PACKET + 1, PACKET):
        p = view[start:start + PACKET]
        pid = ((p[1] & 0x1F) << 8) | p[2]
        if p[0] != 0x47 or pid not in (PAT_PID, PMT_PID) or not p[1] & 0x40 or not p[3] & 0x10:
            continue
        offset = 4 + (1 + p[4] if p[3] & 0x20 else 0)
        if offset >= PACKET:
            continue
        section = offset + 1 + p[offset]
        if section + 8 > PACKET:
            continue
        end = section + 3 + (((p[section + 1] & 0x0F) << 8) | p[section + 2])
        if end > PACKET or end - 4 <= section + 5:
            continue
        p[section + 5] = (p[section + 5] & 0xC1) | ((version & 0x1F) << 1)
        p[end - 4:end] = mpeg_crc32(bytes(p[section:end - 4])).to_bytes(4, "big")
    view.release()
    return bytes(out_)


class Source:
    """One channel: stream.zsh (Streamlink) piped into an ffmpeg remux to MPEG-TS."""

    def __init__(self, relay, channel, hq, version):
        self.relay, self.channel, self.version = relay, channel, version
        self.quality = None
        self.stopped = False
        self.streamlink = subprocess.Popen(relay.source_command(channel, hq), stdin=subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.ffmpeg = subprocess.Popen(relay.ffmpeg_command(), stdin=self.streamlink.stdout,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.streamlink.stdout.close()
        threading.Thread(target=self._streamlink_log, daemon=True).start()
        threading.Thread(target=self._ffmpeg_log, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()

    def _streamlink_log(self):
        for raw in self.streamlink.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            match = QUALITY.search(line)
            if match:
                self.quality = match[1]
            out(line)

    def _ffmpeg_log(self):
        for raw in self.ffmpeg.stderr:
            out(f"[ffmpeg][{self.channel}] {raw.decode('utf-8', 'replace').rstrip()}")

    def _pump(self):
        carry = b""
        while True:
            data = self.ffmpeg.stdout.read(CHUNK)
            if not data:
                break
            data = carry + data
            whole = len(data) - len(data) % PACKET
            data, carry = data[:whole], data[whole:]
            if data:
                self.relay.feed(self, set_table_version(data, self.version))
        self.relay.ended(self)

    def stop(self):
        self.stopped = True
        for process in (self.streamlink, self.ffmpeg):
            if process.poll() is None:
                process.terminate()
        for process in (self.streamlink, self.ffmpeg):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


class Relay:
    def __init__(self, args):
        self.args = args
        self.cond = threading.Condition()
        self.recent = collections.deque()
        self.recent_bytes = 0
        self.keyframe = None  # (seq, offset) of the newest video keyframe in recent
        self.tables = (None, None)  # newest PAT and PMT of the current source
        self.seq = 0
        self.current = None
        self.pending = None
        self.version = 0
        self.viewers = 0
        self.connections = 0  # every GET since start; tells "VLC came and left" from "never came"
        self.had_viewer = False
        self.last_change = time.monotonic()
        self.closing = threading.Event()

    def source_command(self, channel, hq):
        a = self.args
        return ["/bin/zsh", "-f", a.stream_script, a.streamlink, hq, a.service,
                "--twitch-low-latency", "--stdout", f"https://www.twitch.tv/{channel}", "best"]

    def ffmpeg_command(self):
        # Video and audio only: the same PIDs for every source. Twitch's ID3 track is not needed.
        return [self.args.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
                "-mpegts_flags", "+initial_discontinuity", "-f", "mpegts", "pipe:1"]

    def switch(self, channel, hq):
        with self.cond:
            if self.closing.is_set():
                return False
            self.version = self.version % 31 + 1
            previous, self.pending = self.pending, Source(self, channel, hq, self.version)
        out(f"[relay][info] Wissel naar {channel}")
        if previous:
            threading.Thread(target=previous.stop, daemon=True).start()
        return True

    def feed(self, source, data):
        replaced = None
        with self.cond:
            if source is self.pending:
                replaced, self.current, self.pending = self.current, source, None
                self.recent.clear()
                self.recent_bytes = 0
                self.keyframe = None
                self.tables = (None, None)
                out(f"[relay][info] Bron: {source.channel}" + (f" · {source.quality}" if source.quality else ""))
            elif source is not self.current:
                return
            self.seq += 1
            self.recent.append((self.seq, data))
            self.recent_bytes += len(data)
            keyframe, pat, pmt = scan(data)
            if keyframe is not None:
                self.keyframe = (self.seq, keyframe)
            self.tables = (pat or self.tables[0], pmt or self.tables[1])
            while self.recent_bytes > BUFFER and len(self.recent) > 1:
                dropped, chunk = self.recent.popleft()
                self.recent_bytes -= len(chunk)
                if self.keyframe and self.keyframe[0] == dropped:
                    self.keyframe = None
            self.cond.notify_all()
        if replaced:
            threading.Thread(target=replaced.stop, daemon=True).start()

    def ended(self, source):
        with self.cond:
            if source.stopped or self.closing.is_set():
                return
            if source is self.pending:
                self.pending = None
                if self.current:
                    out(f"[relay][warning] {source.channel} start niet; {self.current.channel} blijft spelen.")
                    return
            elif source is self.current:
                self.current = None
                if self.pending:
                    return
            else:
                return
        out(f"[relay][info] Stream ended ({source.channel})")
        self.shutdown()

    def start_point(self):
        """Where a (re)connecting viewer starts: the tables plus the newest keyframe, so it
        decodes at once and as close to live as the source allows."""
        with self.cond:
            if self.keyframe and all(self.tables):
                seq, offset = self.keyframe
                chunk = next((d for n, d in self.recent if n == seq), None)
                if chunk is not None:
                    return self.tables[0] + self.tables[1] + chunk[offset:], seq
            return b"", (self.recent[0][0] - 1 if self.recent else self.seq)

    def status(self):
        with self.cond:
            current = self.current
            return {"channel": current.channel if current else None,
                    "quality": current.quality if current else None,
                    "pending": self.pending.channel if self.pending else None,
                    "viewers": self.viewers, "connections": self.connections, "path": self.args.path}

    def viewer(self, joined):
        with self.cond:
            self.viewers += 1 if joined else -1
            self.connections += 1 if joined else 0
            self.had_viewer = self.had_viewer or joined
            self.last_change = time.monotonic()

    def watch_idle(self):
        """End without viewers: none at all after --idle-first, or none again after --idle-after.
        'HTTP connection closed' marks a real departure (a probe reconnects at once)."""
        reported = False
        while not self.closing.wait(0.5):
            with self.cond:
                quiet = time.monotonic() - self.last_change if self.viewers == 0 else 0
                had = self.had_viewer
            if had and quiet >= 3 and not reported:
                out("[relay][info] HTTP connection closed")
                reported = True
            elif quiet == 0:
                reported = False
            limit = self.args.idle_after if had else self.args.idle_first
            if quiet >= limit:
                out("[relay][info] Geen kijker meer; relay gestopt.")
                self.shutdown()

    def shutdown(self):
        if self.closing.is_set():
            return
        self.closing.set()
        with self.cond:
            sources = [s for s in (self.current, self.pending) if s]
            self.cond.notify_all()
        for source in sources:
            source.stop()


def viewer_handler(relay):
    class Viewer(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_HEAD(self):
            self._headers()

        def _headers(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

        def do_GET(self):
            out(f"[relay][info] Got HTTP request from {self.headers.get('User-Agent', 'onbekend')[:60]}")
            self._headers()
            relay.viewer(True)
            sent = 0
            try:
                first, cursor = relay.start_point()
                if first:
                    self.wfile.write(first)
                    sent += len(first)
                while not relay.closing.is_set():
                    with relay.cond:
                        relay.cond.wait_for(lambda: relay.seq > cursor or relay.closing.is_set(), timeout=1)
                        batch = [(n, d) for n, d in relay.recent if n > cursor]
                    for n, data in batch:
                        self.wfile.write(data)
                        sent += len(data)
                        cursor = n
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                pass
            finally:
                relay.viewer(False)
                out(f"[relay][info] Kijker weg na {sent // 1024} KB")

        def log_message(self, *args):
            pass

    return Viewer


def control_handler(relay):
    class Control(socketserver.StreamRequestHandler):
        def handle(self):
            words = self.rfile.readline(256).decode("utf-8", "replace").split()
            reply = {"ok": False}
            if words == ["status"]:
                reply = {"ok": True, **relay.status()}
            elif len(words) == 3 and words[0] == "switch" and CHANNEL.fullmatch(words[1]) and words[2] in ("0", "1"):
                reply = {"ok": relay.switch(words[1], words[2])}
            elif words == ["stop"]:
                reply = {"ok": True}
                threading.Thread(target=relay.shutdown, daemon=True).start()
            self.wfile.write((json.dumps(reply) + "\n").encode())

    return Control


def serve(args):
    if not CHANNEL.fullmatch(args.channel):
        sys.exit("Ongeldige kanaalnaam.")
    relay = Relay(args)
    try:
        stream = ThreadingHTTPServer((args.listen, args.port), viewer_handler(relay))
    except OSError as error:
        out(f"error: Failed to create HTTP server: {error.strerror or error}")
        sys.exit(1)
    stream.daemon_threads = True
    try:
        os.unlink(args.control)
    except FileNotFoundError:
        pass
    old_umask = os.umask(0o077)
    control = socketserver.ThreadingUnixStreamServer(args.control, control_handler(relay))
    os.umask(old_umask)
    control.daemon_threads = True
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda *_: threading.Thread(target=relay.shutdown, daemon=True).start())
    threading.Thread(target=stream.serve_forever, daemon=True).start()
    threading.Thread(target=control.serve_forever, daemon=True).start()
    threading.Thread(target=relay.watch_idle, daemon=True).start()
    out(f"[relay][info] Relay op http://{args.listen}:{args.port}{args.path}")
    relay.switch(args.channel, args.hq)
    while not relay.closing.wait(0.5):
        pass
    stream.shutdown()
    control.shutdown()
    try:
        os.unlink(args.control)
    except FileNotFoundError:
        pass


def send(path, words, timeout=3):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(path)
        client.sendall((" ".join(words) + "\n").encode())
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
    return json.loads(data or b"{}")


def query(path):
    """For tv.zsh: 'channel pending viewers' on one line, '-' for none; exit 1 if not running."""
    state = send(path, ["status"])
    if not state.get("ok"):
        raise ValueError("no status")
    return f"{state['channel'] or '-'} {state['pending'] or '-'} {int(state['viewers'])}"


def wait_for(path, channel, timeout):
    """After a switch: 0 when the channel plays, 2 when it did not start (the previous one
    keeps playing), 1 when the relay is gone or the switch takes too long."""
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            state = send(path, ["status"])
        except (OSError, ValueError):
            return 1
        if state.get("channel") == channel and not state.get("pending"):
            return 0
        if not state.get("pending"):
            return 2
        time.sleep(0.3)
    return 1


def main():
    if len(sys.argv) > 2 and sys.argv[1] in ("query", "wait"):
        try:
            if sys.argv[1] == "query":
                print(query(sys.argv[2]))
                sys.exit(0)
            sys.exit(wait_for(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 25))
        except (OSError, ValueError, IndexError):
            sys.exit(1)
    if len(sys.argv) > 2 and sys.argv[1] == "send":
        try:
            reply = send(sys.argv[2], sys.argv[3:])
        except (OSError, ValueError):
            sys.exit(1)
        print(json.dumps(reply))
        sys.exit(0 if reply.get("ok") else 1)
    parser = argparse.ArgumentParser(prog="relay.py serve")
    parser.add_argument("mode", choices=["serve"])
    parser.add_argument("--listen", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--path", default="/")
    parser.add_argument("--control", required=True)
    parser.add_argument("--stream-script", required=True)
    parser.add_argument("--streamlink", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--service", default="streamlink-twitch-auth")
    parser.add_argument("--channel", required=True)
    parser.add_argument("--hq", choices=["0", "1"], default="0")
    parser.add_argument("--idle-first", type=float, default=60)
    parser.add_argument("--idle-after", type=float, default=15)
    serve(parser.parse_args())


if __name__ == "__main__":
    main()
