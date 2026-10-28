# PyInstaller spec for the desktop app. Build with packaging/build_mac.sh or packaging/build_windows.ps1.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
IS_MAC = sys.platform == "darwin"
VERSION = (ROOT / "packaging" / "VERSION").read_text().strip()

# The app's own code ships as plain files in "code/" (see packaging/launcher.py) so light updates can
# replace it; packaging/make_patch.py builds the same folder for an update.
CODE = ROOT / "build" / "code"
if not (CODE / "app" / "desktop.py").is_file():
    raise SystemExit("Run `python packaging/make_patch.py --dir build/code` first")

datas = [
    (str(CODE), "code"),
    (str(ROOT / "packaging" / "SHELL_VERSION"), "meta"),
    (str(ROOT / "assets" / "fonts"), "assets/fonts"),
]
binaries = []
hiddenimports = ["app.main", "app.selftest", "tiktoken_ext.openai_public", "tiktoken_ext"]
hiddenimports += collect_submodules("yt_dlp")  # loaded lazily by name

# bundled ffmpeg/ffprobe (packaging/bundle_ffmpeg_mac.py or the Windows build script puts them here)
bin_dir = ROOT / "build" / "bin"
for f in bin_dir.rglob("*"):
    if f.is_file():
        binaries.append((str(f), str(Path("bin") / f.relative_to(bin_dir).parent)))

pkgs = ["webview", "opencc", "certifi", "edge_tts", "gtts", "yt_dlp"]
if IS_MAC:
    pkgs += ["mlx", "mlx_whisper", "Vision"]
else:
    pkgs += ["faster_whisper", "ctranslate2", "rapidocr_onnxruntime", "onnxruntime", "av", "tokenizers"]
for pkg in pkgs:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

excludes = ["torch", "torchaudio", "demucs", "tkinter", "matplotlib", "IPython", "pytest"]
if IS_MAC:  # the Windows-only engines are installed for testing; keep them out of the Mac app
    excludes += ["faster_whisper", "ctranslate2", "rapidocr_onnxruntime", "onnxruntime", "cv2", "av"]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
# analysed above (so its imports are bundled) but loaded from code/ at run time
a.pure = [e for e in a.pure if not (e[0] == "app" or e[0].startswith("app."))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Longtieng",
    console=False,
    icon=str(ROOT / "packaging" / "icon" / ("icon.icns" if IS_MAC else "icon.ico")),
    codesign_identity=None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Longtieng", upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Lồng tiếng.app",
        icon=str(ROOT / "packaging" / "icon" / "icon.icns"),
        bundle_identifier="com.nmhieudut.longtieng",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Lồng tiếng",
            "CFBundleShortVersionString": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",
            "LSApplicationCategoryType": "public.app-category.video",
        },
    )
