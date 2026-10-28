"""Assemble the app's code folder: the `app` package, the built web UI (web/out), VERSION and meta.json.

    python packaging/make_patch.py --dir build/code     # folder bundled into the app
    python packaging/make_patch.py --zip dist/patch.zip # light-update package for a release
"""

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(dest: Path) -> dict:
    if not (ROOT / "web" / "out" / "index.html").is_file():
        raise SystemExit("web/out missing: run `pnpm build` in web/ first")
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    shutil.copytree(ROOT / "app", dest / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "web" / "out", dest / "web" / "out")
    meta = {
        "version": (ROOT / "packaging" / "VERSION").read_text().strip(),
        "shell": (ROOT / "packaging" / "SHELL_VERSION").read_text().strip(),
    }
    (dest / "VERSION").write_text(meta["version"] + "\n")
    (dest / "meta.json").write_text(json.dumps(meta) + "\n")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--zip", type=Path)
    a = ap.parse_args()
    if a.dir:
        print("code folder:", build(a.dir), "->", a.dir)
    if a.zip:
        tmp = ROOT / "build" / "patch-tmp"
        meta = build(tmp)
        a.zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(a.zip, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(tmp.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(tmp).as_posix())
        shutil.rmtree(tmp)
        print("patch:", meta, "->", a.zip, f"{a.zip.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
