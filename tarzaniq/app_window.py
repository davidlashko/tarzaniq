"""Native desktop window for TarzanIQ — also the self-contained .app entry.

Runs the local engine in a background thread and shows the dashboard in a
native macOS window (the system WebKit) — no browser, no visible localhost
address. When frozen into TarzanIQ.app (PyInstaller), it additionally:
seeds the face models from the bundle on first run, and logs to the data dir.

Run:  python -m tarzaniq.app_window [day-folder ...]
      TarzanIQ.app/Contents/MacOS/TarzanIQ --selftest   (headless bundle check)
"""

import json
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import APP_NAME, DEFAULT_PORT
from . import server as srv

URL = f"http://127.0.0.1:{DEFAULT_PORT}"

FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ICON_PNG = (BUNDLE_DIR / "tarzaniq" / "static" / "img" / "icon_1024.png") if FROZEN \
    else Path(__file__).parent / "static" / "img" / "icon_1024.png"


def _ensure_models():
    """First run of the bundled app: copy the face models shipped inside the
    .app into the data dir (where the engine — and reinstalls — expect them).
    No-op when they're already there or when running from source."""
    try:
        from . import config
        from .engine import MODEL_FILES
        src_dir = BUNDLE_DIR / "models"
        if not src_dir.is_dir():
            return
        dst_dir = config.models_dir()
        for name in MODEL_FILES.values():
            src, dst = src_dir / name, dst_dir / name
            if src.is_file() and not dst.is_file():
                shutil.copy2(src, dst)
    except Exception as e:
        print("model provisioning failed:", e)


def _log_to_data_dir():
    """Inside a double-clicked .app, stdout/stderr go nowhere — point them at
    the data dir so client-machine problems leave a trail."""
    try:
        from . import config
        log = config.data_dir() / "logs" / "app.log"
        f = open(log, "a", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n--- {APP_NAME} launch { time.strftime('%Y-%m-%d %H:%M:%S') } ---")
    except Exception:
        pass


def _set_dock_icon():
    """Show the ape in the Dock instead of the generic Python icon.
    NSApplication.sharedApplication() creates the app singleton pywebview
    will reuse, so setting the icon before webview.start() sticks."""
    try:
        from AppKit import NSApplication, NSImage  # pyobjc, ships with pywebview
        img = NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG))
        if img:
            NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:
        pass  # cosmetic only — never block launch over the icon


def _server_up(timeout=1.0):
    try:
        with urllib.request.urlopen(URL + "/api/ping", timeout=timeout) as r:
            return b"TarzanIQ" in r.read()
    except Exception:
        return False


def _enqueue(folders):
    """Queue any day folders passed on the command line (drag-onto-app)."""
    if not folders:
        return
    try:
        req = urllib.request.Request(
            URL + "/api/enqueue",
            data=json.dumps({"folders": folders}).encode(),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("enqueue failed:", e)


def _serve():
    """The local engine — Flask on loopback, in a background thread."""
    srv.create().run(host="127.0.0.1", port=DEFAULT_PORT,
                     threaded=True, debug=False, use_reloader=False)


def _selftest():
    """Headless proof the bundle works: engine serves, heavy deps import,
    real models load. Used by the build script and CI — never opens a window."""
    checks = []
    try:
        import cv2, numpy, flask, webview  # noqa: F401
        from PIL import Image  # noqa: F401
        import pillow_jxl  # noqa: F401
        checks.append(("imports", True))
    except Exception as e:
        checks.append((f"imports ({e})", False))
    _ensure_models()
    up = _server_up()
    if not up:
        threading.Thread(target=_serve, daemon=True).start()
        for _ in range(120):
            if _server_up():
                up = True
                break
            time.sleep(0.5)
    checks.append(("engine serves /api/ping", up))
    try:
        from . import config
        from .engine import FaceEngine
        FaceEngine(config.models_dir(), config.load_config())
        checks.append(("real face models load", True))
    except Exception as e:
        checks.append((f"real face models load ({e})", False))
    ok = all(c[1] for c in checks)
    for label, passed in checks:
        print(("  ok    " if passed else "  FAIL  ") + label)
    print("SELFTEST PASS" if ok else "SELFTEST FAIL")
    return 0 if ok else 1


def main(argv=None):
    args = [a for a in (argv if argv is not None else sys.argv[1:]) if a]
    if "--selftest" in args:
        return _selftest()
    if FROZEN:
        _log_to_data_dir()
        _ensure_models()
    folders = args
    # Start the engine in-process unless one is already running (re-launch).
    if not _server_up():
        threading.Thread(target=_serve, daemon=True).start()
        for _ in range(120):                  # up to ~60s for the first cold start
            if _server_up():
                break
            time.sleep(0.5)
        else:
            print("TarzanIQ engine did not start — see logs in the data dir.")
            return 1
    _enqueue(folders)
    import webview                            # lazy: only needed to show the window
    if sys.platform == "darwin":
        _set_dock_icon()
    start = URL + ("/#/live" if folders else "/")
    webview.create_window(APP_NAME, start, width=1200, height=820,
                          min_size=(900, 640))
    webview.start()                           # blocks on the main thread (required on macOS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
