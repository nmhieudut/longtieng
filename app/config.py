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
# cookies.txt (Netscape format) exported from the browser; used instead of the browser when set
YTDLP_COOKIES_FILE = os.path.expanduser(os.getenv("YTDLP_COOKIES_FILE", "").strip())
if YTDLP_COOKIES_FILE and not os.path.isabs(YTDLP_COOKIES_FILE):
    YTDLP_COOKIES_FILE = str(ROOT / YTDLP_COOKIES_FILE)

ALLOW_LAN = os.getenv("ALLOW_LAN", "0") == "1"
PORT = int(os.getenv("PORT", "8000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
MAX_DURATION_MIN = float(os.getenv("MAX_DURATION_MIN", "15"))

FONTS_DIR = "/System/Library/Fonts/Supplemental"
SUB_FONT = "Arial"

OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()


def _voices() -> dict[str, dict]:
    v = {}

    def add(vid, label, group, gender, note=""):
        v[vid] = {"label": label, "group": group, "gender": gender, "note": note}

    main = "Giọng chính"
    add("google:vi", "Chị Google", main, "nữ", "Giọng Google Dịch quen thuộc, vui, rõ ràng · miễn phí")
    add("vi-VN-HoaiMyNeural", "Hoài My", "Giọng Việt (Edge, miễn phí)", "nữ", "Giọng chuẩn miền Bắc")
    add("vi-VN-NamMinhNeural", "Nam Minh", "Giọng Việt (Edge, miễn phí)", "nam", "Giọng chuẩn miền Bắc")
    # Edge "multilingual" voices also speak Vietnamese (checked by transcribing them back with Whisper)
    multi = [
        ("en-US-AvaMultilingualNeural", "Ava", "nữ"), ("en-US-EmmaMultilingualNeural", "Emma", "nữ"),
        ("fr-FR-VivienneMultilingualNeural", "Vivienne", "nữ"), ("de-DE-SeraphinaMultilingualNeural", "Seraphina", "nữ"),
        ("pt-BR-ThalitaMultilingualNeural", "Thalita", "nữ"),
        ("en-US-AndrewMultilingualNeural", "Andrew", "nam"), ("en-US-BrianMultilingualNeural", "Brian", "nam"),
        ("en-AU-WilliamMultilingualNeural", "William", "nam"), ("fr-FR-RemyMultilingualNeural", "Rémy", "nam"),
        ("de-DE-FlorianMultilingualNeural", "Florian", "nam"), ("it-IT-GiuseppeMultilingualNeural", "Giuseppe", "nam"),
        ("ko-KR-HyunsuMultilingualNeural", "Hyunsu", "nam"),
    ]
    for vid, name, g in multi:
        add(vid, name, "Đa ngôn ngữ (Edge, miễn phí)", g, "Có thể hơi lơ lớ")
    if OPENAI_API_KEY:
        for name, g in [("coral", "nữ"), ("nova", "nữ"), ("shimmer", "nữ"), ("sage", "nữ"),
                        ("ash", "nam"), ("onyx", "nam"), ("echo", "nam"), ("verse", "nam")]:
            add(f"openai:{name}", name.capitalize(), "OpenAI (tốn phí ~0,015$/phút)", g, "Biểu cảm hơn, đọc chậm hơn")
    return v


VOICES = _voices()

# Vietnamese TTS speaks roughly this many characters per second at 1.0x.
# Used to estimate whether a line fits before any audio exists.
VI_CHARS_PER_SEC = 17.0  # measured ~16–19 on HoaiMy at 1.0x
# Edge TTS speed-up we allow on a single line, then atempo on top of that.
MAX_EDGE_SPEEDUP = 1.35
MAX_ATEMPO = 1.15

SAMPLE_RATE = 48000

DEFAULT_SETTINGS = {
    "lang": "zh",              # "zh" | "auto"
    "voice": "google:vi",
    "rate": 1.0,               # 0.8 – 1.3
    "audio_mode": "duck",      # "duck" | "demucs" | "mute"
    "orig_volume": 0.15,       # background volume for duck/demucs
    "subtitle_mode": "burn",   # "burn" | "srt" | "none"
    "sub_size": 1.0,           # multiplier
    "sub_margin": 8,           # % from bottom when mask is off
    "music": {
        "track": None,         # id in the shared music library, None = no music
        "volume": 0.4,
        "duck": True,          # lower the music while the dub voice speaks
        "start": 0.0,          # skip the intro: start the track at this second
    },
    "mask": {
        "enabled": False,
        "auto": True,          # detect the burned-in subtitle band with OCR
        "style": "blur",       # "blur" | "box"
        "bottom": 10,          # % from bottom edge to band bottom
        "height": 12,          # % of video height
    },
}
