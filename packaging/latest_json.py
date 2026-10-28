"""Write latest.json for a release: python packaging/latest_json.py v0.3.1 <assets dir> <notes file>"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tag, assets, notes = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
version = tag.lstrip("v")
base = f"https://github.com/nmhieudut/longtieng/releases/download/{tag}/"


def entry(pattern: str) -> dict:
    f = next(assets.glob(pattern))
    return {"url": base + f.name, "size": f.stat().st_size, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}


print(json.dumps({
    "version": version,
    "shell": (ROOT / "packaging" / "SHELL_VERSION").read_text().strip(),
    "notes": notes.read_text().strip(),
    "patch": entry(f"Longtieng-{version}-patch.zip"),
    "mac": entry(f"Longtieng-{version}-mac-arm64.zip"),
    "windows": entry(f"Longtieng-{version}-windows-x64.zip"),
}, ensure_ascii=False, indent=2))
