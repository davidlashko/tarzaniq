"""Permanent photo archive (Feature A).

During ingest we keep a heavily-compressed JPEG XL copy of every photo plus a
per-day manifest, so the full pipeline can be re-run from pixels later
(`reprocess`). The archive lives OUTSIDE the data dir (configurable, possibly an
external drive) and is never destroyed by deleting a day.

`pillow-jxl-plugin` is imported lazily so importing this module never hard-requires
the wheel — the model-free tests and demo server keep running without it.
"""

import hashlib
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import config


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_jxl(bgr, long_edge: int = 1600, quality: int = 80) -> bytes:
    """Downscale a BGR ndarray so its long edge <= long_edge (never upscale),
    then JPEG-XL-encode it in memory."""
    import pillow_jxl  # noqa: F401  (registers the JXL plugin with Pillow)
    h, w = bgr.shape[:2]
    longest = max(h, w)
    if longest > long_edge:
        s = long_edge / float(longest)
        bgr = cv2.resize(bgr, (max(1, int(round(w * s))), max(1, int(round(h * s)))),
                         interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="JXL", quality=int(quality))
    return buf.getvalue()


def decode_jxl(path) -> np.ndarray:
    """Decode an archived .jxl back to a BGR uint8 ndarray (for reprocess)."""
    import pillow_jxl  # noqa: F401
    with Image.open(str(path)) as im:
        rgb = np.asarray(im.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
