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

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
