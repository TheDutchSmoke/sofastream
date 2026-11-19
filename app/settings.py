"""Local configuration only. This module never contacts an Apple TV."""
import json
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata

ROOT = Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv"))
CONFIG = Path(os.environ.get("TV_APPLE_TV_CONFIG", ROOT / "apple-tv.json"))
DEV = os.environ.get("TV_DEV_MODE") == "1"
DEVICES = ROOT / "apple-tvs.json"


def app_command():
    return "sofastream@dev" if DEV else "tv"


def remote_identity(config):
    """Read only our local pairing markers; never discover or connect here."""
    if not config.get("host"):
        return None
    private = ROOT / "remote"
    paths = [private / "devices" / f"{device_key(config)}.json", private / "device.json"]
    paths.extend(sorted((private / "devices").glob("*.json")))
    identifiers = set(config.get("identifiers") or [])
    for path in dict.fromkeys(paths):
        try:
            identity = json.loads(path.read_text())
            matches = (identifiers.intersection(identity.get("identifiers") or [])
                       if identifiers else identity.get("host") == config["host"])
            if matches:
                return identity
        except (OSError, ValueError, AttributeError):
            continue
    return None


def load():
    try:
        return json.loads(CONFIG.read_text())
    except FileNotFoundError:
        return {"port": 80, "streamPort": int(os.environ.get("TV_STREAM_PORT", 8765)), "autoStart": True}


def save(config, destination=None):
    destination = destination or CONFIG
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destination.parent, prefix=".apple-tv-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, destination)
    finally:
        Path(tmp).unlink(missing_ok=True)


def configure(host, name=""):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}", host or ""):
        raise ValueError("Gebruik een hostnaam of IPv4-adres, zonder http:// of poort.")
    current = load()
    current.update(host=host, name=name or host)
    current.pop("identifiers", None)
    save(current)
    print(f"Apple TV ingesteld: {current['name']}. Geldt vanaf je volgende kanaalkeuze.")


def clean(value):
    return " ".join("".join(c if not unicodedata.category(c).startswith("C") else " "
                            for c in str(value)).split())


def device_key(device):
    identity = sorted(device.get("identifiers") or [device["host"]])
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]


def devices():
    try:
        known = json.loads(DEVICES.read_text())
    except FileNotFoundError:
        known = []
    current = load()
    if current.get("host"):
        known = [device for device in known if device_key(device) != device_key(current)] + [current]
    return sorted(known, key=lambda d: (clean(d["name"]).casefold(), d["host"]))


def scan():
    python = os.environ.get("TV_REMOTE_PYTHON")
    if not python:
        raise ValueError("Apple TV-ondersteuning ontbreekt. Installeer SofaStream opnieuw.")
    result = subprocess.run([python, str(Path(__file__).with_name("remote.py")), "scan"],
                            text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError("Apple TVs zoeken mislukt. Controleer het lokale netwerk; je selectie blijft behouden.")
    found = json.loads(result.stdout)
    known = {device_key(d): d for d in devices()}
    for device in found:
        # Only accept discovery's small public record, never protocol credentials.
        record = {key: device[key] for key in ("name", "host", "identifiers")}
        if not record["identifiers"]:
            continue
        known[device_key(record)] = record
    save(list(known.values()), DEVICES)
    print(f"{len(found)} Apple TVs gevonden. Kies het gewenste apparaat.")


def select(key):
    matches = [d for d in devices() if device_key(d) == key]
    if len(matches) != 1:
        raise ValueError("Apple TV niet meer in de lijst. Zoek opnieuw.")
    current = load()
    chosen = matches[0]
    current.update({k: chosen[k] for k in ("name", "host")})
    current["identifiers"] = chosen.get("identifiers", [])
    save(current)
    print(f"Gekozen: {clean(chosen['name'])}. Geldt vanaf je volgende kanaalkeuze.")


def menu():
    current = load()
    print(f"header\tAPPLE TV · {clean(current.get('name', 'nog niet gekozen'))}")
    print("header\tSelectie geldt bij de volgende start · Esc terug")
    selected = device_key(current) if current.get("host") else None
    for device in devices():
        key = device_key(device)
        mark = "★" if key == selected else "○"
        print(f"device:{key}\t{mark} {clean(device['name'])} · {clean(device['host'])}")
    print("scan\t↻ Zoek Apple TVs op het netwerk")
    paired = remote_identity(current) and (ROOT / "remote/pyatv.conf").is_file()
    pairing = "koppeling opgeslagen · opnieuw koppelen" if paired else "eenmalig koppelen nodig"
    print(f"pair\t⌘ Automatische start: {pairing} (pincode op tv)")
    enabled = current.get("autoStart", True)
    print(f"auto\tAutomatisch wakker maken en VLC openen: {'aan' if enabled else 'uit'}")
    if twitch_login_present():
        login = "Twitch-login gevonden"
    elif streamlink_config_login():
        login = "login uit je Streamlink-config"
    else:
        login = "geen Twitch-login, max 1080p"
    print(f"hq\t2K (1440p, H.265; Apple TV 4K): {'aan' if current.get('twitch2k', False) else 'uit'} · {login}")
    if DEV:
        print("dev-info\tDEV · Versie en gescheiden testomgeving bekijken")
        print("dev-copy\tDEV · Ontbrekende voorkeuren uit stabiel overnemen")


def twitch_login_present():
    """Only checks that the Keychain item exists; never reads the token itself."""
    service = os.environ.get("TV_TWITCH_KEYCHAIN_SERVICE", "streamlink-twitch-auth")
    security = os.environ.get("TV_SECURITY_BIN", "/usr/bin/security")
    try:
        return subprocess.run([security, "find-generic-password", "-a", "twitch", "-s", service],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def streamlink_config_login():
    """True if the user's own Streamlink config sends a Twitch login. Streamlink
    reads those files for SofaStream too; only the option name is matched."""
    for folder in (Path.home() / "Library/Application Support/streamlink", Path.home() / ".config/streamlink"):
        for name in ("config", "config.twitch"):
            try:
                lines = (folder / name).read_text(errors="replace").splitlines()
            except OSError:
                continue
            if any(re.match(r"\s*(--)?twitch-api-header\s*=\s*Authorization\b", line) for line in lines):
                return True
    return False


def toggle_2k():
    current = load()
    current["twitch2k"] = not current.get("twitch2k", False)
    save(current)
    state = "aan" if current["twitch2k"] else "uit"
    has_login = twitch_login_present() or streamlink_config_login()
    hint = "" if not current["twitch2k"] or has_login else " Zonder Twitch-login blijft het maximaal 1080p."
    print(f"2K {state}. Geldt vanaf je volgende kanaalkeuze.{hint}")


def dev_info():
    if not DEV:
        raise ValueError("Deze sectie is alleen beschikbaar in sofastream@dev.")
    version = Path(__file__).parent.parent.joinpath("VERSION").read_text().strip()
    print(f"SofaStream {version} · development")
    print(f"Instellingen: {ROOT}")
    print(f"Streamlink-poort: {os.environ.get('TV_STREAM_PORT', '8766')}")
    print("Bijwerken: brew update && brew upgrade sofastream@dev")


def copy_stable():
    if not DEV:
        raise ValueError("Alleen beschikbaar in sofastream@dev.")
    stable = Path.home() / ".config/tv"
    if stable.resolve() == ROOT.resolve():
        raise ValueError("Dev moet een eigen instellingenmap gebruiken.")
    ROOT.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in ("apple-tv.json", "favorites", "priority-favorites"):
        source, target = stable / name, ROOT / name
        if source.is_file() and not target.exists():
            # Exclusive creation prevents overwriting a concurrently created file.
            try:
                with target.open("x") as handle:
                    handle.write(source.read_text())
                target.chmod(0o600)
                copied += 1
            except FileExistsError:
                pass
    print(f"{copied} ontbrekende voorkeurbestanden overgenomen. Bestaande devgegevens behouden.")


def snapshot():
    destination = os.environ.get("TV_ACTIVE_TV_CONFIG")
    if not destination:
        raise ValueError("Actieve streamconfiguratie ontbreekt.")
    save(load(), Path(destination))


if __name__ == "__main__":
    try:
        action = sys.argv[1] if len(sys.argv) > 1 else "menu"
        if action == "configure":
            configure(sys.argv[2] if len(sys.argv) > 2 else "", sys.argv[3] if len(sys.argv) > 3 else "")
        elif action == "select": select(sys.argv[2])
        elif action == "scan": scan()
        elif action == "menu": menu()
        elif action == "dev-info": dev_info()
        elif action == "dev-copy": copy_stable()
        elif action == "snapshot": snapshot()
        elif action == "hq": toggle_2k()
        elif action == "hq-enabled": print(1 if load().get("twitch2k", False) else 0)
        elif action == "auto":
            current = load()
            current["autoStart"] = not current.get("autoStart", True)
            save(current)
            print(f"Automatisch starten {'aan' if current['autoStart'] else 'uit'}.")
        else: raise ValueError("Onbekende instelling.")
    except (ValueError, OSError, subprocess.TimeoutExpired, IndexError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
