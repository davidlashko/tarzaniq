"""Tests for the JXL archive (Feature A). Run: .venv/bin/python tests/test_archive.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="tarzaniq_archive_"))
os.environ["TARZANIQ_DATA"] = str(TMP / "data")
os.environ["TARZANIQ_ARCHIVE"] = str(TMP / "archive")

import numpy as np  # noqa: E402

from tarzaniq import archive  # noqa: E402

fails = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ok    {label}")
    else:
        fails.append(label)
        print(f"  FAIL  {label}  {detail}")


# ---- codec ----
h, w = 1333, 2000
ramp = np.tile(np.linspace(0, 255, w, dtype=np.uint8), (h, 1))
bgr = np.dstack([ramp, ramp, ramp])
jxl = archive.encode_jxl(bgr, long_edge=1600, quality=80)
check("encode returns bytes", isinstance(jxl, bytes) and len(jxl) > 0, str(len(jxl)))

dst = TMP / "probe.jxl"
dst.write_bytes(jxl)
dec = archive.decode_jxl(dst)
check("decode shape long edge<=1600", max(dec.shape[:2]) <= 1600, str(dec.shape))
check("decode is 3-channel uint8", dec.ndim == 3 and dec.dtype == np.uint8, str(dec.dtype))

small = np.dstack([ramp[:200, :300]] * 3)  # 200x300, smaller than 1600
jxl2 = archive.encode_jxl(small, long_edge=1600, quality=80)
(TMP / "small.jxl").write_bytes(jxl2)
dec2 = archive.decode_jxl(TMP / "small.jxl")
check("small image not upscaled", dec2.shape[:2] == (200, 300), str(dec2.shape))

check("sha256 known vector",
      archive.sha256_bytes(b"abc") ==
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

# ---- config ----
from tarzaniq import config  # noqa: E402

cfg = config.load_config()
for k, default in (("archive_enabled", True), ("archive_long_edge", 1600),
                   ("archive_target_kb", 150), ("archive_quality", 80),
                   ("archive_dir", "")):
    check(f"DEFAULTS has {k}", k in config.DEFAULTS and config.DEFAULTS[k] == default,
          str(config.DEFAULTS.get(k)))
    check(f"loaded cfg has {k}", k in cfg)

ad = config.archive_dir()
check("archive_dir honors TARZANIQ_ARCHIVE",
      str(ad) == os.environ["TARZANIQ_ARCHIVE"], str(ad))
check("archive_dir exists", ad.is_dir())

# round-trips through save/load (keys not in DEFAULTS get dropped)
saved = config.save_config({**cfg, "archive_long_edge": 1200})
check("archive_long_edge persists", config.load_config()["archive_long_edge"] == 1200)
config.save_config({**cfg, "archive_long_edge": 1600})  # restore

# ---- manifest ----
folder = "26.06.07.CityPark.Marko"
entries = [
    {"original_filename": "DSC09998.JPG", "seq": 9998, "exif_time": "10:00:00.000000",
     "exif_source": "exif", "sha256": "a" * 64, "jxl_filename": "DSC09998.jxl",
     "jxl_bytes": 123},
    {"original_filename": "DSC09999.JPG", "seq": 9999, "exif_time": "10:00:02.500000",
     "exif_source": "exif", "sha256": "b" * 64, "jxl_filename": "DSC09999.jxl",
     "jxl_bytes": 456},
]
header = {"folder": folder, "date": "2026-06-07", "place": "CityPark",
          "employee": "Marko", "count": len(entries)}
# place dummy jxl files so iter_archived yields real paths
dd = archive.day_archive_dir(folder)
dd.mkdir(parents=True, exist_ok=True)
for e in entries:
    (dd / e["jxl_filename"]).write_bytes(b"x")
archive.write_manifest(folder, header, entries)

check("manifest written", archive.manifest_path(folder).exists())
man = archive.read_manifest(folder)
check("manifest count", man and man["count"] == 2, str(man))
check("manifest preserves original filename + seq",
      man["photos"][0]["original_filename"] == "DSC09998.JPG"
      and man["photos"][0]["seq"] == 9998)
got = list(archive.iter_archived(folder))
check("iter yields 2 (path, entry)", len(got) == 2 and got[0][0].name == "DSC09998.jxl")
check("read_manifest missing -> None", archive.read_manifest("99.99.99.Nope.Nobody") is None)

# ---- ingest writes the archive (end to end via AppState + MockEngine) ----
import time as _time  # noqa: E402
from PIL import Image as _Image  # noqa: E402
from tarzaniq import db  # noqa: E402
from tarzaniq.engine import MockEngine  # noqa: E402
from tarzaniq.pipeline import AppState  # noqa: E402

ING = TMP / "ingest" / "26.06.11.OldBazaar.Ana"
ING.mkdir(parents=True)
ing_plan = [(1, [0]), (2, [0]), (3, [0])]  # 3 photos, one subject
ing_manifest = {}
for num, subs in ing_plan:
    fn = f"DSC{num:04d}.JPG"
    _Image.new("RGB", (320, 240), (num * 9 % 255, 100, 80)).save(ING / fn, "JPEG")
    ing_manifest[fn] = {"subjects": subs, "extra": 0}

st = AppState(engine_factory=lambda: MockEngine(ing_manifest))
added, errs = st.enqueue([str(ING)])


def _wait_prompt(ptype, timeout=20):
    t0 = _time.time()
    while _time.time() - t0 < timeout:
        p = st.pending_prompt
        if p and p["type"] == ptype:
            return p
        _time.sleep(0.05)
    raise TimeoutError(ptype)


def _wait_done(jid, timeout=30):
    t0 = _time.time()
    while _time.time() - t0 < timeout:
        for j in st.jobs:
            if j.id == jid and j.status in ("done", "error", "discarded", "skipped"):
                return j
        _time.sleep(0.05)
    raise TimeoutError("job")


p = _wait_prompt("money"); st.answer(p["id"], {})
p = _wait_prompt("commit"); st.answer(p["id"], {"commit": True})
job = _wait_done(added[0]["id"])
check("ingest committed", job.status == "done", job.message)

man2 = archive.read_manifest("26.06.11.OldBazaar.Ana")
check("ingest wrote manifest", man2 is not None and man2["count"] == 3, str(man2))
check("ingest preserved filenames + seq",
      man2["photos"][0]["original_filename"] == "DSC0001.JPG"
      and man2["photos"][0]["seq"] == 1)
check("ingest entries have sha256 + jxl_bytes",
      len(man2["photos"][0]["sha256"]) == 64 and man2["photos"][0]["jxl_bytes"] > 0)
adir = archive.day_archive_dir("26.06.11.OldBazaar.Ana")
check("jxl files on disk", (adir / "DSC0001.jxl").exists()
      and (adir / "DSC0003.jxl").exists())
check("archived jxl decodes", archive.decode_jxl(adir / "DSC0001.jxl").ndim == 3)

# ---- shared analyze_frame helper ----
from datetime import datetime as _dt  # noqa: E402
from tarzaniq.pipeline import analyze_frame  # noqa: E402
from tarzaniq.engine import SubjectTracker  # noqa: E402
from tarzaniq.engagements import Engager  # noqa: E402

_tr = SubjectTracker(0.36)
_eng = Engager(config.engagement_params(config.load_config()))
_rec = {"filename": "DSC0001.JPG", "seq": 1,
        "t": _dt(2026, 6, 11, 10, 0, 0), "src": "exif"}
_img = np.zeros((240, 320, 3), dtype=np.uint8)
_record, _obs, _live = analyze_frame(
    MockEngine({"DSC0001.JPG": {"subjects": [0]}}), _tr, _eng, 0, _rec, _img, [])
check("analyze_frame record subjects", _record["subjects"] == [0], str(_record))
check("analyze_frame record seq+kind",
      _record["seq"] == 1 and _record["kind"] in ("cold", "mixed"), str(_record))
check("analyze_frame returns observations + live",
      isinstance(_obs, list) and "kind" in _live)
_r2, _, _ = analyze_frame(MockEngine({}), _tr, _eng, 1, _rec, None, ["decode_failed"])
check("analyze_frame handles img=None",
      _r2["n_focus"] == 0 and "decode_failed" in _r2["flags"])

# ---- reprocess from the archive reproduces the MockEngine ingest ----
import json as _json  # noqa: E402
from tarzaniq.pipeline import reprocess_day  # noqa: E402

con = db.connect()
row = [d for d in db.all_days(con) if d["employee"] == "Ana"][0]
orig = _json.loads(row["stats_json"])
stats2, new_id = reprocess_day(con, row["id"], MockEngine(ing_manifest),
                               config.load_config())
check("reprocess returns stats + new id", stats2 is not None and new_id is not None)
check("reprocess reproduces cold_persons",
      stats2["cold_persons"] == orig["cold_persons"],
      f"{stats2['cold_persons']} vs {orig['cold_persons']}")
check("reprocess reproduces warm_persons",
      stats2["warm_persons"] == orig["warm_persons"])
check("reprocess persisted one day still",
      len([d for d in db.all_days(con) if d["employee"] == "Ana"]) == 1)
check("reprocess missing day -> None",
      reprocess_day(con, 999999, MockEngine({}), config.load_config()) is None)
con.close()

# ---- reprocess runs as a queued worker job ----
con = db.connect()
ana = [d for d in db.all_days(con) if d["employee"] == "Ana"][0]
con.close()
queued = st.enqueue_reprocess([ana["id"]])
check("enqueue_reprocess accepted", len(queued) == 1)
rj = _wait_done(queued[0]["id"])
check("reprocess job done", rj.status == "done", rj.message)

# ---- a declined day leaves no manifest (FIX 1) ----
from PIL import Image as _Img2  # noqa: E402
DEC = TMP / "ingest" / "26.06.12.OldBazaar.Ana"
DEC.mkdir(parents=True)
for _n in (1, 2):
    _Img2.new("RGB", (320, 240), (_n * 7 % 255, 90, 70)).save(DEC / f"DSC{_n:04d}.JPG", "JPEG")
_dec_added, _ = st.enqueue([str(DEC)])
_p = _wait_prompt("money"); st.answer(_p["id"], {})
_p = _wait_prompt("commit"); st.answer(_p["id"], {"commit": False})  # DECLINE
_dj = _wait_done(_dec_added[0]["id"])
check("declined day discarded", _dj.status == "discarded", _dj.status)
check("declined day writes NO manifest",
      archive.read_manifest("26.06.12.OldBazaar.Ana") is None)

# ---- reprocess honors cancel (FIX 2) ----
from tarzaniq.pipeline import reprocess_day as _rp  # noqa: E402
_con = db.connect()
_ana = [d for d in db.all_days(_con) if d["employee"] == "Ana"][0]
_before = len(db.all_days(_con))
_res = _rp(_con, _ana["id"], MockEngine(ing_manifest), config.load_config(),
           cancel_check=lambda: True)
check("reprocess cancel returns None", _res is None)
check("reprocess cancel committed nothing new", len(db.all_days(_con)) == _before)
_con.close()

# ---- Feature B: bring_current routes stale days ----
from tarzaniq import fingerprint as _fpb  # noqa: E402
from tarzaniq.pipeline import bring_current  # noqa: E402

con = db.connect()
# everything currently committed should be current
cur_fp = _fpb.fingerprint(_fpb.current())
check("no stale days initially", len(db.stale_days(con, cur_fp)) == 0,
      str([d["date"] for d in db.stale_days(con, cur_fp)]))

# change a FACE param in config -> Ana (has archive) should route to reprocess
_c = config.load_config(); _c["min_face_frac"] = _c["min_face_frac"] + 0.01
config.save_config(_c)
new_fp = _fpb.fingerprint(_fpb.current())
stale = db.stale_days(con, new_fp)
check("face change makes days stale", len(stale) >= 1)
res = bring_current(st, con)
check("bring_current queued a reprocess for the archived day", res["reprocess_queued"] >= 1, str(res))
con.close()

# restore config so later/other runs aren't affected
_c2 = config.load_config(); _c2["min_face_frac"] = _c2["min_face_frac"] - 0.01
config.save_config(_c2)

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
