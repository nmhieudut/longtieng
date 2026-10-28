"""FastAPI server: JSON API + static UI. Run with `uv run python -m app`."""

import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from . import dub, jobs, logos, music, ocr, publish, render, store, stt, translate, update
from .frame import ASPECTS
from .media import MediaError
from .config import (
    APP_VERSION, DATA_DIR, DEFAULT_SETTINGS, FROZEN, MAX_DURATION_MIN, MAX_UPLOAD_MB, OPENAI_MODEL, USER_DIR, VOICES, WEB_DIR,
    SOURCE_LANGS, demucs_available, openai_key, save_user_settings,
)

ACTIVE = {"queued", "downloading", "extracting", "model", "transcribing", "detecting", "translating",
          "dubbing", "separating", "rendering"}
RENDER_STAGES = {"dubbing", "separating", "rendering"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
ENUMS = {
    "lang": set(SOURCE_LANGS),
    "voice": set(VOICES),
    "audio_mode": {"duck", "demucs", "mute"},
    "subtitle_mode": {"burn", "srt", "none"},
}


def _kill_orphans():
    """ffmpeg/yt-dlp/demucs started by a previous server process keep running after it dies."""
    import os

    import psutil

    me, mark = os.getpid(), str(DATA_DIR)
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] != me and any(mark in a for a in proc.info["cmdline"] or ()):
                proc.kill()
        except (psutil.Error, OSError):
            pass
    for f in DATA_DIR.glob("*/out/*.part.*"):
        f.unlink(missing_ok=True)


def _recover():
    """Jobs live in memory; after a restart nothing is running any more."""
    _kill_orphans()
    for p in store.list_all():
        if p["status"]["stage"] in ACTIVE:
            if p["segments"]:
                store.set_status(p["id"], "review", None, "Server đã khởi động lại, việc đang chạy bị dừng. Bấm lại để chạy tiếp.")
            else:
                store.set_status(p["id"], "error", None, "Server đã khởi động lại giữa chừng.",
                                 error="Bị dừng do server khởi động lại. Bấm Thử lại.")


def _warm_samples():
    for v in VOICES:
        try:
            voice_sample(v)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app):
    _recover()
    _drop_track()
    # make "▶ nghe thử" instant: build every voice's demo clip in the background
    threading.Thread(target=_warm_samples, daemon=True).start()
    update.check_in_background()
    yield


app = FastAPI(title="Longtieng", lifespan=lifespan)


# ---------- helpers

def _load(pid: str) -> dict:
    try:
        return store.load(pid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "Không tìm thấy dự án.")


def _not_busy(pid: str):
    if jobs.busy(pid):
        raise HTTPException(409, "Dự án đang được xử lý, đợi xong đã.")


def _view(p: dict) -> dict:
    # projects made by older versions lack newer settings keys
    return p | {"settings": store.clean_settings(p["settings"]), "busy": jobs.busy(p["id"])}


def _check_settings(s: dict, new: bool = False) -> dict:
    if not isinstance(s, dict):
        raise HTTPException(400, "Cài đặt không hợp lệ.")
    for k, allowed in ENUMS.items():
        if k in s and s[k] not in allowed:
            raise HTTPException(400, f"Giá trị không hợp lệ cho {k}: {s[k]!r}")
    m = s.get("mask")
    if isinstance(m, dict) and "style" in m and m["style"] not in {"blur", "box"}:
        raise HTTPException(400, "Kiểu che phụ đề không hợp lệ.")
    mu = s.get("music")
    nested = {("frame", "aspect"): {"original", *ASPECTS}, ("frame", "fit"): {"blur", "crop"},
              ("logo", "position"): {"tl", "tr", "bl", "br"},
              ("script", "mode"): {"translate", "review"}, ("script", "style"): set(translate.REVIEW_STYLES)}
    for (k, f), allowed in nested.items():
        if isinstance(s.get(k), dict) and f in s[k] and s[k][f] not in allowed:
            raise HTTPException(400, f"Giá trị không hợp lệ cho {k}.{f}: {s[k][f]!r}")
    if "sub_style" in s and s["sub_style"] not in render.SUB_STYLES:
        raise HTTPException(400, "Kiểu phụ đề không hợp lệ.")
    lg = s.get("logo")
    if isinstance(lg, dict) and lg.get("image") and not logos.get(str(lg["image"])):
        raise HTTPException(400, "Logo không còn trong thư viện.")
    if isinstance(mu, dict) and mu.get("track") and not music.get(str(mu["track"])):
        raise HTTPException(400, "Bài nhạc không còn trong thư viện.")
    try:
        return store.new_settings(s) if new else store.clean_settings(s)
    except (TypeError, ValueError):
        raise HTTPException(400, "Cài đặt không hợp lệ.")


def _refit(p: dict):
    """Recompute the fit badge of lines whose audio is missing or stale."""
    st, media = p["settings"], p.get("media")
    if not media:
        return
    segs = p["segments"]
    for i, s in enumerate(segs):
        if dub.needs_tts(s, st["voice"], st["rate"]):
            s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, media["duration"]), st["rate"]) if s["vi"].strip() else None


# ---------- API

@app.get("/api/config")
def config():
    return {
        "voices": VOICES,
        "defaults": store.new_settings({}),
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_duration_min": MAX_DURATION_MIN,
        "translator": f"OpenAI ({OPENAI_MODEL})" if openai_key() else "Google Dịch (chưa nhập OpenAI API key)",
        "features": {"demucs": demucs_available()},
        "langs": {k: v["label"] for k, v in SOURCE_LANGS.items()},
        "sub_styles": {k: v["label"] for k, v in render.SUB_STYLES.items()},
        "review_styles": {k: v[0] for k, v in translate.REVIEW_STYLES.items()},
        "user_defaults": bool(store.user_defaults()),
        "desktop": FROZEN,
    }


def _mask_key(k: str) -> str:
    return f"{k[:7]}…{k[-4:]}" if len(k) > 14 else ("đã nhập" if k else "")


@app.get("/api/app-settings")
def app_settings():
    k = openai_key()
    return {
        "openai_key_set": bool(k),
        "openai_key_hint": _mask_key(k),
        "stt_engine": stt.engine_label(),
        "stt_model_ready": stt.model_cached(),
        "data_dir": str(USER_DIR),
        "version": APP_VERSION,
    }


@app.get("/api/update")
def update_state(force: int = 0):
    return update.check(force=bool(force))


@app.post("/api/update/apply")
def update_apply():
    busy = [p["title"] for p in store.list_all() if p["status"]["stage"] in ACTIVE]
    if busy:
        raise HTTPException(409, f"Đang xử lý “{busy[0]}”. Đợi xong (hoặc bấm Huỷ) rồi cập nhật.")
    try:
        return update.apply()
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.put("/api/app-settings")
def put_app_settings(body: dict = Body(...)):
    if isinstance(body.get("openai_key"), str):
        k = body["openai_key"].strip()
        if k and not k.startswith("sk-"):
            raise HTTPException(400, "Key OpenAI phải bắt đầu bằng “sk-”.")
        if k:
            try:
                from openai import OpenAI
                OpenAI(api_key=k, max_retries=0, timeout=20).models.list()
            except Exception as e:
                name = type(e).__name__
                if "Authentication" in name:
                    raise HTTPException(400, "Key không đúng hoặc đã bị thu hồi.")
                if "Connection" in name or "Timeout" in name:
                    raise HTTPException(502, "Không kết nối được OpenAI để kiểm tra key. Kiểm tra mạng rồi thử lại.")
                raise HTTPException(400, f"OpenAI từ chối key ({name}).")
        save_user_settings({"openai_key": k})
    return app_settings()


# ---------- shared background-music library

@app.get("/api/music")
def music_list():
    return music.list_all()


@app.post("/api/music")
def music_upload(file: UploadFile = File(...)):
    try:
        return music.add(file.filename or "Nhạc", Path(file.filename or "").suffix, file.file)
    except MediaError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/music/{mid}")
def music_delete(mid: str):
    if not music.delete(mid):
        raise HTTPException(404, "Không có bài nhạc này.")
    _drop_track(mid)
    return {"ok": True}


def _drop_track(mid: str | None = None):
    """Unset a deleted track (or, with no id, any track missing from the library) in every project."""
    for summary in store.list_all():
        pid = summary["id"]
        tid = (store.load(pid)["settings"].get("music") or {}).get("track")
        if tid and (tid == mid or (mid is None and not music.get(tid))):
            store.update(pid, lambda q: q["settings"]["music"].__setitem__("track", None))


# ---------- shared logo library

@app.get("/api/logos")
def logo_list():
    return logos.list_all()


@app.post("/api/logos")
def logo_upload(file: UploadFile = File(...)):
    try:
        return logos.add(file.filename or "Logo", Path(file.filename or "").suffix, file.file)
    except MediaError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/logos/{lid}")
def logo_delete(lid: str):
    logos.delete(lid)
    for summary in store.list_all():
        if store.load(summary["id"])["settings"]["logo"].get("image") == lid:
            store.update(summary["id"], lambda q: q["settings"].setdefault("logo", {}).__setitem__("image", None))
    return {"ok": True}


@app.get("/api/logos/{lid}/file")
def logo_file(lid: str):
    item = logos.get(lid)
    if not item or not logos.path(item).exists():
        raise HTTPException(404, "Không có logo này.")
    return FileResponse(logos.path(item), headers={"Cache-Control": "max-age=86400"})


# ---------- default settings for new videos

@app.put("/api/default-settings")
def save_defaults(settings: dict = Body(..., embed=True)):
    st = _check_settings(settings)
    keep = {k: st[k] for k in store.DEFAULT_KEYS}
    keep["mask"] = {"auto": st["mask"]["auto"], "style": st["mask"]["style"]}
    save_user_settings({"defaults": keep})
    return {"ok": True}


@app.delete("/api/default-settings")
def reset_defaults():
    save_user_settings({"defaults": {}})
    return {"ok": True}


@app.get("/api/music/{mid}/file")
def music_file(mid: str):
    m = music.get(mid)
    if not m or not music.path(m).exists():
        raise HTTPException(404, "Không có bài nhạc này.")
    return FileResponse(music.path(m), headers={"Cache-Control": "max-age=86400"})


SAMPLE_TEXT = ("Xin chào các bạn! Hôm nay mình sẽ hướng dẫn mọi người làm món trứng chiên "
               "siêu ngon và đơn giản ngay tại nhà nhé.")
_sample_locks: dict[str, threading.Lock] = {}


@app.get("/api/voices/{voice}/sample")
def voice_sample(voice: str):
    """Short demo clip per voice, generated once and cached."""
    if voice not in VOICES:
        raise HTTPException(404, "Không có giọng này.")
    out = DATA_DIR.parent / "voice_samples" / f"{voice.replace(':', '_')}.mp3"
    with _sample_locks.setdefault(voice, threading.Lock()):
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp.mp3")
            try:
                dub.synth(SAMPLE_TEXT, voice, 1.0, tmp)
            except RuntimeError as e:
                raise HTTPException(502, str(e))
            tmp.replace(out)
    return FileResponse(out, media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/projects")
def list_projects():
    return store.list_all()


@app.post("/api/projects/upload")
def upload(file: UploadFile = File(...), settings: str = Form("{}"), auto_render: bool = Form(False)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Định dạng {ext or '?'} không hỗ trợ. Dùng mp4, mov, webm, mkv.")
    try:
        st = _check_settings(json.loads(settings or "{}"), new=True)
    except json.JSONDecodeError:
        raise HTTPException(400, "Cài đặt không hợp lệ.")
    title = Path(file.filename).stem[:120] or "Video"
    p = store.create(title, {"type": "upload", "file": f"source{ext}", "name": file.filename}, st, auto_render)
    dst = store.pdir(p["id"]) / f"source{ext}"
    limit = MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    try:
        with dst.open("wb") as f:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File lớn hơn {MAX_UPLOAD_MB}MB.")
                f.write(chunk)
    except BaseException:
        store.delete(p["id"])
        raise
    jobs.submit_prepare(p["id"])
    return _view(store.load(p["id"]))


@app.post("/api/projects/url")
def from_url(url: str = Body(..., embed=True), settings: dict = Body({}, embed=True),
             auto_render: bool = Body(False, embed=True)):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    st = _check_settings(settings, new=True)
    p = store.create(url[:120], {"type": "url", "url": url, "file": None}, st, auto_render)
    jobs.submit_prepare(p["id"])
    return _view(store.load(p["id"]))


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _view(_load(pid))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _load(pid)
    _not_busy(pid)
    store.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/cancel")
def cancel_job(pid: str):
    p = _load(pid)
    if not jobs.busy(pid):
        raise HTTPException(400, "Không có việc nào đang chạy.")
    jobs.request_cancel(pid)
    st = p["status"]
    store.set_status(pid, st["stage"], st.get("progress"), "Đang huỷ…")
    return _view(store.load(pid))


@app.post("/api/projects/{pid}/retry")
def retry(pid: str):
    p = _load(pid)
    _not_busy(pid)
    if p["status"]["stage"] != "error":
        raise HTTPException(400, "Dự án không ở trạng thái lỗi.")
    store.set_status(pid, "queued", 0, "Đang chờ xử lý…")
    jobs.submit_prepare(pid)
    return _view(store.load(pid))


@app.patch("/api/projects/{pid}/settings")
def patch_settings(pid: str, settings: dict = Body(...)):
    p = _load(pid)
    # the export reads the settings, so they're locked only while dubbing/exporting;
    # during download/recognition/translation the look (logo, frame, subtitles, music) can still change
    if jobs.busy(pid) and p["status"]["stage"] in RENDER_STAGES:
        raise HTTPException(409, "Đang xuất video, đợi xong (hoặc bấm Huỷ) rồi đổi cài đặt.")

    def fn(p):
        merged = p["settings"] | {k: v for k, v in settings.items() if k != "mask"}
        mask_patch = settings.get("mask") or {}
        merged["mask"] = p["settings"]["mask"] | mask_patch
        for k in ("music", "frame", "logo", "script"):  # nested groups: patch field by field
            merged[k] = (p["settings"].get(k) or {}) | (settings.get(k) or {})
        if set(mask_patch) & {"enabled", "bottom", "height"}:
            merged["mask"]["auto"] = False  # the user took over
        new = _check_settings(merged)
        if new != store.clean_settings(p["settings"]):
            p["edited_at"] = time.time()  # the exported video no longer matches
        p["settings"] = new
        _refit(p)
    return _view(store.update(pid, fn))


@app.post("/api/projects/{pid}/detect-mask")
def detect_mask(pid: str):
    p = _load(pid)
    _not_busy(pid)
    if not p.get("media") or not p["source"].get("file"):
        raise HTTPException(400, "Video chưa sẵn sàng.")
    if not ocr.available():
        raise HTTPException(400, "Máy này không có Apple Vision để nhận dạng chữ.")
    found = ocr.detect(store.pdir(pid) / p["source"]["file"], p["segments"], p["media"]["duration"],
                       p.get("detected_lang") or p["settings"]["lang"])
    jobs.apply_mask_detection(pid, found, force=True)
    return _view(store.update(pid, lambda q: q.__setitem__("edited_at", time.time())))


# ---------- Facebook Reels kit

def _ready(pid: str) -> dict:
    p = _load(pid)
    if not p.get("media") or not p["source"].get("file"):
        raise HTTPException(400, "Video chưa sẵn sàng.")
    return p


@app.post("/api/projects/{pid}/caption")
def make_caption(pid: str):
    p = _ready(pid)
    if not any(s["vi"].strip() for s in p["segments"]):
        raise HTTPException(400, "Chưa có bản dịch để viết caption.")
    try:
        cap = publish.make_caption(p)
    except MediaError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"OpenAI lỗi: {type(e).__name__}: {str(e)[:200]}")
    return _view(store.update(pid, lambda q: q.setdefault("publish", {}).__setitem__("caption", cap)))


@app.patch("/api/projects/{pid}/caption")
def edit_caption(pid: str, title: str = Body(""), description: str = Body(""), hashtags: list[str] = Body([])):
    _ready(pid)
    cap = {"title": title.strip()[:150], "description": description.strip()[:1000],
           "hashtags": [h.strip() for h in hashtags if h.strip()][:20]}
    return _view(store.update(pid, lambda q: q.setdefault("publish", {}).__setitem__("caption", cap)))


@app.post("/api/projects/{pid}/thumb-candidates")
def thumb_candidates(pid: str):
    p = _ready(pid)
    try:
        cands = publish.candidates(store.pdir(pid), p)
    except MediaError as e:
        raise HTTPException(500, str(e))
    stamp = time.time()
    return _view(store.update(pid, lambda q: q.setdefault("publish", {}).__setitem__(
        "candidates", [c | {"at": stamp} for c in cands])))


@app.post("/api/projects/{pid}/cover")
def make_cover(pid: str, t: float = Body(...), title: str = Body(""), position: str = Body("top")):
    p = _ready(pid)
    if position not in {"top", "middle", "bottom"}:
        raise HTTPException(400, "Vị trí không hợp lệ.")
    t = min(max(0.0, float(t)), max(0.0, p["media"]["duration"] - 0.1))
    try:
        publish.cover(store.pdir(pid), p, t, title[:150], position)
    except MediaError as e:
        raise HTTPException(500, str(e))
    info = {"t": round(t, 2), "title": title[:150], "position": position, "file": "thumbs/cover.jpg", "at": time.time()}
    return _view(store.update(pid, lambda q: q.setdefault("publish", {}).__setitem__("cover", info)))


@app.patch("/api/projects/{pid}/segments/{sid}")
def patch_segment(pid: str, sid: int, vi: str = Body(..., embed=True)):
    p = _load(pid)
    _not_busy(pid)
    if not any(s["id"] == sid for s in p["segments"]):
        raise HTTPException(404, "Không tìm thấy câu.")
    vi = " ".join(vi.split())[:500]

    def fn(q):
        for s in q["segments"]:
            if s["id"] == sid and s["vi"] != vi:
                s["vi"] = vi
                q["edited_at"] = time.time()
        _refit(q)
    return _view(store.update(pid, fn))


@app.post("/api/projects/{pid}/segments/{sid}/tts")
def segment_tts(pid: str, sid: int):
    p = _load(pid)
    _not_busy(pid)
    seg = next((s for s in p["segments"] if s["id"] == sid), None)
    if not seg:
        raise HTTPException(404, "Không tìm thấy câu.")
    if not seg["vi"].strip():
        raise HTTPException(400, "Câu này chưa có bản dịch.")
    try:
        jobs.line_tts(pid, sid)
        return _view(store.update(pid, lambda q: q.__setitem__("edited_at", time.time())))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/projects/{pid}/still")
def still_preview(pid: str, t: float = 0.0):
    """One frame exactly as the export will look (framing, mask, subtitle style, logo)."""
    p = _load(pid)
    if not p.get("media"):
        raise HTTPException(400, "Video chưa sẵn sàng.")
    t = min(max(0.0, t), max(0.0, p["media"]["duration"] - 0.1))
    out = store.pdir(pid) / "thumbs" / "still.jpg"
    out.parent.mkdir(exist_ok=True)
    try:
        render.still(store.pdir(pid), p, t, out, width=720)
    except MediaError as e:
        raise HTTPException(500, str(e))
    return FileResponse(out, headers={"Cache-Control": "no-store"})


@app.post("/api/projects/{pid}/rewrite")
def rewrite(pid: str):
    p = _load(pid)
    _not_busy(pid)
    if not p["segments"]:
        raise HTTPException(400, "Chưa có lời thoại để viết lại.")
    if p["settings"]["script"]["mode"] == "review" and not openai_key():
        raise HTTPException(400, "Chế độ review cần OpenAI API key. Nhập key trong Cài đặt (bánh răng).")
    prev = p["status"]
    store.set_status(pid, "translating", 0, "Đang chờ…")
    try:
        jobs.submit_rewrite(pid)
    except RuntimeError as e:
        store.update(pid, lambda q: q.__setitem__("status", prev))
        raise HTTPException(409, str(e))
    return _view(store.load(pid))


@app.post("/api/projects/{pid}/render")
def start_render(pid: str, preview_start: float | None = Body(None, embed=True)):
    p = _load(pid)
    _not_busy(pid)
    if not p["segments"] or not p.get("media"):
        raise HTTPException(400, "Chưa có bản dịch để lồng tiếng.")
    if p["settings"]["audio_mode"] == "demucs" and not demucs_available():
        raise HTTPException(400, "Bản này không có tách nhạc nền (demucs). Chọn 'Giảm âm gốc' trong Cài đặt âm thanh.")
    if preview_start is not None:
        dur = p["media"]["duration"]
        preview_start = min(max(0.0, float(preview_start)), max(0.0, dur - 1.0))
    prev = p["status"]
    store.set_status(pid, "dubbing", 0, "Đang chờ…")
    try:
        jobs.submit_render(pid, preview_start)
    except RuntimeError as e:
        store.update(pid, lambda q: q.__setitem__("status", prev))
        raise HTTPException(409, str(e))
    return _view(store.load(pid))


@app.get("/api/projects/{pid}/files/{path:path}")
def get_file(pid: str, path: str, download: int = 0):
    _load(pid)
    root = store.pdir(pid).resolve()
    f = (root / path).resolve()
    if not f.is_relative_to(root) or not f.is_file() or f.name == "project.json":
        raise HTTPException(404, "Không có file.")
    name = None
    if download:
        p = store.load(pid)
        stem = "".join(c for c in p["title"] if c.isalnum() or c in " -_")[:60].strip() or pid
        name = f"{stem}_longtieng{f.suffix}" if f.stem in ("final", "preview") else f"{stem}_{f.name}"
    return FileResponse(f, filename=name, headers={"Cache-Control": "no-cache"})


@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def web(path: str):
    """Serve the Next.js static export (web/out). /project → project.html, etc."""
    if path.startswith("api/"):
        raise HTTPException(404, "Not found")
    if not WEB_DIR.is_dir():
        return PlainTextResponse("Chưa build giao diện. Chạy: cd web && pnpm install && pnpm build", status_code=503)
    root = WEB_DIR.resolve()
    p = path.strip("/")
    for cand in ([p, f"{p}.html", f"{p}/index.html"] if p else ["index.html"]):
        f = (root / cand).resolve()
        if f.is_relative_to(root) and f.is_file():
            return FileResponse(f)
    return FileResponse(root / "404.html", status_code=404)
