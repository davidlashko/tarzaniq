#!/bin/bash
# TarzanIQ uninstaller. Removes the app, launcher, droplet and Quick Action.
# DOES NOT touch your data folder (~/Documents/TarzanIQ Data) — that's where
# every analyzed day lives. Delete it yourself only if you really mean it.
set -u
APPDIR="$HOME/Library/Application Support/TarzanIQ"
DATA="${TARZANIQ_DATA:-$HOME/Documents/TarzanIQ Data}"

echo "Stopping TarzanIQ server (if running)…"
curl -s --max-time 2 "http://127.0.0.1:43117/api/ping" >/dev/null 2>&1 && \
  pkill -f "tarzaniq.server" 2>/dev/null

echo "Removing app files…"
rm -rf "$APPDIR"
rm -rf "/Applications/TarzanIQ.app" "$HOME/Applications/TarzanIQ.app"
rm -rf "$HOME/Library/Services/Analyze with TarzanIQ.workflow"
/System/Library/CoreServices/pbs -flush 2>/dev/null || true

echo
echo "TarzanIQ removed."
echo "KEPT (your analyzed days, exports, settings): $DATA"
echo "Your photo archive (default: ~/Documents/TarzanIQ Archive, or \$TARZANIQ_ARCHIVE) is also kept."
echo "If you truly want everything gone:  rm -rf \"$DATA\""
