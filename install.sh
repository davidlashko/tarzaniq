#!/bin/bash
# TarzanIQ installer — macOS (Apple Silicon or Intel)
# Easiest: double-click "Install TarzanIQ.command". Or run:  bash install.sh
# Installs Python (if needed), all packages, the face models, the app, and the
# Finder right-click action. Safe to re-run.
set -u

# Double-clicked .command windows get a bare PATH (no Homebrew, no python.org
# installs) — which once made this installer "not find" a Python that was
# right there and try to install Homebrew instead. Fix the PATH up front.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:$PATH"

BOLD=$(tput bold 2>/dev/null || true); DIM=$(tput dim 2>/dev/null || true)
GRN=$(tput setaf 2 2>/dev/null || true); YLW=$(tput setaf 3 2>/dev/null || true)
RED=$(tput setaf 1 2>/dev/null || true); RST=$(tput sgr0 2>/dev/null || true)
say()  { echo "${GRN}●${RST} $*"; }
warn() { echo "${YLW}▲${RST} $*"; }
die()  { echo "${RED}✖ $*${RST}"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$HOME/Library/Application Support/TarzanIQ"
DATA="${TARZANIQ_DATA:-$HOME/Documents/TarzanIQ Data}"
PORT=43117
URL="http://127.0.0.1:$PORT"

echo
echo "${BOLD}  TarzanIQ installer — street photo intelligence${RST}"
echo "${DIM}  app: $APPDIR${RST}"
echo "${DIM}  data: $DATA${RST}"
echo

[ "$(uname)" = "Darwin" ] || die "This installer is for macOS."

# Source of the app files: the downloaded folder normally; if run from the
# installed copy (repair mode — e.g. macOS updated Python underneath the app),
# reuse the files already in place.
SRC=""
if [ -d "$HERE/tarzaniq" ]; then
  SRC="$HERE"
elif [ -d "$APPDIR/app/tarzaniq" ]; then
  SRC=""; say "Repair mode — reusing the installed app files"
else
  die "Run me from inside the TarzanIQ folder (tarzaniq/ not found)."
fi

# strip the "downloaded from the internet" quarantine so the app we build runs
xattr -dr com.apple.quarantine "$HERE" >/dev/null 2>&1 || true

# ---------------------------------------------------------------- python
# opencv/numpy/pillow ship wheels for CPython 3.11–3.13 (NOT the 3.14 dev line,
# and not the bare /usr/bin/python3 stub). Find a good one; if none, install
# python@3.12 via Homebrew so a fresh Mac "just works".
pick_python() {
  local c v
  for c in python3.12 python3.11 python3.13; do
    command -v "$c" >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  # absolute locations, in case PATH is still bare (keg-only Homebrew kegs,
  # python.org framework installs)
  for c in \
      /opt/homebrew/opt/python@3.12/bin/python3.12 \
      /opt/homebrew/opt/python@3.11/bin/python3.11 \
      /opt/homebrew/opt/python@3.13/bin/python3.13 \
      /usr/local/opt/python@3.12/bin/python3.12 \
      /usr/local/opt/python@3.13/bin/python3.13 \
      /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
      /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \
      /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13; do
    [ -x "$c" ] && { echo "$c"; return 0; }
  done
  if command -v python3 >/dev/null 2>&1; then
    v=$(python3 -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null)
    [ -n "$v" ] && [ "$v" -ge 311 ] && [ "$v" -le 313 ] && { echo python3; return 0; }
  fi
  return 1
}

PY="$(pick_python || true)"
if [ -z "$PY" ]; then
  warn "No suitable Python found (need 3.11–3.13)."
  if ! command -v brew >/dev/null 2>&1; then
    say "Installing Homebrew (you may be asked for your Mac password; a Command"
    say "Line Tools window may also pop up — accept it, then this continues)…"
    NONINTERACTIVE=1 /bin/bash -c \
      "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
      || die "Homebrew install failed. Easiest fix: install Python 3.12 from python.org, then run me again."
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"
  fi
  say "Installing Python 3.12 via Homebrew (one time)…"
  brew install python@3.12 || die "Could not install Python. Install Python 3.12 from python.org, then run me again."
  PY="$(brew --prefix 2>/dev/null)/bin/python3.12"
  [ -x "$PY" ] || PY="$(pick_python || true)"
  [ -n "$PY" ] || die "Python still not found. Install Python 3.12 from python.org, then run me again."
fi
PYV=$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
say "Using Python $PYV  ($PY)"

# ---------------------------------------------------------------- app copy + venv
mkdir -p "$APPDIR" "$DATA/models" "$DATA/logs" "$DATA/exports" "$DATA/backups"
if [ -n "$SRC" ]; then
  say "Copying app into place"
  rm -rf "$APPDIR/app"
  mkdir -p "$APPDIR/app"
  cp -R "$SRC/tarzaniq" "$APPDIR/app/"
  cp "$SRC/requirements.txt" "$APPDIR/app/"
fi

# rebuild the venv if it is broken (e.g. a Homebrew upgrade removed the Python
# it was built on) or was built with an unsupported Python
if [ -d "$APPDIR/venv" ]; then
  if [ ! -x "$APPDIR/venv/bin/python" ] \
     || ! "$APPDIR/venv/bin/python" -c 'import sys; sys.exit(0 if (3,11)<=sys.version_info<(3,14) else 1)' 2>/dev/null; then
    warn "Existing environment is broken or unsupported — rebuilding it"
    rm -rf "$APPDIR/venv"
  fi
fi
if [ ! -x "$APPDIR/venv/bin/python" ]; then
  say "Creating Python environment (one time)"
  "$PY" -m venv "$APPDIR/venv" || die "Could not create a virtualenv."
fi
say "Installing Python packages — pip's progress follows (a few minutes the first time):"
"$APPDIR/venv/bin/pip" install --upgrade pip
"$APPDIR/venv/bin/pip" install -r "$APPDIR/app/requirements.txt" \
  || die "pip install failed — check your internet connection and rerun."
say "Packages ready"

# ---------------------------------------------------------------- models
MODEL_I=0
fetch_model() {  # name url sha256 size
  local name="$1" url="$2" sha="$3" size="$4" dst="$DATA/models/$1"
  MODEL_I=$((MODEL_I + 1))
  local mb=$(( (${size:-0} + 524288) / 1048576 )); local mbtxt="${mb} MB"
  [ "$mb" -eq 0 ] && mbtxt="<1 MB"
  if [ -f "$dst" ] && echo "$sha  $dst" | shasum -a 256 -c - >/dev/null 2>&1; then
    say "[$MODEL_I/4] $name — already downloaded, skipping"; return 0
  fi
  say "[$MODEL_I/4] Downloading $name (~$mbtxt) — a progress bar appears below:"
  # --speed-limit/--speed-time abort a stalled connection (so it can't hang
  # forever); --retry then tries again. The bar shows it's actually moving.
  curl -L --fail --progress-bar \
       --connect-timeout 30 --retry 4 --retry-delay 3 \
       --speed-limit 2048 --speed-time 60 \
       -o "$dst.part" "$url" \
    || { rm -f "$dst.part"; die "Download stalled or failed: $name. Check your internet, then double-click the installer again (finished models are skipped)."; }
  echo "$sha  $dst.part" | shasum -a 256 -c - >/dev/null 2>&1 \
    || { rm -f "$dst.part"; die "Checksum mismatch for $name — re-run the installer."; }
  mv "$dst.part" "$dst"
  say "[$MODEL_I/4] $name — done ✓"
}
say "Fetching the 4 face models (~83 MB total, one time)…"
fetch_model "face_detection_yunet_2023mar.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
  "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4" 232589
fetch_model "face_recognition_sface_2021dec.onnx" \
  "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
  "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79" 38696353
fetch_model "age_googlenet.onnx" \
  "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx" \
  "fa2a3228e425056aa2b080b3afd3cf607327c86616e952602ed67b5fc16ab356" 23960165
fetch_model "gender_googlenet.onnx" \
  "https://github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/gender_googlenet.onnx" \
  "af24a4eaa9eaf70913cc9a337a0387c86f11549cbd9bbc16bffeefcdcf88cbf4" 23935566

# ---------------------------------------------------------------- launcher
say "Writing launcher"
cat > "$APPDIR/launch.sh" << LAUNCH
#!/bin/bash
# TarzanIQ launcher. Prefers the native app window (own window, no browser);
# falls back to the local server + your browser if the window stack is missing.
# Any folder paths passed as arguments get queued for analysis.
APPDIR="\$HOME/Library/Application Support/TarzanIQ"
DATA="\${TARZANIQ_DATA:-\$HOME/Documents/TarzanIQ Data}"
PORT=$PORT
URL="http://127.0.0.1:\$PORT"
PYBIN="\$APPDIR/venv/bin/python"
mkdir -p "\$DATA/logs"

# --- self-heal: a macOS/Homebrew update can remove the Python this app was
# --- built on. If the environment is broken, offer a one-click repair.
if ! "\$PYBIN" -c 'import sys' >/dev/null 2>&1; then
  ans=\$(osascript -e 'display dialog "TarzanIQ needs a quick repair — a macOS update changed Python underneath it.\n\nClick Repair to fix it automatically (takes a few minutes; a Terminal window will show progress)." buttons {"Cancel","Repair"} default button "Repair" with title "TarzanIQ" with icon caution' 2>/dev/null)
  case "\$ans" in *Repair*) open -a Terminal "\$APPDIR/install.sh";; esac
  exit 0
fi

# --- preferred: native window (pywebview). Runs the engine in-process. ---
if "\$PYBIN" -c "import webview" >/dev/null 2>&1; then
  cd "\$APPDIR/app" || exit 1
  nohup "\$PYBIN" -m tarzaniq.app_window "\$@" >> "\$DATA/logs/window.log" 2>&1 &
  exit 0
fi

# --- fallback: headless server + browser ---
if ! curl -s --max-time 2 "\$URL/api/ping" 2>/dev/null | grep -q TarzanIQ; then
  cd "\$APPDIR/app" || exit 1
  nohup "\$PYBIN" -m tarzaniq.server >> "\$DATA/logs/server.log" 2>&1 &
  for i in \$(seq 1 60); do
    sleep 0.5
    curl -s --max-time 1 "\$URL/api/ping" 2>/dev/null | grep -q TarzanIQ && break
  done
fi
if [ "\$#" -gt 0 ]; then
  "\$PYBIN" - "\$URL" "\$@" << 'PYEOF'
import json, sys, urllib.request
url, folders = sys.argv[1], sys.argv[2:]
req = urllib.request.Request(url + "/api/enqueue",
    data=json.dumps({"folders": folders}).encode(),
    headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=10)
except Exception as e:
    print("enqueue failed:", e)
PYEOF
  open "\$URL/#/live"
else
  open "\$URL"
fi
LAUNCH
chmod +x "$APPDIR/launch.sh"

# ---------------------------------------------------------------- app icon
ICNS=""
if command -v iconutil >/dev/null 2>&1; then
  ISET="$APPDIR/TarzanIQ.iconset"
  rm -rf "$ISET"; mkdir -p "$ISET"
  IMG="$APPDIR/app/tarzaniq/static/img"    # already copied into place above
  cp "$IMG/icon_16.png"   "$ISET/icon_16x16.png"
  cp "$IMG/icon_32.png"   "$ISET/icon_16x16@2x.png"
  cp "$IMG/icon_32.png"   "$ISET/icon_32x32.png"
  cp "$IMG/icon_64.png"   "$ISET/icon_32x32@2x.png"
  cp "$IMG/icon_128.png"  "$ISET/icon_128x128.png"
  cp "$IMG/icon_256.png"  "$ISET/icon_128x128@2x.png"
  cp "$IMG/icon_256.png"  "$ISET/icon_256x256.png"
  cp "$IMG/icon_512.png"  "$ISET/icon_256x256@2x.png"
  cp "$IMG/icon_512.png"  "$ISET/icon_512x512.png"
  cp "$IMG/icon_1024.png" "$ISET/icon_512x512@2x.png"
  if iconutil -c icns "$ISET" -o "$APPDIR/TarzanIQ.icns" && [ -s "$APPDIR/TarzanIQ.icns" ]; then
    ICNS="$APPDIR/TarzanIQ.icns"
  else
    warn "Could not build the app icon (iconutil failed) — the app will use a generic icon"
  fi
  rm -rf "$ISET"
fi

# ---------------------------------------------------------------- droplet app
say "Building the TarzanIQ app (drop folders on it, or double-click)"
DROPLET="/Applications/TarzanIQ.app"
[ -w "/Applications" ] || DROPLET="$HOME/Applications/TarzanIQ.app"
mkdir -p "$(dirname "$DROPLET")"
rm -rf "$DROPLET"
OSA="$APPDIR/droplet.applescript"
cat > "$OSA" << 'OSAEOF'
on run
  do shell script "/bin/bash " & quoted form of (POSIX path of (path to home folder) & "Library/Application Support/TarzanIQ/launch.sh")
end run
on open theItems
  set launchPath to POSIX path of (path to home folder) & "Library/Application Support/TarzanIQ/launch.sh"
  set args to ""
  repeat with anItem in theItems
    set args to args & " " & quoted form of POSIX path of anItem
  end repeat
  do shell script "/bin/bash " & quoted form of launchPath & args
end open
OSAEOF
if osacompile -o "$DROPLET" "$OSA" 2>/dev/null; then
  if [ -n "$ICNS" ]; then
    # Modern osacompile ships its generic icon in an asset catalog
    # (Assets.car) that macOS prefers over any .icns we drop in — remove it
    # and the CFBundleIconName key so CFBundleIconFile -> applet.icns (ours)
    # actually wins. Then re-sign: editing the bundle breaks its seal.
    cp "$ICNS" "$DROPLET/Contents/Resources/applet.icns"
    cp "$ICNS" "$DROPLET/Contents/Resources/droplet.icns" 2>/dev/null || true
    rm -f "$DROPLET/Contents/Resources/Assets.car"
    /usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" \
      "$DROPLET/Contents/Info.plist" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Set :CFBundleIconFile applet" \
      "$DROPLET/Contents/Info.plist" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string applet" \
           "$DROPLET/Contents/Info.plist" 2>/dev/null || true
    codesign --force --sign - "$DROPLET" >/dev/null 2>&1 \
      || warn "Could not re-sign the app after icon change (it may still open fine)"
    touch "$DROPLET"
    # nudge Finder/Dock to pick up the new icon
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
      -f "$DROPLET" >/dev/null 2>&1 || true
  fi
  say "App created: $DROPLET"
else
  warn "Could not build the droplet app (osacompile failed) — the dashboard still works via launch.sh"
  DROPLET=""
fi

# ---------------------------------------------------------------- Finder Quick Action
say "Installing the Finder right-click action"
WF="$HOME/Library/Services/Analyze with TarzanIQ.workflow"
rm -rf "$WF"
mkdir -p "$WF/Contents"
cat > "$WF/Contents/Info.plist" << 'PLEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Analyze with TarzanIQ</string>
  <key>NSServices</key>
  <array>
    <dict>
      <key>NSMenuItem</key><dict><key>default</key><string>Analyze with TarzanIQ</string></dict>
      <key>NSMessage</key><string>runWorkflowAsService</string>
      <key>NSRequiredContext</key>
      <dict><key>NSApplicationIdentifier</key><string>com.apple.finder</string></dict>
      <key>NSSendFileTypes</key><array><string>public.folder</string></array>
    </dict>
  </array>
</dict>
</plist>
PLEOF
cat > "$WF/Contents/document.wflow" << 'WFEOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>AMApplicationBuild</key><string>523</string>
  <key>AMApplicationVersion</key><string>2.10</string>
  <key>AMDocumentVersion</key><string>2</string>
  <key>actions</key>
  <array>
    <dict>
      <key>action</key>
      <dict>
        <key>AMAccepts</key>
        <dict>
          <key>Container</key><string>List</string>
          <key>Optional</key><true/>
          <key>Types</key><array><string>com.apple.cocoa.path</string></array>
        </dict>
        <key>AMActionVersion</key><string>2.0.3</string>
        <key>AMParameterProperties</key>
        <dict>
          <key>COMMAND_STRING</key><dict/>
          <key>CheckedForUserDefaultShell</key><dict/>
          <key>inputMethod</key><dict/>
          <key>shell</key><dict/>
          <key>source</key><dict/>
        </dict>
        <key>AMProvides</key>
        <dict>
          <key>Container</key><string>List</string>
          <key>Types</key><array><string>com.apple.cocoa.string</string></array>
        </dict>
        <key>ActionBundlePath</key><string>/System/Library/Automator/Run Shell Script.action</string>
        <key>ActionName</key><string>Run Shell Script</string>
        <key>ActionParameters</key>
        <dict>
          <key>COMMAND_STRING</key>
          <string>"$HOME/Library/Application Support/TarzanIQ/launch.sh" "$@"</string>
          <key>CheckedForUserDefaultShell</key><true/>
          <key>inputMethod</key><integer>1</integer>
          <key>shell</key><string>/bin/bash</string>
          <key>source</key><string></string>
        </dict>
        <key>BundleIdentifier</key><string>com.apple.RunShellScript</string>
        <key>CFBundleVersion</key><string>2.0.3</string>
        <key>CanShowSelectedItemsWhenRun</key><false/>
        <key>CanShowWhenRun</key><true/>
        <key>Class Name</key><string>RunShellScriptAction</string>
        <key>InputUUID</key><string>9A2DD493-4707-4E4C-8A1D-2474C0E2A1A1</string>
        <key>Keywords</key><array><string>Shell</string></array>
        <key>OutputUUID</key><string>4C9A99EF-2A1B-43A3-9B5C-3B27D1A4F5A2</string>
        <key>UUID</key><string>7C36A5D1-83C1-4BE6-9E5A-8E9C2A1B3C4D</string>
        <key>isViewVisible</key><integer>1</integer>
      </dict>
    </dict>
  </array>
  <key>connectors</key><dict/>
  <key>workflowMetaData</key>
  <dict>
    <key>serviceInputTypeIdentifier</key><string>com.apple.Automator.fileSystemObject.folder</string>
    <key>serviceOutputTypeIdentifier</key><string>com.apple.Automator.nothing</string>
    <key>serviceProcessesInput</key><integer>0</integer>
    <key>workflowTypeIdentifier</key><string>com.apple.Automator.servicesMenu</string>
  </dict>
</dict>
</plist>
WFEOF
/System/Library/CoreServices/pbs -flush 2>/dev/null || true
say "Right-click action installed (may need a Finder relaunch or logout to appear)"

# ---------------------------------------------------------------- self-copy
# Keep a copy of this installer next to the app so the launcher's "Repair"
# button can re-run it even after the downloaded folder is deleted.
if [ -n "$SRC" ] && [ "$HERE" != "$APPDIR" ]; then
  cp "$HERE/$(basename "$0")" "$APPDIR/install.sh" 2>/dev/null \
    || cp "$0" "$APPDIR/install.sh" 2>/dev/null || true
fi
chmod +x "$APPDIR/install.sh" 2>/dev/null || true

# ---------------------------------------------------------------- finish
echo
echo "${GRN}${BOLD}"
cat << 'APE'
        ▄▄▄▄▄▄
      ▄█▀▀▀▀▀▀█▄        TarzanIQ is installed.
     ██  ▄  ▄  ██
     ██   ██   ██       1. Double-click TarzanIQ in Applications
      █▄ ▀▄▄▀ ▄█           (or drop a day folder straight onto it)
       ▀█▄▄▄▄█▀         2. Or right-click a folder in Finder →
        ▄█▀▀█▄             Quick Actions → Analyze with TarzanIQ
APE
echo "${RST}"
say "Dashboard: $URL  (folder format: YY.MM.DD.Place.Name)"
[ -n "${DROPLET:-}" ] && say "App: $DROPLET"
say "Your numbers live in: $DATA  — safe across reinstalls"
echo
