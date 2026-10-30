"""Background jobs. One heavy job at a time: Whisper/demucs twice on 16GB would swap."""

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from . import cancel, dub, ocr, outdir, render, store, stt, timeline, translate, vieneu_tts
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
            script=p["settings"].get("script"), target=p["settings"]["target"])
        if finder:
            apply_mask_detection(pid, found_future.result())
    finally:
        if finder:
            finder.shutdown(wait=False)

    for i, s in enumerate(segs):
        s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, media["duration"]), p["settings"]["rate"], p["settings"]["target"])

    def fin(q):
        q["segments"] = segs
        q["translated_to"] = p["settings"]["target"]
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


def _lang_of(p: dict, src: int) -> str:
    if src == 0:
        return p.get("detected_lang") or p["settings"]["lang"]
    e = next((x for x in timeline.extra_sources(p) if x["id"] == src), {})
    return e.get("lang") or p["settings"]["lang"]


def _rewrite(pid: str):
    p = store.load(pid)
    segs = [dict(s, vi="") for s in p["segments"]]
    mode = p["settings"]["script"]["mode"]
    label = "Đang viết lại lời dẫn…" if mode == "review" else "Đang dịch lại…"
    step(pid, "translating", 0, label)
    durs = timeline.source_durations(p)
    # each video on its own: lengths of lines and the context sent to the AI only make sense within one video
    groups: dict[int, list[dict]] = {}
    for s in segs:
        groups.setdefault(s.get("src_id", 0), []).append(s)
    warnings: list[str] = []
    for gi, (src, group) in enumerate(groups.items()):
        warnings += translate.translate_all(
            group, durs.get(src, p["media"]["duration"]), _lang_of(p, src), p["settings"]["rate"],
            lambda x, gi=gi: step(pid, "translating", (gi + x) / len(groups), label),
            script=p["settings"]["script"], target=p["settings"]["target"])
    dur = p["media"]["duration"]
    for i, s in enumerate(segs):
        s["fit"] = (dub.estimate(s["vi"], dub.slot(segs, i, dur), p["settings"]["rate"], p["settings"]["target"])
                    if s["vi"].strip() else None)

    def fin(q):
        q["segments"] = segs  # old voice clips no longer match the text, so they get remade on export
        q["translated_to"] = p["settings"]["target"]
        q["warnings"] = list(dict.fromkeys(warnings))
        q["edited_at"] = time.time()
        q["status"] = {"stage": "review", "progress": None,
                       "message": "Đã viết lại. Kiểm tra rồi bấm Lồng tiếng.", "error": None}
    store.update(pid, fin)


# ---------- another video added to the timeline: recognise + translate its speech like the main one

def submit_extra(pid: str, n: int):
    _submit(pid, _prepare_extra, n)


def _prepare_extra(pid: str, n: int):
    d = store.pdir(pid)
    p = store.load(pid)
    info = next(e for e in timeline.extra_sources(p) if e["id"] == n)
    st = p["settings"]
    name = f"video {n + 1}"

    def finish(msg: str, segs=None, lang=None, warnings=None):
        def fin(q):
            if segs:
                q["segments"] = q["segments"] + segs
            for e in q.get("extra_sources", []):
                if e["id"] == n and lang:
                    e["lang"] = lang
            if warnings:
                q["warnings"] = list(dict.fromkeys(q.get("warnings", []) + warnings))
            q["edited_at"] = time.time()
            q["status"] = {"stage": "review", "progress": None, "message": msg, "error": None}
        store.update(pid, fin)

    if not info.get("has_audio", True):
        finish(f"Đã thêm {name}. Video này không có tiếng nên không có lời thoại.")
        return
    step(pid, "extracting", None, f"Đang tách âm thanh {name}…")
    wav = d / f"audio16k_{n}.wav"
    extract_audio_16k(d / info["file"], wav)
    if not stt.model_cached():
        msg = "Lần đầu chạy: đang tải model nhận dạng giọng (~1.6GB), chỉ tải một lần…"
        step(pid, "model", None, msg)
        stt.ensure_model(lambda f: step(pid, "model", f, msg))
    step(pid, "transcribing", 0, f"Đang nhận dạng giọng nói {name}…")
    last = [0.0]

    def prog(x):
        cancel.check(pid)
        if x - last[0] >= 0.02 or x >= 1:
            last[0] = x
            step(pid, "transcribing", x, f"Đang nhận dạng giọng nói {name}…")

    segs, lang = stt.transcribe(wav, st["lang"], prog)
    if not segs:
        finish(f"Đã thêm {name}. Không nhận dạng được câu thoại nào trong video này.", lang=lang)
        return
    step(pid, "translating", 0, f"Đang dịch {len(segs)} câu của {name}…")
    warnings = translate.translate_all(
        segs, info["duration"], lang, st["rate"],
        lambda x: step(pid, "translating", x, f"Đang dịch {len(segs)} câu của {name}…"),
        script=st.get("script"), target=st["target"])
    base = max([s["id"] for s in p["segments"]] + [0])   # ids stay unique across all videos
    for k, s in enumerate(segs, 1):
        s["id"] = base + k
        s["src_id"] = n
    for i, s in enumerate(segs):
        s["fit"] = dub.estimate(s["vi"], dub.slot(segs, i, info["duration"]), st["rate"], st["target"])
    finish(f"Đã thêm {name}. Kiểm tra bản dịch rồi bấm Lồng tiếng.", segs, lang, warnings)


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


def slot_fn(p: dict):
    """(slot_of(i), in_export(seg)) for the lines of project `p`: the room each line has in the video that will be
    exported (the edited one when there are cuts), and whether the line is part of that video at all."""
    segs, dur = p["segments"], p["media"]["duration"]
    if timeline.is_edited(p):
        vslots = timeline.slots(timeline.clips_of(p), segs, dub.slot)
        return (lambda i: vslots.get(segs[i]["id"], dub.slot(segs, i, dur))), (lambda s: s["id"] in vslots)
    return (lambda i: dub.slot(segs, i, dur)), (lambda s: s.get("src_id", 0) == 0)


def synth_missing(pid: str, on_progress=None) -> None:
    p = store.load(pid)
    st, dur = p["settings"], p["media"]["duration"]
    segs = p["segments"]
    # with cuts, a line can land closer to the next one: fit its speed to the slot it has in the edited video,
    # and don't pay for voices of lines that were cut out
    slot_of, in_export = slot_fn(p)

    def too_long_now(i):
        t, s = segs[i].get("tts"), segs[i]
        if not t or not s["vi"].strip():
            return False
        was = t.get("slot") or dub.slot(segs, i, dur)  # lines made before this existed were fitted to the original
        shrank = slot_of(i) < was - 0.15 and t["secs"] > slot_of(i) * 1.02
        # the edit was undone: a voice sped up for a short slot is slower than it needs to be
        grew = slot_of(i) > was + 0.5 and ((s.get("fit") or {}).get("speed") or 1) > 1.01
        return shrank or grew

    todo = [i for i, s in enumerate(segs)
            if in_export(s) and (dub.needs_tts(s, st["voice"], st["rate"]) or too_long_now(i))]
    done = [0]

    def one(i):
        cancel.check(pid)
        res = dub.make_line(store.pdir(pid), segs[i], slot_of(i), st["voice"], st["rate"])
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


def _ensure_voice_model(pid: str, voice: str) -> None:
    if voice.startswith("vieneu:") and not vieneu_tts.model_ready():
        msg = f"Lần đầu dùng giọng VieNeu: đang tải model (~{vieneu_tts.SIZE_MB}MB), chỉ tải một lần…"
        step(pid, "model", None, msg)
        vieneu_tts.ensure_model(lambda f: step(pid, "model", f, msg))


def _render(pid: str, preview_start: float | None):
    d = store.pdir(pid)
    _ensure_voice_model(pid, store.load(pid)["settings"]["voice"])
    step(pid, "dubbing", 0, "Đang tạo giọng lồng tiếng…")
    synth_missing(pid, lambda x: step(pid, "dubbing", x, "Đang tạo giọng lồng tiếng…"))

    p = store.load(pid)
    if timeline.is_edited(p):
        step(pid, "rendering", 0, "Đang cắt ghép video…")
    # no edit: the project itself. Edited: a copy in output time (lines re-timed, edit.mp4 as the source)
    p = timeline.virtual(d, p, lambda x: step(pid, "rendering", x, "Đang cắt ghép video…"))
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
    if not preview:
        deliver(pid)


def deliver(pid: str) -> dict:
    """Copy the finished video to the folder chosen in Cài đặt (if any). Never fails the export."""
    if outdir.current() is None:
        return {}
    p = store.load(pid)
    d = store.pdir(pid)
    prev = (p["outputs"].get("saved") or {}).get("path")
    res = outdir.deliver(d / "out" / "final.mp4", p["title"], pid, prev)
    store.update(pid, lambda q: q["outputs"].__setitem__("saved", res))
    return res


def line_tts(pid: str, sid: int) -> dict:
    """Regenerate one line now (used by the ↻ button). Runs on the light pool."""
    p = store.load(pid)
    st, dur = p["settings"], p["media"]["duration"]
    segs = p["segments"]
    i = next(k for k, s in enumerate(segs) if s["id"] == sid)
    res = dub.make_line(store.pdir(pid), segs[i], slot_fn(p)[0](i), st["voice"], st["rate"])
    text = segs[i]["vi"]

    def apply(q):
        for s in q["segments"]:
            if s["id"] == sid and s["vi"] == text:
                s.update(res)
    return store.update(pid, apply)
