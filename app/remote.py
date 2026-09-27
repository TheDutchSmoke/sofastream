#!/usr/bin/env python3
"""Pair once; wake and launch VLC only on an explicit playback request.

Uses pyatv's public API (pinned in remote-requirements.txt). No background task.
https://pyatv.dev/development/scan_pair_and_connect/
https://pyatv.dev/development/storage/
"""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import termios

import pyatv
from pyatv.const import Protocol, FeatureName, FeatureState
from pyatv.const import OperatingSystem
from pyatv.storage.file_storage import FileStorage
from settings import load as load_config, save as save_config, device_key, remote_identity, app_command

ROOT = Path(__file__).resolve().parent
CONFIG_DIR = Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv"))
PRIVATE = CONFIG_DIR / "remote"
PAIR_HINT = f"Automatische start nog niet gekoppeld. Voer eenmalig '{app_command()} pair' uit (pincode op tv)."


class RemoteError(Exception):
    """A safe, user-facing message (never includes protocol credentials)."""


def save_private(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".remote-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class PrivateStorage(FileStorage):
    def _save_file(self, dumped):
        save_private(Path(self._filename), dumped)


async def read_pin():
    """Keep the event loop responsive to Ctrl-C without an input worker thread."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    hidden = termios.tcgetattr(fd)
    hidden[3] &= ~termios.ECHO

    def ready():
        line = sys.stdin.readline()
        if not future.done():
            future.set_result(line.strip())

    print("Pincode op de Apple TV (leeg = annuleren): ", end="", flush=True)
    try:
        termios.tcsetattr(fd, termios.TCSANOW, hidden)
        loop.add_reader(fd, ready)
        return await future
    finally:
        loop.remove_reader(fd)
        termios.tcsetattr(fd, termios.TCSANOW, original)
        print()


async def discover(config, storage, identity=None):
    loop = asyncio.get_running_loop()
    try:
        addresses = await asyncio.wait_for(loop.getaddrinfo(
            config["host"], None, family=socket.AF_INET, type=socket.SOCK_STREAM), 5)
        host = addresses[0][4][0]
        # Scan the configured host only. Other protocols supply stable device IDs;
        # only Companion will be connected for remote control.
        devices = await asyncio.wait_for(pyatv.scan(
            loop, hosts=[host], timeout=5, storage=storage), 8)
    except (OSError, TimeoutError, KeyError):
        devices = []
    identifiers = (identity or {}).get("identifiers") or config.get("identifiers")
    if identifiers:
        known = set(identifiers)
        devices = [device for device in devices if known.intersection(device.all_identifiers)]
        if not devices:
            devices = await asyncio.wait_for(pyatv.scan(
                loop, identifier=known, timeout=5, storage=storage), 8)
    else:
        devices = [device for device in devices if device.name == config["name"]]
    if len(devices) != 1:
        raise RemoteError("De ingestelde Apple TV is niet eenduidig gevonden; geen bedieningsopdracht verzonden.")
    device = devices[0]
    if not device.get_service(Protocol.Companion):
        raise RemoteError("Deze Apple TV biedt geen Companion-afstandsbediening aan.")
    return device


def pairing_file(config):
    return PRIVATE / "devices" / f"{device_key(config)}.json"


def remember_device(config, device):
    """Keep pairing and the selected address stable across DHCP/ID-list changes."""
    config.update(host=str(device.address), identifiers=sorted(device.all_identifiers))
    save_private(pairing_file(config), {
        "identifiers": config["identifiers"], "name": device.name, "host": config["host"],
    })
    save_config(config)


async def list_devices():
    devices = await pyatv.scan(asyncio.get_running_loop(), timeout=5)
    print(json.dumps([{
        "name": device.name,
        "host": str(device.address),
        "identifiers": sorted(device.all_identifiers),
    } for device in devices if device.device_info.operating_system == OperatingSystem.TvOS
       and device.get_service(Protocol.Companion)]))


async def pair(config, storage):
    if not sys.stdin.isatty():
        raise RemoteError(f"Start '{app_command()} pair' in je terminal om de pincode in te voeren.")
    print("Apple TV koppelen: er verschijnt zo een pincode op de tv. Ctrl-C annuleert.", flush=True)
    device = await discover(config, storage)
    handler = await pyatv.pair(device, Protocol.Companion, asyncio.get_running_loop(),
                              storage=storage, name="tv op Mac")
    try:
        await asyncio.wait_for(handler.begin(), 15)
        pin = await read_pin()
        if not pin:
            raise RemoteError("Koppelen geannuleerd.")
        if not re.fullmatch(r"[0-9]{4}", pin):
            raise RemoteError(f"Gebruik de vier cijfers op de tv. Start '{app_command()} pair' opnieuw.")
        handler.pin(int(pin))
        await asyncio.wait_for(handler.finish(), 15)
        if not handler.has_paired:
            raise RemoteError(f"Koppelen niet bevestigd. Start '{app_command()} pair' opnieuw.")
        await storage.save()
        config["autoStart"] = True
        remember_device(config, device)
        print("Gekoppeld. Een kanaal kiezen wekt voortaan zo nodig de Apple TV en opent VLC.")
    finally:
        await handler.close()


async def wake_vlc(config, storage):
    identity = remote_identity(config)
    if not identity:
        raise RemoteError(PAIR_HINT)
    device = await discover(config, storage, identity)
    companion = device.get_service(Protocol.Companion)
    if not companion.credentials:
        raise RemoteError(PAIR_HINT)
    for service in device.services:
        service.enabled = service.protocol == Protocol.Companion
    atv = await asyncio.wait_for(pyatv.connect(
        device, asyncio.get_running_loop(), storage=storage), 12)
    try:
        for feature in (FeatureName.TurnOn, FeatureName.AppList, FeatureName.LaunchApp):
            if atv.features.get_feature(feature).state != FeatureState.Available:
                raise RemoteError("Deze Apple TV ondersteunt automatisch wekken en apps openen niet.")
        await asyncio.wait_for(atv.power.turn_on(), 8)
        await asyncio.sleep(1)
        # Resolve the installed app by its name instead of navigating Home Screen
        # tiles or hard-coding their positions. An explicit appId can override it.
        # Companion can answer before tvOS has finished waking. Retry read-only
        # app discovery, never replay a launch or a playback command blindly.
        apps = []
        for attempt in range(3):
            try:
                apps = await asyncio.wait_for(atv.apps.app_list(), 4)
                if apps:
                    break
            except (TimeoutError, pyatv.exceptions.ProtocolError):
                if attempt == 2:
                    raise RemoteError("Apple TV is nog niet klaar om VLC te openen. Probeer opnieuw.") from None
            if attempt < 2:
                await asyncio.sleep(1)
        wanted = config.get("appId")
        matches = [app for app in apps if (app.identifier == wanted if wanted
                                          else (app.name or "").casefold() == "vlc")]
        if len(matches) != 1:
            raise RemoteError("VLC niet eenduidig gevonden op de Apple TV. Controleer de installatie.")
        await asyncio.wait_for(atv.apps.launch_app(matches[0].identifier), 10)
        remember_device(config, device)
        return {"host": config["host"]}
    finally:
        tasks = atv.close()
        if tasks:
            await asyncio.wait(tasks, timeout=3)


async def main(action):
    if action == "scan":
        await list_devices()
        return
    config = load_config()
    if not config.get("host"):
        raise RemoteError("Kies eerst een Apple TV via Instellingen → Apple TV kiezen.")
    storage = PrivateStorage(str(PRIVATE / "pyatv.conf"), asyncio.get_running_loop())
    await storage.load()
    if action == "resolve":
        device = await discover(config, storage)
        config["host"] = str(device.address)
        save_config(config)
        print(json.dumps({"host": config["host"]}))
    elif action == "pair":
        await pair(config, storage)
    else:
        print(json.dumps(await wake_vlc(config, storage)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apple TV koppelen of wakker maken en VLC openen.")
    parser.add_argument("action", choices=("pair", "wake-vlc", "scan", "resolve"))
    args = parser.parse_args()
    # Protocol errors may contain private pairing material; show safe messages.
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main(args.action))
    except (KeyboardInterrupt, EOFError):
        print("Koppelen geannuleerd." if args.action == "pair" else "Starten geannuleerd.", file=sys.stderr)
        sys.exit(130)
    except RemoteError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    except TimeoutError:
        print("Apple TV reageert te traag. Probeer later opnieuw.", file=sys.stderr)
        sys.exit(1)
    except Exception:
        print(f"Apple TV-bediening mislukt. Controleer het netwerk; koppel zo nodig opnieuw met '{app_command()} pair'.",
              file=sys.stderr)
        sys.exit(1)
