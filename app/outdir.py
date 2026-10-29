"""Where finished videos go besides the project folder: a folder the user picks.

A Google Drive / OneDrive / Dropbox folder works too when its desktop client is installed, because
those show up as ordinary folders and sync by themselves.
"""

import shutil
import sys
import time
from pathlib import Path

from .config import IS_WIN, user_settings


def current() -> Path | None:
    raw = (user_settings().get("output_dir") or "").strip()
    return Path(raw) if raw else None


def validate(raw: str) -> Path:
    """Turn what the user typed into a usable folder (created if missing), or raise ValueError."""
    raw = raw.strip().strip('"')
    p = Path(raw).expanduser()
    if not p.is_absolute():
        raise ValueError("Hãy nhập đường dẫn đầy đủ, ví dụ /Users/ban/Movies hoặc D:\\Video.")
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".longtieng-{int(time.time())}.tmp"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"Không ghi được vào thư mục này ({e.strerror or e}). Chọn thư mục khác.") from e
    return p


def suggestions() -> list[dict]:
    """Folders worth offering: cloud-drive folders that are mounted on this machine."""
    found: list[dict] = []
    home = Path.home()
    names = ("My Drive", "Drive của tôi")
    if sys.platform == "darwin":
        for root in sorted((home / "Library" / "CloudStorage").glob("GoogleDrive-*")):
            for n in names:
                if (root / n).is_dir():
                    found.append({"label": f"Google Drive · {root.name.removeprefix('GoogleDrive-')}", "path": str(root / n)})
    elif IS_WIN:
        for letter in "GHIJKLMNOPQRSTUVWXYZDEF":
            for n in names:
                p = Path(f"{letter}:\\{n}")
                try:
                    if p.is_dir():
                        found.append({"label": f"Google Drive ({letter}:)", "path": str(p)})
                except OSError:
                    pass
    if (home / "Google Drive").is_dir():
        found.append({"label": "Google Drive", "path": str(home / "Google Drive")})
    for label, p in (("OneDrive", home / "OneDrive"), ("Dropbox", home / "Dropbox")):
        if p.is_dir():
            found.append({"label": label, "path": str(p)})
    seen, out = set(), []
    for f in found:
        if f["path"] not in seen:
            seen.add(f["path"])
            out.append(f)
    return out


def _safe_name(title: str, pid: str) -> str:
    stem = "".join(c for c in title if c.isalnum() or c in " -_")[:60].strip()
    return f"{stem or pid}_longtieng.mp4"


def deliver(src: Path, title: str, pid: str, previous: str | None = None) -> dict:
    """Copy the exported video into the chosen folder. Returns {"path", "at"} or {"error", "at"}.

    Exporting the same project again replaces its earlier copy instead of piling up files."""
    folder = current()
    if folder is None:
        return {}
    try:
        folder = validate(str(folder))
        dest = folder / _safe_name(title, pid)
        old = Path(previous) if previous else None
        if old and old.parent == folder and old.name == dest.name:
            pass  # same project, same place: overwrite
        else:
            n = 2
            while dest.exists():
                dest = folder / f"{_safe_name(title, pid)[:-4]} ({n}).mp4"
                n += 1
        tmp = dest.with_name(dest.name + ".part")  # a sync client must not upload a half-copied file
        shutil.copyfile(src, tmp)
        tmp.replace(dest)
        return {"path": str(dest), "at": time.time()}
    except (OSError, ValueError) as e:
        return {"error": f"Không lưu được vào thư mục đã chọn: {e}", "at": time.time()}
