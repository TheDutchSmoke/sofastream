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
        self.streamlink = self.executable('streamlink', 'for a in "$@"; do printf "%s\\n" "$a"; done')
        self.env = {**os.environ, 'TV_SECURITY_BIN': str(self.security(TOKEN)),
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

    def test_without_2k_streamlink_gets_original_arguments_only(self):
        self.assertEqual(self.run_stream('0'), ['--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])

    def test_2k_adds_codecs_and_login(self):
        args = self.run_stream('1')
        self.assertEqual(args[:2], ['--twitch-supported-codecs', 'h264,h265,av1'])
        self.assertIn(f'Authorization=OAuth {TOKEN}', args)
        self.assertEqual(args[-3:], ['--twitch-low-latency', 'https://www.twitch.tv/x', 'best'])

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
        self.assertIn(f'Authorization=OAuth {TOKEN}', self.run_stream('1'))


if __name__ == '__main__':
    unittest.main()
