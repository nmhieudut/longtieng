"""Cut a release: bump the version, commit, tag and push. GitHub Actions builds and publishes it.

    uv run python packaging/release.py 0.3.1 "Thêm hỗ trợ tiếng Anh, Nhật, Hàn"
    uv run python packaging/release.py 0.4.0 "..." --full      # force a full (native) update

A release is a light update (code + web UI only) unless the native part changed since the last
tag: Python dependencies, the PyInstaller spec, launcher, build scripts or bundled assets.
Then SHELL_VERSION is bumped too and installed apps download the whole app.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ["pyproject.toml", "uv.lock", "packaging/longtieng.spec", "packaging/launcher.py",
          "packaging/bundle_ffmpeg_mac.py", "packaging/build_mac.sh", "packaging/build_windows.ps1", "assets"]


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        sys.exit(__doc__)
    version, notes = args[0].lstrip("v"), args[1]
    if git("status", "--porcelain"):
        sys.exit("Commit or stash your changes first.")
    tags = [t for t in git("tag", "--list", "v*", "--sort=-v:refname").splitlines() if t]
    full = "--full" in sys.argv or not tags or bool(git("diff", "--name-only", tags[0], "HEAD", "--", *NATIVE))
    (ROOT / "packaging" / "VERSION").write_text(version + "\n")
    if full:
        (ROOT / "packaging" / "SHELL_VERSION").write_text(version + "\n")
    git("add", "packaging/VERSION", "packaging/SHELL_VERSION")
    git("commit", "--allow-empty", "-m", f"Phát hành {version}\n\n{notes}")
    git("tag", "-a", f"v{version}", "-m", notes)
    git("push", "origin", "HEAD", f"v{version}")
    kind = "đầy đủ (~300MB)" if full else "nhẹ (vài trăm KB)"
    print(f"Released v{version}: cập nhật {kind}. Theo dõi build: https://github.com/nmhieudut/longtieng/actions")


if __name__ == "__main__":
    main()
