"""Entry point of the packaged app.

The app's own code (the `app` package + the built web UI) is NOT frozen into the executable: it ships
as plain files in <bundle>/code, and a light update drops a newer copy in <user data>/updates/current.
This picks which one to run before anything from `app` is imported.

If an updated copy fails to start, the next launch falls back to the bundled code by itself.
"""

import json
import os
import shutil
import sys
from pathlib import Path


def _user_dir() -> Path:
    # keep in sync with app/config.py::_user_dir
    if os.getenv("LONGTIENG_HOME"):
        return Path(os.environ["LONGTIENG_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "Longtieng"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Longtieng"
    return Path.home() / ".local" / "share" / "longtieng"


def _pick_code_dir() -> Path:
    res = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = res / "code"
    if not bundled.is_dir():  # running the launcher from a source checkout
        return Path(__file__).resolve().parent.parent
    if "--selftest" in sys.argv:  # always test what was built
        return bundled
    shell = (res / "meta" / "SHELL_VERSION").read_text().strip()
    updates = _user_dir() / "updates"
    current, booting = updates / "current", updates / "booting"
    child = sys.argv[1:2] == ["--yt-dlp"]
    try:
        meta = json.loads((current / "meta.json").read_text())
    except (OSError, ValueError):
        return bundled
    if meta.get("shell") != shell:
        return bundled  # made for another native build (a full update replaced the app since)
    if booting.exists() and not child:
        # the last start with this update never got its server up: drop it, use the bundled code
        shutil.rmtree(updates / "broken", ignore_errors=True)
        current.rename(updates / "broken")
        booting.unlink(missing_ok=True)
        return bundled
    if not child:
        booting.write_text(meta.get("version", ""))  # app/desktop.py removes it once the server runs
    return current


def main() -> None:
    code = _pick_code_dir()
    sys.path.insert(0, str(code))
    os.environ["LONGTIENG_CODE_DIR"] = str(code)
    from app.desktop import main as run

    run()


if __name__ == "__main__":
    main()
