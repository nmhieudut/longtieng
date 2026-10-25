"""Speech-to-text with mlx-whisper (Apple Silicon GPU)."""

import re
from pathlib import Path

import opencc
import soundfile as sf

from .config import WHISPER_MODEL

_t2s = opencc.OpenCC("t2s")
_PUNCT_ONLY = re.compile(r"^[\s\W_]*$", re.UNICODE)


def model_cached() -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
        r = try_to_load_from_cache(WHISPER_MODEL, "config.json")
        return isinstance(r, str)
    except Exception:
        return False


def ensure_model(on_progress=None) -> None:
    if model_cached():
        return
    from huggingface_hub import snapshot_download
    if on_progress:
        on_progress(None)
    snapshot_download(WHISPER_MODEL)


def transcribe(audio: Path, lang: str, on_progress=None) -> tuple[list[dict], str]:
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
        # Pass samples, not a path: mlx-whisper would shell out to whatever `ffmpeg` is on PATH
        samples, sr = sf.read(str(audio), dtype="float32")
        assert sr == 16000, sr
        result = mlx_whisper.transcribe(
            samples,
            path_or_hf_repo=WHISPER_MODEL,
            language=None if lang == "auto" else lang,
            verbose=False,
            condition_on_previous_text=False,   # avoids repetition loops
            word_timestamps=True,
            hallucination_silence_threshold=2.0,
            no_speech_threshold=0.6,
            initial_prompt="以下是普通话的句子。" if lang == "zh" else None,
        )
    finally:
        mt.tqdm.tqdm = orig_tqdm

    detected = result.get("language") or lang
    return clean_segments(result["segments"], detected), detected


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
