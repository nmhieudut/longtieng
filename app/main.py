"""FastAPI server: JSON API + static UI. Run with `uv run python -m app`."""

import json
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from . import dub, jobs, logos, media, music, ocr, outdir, overlays, publish, vieneu_tts, render, store, stt, timeline, translate, update
from .frame import ASPECTS
from .media import MediaError
from .config import (
    APP_VERSION, DATA_DIR, DEFAULT_SETTINGS, FFMPEG, FROZEN, MAX_DURATION_MIN, MAX_UPLOAD_MB, OPENAI_MODEL, USER_DIR, VOICES, WEB_DIR,
    SOURCE_LANGS, TARGET_LANGS, demucs_available, default_voice, openai_key, save_user_settings, voice_ok,
)

ACTIVE = {"queued", "downloading", "extracting", "model", "transcribing", "detecting", "translating",
          "dubbing", "separating", "rendering"}
RENDER_STAGES = {"dubbing", "separating", "rendering"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
ENUMS = {
    "lang": set(SOURCE_LANGS),
    "target": set(TARGET_LANGS),
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
    if s.get("voice") and s.get("target") and not voice_ok(s["voice"], s["target"]):
        raise HTTPException(400, "Giọng này không đọc được ngôn ngữ đích đã chọn.")
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
    slot_of = jobs.slot_fn(p)[0]
    for i, s in enumerate(segs):
        if dub.needs_tts(s, st["voice"], st["rate"]):
            s["fit"] = (dub.estimate(s["vi"], slot_of(i), st["rate"], st["target"])
                        if s["vi"].strip() else None)


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
        "target_langs": {k: {"label": v["label"], "voice": v["voice"]} for k, v in TARGET_LANGS.items()},
        "sub_styles": {k: v["label"] for k, v in render.SUB_STYLES.items()},
        "review_styles": {k: v[0] for k, v in translate.REVIEW_STYLES.items()},
        "user_defaults": bool(store.user_defaults()),
        "desktop": FROZEN,
        "output_dir": str(outdir.current() or ""),
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
        "output_dir": str(outdir.current() or ""),
        "output_suggestions": outdir.suggestions(),
        "vieneu": {"available": vieneu_tts.available(), "size_mb": vieneu_tts.SIZE_MB, **vieneu_tts.download_state()},
        "version": APP_VERSION,
    }


@app.post("/api/vieneu/download")
def vieneu_download():
    if not vieneu_tts.available():
        raise HTTPException(400, "Bản này không có giọng VieNeu.")
    return {**vieneu_tts.start_download()}


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
    if isinstance(body.get("output_dir"), str):
        raw = body["output_dir"].strip()
        try:
            save_user_settings({"output_dir": str(outdir.validate(raw)) if raw else ""})
        except ValueError as e:
            raise HTTPException(400, str(e))
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
    free = shutil.disk_usage(DATA_DIR).free
    if free < 3 * 1024**3:  # the video, its audio and the exported copy all live on this disk
        raise HTTPException(507, f"Ổ đĩa chỉ còn {free / 1024**3:.1f}GB trống, cần ít nhất 3GB. Dọn bớt rồi thử lại.")
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
    except OSError as e:  # most likely the disk filled up halfway through a big file
        store.delete(p["id"])
        raise HTTPException(507, f"Không ghi được file ({e.strerror or e}). Kiểm tra dung lượng ổ đĩa.")
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
        for k in ("music", "frame", "color", "logo", "script"):  # nested groups: patch field by field
            merged[k] = (p["settings"].get(k) or {}) | (settings.get(k) or {})
        if set(mask_patch) & {"enabled", "bottom", "height"}:
            merged["mask"]["auto"] = False  # the user took over
        if "target" in settings and "voice" not in settings and not voice_ok(merged["voice"], merged["target"]):
            merged["voice"] = default_voice(merged["target"])  # new language, so a voice that speaks it
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


@app.get("/api/projects/{pid}/poster")
def poster(pid: str):
    """Small frame for the project list. Made once from the source video, then cached."""
    p = _load(pid)
    d = store.pdir(pid)
    out = d / "thumbs" / "poster.jpg"
    if not out.exists():
        src = d / (p["source"].get("file") or "")
        if not p["source"].get("file") or not src.exists():
            raise HTTPException(404, "Chưa có video.")
        dur = (p.get("media") or {}).get("duration") or 0
        t = min(1.5, dur * 0.2) if dur else 0
        out.parent.mkdir(exist_ok=True)
        tmp = out.with_name(f"poster.{threading.get_ident()}.jpg")
        try:
            media.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                       "-vf", "scale=240:240:force_original_aspect_ratio=increase,crop=240:240", "-q:v", "4",
                       str(tmp)], timeout=30)
            tmp.replace(out)
        except Exception as e:  # ffmpeg error, timeout, disk
            tmp.unlink(missing_ok=True)
            raise HTTPException(500, f"Không tạo được ảnh: {e}")
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


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


@app.put("/api/projects/{pid}/timeline")
def put_timeline(pid: str, body: dict = Body(...)):
    """Save the edit list (cut / split / reorder / duplicate). {"clips": null} goes back to the whole video."""
    p = _load(pid)
    if not p.get("media"):
        raise HTTPException(400, "Video chưa sẵn sàng.")
    if jobs.busy(pid) and p["status"]["stage"] in RENDER_STAGES:
        raise HTTPException(409, "Đang xuất video, đợi xong (hoặc bấm Huỷ) rồi sửa timeline.")
    raw = body.get("clips")
    try:
        clips = (timeline.validate(raw, p["media"]["duration"], timeline.source_durations(p), MAX_DURATION_MIN * 60)
                 if raw is not None else None)
    except ValueError as e:
        raise HTTPException(400, str(e))

    def fn(q):
        if clips is None or not timeline.is_edited(q | {"timeline": {"clips": clips}}):
            q.pop("timeline", None)
        else:
            q["timeline"] = {"clips": clips}
        q["edited_at"] = time.time()  # the exported video no longer matches
    return _view(store.update(pid, fn))


@app.put("/api/projects/{pid}/overlays")
def put_overlays(pid: str, body: dict = Body(...)):
    """Save the texts and picture stickers laid over the video (output time)."""
    p = _load(pid)
    if jobs.busy(pid) and p["status"]["stage"] in RENDER_STAGES:
        raise HTTPException(409, "Đang xuất video, đợi xong (hoặc bấm Huỷ) rồi sửa.")
    try:
        items = overlays.validate(body.get("overlays"))
    except ValueError as e:
        raise HTTPException(400, str(e))

    def fn(q):
        if items:
            q["overlays"] = items
        else:
            q.pop("overlays", None)
        q["edited_at"] = time.time()
    return _view(store.update(pid, fn))


FILM_FRAMES = 48
FILM_H = 54


@app.post("/api/projects/{pid}/filmstrip")
def make_filmstrip(pid: str, src: int = 0):
    """One wide picture of frames spread over a video (0 = the main one), for the timeline. Made once, cached."""
    from concurrent.futures import ThreadPoolExecutor
    import tempfile

    p = _load(pid)
    if not p.get("media") or not p["source"].get("file"):
        raise HTTPException(400, "Video chưa sẵn sàng.")
    d = store.pdir(pid)
    if src == 0:
        m, rel, held = p["media"], p["source"]["file"], p.get("film")
    else:
        e = next((x for x in timeline.extra_sources(p) if x["id"] == src), None)
        if not e:
            raise HTTPException(404, "Không có video này trong dự án.")
        m, rel, held = e, e["file"], e.get("film")
    out = d / "thumbs" / ("film.jpg" if src == 0 else f"film_{src}.jpg")
    w = max(2, round(FILM_H * m["width"] / m["height"] / 2) * 2)
    info = {"n": FILM_FRAMES, "w": w, "h": FILM_H, "duration": m["duration"], "file": f"thumbs/{out.name}"}
    if out.exists() and (held or {}).get("duration") == m["duration"]:
        return _view(p)
    out.parent.mkdir(exist_ok=True)
    source = d / rel
    with tempfile.TemporaryDirectory(dir=d) as tmp:
        def grab(i):
            t = (i + 0.5) * m["duration"] / FILM_FRAMES
            f = Path(tmp) / f"{i:03d}.jpg"
            return media.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(source), "-frames:v", "1",
                              "-vf", f"scale={w}:{FILM_H}", "-q:v", "5", str(f)], timeout=60)

        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(grab, range(FILM_FRAMES)))
            tmp_out = out.with_name(out.stem + ".part.jpg")
            media.run([FFMPEG, "-y", "-v", "error", "-framerate", "1", "-i", str(Path(tmp) / "%03d.jpg"),
                       "-vf", f"tile={FILM_FRAMES}x1", "-frames:v", "1", "-q:v", "5", str(tmp_out)], timeout=60)
            tmp_out.replace(out)
        except (MediaError, OSError) as e:
            raise HTTPException(500, f"Không tạo được ảnh timeline: {e}")

    def fn(q):
        if src == 0:
            q["film"] = info
        else:
            for x in q.get("extra_sources", []):
                if x["id"] == src:
                    x["film"] = info
    return _view(store.update(pid, fn))


MAX_EXTRA_SOURCES = 8


def _add_clip(p: dict, entry: dict) -> list[dict]:
    """The project's clips with the whole new video put at the end (ValueError if that makes it too long)."""
    clips = timeline.clips_of(p) or [{"id": "full", "start": 0, "end": p["media"]["duration"]}]
    clips = clips + [{"id": f"s{entry['id']}", "src": entry["id"], "start": 0, "end": entry["duration"]}]
    durs = timeline.source_durations(p) | {entry["id"]: entry["duration"]}
    return timeline.validate(clips, p["media"]["duration"], durs, MAX_DURATION_MIN * 60)


@app.post("/api/projects/{pid}/sources")
def add_source(pid: str, file: UploadFile = File(...)):
    """Add another video to the project: it goes at the end of the timeline and its speech is recognised and
    translated like the main video's."""
    p = _load(pid)
    _not_busy(pid)
    if not p.get("media"):
        raise HTTPException(400, "Video chính chưa sẵn sàng.")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Định dạng {ext or '?'} không hỗ trợ. Dùng mp4, mov, webm, mkv.")
    extras = timeline.extra_sources(p)
    if len(extras) >= MAX_EXTRA_SOURCES:
        raise HTTPException(400, f"Tối đa {MAX_EXTRA_SOURCES} video thêm vào một dự án.")
    free = shutil.disk_usage(DATA_DIR).free
    if free < 3 * 1024**3:
        raise HTTPException(507, f"Ổ đĩa chỉ còn {free / 1024**3:.1f}GB trống, cần ít nhất 3GB. Dọn bớt rồi thử lại.")
    n = max([e["id"] for e in extras] + [0]) + 1
    d = store.pdir(pid)
    dst = d / f"source_{n}{ext}"
    limit, size = MAX_UPLOAD_MB * 1024 * 1024, 0
    try:
        with dst.open("wb") as f:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File lớn hơn {MAX_UPLOAD_MB}MB.")
                f.write(chunk)
        info = media.probe(dst)
        if info["duration"] > MAX_DURATION_MIN * 60:
            raise HTTPException(400, f"Video dài {info['duration'] / 60:.1f} phút, vượt giới hạn {MAX_DURATION_MIN:g} phút.")
        entry = {"id": n, "file": dst.name, "name": Path(file.filename or "video").stem[:80], "duration": info["duration"],
                 "width": info["width"], "height": info["height"], "has_audio": info["has_audio"]}
        # (checked again below on the timeline as it is when the upload has finished: it stays editable meanwhile)
        _add_clip(p, entry)
    except MediaError as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except ValueError as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    except BaseException:
        dst.unlink(missing_ok=True)
        raise

    def fn(q):
        q["extra_sources"] = timeline.extra_sources(q) + [entry]
        q["timeline"] = {"clips": _add_clip(q, entry)}   # from the CURRENT clips, so edits made during the upload stay
        q["edited_at"] = time.time()
    try:
        store.update(pid, fn)
    except ValueError as e:
        dst.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    store.set_status(pid, "extracting", None, "Đang chuẩn bị video mới…")  # so the page starts following the job
    try:
        jobs.submit_extra(pid, n)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return _view(store.load(pid))


@app.post("/api/projects/{pid}/sources/{src}/retry")
def retry_source(pid: str, src: int):
    """Recognise and translate an added video again (it failed or was cancelled)."""
    p = _load(pid)
    _not_busy(pid)
    if not any(x["id"] == src for x in timeline.extra_sources(p)):
        raise HTTPException(404, "Không có video này trong dự án.")
    prev = p["status"]
    store.set_status(pid, "extracting", None, "Đang chuẩn bị video…")
    try:
        jobs.submit_extra(pid, src, retry=True)
    except RuntimeError as e:
        store.update(pid, lambda q: q.__setitem__("status", prev))
        raise HTTPException(409, str(e))
    return _view(store.load(pid))


@app.delete("/api/projects/{pid}/sources/{src}")
def delete_source(pid: str, src: int):
    """Remove an added video with its lines and its clips."""
    p = _load(pid)
    _not_busy(pid)
    e = next((x for x in timeline.extra_sources(p) if x["id"] == src), None)
    if not e:
        raise HTTPException(404, "Không có video này trong dự án.")

    def fn(q):
        q["extra_sources"] = [x for x in timeline.extra_sources(q) if x["id"] != src]
        q["segments"] = [s for s in q["segments"] if s.get("src_id", 0) != src]
        left = [c for c in timeline.clips_of(q) if c.get("src", 0) != src]
        if left:
            q["timeline"] = {"clips": left}
        else:
            q.pop("timeline", None)
        if not q["extra_sources"] and not timeline.is_edited(q):
            q.pop("timeline", None)
        q["edited_at"] = time.time()
    gone = [s["id"] for s in p["segments"] if s.get("src_id", 0) == src]
    out = store.update(pid, fn)
    for sid in gone:
        for f in (store.pdir(pid) / "tts").glob(f"{sid}_*"):
            f.unlink(missing_ok=True)
    for f in (store.pdir(pid) / e["file"], store.pdir(pid) / f"audio16k_{src}.wav", store.pdir(pid) / "thumbs" / f"film_{src}.jpg"):
        f.unlink(missing_ok=True)
    return _view(out)


@app.post("/api/projects/{pid}/render")
def start_render(pid: str, preview_start: float | None = Body(None, embed=True)):
    p = _load(pid)
    _not_busy(pid)
    if not p["segments"] or not p.get("media"):
        raise HTTPException(400, "Chưa có bản dịch để lồng tiếng.")
    if p["settings"]["audio_mode"] == "demucs" and not demucs_available():
        raise HTTPException(400, "Bản này không có tách nhạc nền (demucs). Chọn 'Giảm âm gốc' trong Cài đặt âm thanh.")
    done = p.get("translated_to", "vi")  # projects from before the target language existed were Vietnamese
    if done != p["settings"]["target"]:
        raise HTTPException(400, f"Lời thoại đang là {TARGET_LANGS[done]['name']}. Đã đổi ngôn ngữ đích sang "
                                 f"{TARGET_LANGS[p['settings']['target']]['name']}: mở Cài đặt → Lời thoại và bấm "
                                 "“Viết lại lời thoại” trước khi xuất.")
    if preview_start is not None:
        # output time: with cuts the video is shorter (or longer, with duplicates) than the source
        dur = timeline.out_duration(timeline.clips_of(p)) if timeline.is_edited(p) else p["media"]["duration"]
        preview_start = min(max(0.0, float(preview_start)), max(0.0, dur - 1.0))
    prev = p["status"]
    store.set_status(pid, "dubbing", 0, "Đang chờ…")
    try:
        jobs.submit_render(pid, preview_start)
    except RuntimeError as e:
        store.update(pid, lambda q: q.__setitem__("status", prev))
        raise HTTPException(409, str(e))
    return _view(store.load(pid))


@app.post("/api/projects/{pid}/save-to-folder")
def save_to_folder(pid: str):
    """Copy the already exported video into the folder chosen in Cài đặt."""
    p = _load(pid)
    if outdir.current() is None:
        raise HTTPException(400, "Chưa chọn thư mục lưu. Mở Cài đặt (bánh răng) để chọn.")
    if not p["outputs"].get("final"):
        raise HTTPException(400, "Video chưa được xuất.")
    res = jobs.deliver(pid)
    if res.get("error"):
        raise HTTPException(400, res["error"])
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
            # always revalidate: the web view keeps its cache between runs, so without this it can
            # keep showing the UI of an older version after an update or reinstall
            return FileResponse(f, headers={"Cache-Control": "no-cache"})
    return FileResponse(root / "404.html", status_code=404, headers={"Cache-Control": "no-cache"})
