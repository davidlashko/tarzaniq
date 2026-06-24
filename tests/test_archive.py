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

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
