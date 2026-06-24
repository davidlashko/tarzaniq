"""Server route smoke test + naming edge cases."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="tarzaniq_srv_"))
os.environ["TARZANIQ_DATA"] = str(TMP / "data")

fails = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok    {label}")
    else:
        fails.append(label)
        print(f"  FAIL  {label}  {detail}")


# ---------------------------------------------------------------- naming
from tarzaniq.naming import (parse_folder_name, FolderNameError,  # noqa
                             detect_deletions, filename_seq)

d, pl, emp = parse_folder_name("26.06.11.CityPark.Marko")
check("parse basic", str(d) == "2026-06-11" and pl == "CityPark"
      and emp == "Marko")
d, pl, emp = parse_folder_name("26.06.11.St.Marks.Square.Ana")
check("parse extra dots -> place joins", pl == "St.Marks.Square"
      and emp == "Ana")
for bad in ("26.06.CityPark.Marko", "haha", "26.13.40.X.Y", "26.06.11..Y"):
    try:
        parse_folder_name(bad)
        check(f"reject {bad!r}", False)
    except FolderNameError:
        check(f"reject {bad!r}", True)

from datetime import timedelta  # noqa: E402
t0 = datetime(2026, 6, 7, 10, 0, 0)


def at(i):
    return t0 + timedelta(seconds=i * 10)


seq = [("DSC9998.JPG", at(0)), ("DSC9999.JPG", at(1)),
       ("DSC0001.JPG", at(2)), ("DSC0002.JPG", at(3))]
r = detect_deletions(seq)
check("clean sony wrap = 0 missing", r["suspected_deletions"] == 0, r)
seq = [("DSC9998.JPG", at(0)), ("DSC0001.JPG", at(1))]
r = detect_deletions(seq)
check("wrap with one deleted = 1", r["suspected_deletions"] == 1, r)
r = detect_deletions([("DSC0001.JPG", at(0)), ("A70_0001.JPG", at(1)),
                      ("A70_0002.JPG", at(2))])
check("two prefixes no phantom gaps", r["suspected_deletions"] == 0, r)
check("filename_seq 5 digits", filename_seq("DSC12345.JPG") == ("DSC", 12345))

# ---------------------------------------------------------------- server
from tarzaniq.engine import MockEngine  # noqa: E402
from tarzaniq import server  # noqa: E402

app = server.create(engine_factory=lambda: MockEngine({}))
th = threading.Thread(
    target=lambda: app.run(host="127.0.0.1", port=43990, threaded=True,
                           use_reloader=False), daemon=True)
th.start()
time.sleep(1.2)
B = "http://127.0.0.1:43990"


def get(path):
    with urllib.request.urlopen(B + path, timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


def post(path, body):
    req = urllib.request.Request(
        B + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read() or b"{}")


s, j = get("/api/ping")
check("ping", s == 200 and j["app"] == "TarzanIQ")
s, j = get("/api/state")
check("state", s == 200 and "queue" in j and "config" in j)
s, j = get("/api/overview")
check("overview empty db", s == 200 and j["total"]["days"] == 0)
s, j = get("/api/settings")
check("settings get", s == 200 and "warm_gap_s" in j)
s, j = post("/api/settings", {"warm_gap_s": 7.5, "break_minutes": 25})
check("settings post", s == 200 and j["warm_gap_s"] == 7.5
      and j["break_minutes"] == 25.0)
s, j = post("/api/enqueue", {"folders": ["/nope/26.06.11.X.Y"]})
check("enqueue bad folder -> error list", len(j["errors"]) == 1)
s, j = post("/api/enqueue", {"folders": [str(TMP)]})
check("enqueue bad name -> error list",
      len(j["errors"]) == 1 and "YY.MM.DD" in j["errors"][0]["message"])
s, j = get("/api/registry")
check("registry", s == 200 and j == {"names": [], "places": []})
s, j = get("/api/patterns")
check("patterns empty", s == 200 and j["n_days"] == 0)
s, j = get("/api/places")
check("places empty", s == 200 and j["places"] == [])
s, j = post("/api/reprocess", {"day_id": 999999})
check("reprocess route ok", s == 200 and j["ok"] is True)
s, j = get("/api/comparability")
check("comparability route shape",
      s == 200 and "current_fingerprint" in j and "stale" in j
      and "by_route" in j, str(j))
s, j = post("/api/bring-current", {})
check("bring-current ok", s == 200 and j.get("ok") is True, str(j))

# static files exist & served
s2 = urllib.request.urlopen(B + "/static/vendor/chart.umd.js", timeout=5)
check("chart.js served", s2.status == 200 and len(s2.read()) > 100000)

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
