"""stream.zsh fixtures: fake streamlink, Keychain and Twitch validation. No network, no Apple TV."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

TOKEN = 'abcdefghijklmnopqrstuvwxyz0123'
SCRIPT = Path(__file__).with_name('stream.zsh')


class StreamLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Fake Streamlink: print its arguments, and the contents of each --config file.
        self.streamlink = self.executable('streamlink', '\n'.join([
            'for a in "$@"; do printf "%s\\n" "$a"; done',
            'while (( $# )); do [[ "$1" == --config ]] && { print -r -- "CFG $(stat -f %Lp "$2") $(<$2)"; }; shift; done']))
        self.private = self.root/'private'
        self.private.mkdir(mode=0o700)
        self.env = {**os.environ, 'HOME': str(self.root), 'TV_PRIVATE_TMP': str(self.private),
                    'TV_LOGIN_CONFIG_TTL': '1', 'TV_SECURITY_BIN': str(self.security(TOKEN)),
                    'TV_CURL_BIN': str(self.curl('200'))}

    def executable(self, name, body):
        path = self.root/name
        path.write_text(f'#!/bin/zsh -f\n{body}\n')
        path.chmod(0o755)
        return path

    def security(self, token):
        body = f'print -r -- "{token}"' if token else 'exit 44'
        return self.executable('security', body)

    def curl(self, status):
        # Swallow the header on stdin like curl -H @- does, then report a status.
        return self.executable('curl', f'cat >/dev/null; print -n {status}')

    def run_stream(self, hq):
        result = subprocess.run(['/bin/zsh', '-f', str(SCRIPT), str(self.streamlink), hq, 'svc',
                                 '--twitch-low-latency', 'https://www.twitch.tv/x', 'best'],
                                env=self.env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_without_2k_streamlink_is_held_to_h264(self):
        # The user's own config.twitch may enable H.265/AV1; with 2K off the command line overrides it.
        self.assertEqual(self.run_stream('0'), ['--loglevel', 'info', '--twitch-supported-codecs', 'h264',
                                                '--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])

    def test_2k_adds_codecs_and_login_via_private_config_only(self):
        lines = self.run_stream('1')
        args = [line for line in lines if not line.startswith('CFG ')]
        # --loglevel info overrides a 'loglevel=debug' config, which would log the login header.
        self.assertEqual(args[:4], ['--loglevel', 'info', '--twitch-supported-codecs', 'h264,h265,av1'])
        self.assertEqual(args[-3:], ['--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])
        # The token is never a process argument, only inside a 0600 config file.
        self.assertFalse(any(TOKEN in a for a in args))
        self.assertIn(f'CFG 600 twitch-api-header=Authorization=OAuth {TOKEN}', lines)
        for _ in range(50):
            if not any(self.private.iterdir()):
                break
            time.sleep(0.1)
        self.assertEqual(list(self.private.iterdir()), [], 'login config must be removed after startup')

    def test_leftover_login_files_from_killed_sessions_are_swept(self):
        stale = self.private/'sofastream-login.OLD123'
        stale.write_text('twitch-api-header=Authorization=OAuth stale')
        os.utime(stale, (0, 0))
        fresh = self.private/'sofastream-login.NEW123'
        fresh.write_text('in use by a session that just started')
        self.run_stream('1')
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def leftovers(self):
        return sorted(path.name for path in self.private.iterdir() if path.name.startswith('sofastream-login.'))

    def start_waiting_session(self):
        """stream.zsh with 2K and a Streamlink that keeps waiting for a viewer, like the real server."""
        self.env['TV_LOGIN_CONFIG_TTL'] = '15'
        pidfile = self.root/'streamlink.pid'
        waiting = self.executable('streamlink-wait', f'print $$ > {pidfile}; exec /bin/sleep 30')
        process = subprocess.Popen(['/bin/zsh', '-f', str(SCRIPT), str(waiting), '1', 'svc', 'https://www.twitch.tv/x', 'best'],
                                   env=self.env, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.poll() is None and os.killpg(process.pid, signal.SIGKILL))
        until = time.monotonic() + 5
        while time.monotonic() < until and not (self.leftovers() and pidfile.exists() and pidfile.read_text().strip()):
            time.sleep(0.05)
        self.assertEqual(len(self.leftovers()), 1)
        return process, int(pidfile.read_text())

    def assert_gone(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_stopping_the_job_within_the_ttl_removes_the_login(self):
        # launchd stops a job (tv stop, a new channel) with SIGTERM, to the script or its whole group.
        for whole_group in (False, True):
            with self.subTest(whole_group=whole_group):
                process, streamlink = self.start_waiting_session()
                if whole_group:
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.send_signal(signal.SIGTERM)
                process.wait(timeout=3)
                self.assertEqual(self.leftovers(), [], 'the Twitch login stays on disk after the job stopped')
                self.assert_gone(streamlink)

    def test_login_is_removed_as_soon_as_streamlink_ends(self):
        self.env['TV_LOGIN_CONFIG_TTL'] = '15'
        began = time.monotonic()
        lines = self.run_stream('1')
        self.assertIn(f'CFG 600 twitch-api-header=Authorization=OAuth {TOKEN}', lines)
        self.assertLess(time.monotonic() - began, 3, 'the job must end with Streamlink, not after the TTL')
        self.assertEqual(self.leftovers(), [])

    def test_streamlink_exit_status_is_kept_with_a_login(self):
        failing = self.executable('streamlink-fail', 'exit 3')
        result = subprocess.run(['/bin/zsh', '-f', str(SCRIPT), str(failing), '1', 'svc', 'https://www.twitch.tv/x', 'best'],
                                env=self.env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(self.leftovers(), [])

    def test_a_hard_kill_leftover_is_swept_on_any_next_start(self):
        process, _ = self.start_waiting_session()
        os.killpg(process.pid, signal.SIGKILL)  # no trap can run; only the next start can clean up
        process.wait(timeout=3)
        for path in self.private.iterdir():
            os.utime(path, (0, 0))
        self.run_stream('0')  # 2K turned off meanwhile
        self.assertEqual(self.leftovers(), [])
        process, _ = self.start_waiting_session()
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        for path in self.private.iterdir():
            os.utime(path, (0, 0))
        self.env['TV_CURL_BIN'] = str(self.curl('401'))  # or the login expired meanwhile
        self.run_stream('1')
        self.assertEqual(self.leftovers(), [])

    def test_existing_default_streamlink_config_is_kept(self):
        default = self.root/'.config/streamlink'
        default.mkdir(parents=True)
        (default/'config').write_text('player-no-close\n')
        args = self.run_stream('1')
        self.assertEqual(args[args.index('--config') + 1], str(default/'config'))

    def test_2k_without_login_falls_back_and_warns(self):
        self.env['TV_SECURITY_BIN'] = str(self.security(''))
        args = self.run_stream('1')
        self.assertIn('--twitch-supported-codecs', args)
        self.assertFalse(any('OAuth' in a for a in args))
        self.assertTrue(any('geen Twitch-login' in a for a in args))

    def config_login(self):
        folder = self.root/'Library/Application Support/streamlink'
        folder.mkdir(parents=True)
        (folder/'config.twitch').write_text('twitch-api-header=Authorization=OAuth configtoken0123456789\n')

    def test_2k_with_only_a_streamlink_config_login_says_so(self):
        # Streamlink reads that config itself, so 2K works; the log must not claim "max 1080p".
        self.config_login()
        self.env['TV_SECURITY_BIN'] = str(self.security(''))
        lines = self.run_stream('1')
        self.assertIn('[sofastream][info] 2K met de Twitch-login uit je Streamlink-config.', lines)
        self.assertFalse(any('1080p' in line or 'configtoken' in line for line in lines), lines)
        self.assertIn('--twitch-supported-codecs', lines)

    def test_expired_keychain_login_falls_back_to_the_config_login(self):
        self.config_login()
        self.env['TV_CURL_BIN'] = str(self.curl('401'))
        lines = self.run_stream('1')
        self.assertTrue(any('verlopen; 2K gebruikt nu de login uit je Streamlink-config' in line for line in lines), lines)
        self.assertFalse(any(TOKEN in line for line in lines))

    def test_expired_login_is_not_sent(self):
        self.env['TV_CURL_BIN'] = str(self.curl('401'))
        args = self.run_stream('1')
        self.assertFalse(any('OAuth' in a for a in args))
        self.assertTrue(any('verlopen' in a for a in args))
        self.assertFalse(any(TOKEN in a for a in args))

    def test_validation_outage_still_uses_login(self):
        self.env['TV_CURL_BIN'] = str(self.curl('000'))
        self.assertIn(f'CFG 600 twitch-api-header=Authorization=OAuth {TOKEN}', self.run_stream('1'))


if __name__ == '__main__':
    unittest.main()
