"""Offline Vietnamese voices (VieNeu-TTS v3 Turbo, Apache-2.0, https://github.com/pnnbao97/VieNeu-TTS).

Runs on the CPU through onnxruntime, no torch. The model (~540MB) is downloaded once into
USER_DIR/models/vieneu as plain files: onnxruntime refuses graphs that reach their weights through
the symlinks of the Hugging Face cache.
"""

import importlib.util
import os
import threading
import time
import unicodedata
from pathlib import Path

from . import cancel

BACKBONE_REPO = "pnnbao-ump/VieNeu-TTS-v3-Turbo"
CODEC_REPO = "OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX"
# preset voices need no cloning, so skip the speaker/encoder files
BACKBONE_FILES = ["onnx_update/*"]
CODEC_FILES = ["moss_audio_tokenizer_decode_full.onnx", "moss_audio_tokenizer_decode_shared.data",
               "moss_audio_tokenizer_decode_step.onnx", "codec_browser_onnx_meta.json"]
SIZE_MB = 500

SAMPLE_RATE = 48_000

# (name inside the model, gender, accent, style)  — the 25 voices that ship with VieNeu-TTS v3 Turbo
_PRESETS = [
    ("Adam bựa", "nam", "Bắc", "tự nhiên"), ("Trúc Ly", "nữ", "Bắc", "tự nhiên"),
    ("Thiện Minh", "nam", "Bắc", "kể chuyện"), ("Mai Anh", "nữ", "Bắc", "tin tức"),
    ("Hải Đăng", "nam", "Bắc", "tự nhiên"), ("Thùy Dung", "nữ", "Nam", "tin tức"),
    ("Thiền Tâm Đức", "nam", "Bắc", "kể chuyện"), ("Ngọc Huyền", "nữ", "Bắc", "tự nhiên"),
    ("Quang Sơn", "nam", "Trung", "tự nhiên"), ("Ngọc Trân", "nữ", "Trung", "tự nhiên"),
    ("Minh Đức", "nam", "Bắc", "tin tức"), ("Phạm Tuyên", "nam", "Bắc", "tự nhiên"),
    ("Thái Sơn", "nam", "Nam", "kể chuyện"), ("Xuân Vĩnh", "nam", "Bắc", "tự nhiên"),
    ("Thanh Bình", "nam", "Bắc", "kể chuyện"), ("Ngọc Linh", "nữ", "Bắc", "kể chuyện"),
    ("Đoan Trang", "nữ", "Bắc", "tự nhiên"), ("Thục Đoan", "nữ", "Nam", "kể chuyện"),
    ("Minh Triết", "nam", "Nam", "tin tức"), ("Mỹ Duyên", "nữ", "Nam", "đọc truyện"),
    ("Quỳnh Anh", "nữ", "Bắc", "đọc truyện"), ("Đức Trí", "nam", "Nam", "đọc truyện"),
    ("Kim Thanh", "nữ", "Nam", "đọc truyện"), ("Adam", "nam", "Nam", "tự nhiên"),
    ("Quốc Tuấn", "nam", "Bắc", "tự nhiên"),
]


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return "_".join(s.lower().split())


# voice id (ASCII, safe in URLs and file names) -> name inside the model
_NAMES = {_slug(n): n for n, *_ in _PRESETS}


def presets() -> list[dict]:
    return [{"id": _slug(n), "name": n, "gender": g, "accent": a, "style": s} for n, g, a, s in _PRESETS]


def available() -> bool:
    """The package is part of this build (a source checkout without it just hides the voices)."""
    return importlib.util.find_spec("vieneu") is not None


def model_dir() -> Path:
    from .config import USER_DIR  # not at import time: config imports this module while it is still loading

    return Path(os.getenv("LONGTIENG_VIENEU_DIR") or USER_DIR / "models" / "vieneu")


def _done_marker() -> Path:
    return model_dir() / ".complete"


def model_ready() -> bool:
    return _done_marker().exists()


# ---------- download

_dl = {"running": False, "progress": None, "error": None}
_dl_lock = threading.Lock()


def download_state() -> dict:
    return dict(_dl) | {"ready": model_ready()}


def ensure_model(on_progress=None) -> None:
    """Download once. Progress = bytes on disk / total size of the files we ask for."""
    if model_ready():
        return
    from huggingface_hub import HfApi, snapshot_download

    root = model_dir()
    root.mkdir(parents=True, exist_ok=True)
    jobs = [(BACKBONE_REPO, BACKBONE_FILES, root / "backbone"), (CODEC_REPO, CODEC_FILES, root / "codec")]
    total = 0
    try:
        from fnmatch import fnmatch
        for repo, pats, _dest in jobs:
            info = HfApi().model_info(repo, files_metadata=True, timeout=30)
            total += sum(f.size or 0 for f in info.siblings or [] if any(fnmatch(f.rfilename, p) for p in pats))
    except Exception:
        total = SIZE_MB * 1_048_576
    done = threading.Event()

    def watch():
        while not done.wait(1.0):
            if on_progress and total:
                got = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
                on_progress(min(0.99, got / total))

    threading.Thread(target=watch, daemon=True).start()
    try:
        for repo, pats, dest in jobs:
            for attempt in range(3):
                cancel.check()
                try:
                    snapshot_download(repo, local_dir=str(dest), allow_patterns=pats)
                    break
                except Exception as e:
                    if attempt == 2:
                        raise RuntimeError(f"Không tải được model giọng VieNeu ({type(e).__name__}). "
                                           "Kiểm tra mạng rồi thử lại; phần đã tải sẽ được giữ.") from e
                    time.sleep(3)
        _done_marker().write_text(BACKBONE_REPO)
    finally:
        done.set()


def start_download() -> dict:
    """Background download for the Settings button."""
    with _dl_lock:
        if _dl["running"] or model_ready():
            return download_state()
        _dl.update(running=True, progress=0.0, error=None)

    def run():
        try:
            ensure_model(lambda x: _dl.update(progress=x))
        except Exception as e:  # shown in Settings
            _dl["error"] = str(e)
        finally:
            _dl.update(running=False, progress=None)

    threading.Thread(target=run, daemon=True).start()
    return download_state()


# ---------- synthesis

_engine = None
_engine_lock = threading.Lock()  # one engine (~2GB RAM), one line at a time


def _load():
    from pathlib import Path as _P

    from vieneu import Vieneu
    from vieneu._v3_turbo_engine import onnx_runtime_lite as eng

    root = model_dir()
    codec = str(root / "codec")
    # The wrapper does not pass `codec_dir` down; without it the engine fetches the codec through the
    # Hugging Face cache (symlinks, rejected by onnxruntime). vieneu is pinned so this stays valid.
    cls = eng.OnnxV3LiteEngine
    if not getattr(cls, "_longtieng_patched", False):
        orig = cls.__init__

        def init(self, *a, **kw):
            kw.setdefault("codec_dir", codec)
            orig(self, *a, **kw)

        cls.__init__ = init
        cls._longtieng_patched = True
    return Vieneu(backbone_repo=str(_P(root / "backbone")), onnx_dir=str(root / "backbone" / "onnx_update"))


def synth_wav(text: str, voice_id: str, out: Path) -> None:
    """Read `text` with a preset voice into a WAV file."""
    import numpy as np
    import soundfile as sf

    name = _NAMES.get(voice_id)
    if name is None:
        raise RuntimeError(f"Không có giọng VieNeu “{voice_id}”.")
    if not model_ready():
        raise RuntimeError("Chưa tải model giọng VieNeu (~540MB). Mở Cài đặt (bánh răng) để tải một lần, "
                           "hoặc cứ xuất video, app sẽ tự tải.")
    global _engine
    with _engine_lock:
        cancel.check()
        if _engine is None:
            _engine = _load()
        audio = _engine.infer(text, voice=name)
    sf.write(str(out), np.asarray(audio, dtype=np.float32), SAMPLE_RATE, format="WAV", subtype="PCM_16")
