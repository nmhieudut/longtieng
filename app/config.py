import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

# Source checkout: the repo. Packaged app: the "code" folder (bundled, or a newer one from an update).
ROOT = Path(__file__).resolve().parent.parent
# Packaged desktop app (PyInstaller): bundled files live in _MEIPASS, user data in the OS app-data folder
FROZEN = bool(getattr(sys, "frozen", False))
RES_DIR = Path(getattr(sys, "_MEIPASS", ROOT))


def _read(*paths: Path) -> str:
    for p in paths:
        if p.is_file():
            return p.read_text().strip()
    return "0.0.0"


# APP_VERSION changes with every release; SHELL_VERSION only when the native part (Python, libraries,
# ffmpeg) changes. A light update replaces just the code, so it needs the same SHELL_VERSION.
APP_VERSION = _read(ROOT / "VERSION", ROOT / "packaging" / "VERSION")
SHELL_VERSION = _read(RES_DIR / "meta" / "SHELL_VERSION", ROOT / "packaging" / "SHELL_VERSION")
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"


def _user_dir() -> Path:
    if os.getenv("LONGTIENG_HOME"):
        return Path(os.environ["LONGTIENG_HOME"]).expanduser()
    if not FROZEN:
        return ROOT / "data"  # running from source: keep everything inside the repo
    if IS_WIN:
        return Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "Longtieng"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "Longtieng"
    return Path.home() / ".local" / "share" / "longtieng"


USER_DIR = _user_dir()
USER_DIR.mkdir(parents=True, exist_ok=True)
if not FROZEN:
    load_dotenv(ROOT / ".env")
load_dotenv(USER_DIR / ".env")
if FROZEN:
    # Whisper models stay in the standard ~/.cache/huggingface, shared with other tools (no re-download)
    try:  # frozen apps often can't find the system CA store -> every HTTPS call fails
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass

DATA_DIR = USER_DIR / "projects"
WEB_DIR = ROOT / "web" / "out"  # Next.js static export
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------- settings the user edits inside the app (API key, ...)

_SETTINGS_FILE = USER_DIR / "settings.json"


def user_settings() -> dict:
    try:
        return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_user_settings(patch: dict) -> dict:
    s = user_settings()
    s.update(patch)
    tmp = _SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_SETTINGS_FILE)
    return s


def openai_key() -> str:
    """Key typed in the app wins over OPENAI_API_KEY from .env."""
    return (user_settings().get("openai_key") or os.getenv("OPENAI_API_KEY", "")).strip()


# ---------- bundled tools

_EXE = ".exe" if IS_WIN else ""


def _bin(env: str, name: str, brew_path: str = "") -> str:
    if os.getenv(env):
        return os.environ[env]
    bundled = RES_DIR / "bin" / f"{name}{_EXE}"
    if bundled.exists():
        return str(bundled)
    # ffmpeg-full is keg-only, so the plain `ffmpeg` on PATH has no libass
    if brew_path and Path(brew_path).exists():
        return brew_path
    return shutil.which(name) or name


FFMPEG = _bin("FFMPEG", "ffmpeg", "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
FFPROBE = _bin("FFPROBE", "ffprobe", "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe")


def _ytdlp_cmd() -> list[str]:
    """The packaged app runs yt-dlp as itself (`Longtieng --yt-dlp ...`), so it stays killable by Huỷ."""
    if os.getenv("YTDLP"):
        return [os.environ["YTDLP"]]
    if FROZEN:
        return [sys.executable, "--yt-dlp"]
    found = shutil.which("yt-dlp")
    return [found] if found else [sys.executable, "-m", "yt_dlp"]


YTDLP_CMD = _ytdlp_cmd()



def demucs_available() -> bool:
    """demucs needs torch (~2GB), so the desktop build leaves it out."""
    if FROZEN:
        return False
    import importlib.util
    return importlib.util.find_spec("demucs") is not None


OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
YTDLP_COOKIES_BROWSER = os.getenv("YTDLP_COOKIES_BROWSER", "").strip()
# cookies.txt (Netscape format) exported from the browser; used instead of the browser when set
YTDLP_COOKIES_FILE = os.path.expanduser(os.getenv("YTDLP_COOKIES_FILE", "").strip())
if YTDLP_COOKIES_FILE and not os.path.isabs(YTDLP_COOKIES_FILE):
    YTDLP_COOKIES_FILE = str((ROOT if not FROZEN else USER_DIR) / YTDLP_COOKIES_FILE)

ALLOW_LAN = os.getenv("ALLOW_LAN", "0") == "1"
PORT = int(os.getenv("PORT", "8000"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "2048"))
MAX_DURATION_MIN = float(os.getenv("MAX_DURATION_MIN", "30"))

# Subtitle font ships with the app (full Vietnamese glyphs, same look on Mac and Windows).
# ffmpeg's filter parser chokes on "C:\\..." paths, so filters reference fonts by a path relative
# to their working directory; copying them under USER_DIR keeps that path on the same drive.
SUB_FONT = "Be Vietnam Pro"
FONTS_DIR = USER_DIR / "fonts"
FONTS_DIR.mkdir(exist_ok=True)
for _f in (RES_DIR / "assets" / "fonts").glob("*.ttf"):
    _dst = FONTS_DIR / _f.name
    if not _dst.exists() or _dst.stat().st_size != _f.stat().st_size:
        shutil.copyfile(_f, _dst)

# Bundled ffmpeg builds use fontconfig, which looks for a config that doesn't exist on the
# user's machine. Point it at a tiny one that only knows our font folder.
if FROZEN or os.getenv("LONGTIENG_FONTCONFIG"):
    _fc = USER_DIR / "fontconfig.conf"  # not inside FONTS_DIR: libass tries to load every file there
    # Windows: also the system fonts, for subtitles in Chinese / Japanese / Korean / Thai (Microsoft YaHei, Yu Gothic,
    # Malgun Gothic, Leelawadee UI). macOS finds its own fallback fonts without this.
    _sys_fonts = f"  <dir>{Path(os.getenv('WINDIR') or 'C:/Windows') / 'Fonts'}</dir>\n" if IS_WIN else ""
    _fc.write_text(
        f"""<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>
  <dir>{FONTS_DIR}</dir>\n{_sys_fonts}  <cachedir>{USER_DIR / "fontcache"}</cachedir>\n</fontconfig>\n""",
        encoding="utf-8")
    os.environ["FONTCONFIG_FILE"] = str(_fc)


def fonts_rel(cwd: Path) -> str:
    """fontsdir= value for an ffmpeg filter that runs with this working directory."""
    return os.path.relpath(FONTS_DIR, cwd).replace("\\", "/")


OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()

# Language the video is dubbed INTO. "cps" = characters a TTS voice reads per second at 1.0x (measured with the
# Edge voices on a normal sentence; used to size translations and to estimate whether a line will fit).
TARGET_LANGS: dict[str, dict] = {
    "vi": {"label": "Tiếng Việt", "name": "tiếng Việt", "google": "vi", "voice": "google:vi", "cps": 17.0,
           "font_mac": "Be Vietnam Pro", "font_win": "Be Vietnam Pro", "cjk": False},
    "en": {"label": "Tiếng Anh", "name": "tiếng Anh", "google": "en", "voice": "en-US-AriaNeural", "cps": 16.0,
           "font_mac": "Be Vietnam Pro", "font_win": "Be Vietnam Pro", "cjk": False},
    "zh": {"label": "Tiếng Trung", "name": "tiếng Trung (giản thể)", "google": "zh-CN", "voice": "zh-CN-XiaoxiaoNeural",
           "cps": 5.0, "font_mac": "PingFang SC", "font_win": "Microsoft YaHei", "cjk": True},
    "ja": {"label": "Tiếng Nhật", "name": "tiếng Nhật", "google": "ja", "voice": "ja-JP-NanamiNeural", "cps": 5.5,
           "font_mac": "Hiragino Sans", "font_win": "Yu Gothic", "cjk": True},
    "ko": {"label": "Tiếng Hàn", "name": "tiếng Hàn", "google": "ko", "voice": "ko-KR-SunHiNeural", "cps": 7.5,
           "font_mac": "Apple SD Gothic Neo", "font_win": "Malgun Gothic", "cjk": True},
}


def target_info(code: str | None) -> dict:
    return TARGET_LANGS.get(code or "vi", TARGET_LANGS["vi"])


def sub_font(target: str | None) -> str:
    """Font family for burned-in subtitles in this language. Latin scripts use the bundled font; the others
    use a font every Mac / Windows already has."""
    info = target_info(target)
    return info["font_win" if IS_WIN else "font_mac"]


def _voices() -> dict[str, dict]:
    """id -> {label, group, gender, note, langs}. `langs` = target languages the voice can read."""
    v = {}

    def add(vid, label, group, gender, note="", langs=("vi",)):
        v[vid] = {"label": label, "group": group, "gender": gender, "note": note, "langs": list(langs)}

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
        # the English ones are also natural in English; the rest only claim Vietnamese
        add(vid, name, "Đa ngôn ngữ (Edge, miễn phí)", g, "Có thể hơi lơ lớ",
            langs=("vi", "en") if vid.startswith("en-") else ("vi", "ko") if vid.startswith("ko-") else ("vi",))
    # other languages: a few Edge voices (checked against Edge's own voice list) and Google's voice
    others = {
        "en": [("en-US-AriaNeural", "Aria", "nữ"), ("en-US-JennyNeural", "Jenny", "nữ"), ("en-US-GuyNeural", "Guy", "nam"),
               ("en-GB-SoniaNeural", "Sonia (Anh)", "nữ"), ("en-GB-RyanNeural", "Ryan (Anh)", "nam")],
        "zh": [("zh-CN-XiaoxiaoNeural", "Xiaoxiao", "nữ"), ("zh-CN-XiaoyiNeural", "Xiaoyi", "nữ"),
               ("zh-CN-YunxiNeural", "Yunxi", "nam"), ("zh-CN-YunjianNeural", "Yunjian", "nam"),
               ("zh-CN-YunyangNeural", "Yunyang", "nam")],
        "ja": [("ja-JP-NanamiNeural", "Nanami", "nữ"), ("ja-JP-KeitaNeural", "Keita", "nam")],
        "ko": [("ko-KR-SunHiNeural", "SunHi", "nữ"), ("ko-KR-InJoonNeural", "InJoon", "nam")],
    }
    for lang, items in others.items():
        grp = f"{TARGET_LANGS[lang]['label']} (Edge, miễn phí)"
        for vid, name, g in items:
            add(vid, name, grp, g, langs=(lang,))
        add(f"google:{TARGET_LANGS[lang]['google']}", "Google", grp, "nữ", "Giọng Google Dịch · miễn phí", langs=(lang,))
    # listed even without a key so the picker is stable; dub.py says when the key is missing
    for name, g in [("coral", "nữ"), ("nova", "nữ"), ("shimmer", "nữ"), ("sage", "nữ"),
                    ("ash", "nam"), ("onyx", "nam"), ("echo", "nam"), ("verse", "nam")]:
        add(f"openai:{name}", name.capitalize(), "OpenAI (cần API key, ~0,015$/phút)", g, "Biểu cảm hơn, đọc chậm hơn",
            langs=tuple(TARGET_LANGS))
    from . import vieneu_tts  # offline voices: only listed when this build has the package

    if vieneu_tts.available():
        for x in vieneu_tts.presets():
            add(f"vieneu:{x['id']}", x["name"], "VieNeu (offline, miễn phí)", x["gender"],
                f"Giọng {x['accent']} · {x['style']} · chạy trên máy, tải model ~{vieneu_tts.SIZE_MB}MB lần đầu")
    return v


def voice_ok(voice: str, target: str) -> bool:
    v = VOICES.get(voice)
    return bool(v and target in v["langs"])


def default_voice(target: str) -> str:
    return target_info(target)["voice"]


VOICES = _voices()

# Vietnamese TTS speaks roughly this many characters per second at 1.0x.
# Used to estimate whether a line fits before any audio exists.
VI_CHARS_PER_SEC = 17.0  # measured ~16–19 on HoaiMy at 1.0x (see TARGET_LANGS for the other languages)
# Edge TTS speed-up we allow on a single line, then atempo on top of that.
MAX_EDGE_SPEEDUP = 1.35
MAX_ATEMPO = 1.15

SAMPLE_RATE = 48000

# Spoken language of the source video (the dubbing language is chosen separately: TARGET_LANGS).
SOURCE_LANGS: dict[str, dict] = {
    "zh": {"label": "Tiếng Trung", "name": "tiếng Trung", "google": "zh-CN", "prompt": "以下是普通话的句子。",
           "names": "Tên riêng tiếng Trung: dùng Hán Việt nếu phổ biến, nếu không giữ phiên âm."},
    "en": {"label": "Tiếng Anh", "name": "tiếng Anh", "google": "en",
           "names": "Tên riêng, thương hiệu: giữ nguyên tiếng Anh."},
    "ja": {"label": "Tiếng Nhật", "name": "tiếng Nhật", "google": "ja",
           "names": "Tên riêng tiếng Nhật: viết phiên âm Latin (romaji), ví dụ Tanaka, Sakura."},
    "ko": {"label": "Tiếng Hàn", "name": "tiếng Hàn", "google": "ko",
           "names": "Tên riêng tiếng Hàn: viết phiên âm Latin, ví dụ Kim Ji-woo, Seoul."},
    "th": {"label": "Tiếng Thái", "name": "tiếng Thái", "google": "th",
           "names": "Tên riêng tiếng Thái: viết phiên âm Latin."},
    "auto": {"label": "Tự nhận diện", "name": "tiếng gốc", "google": "auto",
             "names": "Tên riêng: giữ phiên âm hoặc dạng quen dùng ở Việt Nam."},
}


def lang_info(code: str | None) -> dict:
    """Info for a language code (also Whisper's detected codes like 'es' that aren't in the list)."""
    if code in SOURCE_LANGS:
        return SOURCE_LANGS[code]
    base = dict(SOURCE_LANGS["auto"])
    if code and code.isalpha() and len(code) == 2:
        base["google"] = code
    return base


DEFAULT_SETTINGS = {
    "lang": "zh",              # key of SOURCE_LANGS
    "target": "vi",            # key of TARGET_LANGS: the language the video is dubbed into
    "voice": "google:vi",      # must be able to read `target` (VOICES[voice]["langs"])
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
    "frame": {
        "aspect": "original",  # "original" | "9:16" | "16:9" | "1:1" | "4:5"
        "fit": "blur",         # "blur": whole video on a blurred copy of itself | "crop": fill, cut the edges
        "zoom": 1.0,           # 1.0 – 2.0
    },
    "logo": {
        "image": None,         # id in the shared logo library
        "text": "",            # or a channel name, e.g. "@kenhcuatoi"
        "position": "tr",      # tl | tr | bl | br
        "size": 0.16,          # logo width as a fraction of the video width
        "opacity": 0.85,
    },
    "sub_style": "classic",    # see render.SUB_STYLES
    "script": {
        "mode": "translate",   # "translate": faithful | "review": AI narration in a chosen style
        "style": "drama",      # see translate.REVIEW_STYLES
    },
    "mask": {
        "enabled": False,
        "auto": True,          # detect the burned-in subtitle band with OCR
        "style": "blur",       # "blur" | "box"
        "bottom": 10,          # % from bottom edge to band bottom
        "height": 12,          # % of video height
    },
}
