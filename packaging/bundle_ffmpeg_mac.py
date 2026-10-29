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
# /usr/lib libraries every supported macOS has. Anything else under /usr/lib is newer than that (a Homebrew
# bottle built on the latest macOS links e.g. /usr/lib/libhvf.dylib, which only macOS 26+ has).
OLD_SYSTEM_LIBS = {"libSystem.B.dylib", "libc++.1.dylib", "libc++abi.dylib", "libz.1.dylib", "libbz2.1.0.dylib",
                   "libiconv.2.dylib", "libxml2.2.dylib", "libresolv.9.dylib", "libcharset.1.dylib",
                   "libobjc.A.dylib", "libexpat.1.dylib", "liblzma.5.dylib", "libsqlite3.dylib",
                   "libncurses.5.4.dylib", "libedit.3.dylib", "libm.dylib", "libpthread.dylib", "libdl.dylib",
                   "libcurl.4.dylib", "libffi.dylib"}
LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB = 0x0C, 0x80000018


def deps(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True).stdout
    return [l.strip().split(" (")[0] for l in out.splitlines()[1:]]


def rpaths(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()
    return [out[i + 2].split()[1] for i, l in enumerate(out) if "LC_RPATH" in l]


def _dylib_commands(data: bytes):
    """(offset of the load command, command, library path) for each dylib a 64-bit little-endian Mach-O loads."""
    import struct

    if struct.unpack_from("<I", data, 0)[0] != 0xFEEDFACF:
        raise RuntimeError("not a thin 64-bit Mach-O")
    ncmds = struct.unpack_from("<I", data, 16)[0]
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB):
            name_off = struct.unpack_from("<I", data, off + 8)[0]
            end = data.index(b"\0", off + name_off)
            yield off, cmd, data[off + name_off:end].decode()
        off += size


def new_system_deps(path: Path) -> list[str]:
    return [lib for _, cmd, lib in _dylib_commands(path.read_bytes())
            if cmd == LC_LOAD_DYLIB and lib.startswith("/usr/lib/") and Path(lib).name not in OLD_SYSTEM_LIBS]


def build_stub(lib_dir: Path, system_lib: str, users: list[Path]) -> None:
    """A do-nothing copy of a system library that older macOS lacks, shipped next to the others.

    freetype 2.15 binds 8 functions of /usr/lib/libhvf.dylib (Apple's variable-font renderer, macOS 26+) when it
    loads, so the app would not even start on an older macOS. We only draw our own bundled font, so the
    functions are never called; they just have to exist."""
    name = Path(system_lib).name
    short = Path(system_lib).stem
    syms: set[str] = set()
    for u in users:
        out = subprocess.run(["dyld_info", "-fixups", str(u)], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if f"{short}/" in line:
                syms.add(line.split(f"{short}/")[1].split()[0])
    if not syms:
        sys.exit(f"no symbols found for {system_lib}")
    src = lib_dir.parent / f"{short}_stub.c"
    src.write_text("".join(f"long {s.lstrip('_')}(void) {{ return 0; }}\n" for s in sorted(syms)))
    subprocess.run(["clang", "-dynamiclib", "-arch", "arm64", "-mmacosx-version-min=11.0", "-o", str(lib_dir / name),
                    "-install_name", f"@loader_path/{name}", str(src)], check=True, capture_output=True)
    src.unlink()
    for u in users:
        subprocess.run(["install_name_tool", "-change", system_lib, f"@loader_path/{name}", str(u)],
                       check=True, capture_output=True)
    print(f"  {name}: replaced by a stub ({len(syms)} functions) used by {', '.join(u.name for u in users)}")


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
    # system libraries that only the newest macOS has: replace by stubs so the app starts on older Macs too
    wanted: dict[str, list[Path]] = {}
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        for dep in new_system_deps(f):
            wanted.setdefault(dep, []).append(f)
    for dep, users in wanted.items():
        build_stub(lib, dep, users)
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        subprocess.run(["codesign", "--force", "-s", "-", str(f)], check=True, capture_output=True)
    # nothing may still point into Homebrew
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        bad = [d for d in deps(f) if d.startswith("/opt/") or d.startswith("/usr/local/")]
        if bad:
            sys.exit(f"{f.name} still links {bad}")
    # a required /usr/lib library that only new macOS has would stop ffmpeg from starting on older Macs
    for f in [*lib.iterdir(), dest / "ffmpeg", dest / "ffprobe"]:
        strict = new_system_deps(f)
        if strict:
            sys.exit(f"{f.name} needs {strict}, which older macOS does not have")
    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e6
    print(f"ffmpeg bundled: {len(copied)} libs, {size:.0f} MB -> {dest}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/bin"))
