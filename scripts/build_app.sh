#!/bin/bash
# Build the self-contained TarzanIQ.app (no installer, no system Python).
#
#   bash scripts/build_app.sh
#
# Produces dist/TarzanIQ.app and dist/TarzanIQ-<version>-mac.zip. The bundle
# carries Python, all packages, the SPA, and the four face models — drag it to
# /Applications and open. Ad-hoc signed; Developer-ID signing + notarization
# can be layered on top later.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

say() { echo "● $*"; }
die() { echo "✖ $*"; exit 1; }

VERSION=$(python3 - <<'PY' 2>/dev/null || sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' tarzaniq/__init__.py
import re, pathlib
print(re.search(r'APP_VERSION = "(.*?)"', pathlib.Path("tarzaniq/__init__.py").read_text()).group(1))
PY
)
say "Building TarzanIQ.app v$VERSION"

# ---------------------------------------------------------------- build venv
PYBIN=""
for c in python3.12 python3.11 python3.13; do
  command -v "$c" >/dev/null 2>&1 && { PYBIN="$c"; break; }
done
[ -n "$PYBIN" ] || die "Need Python 3.11–3.13 to build."
say "Build python: $($PYBIN --version)"
rm -rf build/venv
"$PYBIN" -m venv build/venv
build/venv/bin/pip install -q --upgrade pip
build/venv/bin/pip install -q -r requirements.txt pyinstaller
say "Build environment ready"

# ---------------------------------------------------------------- models
# Same URLs + pins as install.sh — keep in lockstep with engine.MODEL_FILES.
mkdir -p build/models
fetch() { # name url sha
  local dst="build/models/$1"
  if [ -f "$dst" ] && echo "$3  $dst" | shasum -a 256 -c - >/dev/null 2>&1; then
    say "model $1 cached"; return 0
  fi
  say "downloading $1"
  curl -fL --progress-bar --connect-timeout 30 --retry 3 -o "$dst.part" "$2" \
    || die "download failed: $1"
  echo "$3  $dst.part" | shasum -a 256 -c - >/dev/null 2>&1 || die "sha mismatch: $1"
  mv "$dst.part" "$dst"
}
fetch "face_detection_yunet_2023mar.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
  "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
fetch "face_recognition_sface_2021dec.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
  "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
fetch "age_googlenet.onnx" \
  "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx" \
  "fa2a3228e425056aa2b080b3afd3cf607327c86616e952602ed67b5fc16ab356"
fetch "gender_googlenet.onnx" \
  "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx" \
  "af24a4eaa9eaf70913cc9a337a0387c86f11549cbd9bbc16bffeefcdcf88cbf4"

# ---------------------------------------------------------------- icon
ICNS="build/TarzanIQ.icns"
ISET="build/TarzanIQ.iconset"
rm -rf "$ISET"; mkdir -p "$ISET"
IMG=tarzaniq/static/img
cp "$IMG/icon_16.png"   "$ISET/icon_16x16.png";    cp "$IMG/icon_32.png"  "$ISET/icon_16x16@2x.png"
cp "$IMG/icon_32.png"   "$ISET/icon_32x32.png";    cp "$IMG/icon_64.png"  "$ISET/icon_32x32@2x.png"
cp "$IMG/icon_128.png"  "$ISET/icon_128x128.png";  cp "$IMG/icon_256.png" "$ISET/icon_128x128@2x.png"
cp "$IMG/icon_256.png"  "$ISET/icon_256x256.png";  cp "$IMG/icon_512.png" "$ISET/icon_256x256@2x.png"
cp "$IMG/icon_512.png"  "$ISET/icon_512x512.png";  cp "$IMG/icon_1024.png" "$ISET/icon_512x512@2x.png"
iconutil -c icns "$ISET" -o "$ICNS" || die "iconutil failed"
rm -rf "$ISET"

# ---------------------------------------------------------------- bundle
cat > build/entry.py <<'PY'
import sys
from tarzaniq.app_window import main
sys.exit(main())
PY
say "Running PyInstaller (a few minutes)…"
rm -rf dist/TarzanIQ.app
ROOT="$PWD"
build/venv/bin/python -m PyInstaller --noconfirm --clean --log-level WARN \
  --name TarzanIQ --windowed \
  --icon "$ROOT/$ICNS" \
  --osx-bundle-identifier com.tarzaniq.app \
  --add-data "$ROOT/tarzaniq/static:tarzaniq/static" \
  --add-data "$ROOT/build/models:models" \
  --workpath "$ROOT/build/pyi" --specpath "$ROOT/build" --distpath "$ROOT/dist" \
  "$ROOT/build/entry.py" \
  || die "PyInstaller failed"
[ -d dist/TarzanIQ.app ] || die "No .app produced"

# ---------------------------------------------------------------- sign + verify
say "Ad-hoc signing"
codesign --force --deep --sign - dist/TarzanIQ.app || die "codesign failed"
codesign --verify dist/TarzanIQ.app || die "signature invalid"

say "Selftest (headless)"
dist/TarzanIQ.app/Contents/MacOS/TarzanIQ --selftest || die "bundle selftest FAILED"

# ---------------------------------------------------------------- zip
ZIP="dist/TarzanIQ-$VERSION-mac.zip"
rm -f "$ZIP"
ditto -c -k --keepParent dist/TarzanIQ.app "$ZIP"
say "Done:"
du -sh dist/TarzanIQ.app "$ZIP"
