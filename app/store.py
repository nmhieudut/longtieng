"""Project storage: one folder per project with a project.json."""

import copy
import json
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from .config import DATA_DIR, DEFAULT_SETTINGS, TARGET_LANGS, default_voice, voice_ok

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()
_ID_RE = re.compile(r"^[a-z0-9]{10}$")


def _lock(pid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(pid, threading.RLock())


def valid_id(pid: str) -> bool:
    return bool(_ID_RE.match(pid))


def pdir(pid: str) -> Path:
    if not valid_id(pid):
        raise KeyError(pid)
    return DATA_DIR / pid


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif k in out:
            out[k] = v
    return out


def clean_settings(s: dict) -> dict:
    s = _merge(DEFAULT_SETTINGS, s)
    if s["target"] not in TARGET_LANGS:
        s["target"] = "vi"
    if not voice_ok(s["voice"], s["target"]):  # e.g. the language was changed: use that language's default voice
        s["voice"] = default_voice(s["target"])
    s["rate"] = min(1.3, max(0.8, float(s["rate"])))
    s["orig_volume"] = min(1.0, max(0.0, float(s["orig_volume"])))
    s["sub_size"] = min(2.0, max(0.5, float(s["sub_size"])))
    s["sub_margin"] = min(50, max(0, float(s["sub_margin"])))
    mu = s["music"]
    mu["volume"] = min(1.0, max(0.0, float(mu["volume"])))
    mu["start"] = max(0.0, float(mu["start"]))
    mu["duck"] = bool(mu["duck"])
    if mu["track"] is not None and not isinstance(mu["track"], str):
        mu["track"] = None
    m = s["mask"]
    m["bottom"] = min(90, max(0, float(m["bottom"])))
    m["height"] = min(50, max(2, float(m["height"])))
    fr = s["frame"]
    fr["zoom"] = min(2.0, max(1.0, float(fr["zoom"])))
    lg = s["logo"]
    lg["text"] = str(lg["text"] or "").strip()[:40]
    lg["size"] = min(0.4, max(0.05, float(lg["size"])))
    lg["opacity"] = min(1.0, max(0.2, float(lg["opacity"])))
    if lg["image"] is not None and not isinstance(lg["image"], str):
        lg["image"] = None
    return s


# Settings worth carrying over to new videos ("Lưu làm mặc định"); the subtitle band is per video.
DEFAULT_KEYS = ("lang", "target", "voice", "rate", "audio_mode", "orig_volume", "subtitle_mode", "sub_size", "sub_margin",
                "music", "frame", "logo", "sub_style", "script")


def user_defaults() -> dict:
    from .config import user_settings
    d = user_settings().get("defaults") or {}
    out = {k: d[k] for k in DEFAULT_KEYS if k in d}
    if isinstance(d.get("mask"), dict):
        out["mask"] = {k: d["mask"][k] for k in ("auto", "style") if k in d["mask"]}
    return out


def new_settings(given: dict) -> dict:
    """Settings for a new video: built-in defaults < the user's saved defaults < what the form sent."""
    return clean_settings(_merge(_merge(DEFAULT_SETTINGS, user_defaults()), given or {}))


def create(title: str, source: dict, settings: dict, auto_render: bool = False) -> dict:
    pid = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
    d = DATA_DIR / pid
    (d / "tts").mkdir(parents=True)
    (d / "out").mkdir()
    proj = {
        "id": pid,
        "title": title,
        "created": time.time(),
        "source": source,
        "media": None,
        "settings": settings,
        "status": {"stage": "queued", "progress": 0, "message": "Đang chờ xử lý…", "error": None},
        "warnings": [],
        "segments": [],
        "outputs": {},
        "auto_render": bool(auto_render),  # batch: export as soon as the translation is ready
    }
    save(proj)
    return proj


def load(pid: str) -> dict:
    with _lock(pid):
        p = json.loads((pdir(pid) / "project.json").read_text("utf-8"))
    # projects made by older versions lack newer settings keys
    p["settings"] = clean_settings(p["settings"])
    return p


def save(proj: dict) -> None:
    with _lock(proj["id"]):
        p = pdir(proj["id"]) / "project.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(p)


def update(pid: str, fn) -> dict:
    """Load, mutate with fn(proj), save — atomically per project."""
    with _lock(pid):
        proj = load(pid)
        fn(proj)
        save(proj)
        return proj


def set_status(pid: str, stage: str, progress: float | None = None, message: str = "", error: str | None = None):
    def fn(p):
        p["status"] = {
            "stage": stage,
            "progress": round(progress, 3) if progress is not None else None,
            "message": message,
            "error": error,
        }
    return update(pid, fn)


def list_all() -> list[dict]:
    out = []
    for d in DATA_DIR.iterdir():
        f = d / "project.json"
        if f.exists():
            try:
                p = json.loads(f.read_text("utf-8"))
            except json.JSONDecodeError:
                continue
            out.append({
                "id": p["id"],
                "title": p["title"],
                "created": p["created"],
                "status": p["status"],
                "duration": (p.get("media") or {}).get("duration"),
                "segments": len(p["segments"]),
                "has_final": bool(p["outputs"].get("final")),
            })
    return sorted(out, key=lambda x: -x["created"])


def delete(pid: str) -> None:
    shutil.rmtree(pdir(pid), ignore_errors=True)
