"""Headless test of the native-window entry point (webview stubbed).
Run: .venv/bin/python tests/test_app_window.py"""
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TARZANIQ_DATA"] = str(Path(tempfile.mkdtemp(prefix="tq_win_")) / "data")

fails = []


def check(label, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond:
        fails.append(label)


# Stub `webview` BEFORE main() lazy-imports it, so no real window opens.
calls = {}
stub = types.ModuleType("webview")
stub.create_window = lambda title, url, **kw: calls.update(title=title, url=url, kw=kw)
stub.start = lambda *a, **k: calls.update(started=True)
sys.modules["webview"] = stub

from tarzaniq import app_window, DEFAULT_PORT  # noqa: E402

rc = app_window.main([])  # no folders -> opens the dashboard root
check("main() returns 0", rc == 0, str(rc))
check("engine came up in-process", app_window._server_up(), "ping failed")
check("window opened at dashboard root",
      calls.get("url") == f"http://127.0.0.1:{DEFAULT_PORT}/", calls.get("url"))
check("webview.start() called", calls.get("started") is True)
check("window titled with the app name", bool(calls.get("title")))

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
