import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data" / "projects"
WEB_DIR = ROOT / "web" / "out"  # Next.js static export
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _bin(env: str, brew_path: str, name: str) -> str:
    if os.getenv(env):
        return os.environ[env]
    # ffmpeg-full is keg-only, so the plain `ffmpeg` on PATH has no libass
    if Path(brew_path).exists():
        return brew_path
    return shutil.which(name) or name


FFMPEG = _bin("FFMPEG", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "ffmpeg")
FFPROBE = _bin("FFPROBE", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe", "ffprobe")
YTDLP = shutil.which("yt-dlp") or "yt-dlp"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
YTDLP_COOKIES_BROWSER = os.getenv("YTDLP_COOKIES_BROWSER", "").strip()

ALLOW_LAN = os.getenv("ALLOW_LAN", "0") == "1"
PORT = int(os.getenv("PORT", "8000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
MAX_DURATION_MIN = float(os.getenv("MAX_DURATION_MIN", "15"))

FONTS_DIR = "/System/Library/Fonts/Supplemental"
SUB_FONT = "Arial"

VOICES = {
    "vi-VN-HoaiMyNeural": "Hoài My (nữ)",
    "vi-VN-NamMinhNeural": "Nam Minh (nam)",
}

# Vietnamese TTS speaks roughly this many characters per second at 1.0x.
# Used to estimate whether a line fits before any audio exists.
VI_CHARS_PER_SEC = 17.0  # measured ~16–19 on HoaiMy at 1.0x
# Edge TTS speed-up we allow on a single line, then atempo on top of that.
MAX_EDGE_SPEEDUP = 1.35
MAX_ATEMPO = 1.15

SAMPLE_RATE = 48000

DEFAULT_SETTINGS = {
    "lang": "zh",              # "zh" | "auto"
    "voice": "vi-VN-HoaiMyNeural",
    "rate": 1.0,               # 0.8 – 1.3
    "audio_mode": "duck",      # "duck" | "demucs" | "mute"
    "orig_volume": 0.15,       # background volume for duck/demucs
    "subtitle_mode": "burn",   # "burn" | "srt" | "none"
    "sub_size": 1.0,           # multiplier
    "sub_margin": 8,           # % from bottom when mask is off
    "mask": {
        "enabled": False,
        "style": "blur",       # "blur" | "box"
        "bottom": 10,          # % from bottom edge to band bottom
        "height": 12,          # % of video height
    },
}
