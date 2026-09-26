"""Local configuration only. This module never contacts an Apple TV."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(os.environ.get("TV_CONFIG_DIR", Path.home() / ".config/tv"))
CONFIG = Path(os.environ.get("TV_APPLE_TV_CONFIG", ROOT / "apple-tv.json"))


def load():
    try:
        return json.loads(CONFIG.read_text())
    except FileNotFoundError:
        return {"port": 80, "streamPort": int(os.environ.get("TV_STREAM_PORT", 8765)), "autoStart": True}


def save(config):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG.parent, prefix=".apple-tv-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        os.replace(tmp, CONFIG)
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


if __name__ == "__main__":
    try:
        if len(sys.argv) < 3 or sys.argv[1] != "configure":
            raise ValueError("Gebruik: tv configure <host> [naam]")
        configure(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
