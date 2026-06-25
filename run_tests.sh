#!/usr/bin/env bash
# Run the ENTIRE TarzanIQ test suite from a known-good state.
#
# Prereqs (one-time):
#   python3.12 -m venv .venv
#   .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
#   npm install                         # jsdom, for the DOM smoke test
#
# Then just:  ./run_tests.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
PORT=43991
DEMO=/tmp/tq_demo

echo "== unit + integration (Python) =="
"$PY" tests/test_engagements.py
"$PY" tests/test_server.py
"$PY" tests/test_fingerprint.py
"$PY" tests/test_significance.py
"$PY" tests/test_migration.py
"$PY" tests/test_app_window.py
"$PY" tests/test_e2e.py
"$PY" tests/test_archive.py

echo ""
echo "== DOM smoke (real SPA in jsdom vs a MockEngine server) =="
rm -rf "$DEMO"
TARZANIQ_DATA="$DEMO" "$PY" tests/seed_demo.py
TARZANIQ_DATA="$DEMO" "$PY" tests/run_demo_server.py --port "$PORT" >/tmp/tq_demo_server.log 2>&1 &
SRV=$!
trap 'kill "$SRV" 2>/dev/null || true' EXIT

tries=0
until curl -s -o /dev/null "http://127.0.0.1:$PORT/api/state"; do
  tries=$((tries + 1))
  if [ "$tries" -ge 30 ]; then echo "demo server never came up; see /tmp/tq_demo_server.log"; exit 1; fi
  sleep 0.5
done

node tests/dom_smoke.mjs "http://127.0.0.1:$PORT"

echo ""
echo "== all suites green =="
