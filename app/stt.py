"""Speech-to-text. Apple Silicon: mlx-whisper (GPU). Windows / other: faster-whisper (CPU, int8).

Both run Whisper large-v3-turbo locally; the model (~1.6GB) is downloaded once on first use.
"""

import os
import platform
import re
import sys
import threading
import time
from pathlib import Path

import opencc
import soundfile as sf

from . import cancel

_t2s = opencc.OpenCC("t2s")
_PUNCT_ONLY = re.compile(r"^[\s\W_]*$", re.UNICODE)


def engine() -> str:
    forced = os.getenv("LONGTIENG_STT", "").strip()
    if forced in ("mlx", "faster"):
        return forced
    return "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "faster"


def engine_label() -> str:
    return "Whisper turbo (Apple GPU)" if engine() == "mlx" else "Whisper turbo (CPU)"


def _repo() -> str:
    """Hugging Face repo of the model for the active engine.
    WHISPER_MODEL overrides the mlx model, FASTER_WHISPER_MODEL the faster-whisper one (e.g. 'tiny' in CI)."""
    if engine() == "mlx":
        return os.getenv("WHISPER_MODEL", "").strip() or "mlx-community/whisper-large-v3-turbo"
    from faster_whisper.utils import _MODELS
    name = os.getenv("FASTER_WHISPER_MODEL", "").strip() or "large-v3-turbo"
    return _MODELS.get(name, name)


def _probe_file() -> str:
    return "config.json" if engine() == "mlx" else "model.bin"


def model_cached() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        return isinstance(try_to_load_from_cache(_repo(), _probe_file()), str)
    except Exception:
        return False


def ensure_model(on_progress=None) -> None:
    """Download the model once. Progress comes from bytes on disk vs. the repo's total size."""
    if model_cached():
        return
    from huggingface_hub import HfApi, snapshot_download
    from huggingface_hub.constants import HF_HUB_CACHE

    repo = _repo()
    total = 0
    try:
        info = HfApi().model_info(repo, files_metadata=True, timeout=30)
        total = sum(f.size or 0 for f in info.siblings or [])
    except Exception:
        pass
    folder = Path(HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "blobs"
    done = threading.Event()

    def watch():
        while not done.wait(1.0):
            if on_progress and total:
                got = sum(f.stat().st_size for f in folder.glob("*") if f.is_file()) if folder.exists() else 0
                on_progress(min(0.99, got / total))

    threading.Thread(target=watch, daemon=True).start()
    try:
        for attempt in range(3):
            cancel.check()
            try:
                snapshot_download(repo)
                break
            except Exception as e:
                if attempt == 2:
                    raise RuntimeError(f"Không tải được model nhận dạng giọng ({type(e).__name__}). "
                                       "Kiểm tra mạng rồi bấm Thử lại; phần đã tải sẽ được giữ.") from e
                time.sleep(3)
    finally:
        done.set()


def transcribe(audio: Path, lang: str, on_progress=None) -> tuple[list[dict], str]:
    # Pass samples, not a path: the engines would otherwise shell out to whatever `ffmpeg` is on PATH
    samples, sr = sf.read(str(audio), dtype="float32")
    assert sr == 16000, sr
    language = None if lang == "auto" else lang
    prompt = "以下是普通话的句子。" if lang == "zh" else None
    if engine() == "mlx":
        raw, detected = _mlx(samples, language, prompt, on_progress)
    else:
        raw, detected = _faster(samples, language, prompt, on_progress)
    detected = detected or lang
    return clean_segments(raw, detected), detected


def _mlx(samples, language, prompt, on_progress):
    import importlib

    import mlx_whisper

    # `import mlx_whisper.transcribe as mt` would give the re-exported function, not the module
    mt = importlib.import_module("mlx_whisper.transcribe")

    # mlx-whisper reports progress through tqdm; hook it to get a percentage.
    orig_tqdm = mt.tqdm.tqdm

    class Hook(orig_tqdm):
        def __init__(self, *a, **kw):
            kw["disable"] = False
            super().__init__(*a, **kw)

        def update(self, n=1):
            r = super().update(n)
            if on_progress and self.total:
                on_progress(min(1.0, self.n / self.total))
            return r

    mt.tqdm.tqdm = Hook
    try:
        result = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=_repo(),
            language=language,
            verbose=False,
            condition_on_previous_text=False,   # avoids repetition loops
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
            no_speech_threshold=0.6,
            initial_prompt=prompt,
        )
    finally:
        mt.tqdm.tqdm = orig_tqdm
    return result["segments"], result.get("language")


_fw_model = None
_fw_lock = threading.Lock()


def _faster(samples, language, prompt, on_progress):
    global _fw_model
    from faster_whisper import WhisperModel

    with _fw_lock:
        if _fw_model is None:
            _fw_model = WhisperModel(_repo(), device="cpu", compute_type="int8",
                                     cpu_threads=max(1, (os.cpu_count() or 4) - 1))
    segments, info = _fw_model.transcribe(
        samples,
        language=language,
        beam_size=1,                        # greedy, like mlx-whisper; much faster on CPU
        condition_on_previous_text=False,
        word_timestamps=True,
        hallucination_silence_threshold=2.0,
        no_speech_threshold=0.6,
        initial_prompt=prompt,
    )
    dur = max(0.1, float(info.duration or len(samples) / 16000))
    raw = []
    for seg in segments:  # lazy: the work happens while iterating
        cancel.check()
        raw.append({"start": seg.start, "end": seg.end, "text": seg.text, "no_speech_prob": seg.no_speech_prob,
                    "avg_logprob": seg.avg_logprob, "compression_ratio": seg.compression_ratio})
        if on_progress:
            on_progress(min(1.0, seg.end / dur))
    return raw, info.language


def clean_segments(raw: list[dict], lang: str) -> list[dict]:
    out = []
    prev_text, repeat = None, 0
    for s in raw:
        text = (s.get("text") or "").strip()
        if lang and lang.startswith("zh"):
            text = _t2s.convert(text)
        if not text or _PUNCT_ONLY.match(text):
            continue
        # Music/silence hallucinations: low confidence + likely no speech
        if s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -0.8:
            continue
        if s.get("compression_ratio", 0) > 2.6:
            continue
        if text == prev_text:
            repeat += 1
            if repeat >= 1:
                continue
        else:
            repeat = 0
        prev_text = text
        start, end = float(s["start"]), float(s["end"])
        if end - start < 0.2:
            continue
        out.append({"start": round(start, 2), "end": round(end, 2), "src": text})
    for i, s in enumerate(out):
        s["id"] = i + 1
        s["vi"] = ""
        s["tts"] = None
        s["fit"] = None
    return out
