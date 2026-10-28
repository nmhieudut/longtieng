# PyInstaller spec for the desktop app. Build with packaging/build_mac.sh or packaging/build_windows.ps1.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
IS_MAC = sys.platform == "darwin"
VERSION = (ROOT / "packaging" / "VERSION").read_text().strip()

datas = [
    (str(ROOT / "web" / "out"), "web/out"),
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
