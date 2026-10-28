"""Background jobs. One heavy job at a time: Whisper/demucs twice on 16GB would swap."""

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from . import cancel, dub, ocr, render, store, stt, translate
from .cancel import Cancelled
from .config import MAX_DURATION_MIN
from .media import MediaError, download_url, extract_audio_16k, probe

heavy = ThreadPoolExecutor(max_workers=1, thread_name_prefix="heavy")
light = ThreadPoolExecutor(max_workers=6, thread_name_prefix="light")
_queued: set[str] = set()


def busy(pid: str) -> bool:
    return pid in _queued


def step(pid: str, stage: str, progress: float | None = None, message: str = "") -> None:
    """Report progress — and stop here if the user pressed Huỷ."""
    cancel.check(pid)
    store.set_status(pid, stage, progress, message)


def request_cancel(pid: str) -> None:
    cancel.cancel(pid)


def _submit(pid: str, fn, *args):
    if pid in _queued:
        raise RuntimeError("Dự án đang được xử lý, đợi xong đã.")
    _queued.add(pid)
    cancel.reset(pid)

    def wrapped():
        cancel.bind(pid)
        try:
            cancel.check(pid)
            fn(pid, *args)
        except Cancelled:
            p = store.load(pid)
            if p["segments"]:
                store.set_status(pid, "review", None, "Đã huỷ. Bản dịch vẫn giữ nguyên, bấm xuất lại khi sẵn sàng.")
            else:
                store.set_status(pid, "error", None, "Đã huỷ.", error="Đã huỷ theo yêu cầu. Bấm Thử lại để chạy lại.")
        except Exception as e:
            known = (MediaError, RuntimeError, TimeoutError)
            msg = str(e) if isinstance(e, known) else f"{type(e).__name__}: {e}"
            traceback.print_exc()
            p = store.load(pid)
            back = "review" if p["segments"] else "error"
            store.set_status(pid, back, None, "Có lỗi xảy ra.", error=msg)
        finally:
            cancel.bind(None)
            _queued.discard(pid)

    heavy.submit(wrapped)


# ---------- prepare: ingest → transcribe → translate

def submit_prepare(pid: str):
    _submit(pid, _prepare)


def _prepare(pid: str):
    d = store.pdir(pid)
    p = store.load(pid)

    if p["source"]["type"] == "url" and not p["source"].get("file"):
        step(pid, "downloading", 0, "Đang tải video từ link…")
        f = download_url(p["source"]["url"], d,
                         lambda x: step(pid, "downloading", x, "Đang tải video từ link…"))
        store.update(pid, lambda q: q["source"].__setitem__("file", f.name))
        p = store.load(pid)

    src = d / p["source"]["file"]
    media = probe(src)
    if media["duration"] > MAX_DURATION_MIN * 60:
        raise MediaError(f"Video dài {media['duration'] / 60:.1f} phút, vượt giới hạn {MAX_DURATION_MIN:g} phút.")
    if not media["has_audio"]:
        raise MediaError("Video không có âm thanh, không có gì để nhận dạng.")
    store.update(pid, lambda q: q.__setitem__("media", media))

    step(pid, "extracting", None, "Đang tách âm thanh…")
    extract_audio_16k(src, d / "audio16k.wav")

    if not stt.model_cached():
        msg = "Lần đầu chạy: đang tải model nhận dạng giọng (~1.6GB), chỉ tải một lần…"
        step(pid, "model", None, msg)
        stt.ensure_model(lambda f: step(pid, "model", f, msg))

    step(pid, "transcribing", 0, "Đang nhận dạng giọng nói…")
    last = [0.0]

    def prog(x):
        cancel.check(pid)  # called from Whisper's progress hook, so this interrupts transcription
        if x - last[0] >= 0.02 or x >= 1:
            last[0] = x
            step(pid, "transcribing", x, "Đang nhận dạng giọng nói…")

    segs, lang = stt.transcribe(d / "audio16k.wav", p["settings"]["lang"], prog)
    if not segs:
        raise MediaError("Không nhận dạng được câu thoại nào trong video.")

    # Looking for burned-in subtitles (local, CPU/GPU) and translating (network) don't need each
    # other, so do both at once.
    finder = None
    if p["settings"]["mask"].get("auto", True) and ocr.available():
        def find():
            cancel.bind(pid)
            return ocr.detect(src, segs, media["duration"], lang)
        finder = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
        found_future = finder.submit(find)

    step(pid, "translating", 0, f"Đang dịch {len(segs)} câu…")
    try:
        warnings = translate.translate_all(
            segs, media["duration"], lang, p["settings"]["rate"],
            lambda x: step(pid, "translating", x, f"Đang dịch {len(segs)} câu…"),
            script=p["settings"].get("script"))
        if finder:
            apply_mask_detection(pid, found_future.result())
    finally:
        if finder:
            finder.shutdown(wait=False)

    for i, s in enumerate(segs):
        s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, media["duration"]), p["settings"]["rate"])

    def fin(q):
        q["segments"] = segs
        q["detected_lang"] = lang
        q["warnings"] = warnings
        q["status"] = {"stage": "review", "progress": None,
                       "message": "Xong. Kiểm tra bản dịch rồi bấm Lồng tiếng.", "error": None}
    store.update(pid, fin)
    if store.load(pid).get("auto_render"):  # batch: go straight on to the export
        _render(pid, None)


# ---------- rewrite: translate again (e.g. after switching to review mode)

def submit_rewrite(pid: str):
    _submit(pid, _rewrite)


def _rewrite(pid: str):
    p = store.load(pid)
    segs = [dict(s, vi="") for s in p["segments"]]
    mode = p["settings"]["script"]["mode"]
    label = "Đang viết lại lời dẫn…" if mode == "review" else "Đang dịch lại…"
    step(pid, "translating", 0, label)
    warnings = translate.translate_all(
        segs, p["media"]["duration"], p.get("detected_lang") or p["settings"]["lang"], p["settings"]["rate"],
        lambda x: step(pid, "translating", x, label), script=p["settings"]["script"])
    dur = p["media"]["duration"]
    for i, s in enumerate(segs):
        s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, dur), p["settings"]["rate"]) if s["vi"].strip() else None

    def fin(q):
        q["segments"] = segs  # old voice clips no longer match the text, so they get remade on export
        q["warnings"] = warnings
        q["edited_at"] = time.time()
        q["status"] = {"stage": "review", "progress": None,
                       "message": "Đã viết lại. Kiểm tra rồi bấm Lồng tiếng.", "error": None}
    store.update(pid, fin)


def apply_mask_detection(pid: str, found: dict | None, force: bool = False) -> dict:
    """force: the user pressed "Dò tự động". Otherwise a band they set by hand meanwhile wins."""
    def fn(q):
        m = q["settings"]["mask"]
        q["mask_detect"] = {"found": bool(found), **(found or {})}
        if not force and not m.get("auto", True):
            return
        m["auto"] = True
        if found:
            m.update(enabled=True, bottom=found["bottom"], height=found["height"])
        else:
            m["enabled"] = False
    return store.update(pid, fn)


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
        cancel.check(pid)
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

    futures = [(i, light.submit(one, i)) for i in todo]
    try:
        for i, f in futures:
            try:
                # every TTS call has its own timeout; this is the last safety net against a stuck line
                f.result(timeout=300)
            except FutureTimeout:
                raise TimeoutError(f"Tạo giọng câu #{segs[i]['id']} quá 5 phút nên đã dừng. Thử lại hoặc đổi giọng khác.")
            except Cancelled:
                raise
            except Exception as e:
                raise RuntimeError(f"Tạo giọng câu #{segs[i]['id']} lỗi: {e}")
    except BaseException:
        for _, f in futures:
            f.cancel()
        raise


def _render(pid: str, preview_start: float | None):
    d = store.pdir(pid)
    step(pid, "dubbing", 0, "Đang tạo giọng lồng tiếng…")
    synth_missing(pid, lambda x: step(pid, "dubbing", x, "Đang tạo giọng lồng tiếng…"))

    p = store.load(pid)
    st, media = p["settings"], p["media"]
    dub.mix(d, p["segments"], media["duration"], d / "dub.wav")

    src = d / p["source"]["file"]
    bg = None
    if st["audio_mode"] == "duck":
        bg = src
    elif st["audio_mode"] == "demucs":
        step(pid, "separating", None, "Đang tách nhạc nền (demucs, vài phút)…")
        bg = render.separate_background(d, src)

    render.write_srt(p["segments"], media["duration"], d / "out" / "phude.srt")
    render.write_transcript(p["segments"], d / "out" / "transcript.json", d / "out" / "transcript.txt")

    preview = preview_start is not None
    out = d / "out" / ("preview.mp4" if preview else "final.mp4")
    label = "Đang dựng bản xem thử…" if preview else "Đang xuất video…"
    step(pid, "rendering", 0, label)
    render.render(d, p, out, bg,
                  start=preview_start or 0.0,
                  length=min(30.0, media["duration"] - preview_start) if preview else None,
                  on_progress=lambda x: step(pid, "rendering", x, label))

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
