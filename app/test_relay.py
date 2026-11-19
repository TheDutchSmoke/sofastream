"""relay.py with a fake Streamlink and a pass-through ffmpeg: real MPEG-TS packets, no network."""
import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
RELAY = Path(__file__).with_name("relay.py")
spec = importlib.util.spec_from_file_location("relay", RELAY)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)

PACKET = 188


def packet(pid, payload, start=False, adaptation=None):
    header = bytes([0x47, (0x40 if start else 0) | (pid >> 8), pid & 0xFF])
    if adaptation is None:
        body = bytes([0x10]) + payload
    else:
        body = bytes([0x30, len(adaptation)]) + adaptation + payload
    data = header + body
    return data + b"\xff" * (PACKET - len(data))


def section(table_id, extension, body):
    length = 5 + len(body) + 4
    head = bytes([table_id, 0xB0 | (length >> 8), length & 0xFF, extension >> 8, extension & 0xFF,
                  0xC1, 0x00, 0x00]) + body  # version 0, current_next 1
    return head + relay.mpeg_crc32(head).to_bytes(4, "big")


PAT = packet(0, b"\x00" + section(0x00, 1, bytes([0x00, 0x01, 0xF0, 0x00])), start=True)
PMT = packet(0x1000, b"\x00" + section(0x02, 1, bytes([0xE1, 0x00, 0xF0, 0x00, 0x24, 0xE1, 0x00, 0xF0, 0x00])), start=True)
KEYFRAME = packet(0x100, b"\x00\x00\x01\xe0key", start=True, adaptation=bytes([0x40]))
AUDIO_KEY = packet(0x101, b"\x00\x00\x01\xc0aud", start=True, adaptation=bytes([0x40]))
FILLER = packet(0x100, b"frame")


def pat_versions(data):
    """Versions of every PAT in a byte stream that may not start on a packet boundary."""
    versions, at = [], data.find(b"\x47\x40\x00")
    while at != -1 and at + PACKET <= len(data):
        versions.append(table_version(data[at:at + PACKET], 0)[0])
        at = data.find(b"\x47\x40\x00", at + 1)
    return versions


def table_version(data, pid):
    """Version and CRC validity of the first table section on this PID."""
    for start in range(0, len(data) - PACKET + 1, PACKET):
        p = data[start:start + PACKET]
        if p[0] == 0x47 and relay.pid_of(p, 0) == pid and p[1] & 0x40:
            sec = 5 + p[4]
            end = sec + 3 + (((p[sec + 1] & 0x0F) << 8) | p[sec + 2])
            valid = relay.mpeg_crc32(p[sec:end - 4]) == int.from_bytes(p[end - 4:end], "big")
            return (p[sec + 5] >> 1) & 0x1F, valid
    return None, False


class Tables(unittest.TestCase):
    def test_each_source_gets_its_own_table_version_with_a_valid_crc(self):
        patched = relay.set_table_version(PAT + PMT + FILLER, 7)
        self.assertEqual(table_version(patched, 0), (7, True))
        self.assertEqual(table_version(patched, 0x1000), (7, True))
        self.assertEqual(patched[2 * PACKET:], FILLER, "media packets stay untouched")

    def test_viewers_start_at_a_video_keyframe_not_an_audio_frame(self):
        keyframe, pat, pmt = relay.scan(PAT + PMT + FILLER + KEYFRAME + FILLER + AUDIO_KEY)
        self.assertEqual(keyframe, 3 * PACKET)
        self.assertEqual((pat, pmt), (PAT, PMT))


GENERATOR = '''import os, sys, time
url = sys.argv[-2]
channel = url.rsplit("/", 1)[-1]
folder = os.environ["RELAY_TEST_DIR"]
open(os.path.join(folder, channel + ".pid"), "w").write(str(os.getpid()))
if channel == "offline":
    print("error: No playable streams found on this URL: " + url, file=sys.stderr, flush=True)
    sys.exit(1)
print("[cli][info] Opening stream: 1080p60 (hls)", file=sys.stderr, flush=True)
packets = open(os.path.join(folder, "packets.bin"), "rb").read()
marker = channel.encode().ljust(16, b"_")[:16]
out = sys.stdout.buffer
while True:
    out.write(packets + bytes([0x47, 0x01, 0x00, 0x10]) + marker + b"\\xff" * 168)
    out.flush()
    time.sleep(0.02)
'''


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class RelayProcess(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tv-relay-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "packets.bin").write_bytes(PAT + PMT + KEYFRAME + FILLER * 20)
        (self.root / "gen.py").write_text(GENERATOR)
        # stream.zsh stand-in: same arguments, runs the generator (stdout = video, stderr = log).
        self.stream = self.executable("stream.zsh", f'exec {sys.executable} -I {self.root / "gen.py"} "$@"')
        self.ffmpeg = self.executable("ffmpeg", "exec /bin/cat")
        self.socket = str(self.root / "relay.sock")
        self.port = free_port()

    def executable(self, name, body):
        path = self.root / name
        path.write_text(f"#!/bin/zsh -f\n{body}\n")
        path.chmod(0o755)
        return path

    def start(self, channel="one", idle_first=20, idle_after=4, port=None):
        with open(self.root / "relay.log", "ab") as log:
            process = self._spawn(channel, idle_first, idle_after, port, log)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def _spawn(self, channel, idle_first, idle_after, port, log):
        return subprocess.Popen(
            [sys.executable, "-I", str(RELAY), "serve", "--listen", "127.0.0.1", "--port", str(port or self.port),
             "--path", "/s1", "--control", self.socket, "--stream-script", str(self.stream),
             "--streamlink", "/usr/bin/true", "--ffmpeg", str(self.ffmpeg), "--channel", channel,
             "--idle-first", str(idle_first), "--idle-after", str(idle_after)],
            stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "RELAY_TEST_DIR": str(self.root)})

    def log(self):
        return (self.root / "relay.log").read_text()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(RELAY), *args], capture_output=True, text=True, timeout=30)

    def wait_for(self, condition, timeout=8):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if condition():
                return True
            time.sleep(0.05)
        return condition()

    def viewer(self):
        client = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        client.sendall(b"GET /s1 HTTP/1.1\r\nHost: tv\r\nUser-Agent: VLC/3.0.24 LibVLC/3.0.24\r\n\r\n")
        data = b""
        while b"\r\n\r\n" not in data:
            data += client.recv(4096)
        head, body = data.split(b"\r\n\r\n", 1)
        self.assertIn(b"200", head.split(b"\r\n")[0])
        return client, body

    def read(self, client, body, until_marker, limit=4_000_000):
        while until_marker not in body and len(body) < limit:
            chunk = client.recv(65536)
            if not chunk:
                break
            body += chunk
        return body

    def running(self, channel):
        try:
            os.kill(int((self.root / f"{channel}.pid").read_text()), 0)
            return True
        except (OSError, ValueError):
            return False

    def test_a_viewer_starts_at_tables_and_keyframe_and_keeps_its_connection_across_a_switch(self):
        process = self.start()
        self.assertTrue(self.wait_for(lambda: "Bron: one · 1080p60" in self.log()), self.log())
        client, body = self.viewer()
        body = self.read(client, body, b"one_")
        self.assertEqual(body[:3 * PACKET], relay.set_table_version(PAT + PMT, 1) + KEYFRAME,
                         "a viewer must start with the tables and the newest keyframe")
        self.assertEqual(self.cli("query", self.socket).stdout.split(), ["one", "-", "1"])
        self.assertEqual(self.cli("send", self.socket, "switch", "two", "0").returncode, 0)
        self.assertEqual(self.cli("wait", self.socket, "two", "10").returncode, 0)
        body = self.read(client, b"", b"two_")
        self.assertIn(b"two_", body, "the same connection carries the new channel")
        body = self.read(client, body[-PACKET:], b"never", limit=400_000)
        self.assertEqual(pat_versions(body)[-1], 2, "the new source announces itself with table version 2")
        self.assertTrue(self.wait_for(lambda: not self.running("one")), "the old source is stopped")
        self.assertIn("Bron: two", self.log())
        client.close()
        process.terminate()
        process.wait(timeout=10)

    def test_a_probe_connection_does_not_end_the_stream(self):
        process = self.start()
        self.assertTrue(self.wait_for(lambda: "Bron:" in self.log()))
        probe, _ = self.viewer()
        probe.close()  # VLC opens with a short probe, then connects again
        client, body = self.viewer()
        self.assertIn(b"one_", self.read(client, body, b"one_"))
        self.assertIsNone(process.poll())
        client.close()

    def test_a_channel_that_does_not_start_leaves_the_current_one_playing(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: "Bron:" in self.log()))
        client, body = self.viewer()
        self.cli("send", self.socket, "switch", "offline", "0")
        self.assertEqual(self.cli("wait", self.socket, "offline", "10").returncode, 2)
        self.assertEqual(self.cli("query", self.socket).stdout.split()[:2], ["one", "-"])
        self.assertIn("offline start niet; one blijft spelen", self.log())
        self.assertIn(b"one_", self.read(client, b"", b"one_"))
        client.close()

    def test_without_a_viewer_the_relay_ends_and_stops_its_source(self):
        process = self.start(idle_first=1)
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertIn("Geen kijker meer", self.log())
        self.assertFalse(self.running("one"))
        self.assertFalse(os.path.exists(self.socket))

    def test_a_viewer_leaving_is_logged_and_ends_the_relay(self):
        process = self.start(idle_after=4)
        self.assertTrue(self.wait_for(lambda: "Bron:" in self.log()))
        client, _ = self.viewer()
        client.close()
        self.assertEqual(process.wait(timeout=15), 0)
        log = self.log()
        self.assertIn("Got HTTP request from VLC/3.0.24", log)
        self.assertIn("HTTP connection closed", log, "tv.zsh's profile retry looks for this line")

    def test_sigterm_stops_the_source(self):
        process = self.start()
        self.assertTrue(self.wait_for(lambda: "Bron:" in self.log()))
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=10)
        self.assertTrue(self.wait_for(lambda: not self.running("one")))

    def test_an_offline_first_channel_ends_the_relay(self):
        process = self.start(channel="offline")
        process.wait(timeout=10)
        self.assertIn("error: No playable streams found", self.log())

    def test_a_busy_port_is_reported_in_streamlink_error_form(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", self.port))
            busy.listen()
            process = self.start()
            self.assertEqual(process.wait(timeout=10), 1)
        self.assertIn("error: Failed to create HTTP server", self.log())

    def test_cli_reports_a_missing_relay(self):
        self.assertEqual(self.cli("query", self.socket).returncode, 1)
        self.assertEqual(self.cli("wait", self.socket, "one", "1").returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
