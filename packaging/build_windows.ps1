# Build the Windows app (folder + zip). Used by .github/workflows/release.yml. Run on Windows with uv, pnpm (via corepack) installed.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Version = (Get-Content packaging/VERSION).Trim()

Push-Location web; pnpm install --frozen-lockfile; pnpm build; Pop-Location
uv sync --group build

# ffmpeg with libass (BtbN builds, shared libs so ffmpeg and ffprobe share the DLLs)
$ff = "build/ffmpeg.zip"
New-Item -ItemType Directory -Force build | Out-Null
Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip" -OutFile $ff
Expand-Archive $ff -DestinationPath build/ffmpeg -Force
$src = Get-ChildItem build/ffmpeg -Directory | Select-Object -First 1
Remove-Item build/bin -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force build/bin | Out-Null
Copy-Item "$($src.FullName)/bin/*" build/bin/
Remove-Item build/bin/ffplay.exe -ErrorAction SilentlyContinue

uv run python packaging/make_patch.py --dir build/code
uv run pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/longtieng.spec

# GUI exe: run it with redirected output and wait, so we see the log and the exit code
$p = Start-Process dist/Longtieng/Longtieng.exe -ArgumentList "--selftest" -Wait -PassThru -NoNewWindow `
  -RedirectStandardOutput build/selftest.out -RedirectStandardError build/selftest.err
Get-Content build/selftest.out, build/selftest.err | Out-Host
if ($p.ExitCode -ne 0) { throw "selftest failed ($($p.ExitCode))" }

$zip = "dist/Longtieng-$Version-windows-x64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path dist/Longtieng -DestinationPath $zip
Write-Host "Built $zip"
