"""Settings fixtures use an isolated home and never discover or contact devices."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root/'dev'
        self.config.mkdir()
        self.env = {**os.environ, 'HOME': str(self.root), 'TV_DEV_MODE': '1',
                    'TV_CONFIG_DIR': str(self.config), 'TV_APPLE_TV_CONFIG': str(self.config/'apple-tv.json'),
                    'TV_ACTIVE_TV_CONFIG': str(self.root/'active.json'), 'TV_STREAM_PORT': '8766'}

    def run_setting(self, *args):
        return subprocess.run([sys.executable, str(Path(__file__).with_name('settings.py')), *args],
                              env=self.env, text=True, capture_output=True, timeout=5)

    def test_selector_saves_choice_but_keeps_active_session_and_preferences(self):
        devices = [{'name': 'TV Alpha', 'host': '192.0.2.10', 'identifiers': ['alpha']},
                   {'name': 'TV Beta', 'host': '192.0.2.11', 'identifiers': ['beta']}]
        (self.config/'apple-tvs.json').write_text(json.dumps(devices))
        self.assertEqual(self.run_setting('configure','old.local','Old TV').returncode, 0)
        self.assertEqual(self.run_setting('snapshot').returncode, 0)
        active = (self.root/'active.json').read_bytes()
        rows = self.run_setting('menu').stdout.splitlines()
        key = next(row.split('\t')[0].split(':')[1] for row in rows if 'TV Beta' in row)
        self.assertEqual(self.run_setting('select',key).returncode, 0)
        chosen = json.loads((self.config/'apple-tv.json').read_text())
        self.assertEqual(chosen['identifiers'], ['beta'])
        self.assertEqual(chosen['streamPort'], 8766)
        self.assertEqual((self.root/'active.json').read_bytes(), active)

    def test_empty_settings_still_offer_discovery_without_doing_it(self):
        result = self.run_setting('menu')
        self.assertEqual(result.returncode, 0)
        self.assertIn('nog niet gekozen', result.stdout)
        self.assertIn('scan\t', result.stdout)
        self.assertFalse((self.config/'apple-tv.json').exists())

    def test_bad_selection_never_changes_config(self):
        self.run_setting('configure','alpha.local','Alpha')
        before = (self.config/'apple-tv.json').read_bytes()
        self.assertNotEqual(self.run_setting('select','not-a-device').returncode, 0)
        self.assertEqual((self.config/'apple-tv.json').read_bytes(), before)

    def test_dev_import_preserves_existing_data_and_excludes_credentials(self):
        stable = self.root/'.config/tv'
        stable.mkdir(parents=True)
        (stable/'favorites').write_text('alpha\n')
        (stable/'priority-favorites').write_text('alpha\n')
        (stable/'remote').mkdir()
        (stable/'remote/pyatv.conf').write_text('private fixture')
        (self.config/'favorites').write_text('beta\n')
        result = self.run_setting('dev-copy')
        self.assertEqual(result.returncode, 0)
        self.assertEqual((self.config/'favorites').read_text(), 'beta\n')
        self.assertEqual((self.config/'priority-favorites').read_text(), 'alpha\n')
        self.assertFalse((self.config/'remote').exists())
        self.assertEqual((stable/'favorites').read_text(), 'alpha\n')

    def test_dev_section_hidden_in_stable(self):
        self.env['TV_DEV_MODE'] = ''
        self.assertNotIn('dev-copy', self.run_setting('menu').stdout)
        self.assertNotEqual(self.run_setting('dev-copy').returncode, 0)

    def test_toggle_changes_only_auto_start(self):
        self.run_setting('configure', 'alpha.local', 'Alpha')
        self.run_setting('auto')
        config = json.loads((self.config/'apple-tv.json').read_text())
        self.assertFalse(config['autoStart'])
        self.assertEqual(config['host'], 'alpha.local')


if __name__ == '__main__':
    unittest.main()
