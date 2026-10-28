"""Shared background-music library: data/music/<id>.<ext> + index.json."""

import json
import re
import secrets
import threading
from pathlib import Path

from .config import DATA_DIR
from .media import MediaError, probe_audio

MUSIC_DIR = DATA_DIR.parent / "music"
MUSIC_EXT = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}
MAX_MB = 50
_ID = re.compile(r"^[a-z0-9]{10}$")
_lock = threading.Lock()


def _index_path() -> Path:
    return MUSIC_DIR / "index.json"


def _read() -> list[dict]:
    p = _index_path()
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def _write(items: list[dict]) -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _index_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(_index_path())


def list_all() -> list[dict]:
    return _read()


def get(mid: str) -> dict | None:
    if not mid or not _ID.match(mid):
        return None
    return next((m for m in _read() if m["id"] == mid), None)


def path(m: dict) -> Path:
    return MUSIC_DIR / m["file"]


def add(name: str, ext: str, fileobj) -> dict:
    ext = ext.lower()
    if ext not in MUSIC_EXT:
        raise MediaError(f"Định dạng {ext or '?'} không hỗ trợ. Dùng mp3, m4a, wav, ogg, flac.")
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    mid = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
    dst = MUSIC_DIR / f"{mid}{ext}"
    size, limit = 0, MAX_MB * 1024 * 1024
    try:
        with dst.open("wb") as f:
            while chunk := fileobj.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise MediaError(f"File nhạc lớn hơn {MAX_MB}MB.")
                f.write(chunk)
        duration = probe_audio(dst)
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    item = {"id": mid, "name": (Path(name).stem or "Nhạc")[:100], "file": dst.name, "duration": round(duration, 2)}
    with _lock:
        _write(_read() + [item])
    return item


def delete(mid: str) -> bool:
    with _lock:
        items = _read()
        m = next((x for x in items if x["id"] == mid), None)
        if not m:
            return False
        path(m).unlink(missing_ok=True)
        _write([x for x in items if x["id"] != mid])
    return True
