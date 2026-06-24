"""End-to-end pipeline test with synthetic photos + mock face engine.
Run: python3 tests/test_e2e.py"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="tarzaniq_test_"))
os.environ["TARZANIQ_DATA"] = str(TMP / "data")

import numpy as np  # noqa: E402
import piexif  # noqa: E402
from PIL import Image  # noqa: E402

from tarzaniq import config, db  # noqa: E402
from tarzaniq.engine import MockEngine  # noqa: E402
from tarzaniq.pipeline import AppState, recompute_day  # noqa: E402
from tarzaniq.excelio import import_day  # noqa: E402


def make_jpg(path, hhmmss, color):
    im = Image.new("RGB", (320, 240), color)
    exif = piexif.dump({"Exif": {
        piexif.ExifIFD.DateTimeOriginal: f"2020:01:05 {hhmmss}".encode()}})
    im.save(path, "JPEG", exif=exif)  # EXIF date is WRONG on purpose:
    # the folder name must win for the date, EXIF only supplies the time.


# ---------------------------------------------------------------- build day
FOLDER = TMP / "26.06.07.CityPark.Marko"
FOLDER.mkdir(parents=True)
(FOLDER / "notes.txt").write_text("not a jpeg")  # should count as skipped

# (filename_num, time, subjects, extra_rejected)
plan = [
    (1, "10:00:00", [0], 0), (2, "10:00:02", [0], 0),          # S0 cold
    (3, "10:00:40", [0], 0), (4, "10:00:43", [0], 0),          # S0 warm p1
    (5, "10:00:52", [0], 0),                                   # S0 warm p2 (9s gap)
    (6, "10:05:00", [1, 2], 0), (7, "10:05:02", [1, 2], 0),    # group cold
    (11, "10:05:30", [1], 0), (12, "10:05:33", [1], 0),        # S1 warm (gap 8..10 deleted)
    (13, "10:35:00", [3], 0),                                  # S3 cold after 29min break
    (14, "10:36:00", [], 2),                                   # air shot, 2 rejected
    (15, "10:40:00", [4], 0),                                  # S4 cold
    (16, "10:41:00", [4], 0), (17, "10:41:02", [4], 0),        # S4 warm
]
manifest = {}
for num, t, subs, extra in plan:
    fn = f"DSC{num:04d}.JPG"
    make_jpg(FOLDER / fn, t, (num * 9 % 255, 120, 90))
    manifest[fn] = {"subjects": subs, "extra": extra,
                    "gender": {0: "M", 1: "F", 2: "F", 3: "M", 4: "M"},
                    "age": {0: 4, 1: 4, 2: 5, 3: 6, 4: 3}}

state = AppState(engine_factory=lambda: MockEngine(manifest))


def wait_prompt(ptype, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        p = state.pending_prompt
        if p and p["type"] == ptype:
            return p
        time.sleep(0.05)
    raise TimeoutError(f"prompt {ptype} never appeared "
                       f"(now: {state.pending_prompt}, "
                       f"jobs: {[j.brief() for j in state.jobs]})")


def wait_done(job_id, statuses=("done", "error", "discarded", "skipped"),
              timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for j in state.jobs:
            if j.id == job_id and j.status in statuses:
                return j
        time.sleep(0.05)
    raise TimeoutError("job never finished")


fails = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok    {label}")
    else:
        fails.append(label)
        print(f"  FAIL  {label}  {detail}")


# ---------------------------------------------------------------- run 1
added, errs = state.enqueue([str(FOLDER)])
check("enqueue accepted", len(added) == 1 and not errs, f"{added} {errs}")

p = wait_prompt("money")
state.answer(p["id"], {"cash": "150.5", "card": "200"})
p = wait_prompt("commit")
sumcard = p["payload"]["summary"]
state.answer(p["id"], {"commit": True})
job = wait_done(added[0]["id"])
check("job done", job.status == "done", job.message)

con = db.connect()
days = db.all_days(con)
check("one day in db", len(days) == 1)
st = json.loads(days[0]["stats_json"])

check("date from folder not exif", days[0]["date"] == "2026-06-07")
check("weekday", st["weekday"] == "Sunday", st["weekday"])
check("photos_total", st["photos_total"] == 14, st["photos_total"])
check("skipped_files", st["skipped_files"] == 1)
check("cold_persons=5", st["cold_persons"] == 5, st["cold_persons"])
check("warm_persons=3", st["warm_persons"] == 3, st["warm_persons"])
check("cold_events=4", st["cold_events"] == 4, st["cold_events"])
check("conversion=0.6", abs(st["conversion"] - 0.6) < 1e-9, st["conversion"])
check("breaks=1", st["breaks_n"] == 1)
check("hot_streak=2", st["hot_streak"] == 2, st["hot_streak"])
check("deletions=3", st["suspected_deletions"] == 3,
      st["suspected_deletions"])
check("air shots=1", st["photos_air"] == 1)
check("money saved", days[0]["money_cash"] == 150.5
      and days[0]["money_card"] == 200.0)
check("group conv 0.5", abs(st["group_conv"] - 0.5) < 1e-9, st["group_conv"])
check("solo conv 2/3", abs(st["solo_conv"] - 2 / 3) < 1e-9, st["solo_conv"])
check("gender counts", st["gender_count"] == {"M": 3, "F": 2},
      st["gender_count"])
check("age bucket S0 25-32",
      any(s["age_bucket"] == "25-32" and s["local_id"] == 0
          for s in db.day_subjects(con, days[0]["id"])))
check("summary card matches", sumcard["warm_persons"] == 3
      and sumcard["cold_persons"] == 5)

subs = db.day_subjects(con, days[0]["id"])
s0 = next(s for s in subs if s["local_id"] == 0)
check("S0 pitch 38s", abs(s0["pitch_s"] - 38) < 0.01, s0["pitch_s"])
check("S0 poses 2", s0["poses_est"] == 2, s0["poses_est"])
check("S0 warm dur 12s", abs(s0["warm_duration_s"] - 12) < 0.01,
      s0["warm_duration_s"])

xlsx = config.exports_dir() / "26.06.07.CityPark.Marko.xlsx"
check("excel exported", xlsx.exists())

# ---- Feature B: a freshly committed day is born current ----
from tarzaniq import fingerprint as _fp  # noqa: E402
_d0 = db.all_days(con)[0]
_cur = _fp.current()
check("committed day stamped current",
      _d0["processing_fingerprint"] == _fp.fingerprint(_cur),
      _d0["processing_fingerprint"])
check("committed day fp_components match current",
      json.loads(_d0["fp_components"]) == _cur)

# ---------------------------------------------------------------- roundtrip
rec = import_day(xlsx)
check("import chunks parse", rec["stats"]["cold_persons"] == 5)
check("import photos count", len(rec["photos"]) == 14)

# ---------------------------------------------------------------- duplicate
added2, _ = state.enqueue([str(FOLDER)])
p = wait_prompt("duplicate_day")
state.answer(p["id"], {"action": "replace"})
p = wait_prompt("money")
state.answer(p["id"], {})
p = wait_prompt("commit")
state.answer(p["id"], {"commit": True})
job2 = wait_done(added2[0]["id"])
check("replace done", job2.status == "done", job2.message)
check("still one day", len(db.all_days(con)) == 1)
check("money cleared on replace",
      db.all_days(con)[0]["money_cash"] is None)

# ---------------------------------------------------------------- new name
FOLDER2 = TMP / "26.06.08.CityPark.Petar"
shutil.copytree(FOLDER, FOLDER2)
added3, _ = state.enqueue([str(FOLDER2)])
p = wait_prompt("new_name")
check("new_name prompt payload", p["payload"]["value"] == "Petar"
      and "Marko" in p["payload"]["known"])
state.answer(p["id"], {"action": "add"})
p = wait_prompt("money")
state.answer(p["id"], {"cash": "99"})
p = wait_prompt("commit")
state.answer(p["id"], {"commit": True})
job3 = wait_done(added3[0]["id"])
check("second ape committed", job3.status == "done", job3.message)
check("two days now", len(db.all_days(con)) == 2)

# ---------------------------------------------------------------- map typo
FOLDER3 = TMP / "26.06.09.CityPark.Marc"
shutil.copytree(FOLDER, FOLDER3)
added4, _ = state.enqueue([str(FOLDER3)])
p = wait_prompt("new_name")
state.answer(p["id"], {"action": "map", "map_to": "Marko"})
p = wait_prompt("money")
state.answer(p["id"], {})
p = wait_prompt("commit")
state.answer(p["id"], {"commit": True})
job4 = wait_done(added4[0]["id"])
d4 = [d for d in db.all_days(con) if d["date"] == "2026-06-09"][0]
check("typo mapped to Marko", d4["employee"] == "Marko")

# ---------------------------------------------------------------- discard
FOLDER4 = TMP / "26.06.10.Mall.Marko"
shutil.copytree(FOLDER, FOLDER4)
added5, _ = state.enqueue([str(FOLDER4)])
p = wait_prompt("new_place")
state.answer(p["id"], {"action": "add"})
p = wait_prompt("money")
state.answer(p["id"], {})
p = wait_prompt("commit")
state.answer(p["id"], {"commit": False})
job5 = wait_done(added5[0]["id"])
check("discard works", job5.status == "discarded")
check("discarded day not in db",
      not any(d["date"] == "2026-06-10" for d in db.all_days(con)))

# ---------------------------------------------------------------- recompute
day_id = db.all_days(con)[0]["id"]
params = config.engagement_params(config.load_config())
params["warm_gap_s"] = 60.0  # S0 (38s) and S1 (28s) returns now extend
# their cold shoots; only S4's 60s return still counts as warm
new_stats = recompute_day(con, day_id, params)
check("recompute drops sub-60s warms", new_stats["warm_persons"] == 1,
      new_stats["warm_persons"])
check("recompute keeps cold persons", new_stats["cold_persons"] == 5)
con2 = db.connect()
st2 = json.loads(db.day_row(con2, day_id)["stats_json"])
check("recompute persisted", st2["warm_persons"] == 1)

# ---------------------------------------------------------------- agg smoke
from tarzaniq import agg  # noqa: E402
ov = agg.overview(con2)
check("overview totals", ov["total"]["days"] == 3
      and ov["total"]["employees"] == 2, ov["total"])
emp = agg.employee_detail(con2, "Marko")
check("employee detail", emp["summary"]["days"] == 2
      and len(emp["series"]) == 2)
pl = agg.places(con2)
check("places agg", pl["places"][0]["place"] == "CityPark")
pat = agg.patterns(con2)
check("patterns hours", any(h["hour"] == 10 for h in pat["hours"]))
day_d = agg.day_detail(con2, day_id)
check("day detail blocks", len(day_d["blocks"]) > 0)

con.close(); con2.close()
print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
