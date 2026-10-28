"""Shared logo library: <data>/logos/<id>.<ext> + index.json (same idea as the music library)."""

import json
import re
import secrets
import threading
from pathlib import Path

from .config import DATA_DIR
from .media import MediaError

LOGO_DIR = DATA_DIR.parent / "logos"
LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_MB = 10
_ID = re.compile(r"^[a-z0-9]{10}$")
_lock = threading.Lock()


def _index() -> Path:
    return LOGO_DIR / "index.json"


def list_all() -> list[dict]:
    p = _index()
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def _write(items: list[dict]) -> None:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _index().with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(_index())


def get(lid: str | None) -> dict | None:
    if not lid or not _ID.match(lid):
        return None
    return next((x for x in list_all() if x["id"] == lid), None)


def path(item: dict) -> Path:
    return LOGO_DIR / item["file"]


def add(name: str, ext: str, fileobj) -> dict:
    ext = ext.lower()
    if ext not in LOGO_EXT:
        raise MediaError("Logo phải là ảnh PNG, JPG hoặc WEBP (PNG nền trong suốt đẹp nhất).")
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    lid = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
    dst = LOGO_DIR / f"{lid}{ext}"
    size, limit = 0, MAX_MB * 1024 * 1024
    with dst.open("wb") as f:
        while chunk := fileobj.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                f.close()
                dst.unlink(missing_ok=True)
                raise MediaError(f"Ảnh lớn hơn {MAX_MB}MB.")
            f.write(chunk)
    item = {"id": lid, "name": Path(name).stem[:60] or "Logo", "file": dst.name}
    with _lock:
        _write(list_all() + [item])
    return item


def delete(lid: str) -> None:
    with _lock:
        items = list_all()
        item = next((x for x in items if x["id"] == lid), None)
        if item:
            path(item).unlink(missing_ok=True)
            _write([x for x in items if x["id"] != lid])
