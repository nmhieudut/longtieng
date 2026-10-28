#!/usr/bin/env bash
# Build "Lồng tiếng.app" and a .dmg for Apple Silicon Macs. Needs: brew install ffmpeg-full, pnpm.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(cat packaging/VERSION)

(cd web && pnpm install --frozen-lockfile && pnpm build)
uv sync --inexact --group build
uv run python packaging/bundle_ffmpeg_mac.py build/bin
uv run python packaging/make_patch.py --dir build/code
uv run pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/longtieng.spec

APP="dist/Lồng tiếng.app"
codesign --force --deep -s - "$APP"   # ad-hoc: Apple Silicon refuses unsigned code
"$APP/Contents/MacOS/Longtieng" --selftest

# zip of the .app for in-app full updates (ditto keeps symlinks + signature)
ditto -c -k --keepParent "$APP" "dist/Longtieng-${VERSION}-mac-arm64.zip"

DMG="dist/Longtieng-${VERSION}-mac-arm64.dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Lồng tiếng" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
echo "Built $DMG ($(du -h "$DMG" | cut -f1))"
