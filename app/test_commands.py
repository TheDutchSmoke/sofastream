"""Run actual tv shell commands with only playback/launchctl replaced by fixtures."""
from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest


class Commands(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='tv-commands-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.trace = self.root/'launches'
        self.log = self.root/'stream.log'
        self.log.write_text('existing stream log')
        actual = Path(__file__).with_name('tui.py')
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
    if [[ "$TV_TEST_VLC" == unavailable ]]; then
        echo 'Open VLC en zet Afspelen op afstand aan.' >&2
        return 1
    fi
    [[ "$2" == play ]] && echo "Speelt: $3"
    [[ "$2" == stop ]] && echo 'VLC: tv-stream gestopt.'
    return 0
}}
launchctl() {{
    print -r -- "$*" >> {shlex.quote(str(self.trace))}
    return 0
}}
tv "$@"
''')

    def run_tv(self, *args, unavailable=False):
        return subprocess.run(['zsh','-f',str(self.script),*args], text=True, capture_output=True,
                              env={**os.environ, 'TV_TEST_VLC': 'unavailable' if unavailable else 'ready', 'TV_APP_DIR': str(self.root), 'TV_CONFIG_DIR': str(self.root), 'TV_STREAM_LOG': str(self.log), 'TV_STREAM_ERR': str(self.root/'stream.err'), 'TV_STREAM_PORT': '18765', 'TV_LAUNCH_LABEL': 'nl.sofastream.fixture'}, timeout=5)

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
        self.assertIn('https://www.twitch.tv/star best', launches[1])

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
