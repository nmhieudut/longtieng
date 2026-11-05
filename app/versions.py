"""Saved states of a project's edit (timeline, texts, stickers, look), kept in versions.json next to the project.

A version is made after each export, before a big automatic change, and when the user asks. Restoring one first
saves the current state, so a restore can itself be undone."""

import json
import secrets
import time

from . import store

KEEP = 20
# what a version holds from the project settings: the look and the sound, not the language or the voice
SETTING_KEYS = ("music", "frame", "color", "logo", "export", "sub_style", "sub_size", "sub_margin", "mask", "audio_mode", "orig_volume", "subtitle_mode")


def _file(pid: str):
    return store.pdir(pid) / "versions.json"


def _load(pid: str) -> list[dict]:
    try:
        return json.loads(_file(pid).read_text("utf-8"))
    except (OSError, ValueError):
        return []


def list_versions(pid: str) -> list[dict]:
    return [{"id": v["id"], "at": v["at"], "label": v["label"], "clips": len((v.get("timeline") or {}).get("clips") or []) or 1,
             "overlays": len(v.get("overlays") or [])} for v in _load(pid)]


def snapshot(pid: str, label: str) -> dict:
    p = store.load(pid)
    v = {"id": secrets.token_hex(4), "at": time.time(), "label": label[:60], "timeline": p.get("timeline"),
         "overlays": p.get("overlays") or [], "settings": {k: p["settings"][k] for k in SETTING_KEYS if k in p["settings"]}}
    vs = [v] + _load(pid)
    tmp = _file(pid).with_suffix(".tmp")
    tmp.write_text(json.dumps(vs[:KEEP], ensure_ascii=False), "utf-8")
    tmp.replace(_file(pid))
    return {"id": v["id"], "at": v["at"], "label": v["label"]}


def restore(pid: str, vid: str) -> dict | None:
    v = next((x for x in _load(pid) if x["id"] == vid), None)
    if not v:
        return None
    snapshot(pid, "Trước khi khôi phục")

    def fn(q):
        if v.get("timeline"):
            q["timeline"] = v["timeline"]
        else:
            q.pop("timeline", None)
        if v.get("overlays"):
            q["overlays"] = v["overlays"]
        else:
            q.pop("overlays", None)
        q["settings"].update(v.get("settings") or {})
        q["edited_at"] = time.time()
    return store.update(pid, fn)
