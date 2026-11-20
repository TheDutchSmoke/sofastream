"""Run actual tv shell commands with only playback/launchctl replaced by fixtures."""
from pathlib import Path
import os
import plistlib
import shlex
import signal
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
        (self.root/'page.py').write_text(Path(__file__).with_name('page.py').read_text())
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
        (self.root/'bin').mkdir()
        fake_ffmpeg = self.root/'bin'/'ffmpeg'
        fake_ffmpeg.write_text('#!/bin/sh\nexec cat\n')
        fake_ffmpeg.chmod(0o755)
        self.script.write_text(source + f'''
node() {{
    print -r -- "node $2" >> {shlex.quote(str(self.calls))}
    if [[ "$TV_TEST_VLC" == unavailable ]]; then
        echo 'Open VLC en zet Afspelen op afstand aan.' >&2
        return 1
    fi
    [[ "$2" == address ]] && echo 192.0.2.5
    [[ "$2" == prepare && -n "$TV_TEST_PREPARE_DELAY" ]] && sleep "$TV_TEST_PREPARE_DELAY"
    [[ "$2" == prepare && -n "$TV_TEST_WOKE" ]] && echo woke
    [[ "$2" == play && -n "$TV_TEST_VIEWER" ]] && echo '[cli][info] Got HTTP request from VLC/3.0' >> "$TV_STREAM_LOG"
    [[ "$2" == play && -n "$TV_TEST_PLAY_DELAY" ]] && sleep "$TV_TEST_PLAY_DELAY"
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
_tv_relay() {{
    case "$1" in
        query) [[ -n "$TV_TEST_RELAY" ]] || return 1; print -r -- "$TV_TEST_RELAY" ;;
        send) print -r -- "relay $2 $3 $4" >> {shlex.quote(str(self.calls))} ;;
        wait) return ${{TV_TEST_RELAY_WAIT:-0}} ;;
    esac
}}
launchctl() {{
    print -r -- "$*" >> {shlex.quote(str(self.trace))}
    print -r -- "launchctl $1" >> {shlex.quote(str(self.calls))}
    return 0
}}
tv "$@"
''')

    def env(self, unavailable=False, play_fails=False, viewer=False, woke=False, drops=False,
            prepare_delay='', play_delay='', relay='', relay_wait='0'):
        return {**os.environ, 'PATH': f"{self.root/'bin'}:{os.environ['PATH']}", 'TV_TEST_RELAY': relay, 'TV_TEST_RELAY_WAIT': relay_wait, 'TV_TEST_PREPARE_DELAY': prepare_delay, 'TV_TEST_PLAY_DELAY': play_delay, 'TV_TEST_WOKE': '1' if woke else '', 'TV_TEST_PLAY_DROP': '1' if drops else '', 'TV_PROFILE_RETRY_WINDOW': '3', 'TV_PROFILE_RETRY_POLL': '0.1', 'TV_TEST_VLC': 'unavailable' if unavailable else 'ready', 'TV_TEST_PLAY_FAIL': '1' if play_fails else '', 'TV_TEST_VIEWER': '1' if viewer else '','TV_CACHE_DIR': str(self.root/'cache'), 'TV_APP_DIR': str(self.root), 'TV_CONFIG_DIR': str(self.root), 'TV_APPLE_TV_CONFIG': str(self.root/'apple-tv.json'), 'TV_ACTIVE_TV_CONFIG': str(self.root/'active.json'), 'TV_STREAM_LOG': str(self.log), 'TV_STREAM_ERR': str(self.root/'stream.err'), 'TV_STREAM_PORT': '18765', 'TV_LAUNCH_LABEL': 'nl.sofastream.fixture'}

    def run_tv(self, *args, **options):
        return subprocess.run(['zsh','-f',str(self.script),*args], text=True, capture_output=True,
                              env=self.env(**options), timeout=8)

    def spawn_tv(self, *args, **options):
        process = subprocess.Popen(['zsh','-f',str(self.script),*args], text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=self.env(**options), start_new_session=True)
        self.addCleanup(lambda: process.poll() is None and os.killpg(process.pid, signal.SIGKILL))
        return process

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
        # One-shot: launchd must not restart the relay after it ends.
        self.assertIs(job['KeepAlive'], False)
        args = job['ProgramArguments']
        self.assertEqual(args[1:3], [str(self.root/'relay.py'), 'serve'])
        option = lambda name: args[args.index(name) + 1]
        self.assertEqual(option('--channel'), 'star')
        self.assertEqual(option('--listen'), '192.0.2.5')
        self.assertEqual(option('--port'), '18765')
        self.assertEqual(option('--control'), str(self.root/'cache'/'relay.sock'))
        self.assertEqual(option('--ffmpeg'), str(self.root/'bin'/'ffmpeg'))
        session = (self.root/'cache'/'session').read_text().strip()
        self.assertEqual(option('--path'), '/' + session, 'a fresh URL per relay session')
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

    def test_a_watched_relay_switches_inside_its_stream_without_touching_vlc(self):
        # VLC 3.0.24 on tvOS fails on a second item; the relay keeps VLC's one connection.
        result = self.run_tv('star', relay='ohnepixel - 1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Gewisseld naar star', result.stdout)
        calls = self.calls.read_text().splitlines()
        self.assertIn('relay switch star 0', calls)
        self.assertNotIn('node play', calls, 'VLC must get no command while it watches the relay')
        self.assertFalse(any(call.startswith('launchctl') for call in calls), calls)
        self.assertEqual(self.log.read_text(), 'existing stream log', 'the running relay keeps its log')

    def test_a_relay_nobody_watches_switches_and_vlc_opens_it(self):
        result = self.run_tv('star', relay='ohnepixel - 0')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text().splitlines()
        self.assertLess(calls.index('relay switch star 0'), calls.index('node play'), calls)
        self.assertFalse(any(call.startswith('launchctl') for call in calls), calls)

    def test_the_playing_channel_is_not_restarted(self):
        result = self.run_tv('star', relay='star - 1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(call.startswith('relay switch') for call in self.calls.read_text().splitlines()))

    def test_a_channel_that_does_not_start_keeps_the_previous_one(self):
        result = self.run_tv('star', relay='ohnepixel - 1', relay_wait='2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('star start niet; het vorige kanaal blijft spelen', result.stdout)

    def test_the_previous_session_log_is_kept(self):
        self.run_tv('star')
        self.assertEqual((self.root/'stream.log.1').read_text(), 'existing stream log')

    def test_stop_unloads_the_relay_before_it_asks_vlc(self):
        self.run_tv('stop')
        calls = self.calls.read_text().splitlines()
        self.assertLess(calls.index('launchctl bootout'), calls.index('node stop'), calls)

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
        self.assertIn('verbrak de stream direct', self.retry_log_with('verbrak de stream direct'))

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

    def retry_log_with(self, text, timeout=3):
        """The retry runs detached; its output lands after the bootstrap the tests wait for."""
        log = self.root/'cache'/'profile-retry.log'
        until = time.monotonic() + timeout
        while time.monotonic() < until and text not in (log.read_text() if log.exists() else ''):
            time.sleep(0.05)
        return log.read_text() if log.exists() else ''

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
        retry_log = self.retry_log_with('Speelt: star')
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
        self.assertEqual(args[args.index('--channel') + 1], 'other')

    def channel_in_job(self):
        args = plistlib.loads((self.root/'cache'/'nl.sofastream.fixture.plist').read_bytes())['ProgramArguments']
        return args[args.index('--channel') + 1]

    def wait_until_retry_restarts(self):
        # The retry removes its marker right before it calls _tv_start again.
        marker = self.root/'cache'/'profile-retry'
        until = time.monotonic() + 3
        while time.monotonic() < until and marker.exists():
            time.sleep(0.05)
        self.assertFalse(marker.exists(), 'the profile retry did not start')

    def test_stop_cancels_a_profile_retry_that_is_already_restarting(self):
        # Reported by Fable: the retry sits in a slow prepare (wake, profile choice) when the user stops.
        self.assertEqual(self.run_tv('star', woke=True, prepare_delay='2').returncode, 0)
        self.vlc_closes()
        self.wait_until_retry_restarts()
        self.assertIn('Streamlink: gestopt.', self.run_tv('stop').stdout)
        time.sleep(3)
        self.assertEqual(self.starts(), 1, self.trace.read_text())
        self.assertIn('Vervangen', self.retry_log_with('Vervangen'))

    def test_new_channel_is_not_replaced_by_a_running_profile_retry(self):
        self.assertEqual(self.run_tv('star', woke=True, prepare_delay='2').returncode, 0)
        self.vlc_closes()
        self.wait_until_retry_restarts()
        self.assertEqual(self.run_tv('other').returncode, 0)
        time.sleep(3)
        self.assertEqual(self.channel_in_job(), 'other', self.trace.read_text())
        self.assertEqual(self.starts(), 2)

    def test_stop_in_another_terminal_ends_a_start_that_is_still_waking(self):
        start = self.spawn_tv('star', prepare_delay='2')
        time.sleep(0.8)
        self.assertEqual(self.run_tv('stop').returncode, 0)
        out, _ = start.communicate(timeout=10)
        self.assertNotEqual(start.returncode, 0)
        self.assertIn('Vervangen', out)
        self.assertEqual(self.starts(), 0, self.trace.read_text())
        self.assertNotIn('node play', self.calls.read_text().splitlines(), 'a replaced start must not open VLC')

    def interrupt_during_play(self, viewer):
        start = self.spawn_tv('star', play_delay='5', viewer=viewer)
        until = time.monotonic() + 5
        while time.monotonic() < until and not self.starts():
            time.sleep(0.05)
        self.assertEqual(self.starts(), 1)
        time.sleep(0.3)
        os.killpg(start.pid, signal.SIGINT)  # Ctrl-C reaches the whole foreground group
        out, _ = start.communicate(timeout=10)
        return start.returncode, out, self.trace.read_text().splitlines()

    def test_ctrl_c_while_starting_unloads_the_waiting_server(self):
        code, out, launches = self.interrupt_during_play(viewer=False)
        self.assertNotEqual(code, 0)
        self.assertTrue(launches[-1].startswith('bootout '), launches)
        self.assertIn('Afgebroken', out)

    def test_ctrl_c_after_the_tv_connected_keeps_the_stream(self):
        # Like closing the menu: a stream the TV already plays keeps playing.
        code, _, launches = self.interrupt_during_play(viewer=True)
        self.assertNotEqual(code, 0)
        self.assertTrue(launches[-1].startswith('bootstrap '), launches)

    def test_retry_window_expires(self):
        self.run_tv('star', woke=True)
        time.sleep(3.5)
        self.vlc_closes()
        time.sleep(0.5)
        self.assertEqual(self.starts(), 1)
        self.assertFalse((self.root/'cache'/'profile-retry').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
