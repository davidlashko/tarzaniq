"""EXIF reading. Per Tbone's spec: DATE comes from the folder name,
TIME comes from the photo's EXIF. Camera clock drift is deliberately
ignored — we only trust the time-of-day."""

import re
from datetime import datetime, date, time, timedelta
from pathlib import Path

from PIL import Image

_DT_RE = re.compile(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")

TAG_DATETIME = 306          # ImageIFD DateTime
TAG_EXIF_IFD = 0x8769
TAG_DT_ORIGINAL = 36867     # DateTimeOriginal
TAG_DT_DIGITIZED = 36868
TAG_SUBSEC_ORIGINAL = 37521


def read_time_of_day(path: Path):
    """Return (time_of_day, subseconds_float, source_str).

    Tries DateTimeOriginal -> DateTimeDigitized -> DateTime -> file mtime.
    PIL only reads the header here; the pixels stay on disk.
    """
    subsec = 0.0
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            raw = None
            try:
                ifd = ex.get_ifd(TAG_EXIF_IFD)
            except Exception:
                ifd = {}
            for tag, src in ((ifd.get(TAG_DT_ORIGINAL), "exif"),
                             (ifd.get(TAG_DT_DIGITIZED), "exif"),
                             (ex.get(TAG_DATETIME), "exif")):
                if tag:
                    raw = (str(tag), src)
                    break
            ss = ifd.get(TAG_SUBSEC_ORIGINAL)
            if ss:
                digits = re.sub(r"\D", "", str(ss))[:3]
                if digits:
                    subsec = int(digits) / (10 ** len(digits))
            if raw:
                m = _DT_RE.search(raw[0])
                if m:
                    _, _, _, hh, mm, sss = (int(g) for g in m.groups())
                    return time(hh, mm, sss), subsec, raw[1]
    except Exception:
        pass
    # fallback: file modification time-of-day (flagged upstream)
    try:
        mt = datetime.fromtimestamp(path.stat().st_mtime)
        return mt.time(), 0.0, "mtime"
    except Exception:
        return time(0, 0, 0), 0.0, "none"


def combine(day: date, tod: time, subsec: float) -> datetime:
    return datetime.combine(day, tod) + timedelta(seconds=subsec)
