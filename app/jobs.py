"""Background jobs. One heavy job at a time: Whisper/demucs twice on 16GB would swap."""

import traceback
from concurrent.futures import ThreadPoolExecutor

from . import dub, render, store, stt, translate
from .config import MAX_DURATION_MIN
from .media import MediaError, download_url, extract_audio_16k, probe

heavy = ThreadPoolExecutor(max_workers=1, thread_name_prefix="heavy")
light = ThreadPoolExecutor(max_workers=4, thread_name_prefix="light")
_queued: set[str] = set()


def busy(pid: str) -> bool:
    return pid in _queued


def _submit(pid: str, fn, *args):
    if pid in _queued:
        raise RuntimeError("Dự án đang được xử lý, đợi xong đã.")
    _queued.add(pid)

    def wrapped():
        try:
            fn(pid, *args)
        except Exception as e:
            msg = str(e) if isinstance(e, (MediaError, RuntimeError)) else f"{type(e).__name__}: {e}"
            traceback.print_exc()
            p = store.load(pid)
            back = "review" if p["segments"] else "error"
            store.set_status(pid, back, None, "Có lỗi xảy ra.", error=msg)
        finally:
            _queued.discard(pid)

    heavy.submit(wrapped)


# ---------- prepare: ingest → transcribe → translate

def submit_prepare(pid: str):
    _submit(pid, _prepare)


def _prepare(pid: str):
    d = store.pdir(pid)
    p = store.load(pid)

    if p["source"]["type"] == "url" and not p["source"].get("file"):
        store.set_status(pid, "downloading", 0, "Đang tải video từ link…")
        f = download_url(p["source"]["url"], d,
                         lambda x: store.set_status(pid, "downloading", x, "Đang tải video từ link…"))
        store.update(pid, lambda q: q["source"].__setitem__("file", f.name))
        p = store.load(pid)

    src = d / p["source"]["file"]
    media = probe(src)
    if media["duration"] > MAX_DURATION_MIN * 60:
        raise MediaError(f"Video dài {media['duration'] / 60:.1f} phút, vượt giới hạn {MAX_DURATION_MIN:g} phút.")
    if not media["has_audio"]:
        raise MediaError("Video không có âm thanh, không có gì để nhận dạng.")
    store.update(pid, lambda q: q.__setitem__("media", media))

    store.set_status(pid, "extracting", None, "Đang tách âm thanh…")
    extract_audio_16k(src, d / "audio16k.wav")

    if not stt.model_cached():
        store.set_status(pid, "model", None, "Lần đầu chạy: đang tải model Whisper (~1.6GB), chờ vài phút…")
        stt.ensure_model()

    store.set_status(pid, "transcribing", 0, "Đang nhận dạng giọng nói…")
    last = [0.0]

    def prog(x):
        if x - last[0] >= 0.02 or x >= 1:
            last[0] = x
            store.set_status(pid, "transcribing", x, "Đang nhận dạng giọng nói…")

    segs, lang = stt.transcribe(d / "audio16k.wav", p["settings"]["lang"], prog)
    if not segs:
        raise MediaError("Không nhận dạng được câu thoại nào trong video.")

    store.set_status(pid, "translating", 0, f"Đang dịch {len(segs)} câu…")
    warnings = translate.translate_all(
        segs, media["duration"], lang, p["settings"]["rate"],
        lambda x: store.set_status(pid, "translating", x, f"Đang dịch {len(segs)} câu…"))

    for i, s in enumerate(segs):
        s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, media["duration"]), p["settings"]["rate"])

    def fin(q):
        q["segments"] = segs
        q["detected_lang"] = lang
        q["warnings"] = warnings
        q["status"] = {"stage": "review", "progress": None,
                       "message": "Xong. Kiểm tra bản dịch rồi bấm Lồng tiếng.", "error": None}
    store.update(pid, fin)


# ---------- dub + render

def submit_render(pid: str, preview_start: float | None):
    _submit(pid, _render, preview_start)


def synth_missing(pid: str, on_progress=None) -> None:
    p = store.load(pid)
    st, dur = p["settings"], p["media"]["duration"]
    segs = p["segments"]
    todo = [i for i, s in enumerate(segs) if dub.needs_tts(s, st["voice"], st["rate"])]
    done = [0]

    def one(i):
        res = dub.make_line(store.pdir(pid), segs[i], dub.slot(segs, i, dur), st["voice"], st["rate"])
        sid = segs[i]["id"]
        text = segs[i]["vi"]

        def apply(q):
            for s in q["segments"]:
                if s["id"] == sid and s["vi"] == text:  # skip if edited meanwhile
                    s.update(res)
        store.update(pid, apply)
        done[0] += 1
        if on_progress:
            on_progress(done[0] / len(todo))

    for f in [light.submit(one, i) for i in todo]:
        f.result()


def _render(pid: str, preview_start: float | None):
    d = store.pdir(pid)
    store.set_status(pid, "dubbing", 0, "Đang tạo giọng lồng tiếng…")
    synth_missing(pid, lambda x: store.set_status(pid, "dubbing", x, "Đang tạo giọng lồng tiếng…"))

    p = store.load(pid)
    st, media = p["settings"], p["media"]
    dub.mix(d, p["segments"], media["duration"], d / "dub.wav")

    src = d / p["source"]["file"]
    bg = None
    if st["audio_mode"] == "duck":
        bg = src
    elif st["audio_mode"] == "demucs":
        store.set_status(pid, "separating", None, "Đang tách nhạc nền (demucs, vài phút)…")
        bg = render.separate_background(d, src)

    render.write_srt(p["segments"], media["duration"], d / "out" / "phude.srt")
    render.write_transcript(p["segments"], d / "out" / "transcript.json", d / "out" / "transcript.txt")

    preview = preview_start is not None
    out = d / "out" / ("preview.mp4" if preview else "final.mp4")
    label = "Đang dựng bản xem thử…" if preview else "Đang xuất video…"
    store.set_status(pid, "rendering", 0, label)
    render.render(d, p, out, bg,
                  start=preview_start or 0.0,
                  length=min(30.0, media["duration"] - preview_start) if preview else None,
                  on_progress=lambda x: store.set_status(pid, "rendering", x, label))

    import time

    def fin(q):
        key = "preview" if preview else "final"
        q["outputs"][key] = {"file": f"out/{out.name}", "at": time.time()}
        q["outputs"]["srt"] = {"file": "out/phude.srt"}
        q["outputs"]["json"] = {"file": "out/transcript.json"}
        q["outputs"]["txt"] = {"file": "out/transcript.txt"}
        q["status"] = {"stage": "review" if preview else "done", "progress": None,
                       "message": "Bản xem thử đã sẵn sàng." if preview else "Xuất video xong!",
                       "error": None}
    store.update(pid, fin)


def line_tts(pid: str, sid: int) -> dict:
    """Regenerate one line now (used by the ↻ button). Runs on the light pool."""
    p = store.load(pid)
    st, dur = p["settings"], p["media"]["duration"]
    segs = p["segments"]
    i = next(k for k, s in enumerate(segs) if s["id"] == sid)
    res = dub.make_line(store.pdir(pid), segs[i], dub.slot(segs, i, dur), st["voice"], st["rate"])
    text = segs[i]["vi"]

    def apply(q):
        for s in q["segments"]:
            if s["id"] == sid and s["vi"] == text:
                s.update(res)
    return store.update(pid, apply)
