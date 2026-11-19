"""stream.zsh fixtures: fake streamlink, Keychain and Twitch validation. No network, no Apple TV."""
import os
from pathlib import Path
import subprocess
import tempfile
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
        self.assertEqual(self.run_stream('0'), ['--twitch-supported-codecs', 'h264',
                                                '--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])

    def test_2k_adds_codecs_and_login_via_private_config_only(self):
        lines = self.run_stream('1')
        args = [line for line in lines if not line.startswith('CFG ')]
        self.assertEqual(args[:2], ['--twitch-supported-codecs', 'h264,h265,av1'])
        self.assertEqual(args[-3:], ['--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])
        # The token is never a process argument, only inside a 0600 config file.
        self.assertFalse(any(TOKEN in a for a in args))
        self.assertIn(f'CFG 600 twitch-api-header=Authorization=OAuth {TOKEN}', lines)
        import time
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
