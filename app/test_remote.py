"""Exercise wake/pair flows with real pyatv storage and mocked device APIs only."""
import asyncio
from ipaddress import ip_address
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import pyatv
from pyatv.conf import AppleTV, ManualService
from pyatv.const import FeatureState, Protocol

import remote
import settings


def device(host="192.0.2.20", identifier="living-room"):
    result = AppleTV(ip_address(host), "Living Room")
    result.add_service(ManualService(identifier, Protocol.Companion, 1234, {},
                                    credentials="fixture-credential"))
    result.add_service(ManualService("airplay-" + identifier, Protocol.AirPlay, 7000, {}))
    return result


class RemoteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for target, name, value in [
            (settings, "ROOT", self.root), (settings, "CONFIG", self.root / "apple-tv.json"),
            (settings, "DEV", True), (remote, "PRIVATE", self.root / "remote"),
            (remote, "PAIR_HINT", "Voer eenmalig 'sofastream@dev pair' uit (pincode op tv)."),
        ]:
            context = patch.object(target, name, value)
            context.start()
            self.addCleanup(context.stop)
        # A missed mock is a test failure, never an accidental hardware request.
        self.scan = patch.object(pyatv, "scan", AsyncMock(side_effect=AssertionError("unexpected scan")))
        self.connect = patch.object(pyatv, "connect", AsyncMock(side_effect=AssertionError("unexpected connect")))
        self.pair = patch.object(pyatv, "pair", AsyncMock(side_effect=AssertionError("unexpected pair")))
        for context in (self.scan, self.connect, self.pair):
            context.start()
            self.addCleanup(context.stop)
        self.config = {"host": "192.0.2.10", "name": "Living Room", "port": 80,
                       "streamPort": 8766, "identifiers": ["living-room"], "autoStart": True}
        self.storage = remote.PrivateStorage(str(self.root / "remote/pyatv.conf"), asyncio.get_running_loop())

    def mark_paired(self):
        remote.save_private(remote.pairing_file(self.config), self.config)

    def controller(self, apps=None):
        return SimpleNamespace(
            features=SimpleNamespace(get_feature=Mock(return_value=SimpleNamespace(state=FeatureState.Available))),
            power=SimpleNamespace(turn_on=AsyncMock()),
            apps=SimpleNamespace(app_list=AsyncMock(return_value=apps if apps is not None else [
                SimpleNamespace(name="VLC", identifier="org.videolan.vlc")]), launch_app=AsyncMock()),
            close=Mock(return_value=set()),
        )

    async def test_missing_pairing_never_scans_or_connects(self):
        with self.assertRaisesRegex(remote.RemoteError, "sofastream@dev pair"):
            await remote.wake_vlc(self.config, self.storage)
        pyatv.scan.assert_not_called()
        pyatv.connect.assert_not_called()
        self.assertFalse((self.root / "apple-tv.json").exists())

    async def test_wake_retries_app_discovery_then_launches_once_and_saves_new_address(self):
        self.mark_paired()
        found = device()
        atv = self.controller()
        atv.apps.app_list.side_effect = [TimeoutError(), [], [SimpleNamespace(name="VLC", identifier="org.videolan.vlc")]]
        pyatv.connect.side_effect = None
        pyatv.connect.return_value = atv
        with patch.object(remote, "discover", AsyncMock(return_value=found)), patch.object(remote.asyncio, "sleep", AsyncMock()):
            result = await remote.wake_vlc(self.config, self.storage)
        self.assertEqual(result, {"host": "192.0.2.20"})
        atv.power.turn_on.assert_awaited_once_with()
        self.assertEqual(atv.apps.app_list.await_count, 3)
        atv.apps.launch_app.assert_awaited_once_with("org.videolan.vlc")
        atv.close.assert_called_once()
        self.assertTrue(found.get_service(Protocol.Companion).enabled)
        self.assertFalse(found.get_service(Protocol.AirPlay).enabled)
        saved = json.loads((self.root / "apple-tv.json").read_text())
        self.assertEqual(saved["host"], "192.0.2.20")
        self.assertEqual(saved["streamPort"], 8766)
        self.assertIsNotNone(settings.remote_identity(saved))

    async def test_missing_app_or_unsupported_feature_closes_without_launch(self):
        self.mark_paired()
        for unsupported in (False, True):
            atv = self.controller([SimpleNamespace(name="Other App", identifier="other")])
            if unsupported:
                atv.features.get_feature.return_value.state = FeatureState.Unsupported
            pyatv.connect.side_effect = None
            pyatv.connect.return_value = atv
            with patch.object(remote, "discover", AsyncMock(return_value=device())), patch.object(remote.asyncio, "sleep", AsyncMock()):
                with self.assertRaises(remote.RemoteError):
                    await remote.wake_vlc(self.config, self.storage)
            atv.apps.launch_app.assert_not_called()
            atv.close.assert_called_once()
        self.assertFalse((self.root / "apple-tv.json").exists())

    async def test_old_ip_cannot_wake_a_different_device(self):
        wrong, correct = device(identifier="other-room"), device()
        pyatv.scan.side_effect = [[wrong], [correct]]
        dns = AsyncMock(return_value=[(None, None, None, None, ("192.0.2.10", 0))])
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", dns):
            found = await remote.discover(self.config, self.storage)
        self.assertIs(found, correct)
        self.assertEqual(pyatv.scan.await_args_list[1].kwargs["identifier"], {"living-room"})
        pyatv.connect.assert_not_called()

    async def test_storage_round_trip_keeps_credentials_private(self):
        found = device()
        await self.storage.update_settings(found)
        await self.storage.save()
        path = self.root / "remote/pyatv.conf"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        restored = remote.PrivateStorage(str(path), asyncio.get_running_loop())
        await restored.load()
        stored = await restored.get_settings(found)
        self.assertEqual(stored.protocols.companion.credentials, "fixture-credential")

    async def test_pair_success_enables_auto_start_and_pins_identity_without_playback(self):
        self.config["autoStart"] = False
        handler = SimpleNamespace(begin=AsyncMock(), finish=AsyncMock(), close=AsyncMock(), pin=Mock(), has_paired=True)
        pyatv.pair.side_effect = None
        pyatv.pair.return_value = handler
        storage = SimpleNamespace(save=AsyncMock())
        with patch.object(remote.sys.stdin, "isatty", return_value=True), patch.object(remote, "read_pin", AsyncMock(return_value="1234")), patch.object(remote, "discover", AsyncMock(return_value=device())):
            await remote.pair(self.config, storage)
        saved = json.loads((self.root / "apple-tv.json").read_text())
        self.assertTrue(saved["autoStart"])
        self.assertIn("living-room", saved["identifiers"])
        self.assertEqual(saved["host"], "192.0.2.20")
        storage.save.assert_awaited_once()
        handler.pin.assert_called_once_with(1234)
        handler.close.assert_awaited_once()
        pyatv.connect.assert_not_called()

    async def test_pair_cancel_never_saves_or_starts_playback(self):
        handler = SimpleNamespace(begin=AsyncMock(), finish=AsyncMock(), close=AsyncMock(), pin=Mock(), has_paired=False)
        pyatv.pair.side_effect = None
        pyatv.pair.return_value = handler
        storage = SimpleNamespace(save=AsyncMock())
        with patch.object(remote.sys.stdin, "isatty", return_value=True), patch.object(remote, "read_pin", AsyncMock(return_value="")), patch.object(remote, "discover", AsyncMock(return_value=device())):
            with self.assertRaisesRegex(remote.RemoteError, "geannuleerd"):
                await remote.pair(self.config, storage)
        storage.save.assert_not_called()
        handler.finish.assert_not_called()
        handler.close.assert_awaited_once()
        pyatv.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
