"""Copy Homebrew's ffmpeg-full (has libass) plus every non-system dylib it needs into one folder,
rewrite the load paths to be relative, and ad-hoc sign it, so the .app runs on Macs without Homebrew.

    uv run python packaging/bundle_ffmpeg_mac.py build/bin
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path("/opt/homebrew/opt/ffmpeg-full/bin")
SYSTEM = ("/usr/lib/", "/System/")


def deps(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True).stdout
    return [l.strip().split(" (")[0] for l in out.splitlines()[1:]]


def rpaths(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()
    return [out[i + 2].split()[1] for i, l in enumerate(out) if "LC_RPATH" in l]


def resolve(dep: str, owner: Path) -> Path:
    if dep.startswith("@rpath/"):
        name = dep[len("@rpath/"):]
        for rp in rpaths(owner) + [str(owner.parent)]:
            rp = rp.replace("@loader_path", str(owner.parent)).replace("@executable_path", str(owner.parent))
            if (Path(rp) / name).exists():
                return Path(os.path.realpath(Path(rp) / name))
        raise FileNotFoundError(f"{dep} needed by {owner}")
    if dep.startswith("@loader_path/"):
        return Path(os.path.realpath(owner.parent / dep[len("@loader_path/"):]))
    return Path(os.path.realpath(dep))


def main(dest: Path) -> None:
    lib = dest / "lib"
    shutil.rmtree(dest, ignore_errors=True)
    lib.mkdir(parents=True)
    copied: dict[str, Path] = {}          # basename in bundle -> original file
    todo: list[tuple[Path, Path]] = []    # (original, copy)
    for exe in ("ffmpeg", "ffprobe"):
        dst = dest / exe
        shutil.copyfile(SRC / exe, dst)
        todo.append((Path(os.path.realpath(SRC / exe)), dst))
    while todo:
        orig, copy = todo.pop()
        os.chmod(copy, 0o755)
        is_exe = copy.parent == dest
        changes = []
        for d in deps(orig):
            if d.startswith(SYSTEM):
                continue
            real = resolve(d, orig)
            if real == orig:  # the dylib's own id line
                continue
            name = Path(d).name
            if name not in copied:
                copied[name] = real
                shutil.copyfile(real, lib / name)
                todo.append((real, lib / name))
            new = f"@executable_path/lib/{name}" if is_exe else f"@loader_path/{name}"
            changes += ["-change", d, new]
        if not is_exe:
            changes += ["-id", f"@loader_path/{copy.name}"]
        if changes:
            subprocess.run(["install_name_tool", *changes, str(copy)], check=True, capture_output=True)
        for rp in rpaths(copy):
            subprocess.run(["install_name_tool", "-delete_rpath", rp, str(copy)], capture_output=True)
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        subprocess.run(["codesign", "--force", "-s", "-", str(f)], check=True, capture_output=True)
    # nothing may still point into Homebrew
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        bad = [d for d in deps(f) if d.startswith("/opt/") or d.startswith("/usr/local/")]
        if bad:
            sys.exit(f"{f.name} still links {bad}")
    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e6
    print(f"ffmpeg bundled: {len(copied)} libs, {size:.0f} MB -> {dest}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/bin"))
