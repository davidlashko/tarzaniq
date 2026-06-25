"""Native desktop window for TarzanIQ (standalone app — phase 1).

Runs the local engine in a background thread and shows the dashboard in a
native macOS window (the system WebKit) — no browser, no visible localhost
address. Phase 2 bundles this into a fully self-contained `.app`.

Run:  python -m tarzaniq.app_window [day-folder ...]
"""

import json
import sys
import threading
import time
import urllib.request

from . import APP_NAME, DEFAULT_PORT
from . import server as srv

URL = f"http://127.0.0.1:{DEFAULT_PORT}"


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


def main(argv=None):
    folders = [a for a in (argv if argv is not None else sys.argv[1:]) if a]
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
    start = URL + ("/#/live" if folders else "/")
    webview.create_window(APP_NAME, start, width=1200, height=820,
                          min_size=(900, 640))
    webview.start()                           # blocks on the main thread (required on macOS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
