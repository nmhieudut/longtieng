"""FastAPI server: JSON API + static UI. Run with `uv run python -m app`."""

import json
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from . import dub, jobs, store
from .config import (
    DEFAULT_SETTINGS, MAX_DURATION_MIN, MAX_UPLOAD_MB, OPENAI_API_KEY, OPENAI_MODEL, VOICES, WEB_DIR,
)

ACTIVE = {"queued", "downloading", "extracting", "model", "transcribing", "translating",
          "dubbing", "separating", "rendering"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
ENUMS = {
    "lang": {"zh", "auto"},
    "voice": set(VOICES),
    "audio_mode": {"duck", "demucs", "mute"},
    "subtitle_mode": {"burn", "srt", "none"},
}


def _recover():
    """Jobs live in memory; after a restart nothing is running any more."""
    for p in store.list_all():
        if p["status"]["stage"] in ACTIVE:
            if p["segments"]:
                store.set_status(p["id"], "review", None, "Server đã khởi động lại, việc đang chạy bị dừng. Bấm lại để chạy tiếp.")
            else:
                store.set_status(p["id"], "error", None, "Server đã khởi động lại giữa chừng.",
                                 error="Bị dừng do server khởi động lại. Bấm Thử lại.")


@asynccontextmanager
async def lifespan(_app):
    _recover()
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
    return p | {"busy": jobs.busy(p["id"])}


def _check_settings(s: dict) -> dict:
    if not isinstance(s, dict):
        raise HTTPException(400, "Cài đặt không hợp lệ.")
    for k, allowed in ENUMS.items():
        if k in s and s[k] not in allowed:
            raise HTTPException(400, f"Giá trị không hợp lệ cho {k}: {s[k]!r}")
    m = s.get("mask")
    if isinstance(m, dict) and "style" in m and m["style"] not in {"blur", "box"}:
        raise HTTPException(400, "Kiểu che phụ đề không hợp lệ.")
    try:
        return store.clean_settings(s)
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
        "defaults": DEFAULT_SETTINGS,
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_duration_min": MAX_DURATION_MIN,
        "translator": f"OpenAI ({OPENAI_MODEL})" if OPENAI_API_KEY else "Google Dịch (chưa có OPENAI_API_KEY)",
    }


@app.get("/api/projects")
def list_projects():
    return store.list_all()


@app.post("/api/projects/upload")
def upload(file: UploadFile = File(...), settings: str = Form("{}")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, f"Định dạng {ext or '?'} không hỗ trợ. Dùng mp4, mov, webm, mkv.")
    try:
        st = _check_settings(json.loads(settings or "{}"))
    except json.JSONDecodeError:
        raise HTTPException(400, "Cài đặt không hợp lệ.")
    title = Path(file.filename).stem[:120] or "Video"
    p = store.create(title, {"type": "upload", "file": f"source{ext}", "name": file.filename}, st)
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
def from_url(url: str = Body(..., embed=True), settings: dict = Body({}, embed=True)):
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Link phải bắt đầu bằng http:// hoặc https://")
    st = _check_settings(settings)
    p = store.create(url[:120], {"type": "url", "url": url, "file": None}, st)
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
    _load(pid)
    _not_busy(pid)

    def fn(p):
        merged = p["settings"] | {k: v for k, v in settings.items() if k != "mask"}
        merged["mask"] = p["settings"]["mask"] | (settings.get("mask") or {})
        p["settings"] = _check_settings(merged)
        _refit(p)
    return _view(store.update(pid, fn))


@app.patch("/api/projects/{pid}/segments/{sid}")
def patch_segment(pid: str, sid: int, vi: str = Body(..., embed=True)):
    p = _load(pid)
    _not_busy(pid)
    if not any(s["id"] == sid for s in p["segments"]):
        raise HTTPException(404, "Không tìm thấy câu.")
    vi = " ".join(vi.split())[:500]

    def fn(q):
        for s in q["segments"]:
            if s["id"] == sid:
                s["vi"] = vi
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
        return _view(jobs.line_tts(pid, sid))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.post("/api/projects/{pid}/render")
def start_render(pid: str, preview_start: float | None = Body(None, embed=True)):
    p = _load(pid)
    _not_busy(pid)
    if not p["segments"] or not p.get("media"):
        raise HTTPException(400, "Chưa có bản dịch để lồng tiếng.")
    if p["settings"]["audio_mode"] == "demucs":
        try:
            import demucs  # noqa: F401
        except ImportError:
            raise HTTPException(400, "Chưa cài demucs. Chạy: uv sync --extra demucs  (hoặc chọn 'Giảm âm gốc').")
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
