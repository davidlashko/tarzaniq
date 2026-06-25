#!/bin/bash
# ============================================================================
#  TarzanIQ — double-click installer for macOS
#
#  HOW TO USE (non-technical):
#    1. Download the repo ZIP (green "Code" button on GitHub -> Download ZIP).
#    2. Double-click the ZIP to unzip it.
#    3. Double-click  "Install TarzanIQ.command"  inside the unzipped folder.
#       (First time only, macOS may say "unidentified developer" — then
#        RIGHT-click the file -> Open -> Open. This is normal for free apps.)
#
#  It installs everything (Python if needed, all packages, the face models,
#  the TarzanIQ app, and the Finder right-click action). Re-running is safe.
# ============================================================================

# Always work from the folder this file lives in (whatever it's named).
cd "$(dirname "$0")" || { echo "Could not enter the install folder."; exit 1; }

# Remove the "downloaded from the internet" quarantine from the whole folder so
# the app we build launches without Gatekeeper fighting it.
xattr -dr com.apple.quarantine . >/dev/null 2>&1 || true

clear
echo "Installing TarzanIQ — progress will appear below."
echo "(You can leave this window; it'll tell you when it's done.)"
echo

/bin/bash "./install.sh"
status=$?

echo
if [ "$status" -eq 0 ]; then
  echo "✅  All done — TarzanIQ is installed. You can close this window."
else
  echo "❌  The install hit a problem (see the messages above)."
  echo "    Fix it, then double-click \"Install TarzanIQ.command\" again."
fi
echo
echo "Press Return to close this window…"
read -r _
