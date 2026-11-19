"""Run actual tv shell commands with only playback/launchctl replaced by fixtures."""
from pathlib import Path
import os
import plistlib
import shlex
import subprocess
import tempfile
import time
import unittest


class Commands(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tv-commands-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.trace = self.root/'launches'
        # node and launchctl calls in order, to check what happens before the port reopens.
        self.calls = self.root/'calls'
        self.log = self.root/'stream.log'
        self.log.write_text('existing stream log')
        actual = Path(__file__).with_name('tui.py')
        (self.root/'settings.py').write_text(Path(__file__).with_name('settings.py').read_text())
        wrapper = self.root/'tui.py'
        wrapper.write_text(f'''import importlib.util, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('tui', {str(actual)!r})
tui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tui)
def playable(login):
    if login == 'offline':
        raise ValueError('offline is offline. Je huidige stream blijft ongewijzigd.')
tui.check_playable = playable
sys.argv += ['--favorites', {str(self.root/'favorites')!r}, '--priority', {str(self.root/'priority')!r}]
tui.main()
''')
        source = Path(__file__).with_name('tv.zsh').read_text()
        self.script = self.root/'commands.zsh'
        self.script.write_text(source + f'''
node() {{
    print -r -- "node $2" >> {shlex.quote(str(self.calls))}
    if [[ "$TV_TEST_VLC" == unavailable ]]; then
        echo 'Open VLC en zet Afspelen op afstand aan.' >&2
        return 1
    fi
    [[ "$2" == address ]] && echo 192.0.2.5
    [[ "$2" == prepare && -n "$TV_TEST_WOKE" ]] && echo woke
    [[ "$2" == play && -n "$TV_TEST_VIEWER" ]] && echo '[cli][info] Got HTTP request from VLC/3.0' >> "$TV_STREAM_LOG"
    [[ "$2" == release && -n "$TV_TEST_RELEASE_FAIL" ]] && {{ echo 'VLC stopt de vorige stream niet.' >&2; return 1; }}
    [[ "$2" == play && -n "$TV_TEST_PLAY_FAIL" ]] && {{ echo 'VLC bevestigt nog geen beeld.' >&2; return 1; }}
    [[ "$2" == play && -n "$TV_TEST_PLAY_DROP" ]] && {{
        print -l '[cli][info] Got HTTP request from VLC/3.0' '[cli][info] HTTP connection closed' >> "$TV_STREAM_LOG"
        echo 'VLC op Test TV verbrak de stream direct.' >&2
        return 3
    }}
    [[ "$2" == play ]] && echo "Speelt: $3"
    [[ "$2" == stop ]] && echo 'VLC: tv-stream gestopt.'
    return 0
}}
launchctl() {{
    print -r -- "$*" >> {shlex.quote(str(self.trace))}
    print -r -- "launchctl $1" >> {shlex.quote(str(self.calls))}
    return 0
}}
tv "$@"
''')

    def run_tv(self, *args, unavailable=False, play_fails=False, viewer=False, woke=False, release_fails=False, drops=False):
        return subprocess.run(['zsh','-f',str(self.script),*args], text=True, capture_output=True,
                              env={**os.environ, 'TV_TEST_WOKE': '1' if woke else '', 'TV_TEST_RELEASE_FAIL': '1' if release_fails else '', 'TV_TEST_PLAY_DROP': '1' if drops else '', 'TV_PROFILE_RETRY_WINDOW': '3', 'TV_PROFILE_RETRY_POLL': '0.1', 'TV_TEST_VLC': 'unavailable' if unavailable else 'ready', 'TV_TEST_PLAY_FAIL': '1' if play_fails else '', 'TV_TEST_VIEWER': '1' if viewer else '','TV_CACHE_DIR': str(self.root/'cache'), 'TV_APP_DIR': str(self.root), 'TV_CONFIG_DIR': str(self.root), 'TV_APPLE_TV_CONFIG': str(self.root/'apple-tv.json'), 'TV_ACTIVE_TV_CONFIG': str(self.root/'active.json'), 'TV_STREAM_LOG': str(self.log), 'TV_STREAM_ERR': str(self.root/'stream.err'), 'TV_STREAM_PORT': '18765', 'TV_LAUNCH_LABEL': 'nl.sofastream.fixture'}, timeout=5)

    def test_invalid_offline_and_unreachable_tv_preserve_existing_stream(self):
        for channel, unavailable in [('bad name', False), ('offline', False), ('star', True)]:
            result = self.run_tv(channel, unavailable=unavailable)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse(self.trace.exists(), result.stdout)
            self.assertEqual(self.log.read_text(), 'existing stream log')

    def test_twitch_link_starts_normalized_channel(self):
        result = self.run_tv('https://twitch.tv/STAR?ref=test')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Speelt: star', result.stdout)
        launches = self.trace.read_text().splitlines()
        self.assertEqual(len(launches), 2)
        self.assertTrue(launches[0].startswith('bootout '))
        self.assertTrue(launches[1].startswith('bootstrap gui/'))
        job = plistlib.loads((self.root/'cache'/'nl.sofastream.fixture.plist').read_bytes())
        # One-shot: launchd must not restart Streamlink after VLC closes the stream.
        self.assertIs(job['KeepAlive'], False)
        args = job['ProgramArguments']
        self.assertEqual(args[-2:], ['https://www.twitch.tv/star', 'best'])
        self.assertEqual(args[args.index('--player-external-http-interface') + 1], '192.0.2.5')
        self.assertNotIn('0.0.0.0', args)

    def test_failed_play_without_viewer_unloads_the_waiting_server(self):
        result = self.run_tv('star', play_fails=True)
        self.assertNotEqual(result.returncode, 0)
        launches = self.trace.read_text().splitlines()
        self.assertTrue(launches[-1].startswith('bootout '), launches)

    def test_failed_play_confirmation_keeps_a_connected_stream(self):
        result = self.run_tv('star', play_fails=True, viewer=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.trace.read_text().splitlines()[-1].startswith('bootstrap '))

    def test_vlc_releases_previous_stream_before_the_port_reopens(self):
        result = self.run_tv('star')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        self.assertEqual(calls[calls.index('node prepare') + 1], 'node release', calls)
        self.assertLess(calls.index('node release'), calls.index('launchctl bootout'), calls)
        self.assertLess(calls.index('launchctl bootstrap'), calls.index('node play'), calls)

    def test_release_failure_keeps_the_current_stream(self):
        result = self.run_tv('star', release_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stopt de vorige stream niet', result.stderr)
        self.assertFalse(self.trace.exists(), 'No bootout or bootstrap after a failed release')
        self.assertEqual(self.log.read_text(), 'existing stream log')

    def test_dropped_stream_is_reported_not_retried_without_wake(self):
        result = self.run_tv('star', drops=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('verbrak de stream direct', result.stderr)
        self.assertNotIn('Speelt', result.stdout)
        time.sleep(1)
        self.assertEqual(self.starts(), 1)

    def test_dropped_stream_right_after_wake_restarts_once(self):
        result = self.run_tv('star', woke=True, drops=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('één keer opnieuw', result.stdout)
        self.assertNotIn('verbrak', result.stdout + result.stderr)
        self.assertEqual(self.wait_for_starts(2), 2)
        # The restart drops again: it reports the error and does not loop.
        time.sleep(1)
        self.assertEqual(self.starts(), 2)
        self.assertIn('verbrak de stream direct', (self.root/'cache'/'profile-retry.log').read_text())

    def test_cli_favorites_duplicate_remove_and_list(self):
        self.assertIn('opgeslagen', self.run_tv('fav','add','@Star').stdout)
        self.assertIn('staat al', self.run_tv('fav','add','star').stdout)
        self.assertEqual(self.run_tv('fav','list').stdout, 'star\n')
        self.assertIn('verwijderd', self.run_tv('fav','remove','star').stdout)
        self.assertIn('staat niet', self.run_tv('fav','remove','star').stdout)
        self.assertIn('Nog geen kanalen', self.run_tv('fav','list').stdout)
        self.assertNotEqual(self.run_tv('fav','invalid').returncode, 0)

    def test_stop_still_stops_local_server_if_vlc_cannot_be_reached(self):
        result = self.run_tv('stop', unavailable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Streamlink: gestopt.', result.stdout)
        self.assertIn('VLC: stoppen niet bevestigd', result.stdout)
        self.assertEqual(len(self.trace.read_text().splitlines()), 1)


    def starts(self):
        if not self.trace.exists():
            return 0
        return sum(line.startswith('bootstrap ') for line in self.trace.read_text().splitlines())

    def vlc_closes(self):
        with self.log.open('a') as handle:
            handle.write('[cli][info] HTTP connection closed\n')

    def wait_for_starts(self, expected, timeout=3):
        until = time.monotonic() + timeout
        while time.monotonic() < until and self.starts() < expected:
            time.sleep(0.05)
        return self.starts()

    def test_profile_choice_after_wake_restarts_once_without_blocking(self):
        began = time.monotonic()
        result = self.run_tv('star', woke=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The TUI captures this output; a detached retry must not hold it open.
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual(self.starts(), 1)
        self.vlc_closes()
        self.assertEqual(self.wait_for_starts(2), 2)
        retry_log = (self.root/'cache'/'profile-retry.log').read_text()
        self.assertIn('eenmalig opnieuw starten', retry_log)
        self.assertIn('Speelt: star', retry_log)
        # The retry itself never schedules another retry.
        self.vlc_closes()
        time.sleep(1)
        self.assertEqual(self.starts(), 2)
        self.assertFalse((self.root/'cache'/'profile-retry').exists())

    def test_no_retry_without_wake(self):
        self.run_tv('star')
        self.vlc_closes()
        time.sleep(1)
        self.assertEqual(self.starts(), 1)

    def test_stop_cancels_pending_retry(self):
        self.run_tv('star', woke=True)
        self.run_tv('stop')
        self.vlc_closes()
        time.sleep(1)
        self.assertEqual(self.starts(), 1)

    def test_new_channel_replaces_pending_retry(self):
        self.run_tv('star', woke=True)
        self.run_tv('other')
        self.vlc_closes()
        time.sleep(1)
        self.assertEqual(self.starts(), 2)
        args = plistlib.loads((self.root/'cache'/'nl.sofastream.fixture.plist').read_bytes())['ProgramArguments']
        self.assertEqual(args[-2], 'https://www.twitch.tv/other')

    def test_retry_window_expires(self):
        self.run_tv('star', woke=True)
        time.sleep(3.5)
        self.vlc_closes()
        time.sleep(0.5)
        self.assertEqual(self.starts(), 1)
        self.assertFalse((self.root/'cache'/'profile-retry').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
