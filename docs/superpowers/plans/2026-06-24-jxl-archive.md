# Feature A — Permanent JXL Photo Archive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** During ingest, save a ~150 KB / ~1600px JPEG XL of every photo plus a per-day `manifest.json` to a configurable archive, and add a `reprocess` job tier that re-runs the full face pipeline from that archive.

**Architecture:** A new isolated `tarzaniq/archive.py` owns the JXL codec, hashing, and on-disk manifest layout. The ingest loop in `pipeline.py` gains an archive-write step; a new `reprocess_day()` mirrors the ingest inference path but reads archived JXLs. Reprocess rides the existing `AppState` worker/queue/SSE machinery as a new `Job.kind`. **No DB migration** — archive presence is tracked by the manifest on disk; DB flags are deferred to Feature B.

**Tech Stack:** Python 3.11–3.12, OpenCV (`cv2`), Pillow + `pillow-jxl-plugin`, Flask, SQLite. Tests are standalone scripts (no pytest) run via `.venv/bin/python tests/<name>.py`.

## Global Constraints

- Python 3.11–3.12 only (system 3.14 has no `cv2` wheel). Use `.venv/bin/python`.
- Codec: `pillow-jxl-plugin` (lazy-imported inside `archive.encode_jxl`/`decode_jxl` so importing `archive` never hard-requires the wheel and the existing model-free tests keep running).
- Archive layout: `<archive_dir>/<YY.MM.DD.Place.Name>/<original-stem>.jxl` + `manifest.json`. **Preserve original filenames** (`DSC09998.JPG` → `DSC09998.jxl`) — deletion detection depends on the sequence.
- `archive_dir` precedence: `config['archive_dir']` → `$TARZANIQ_ARCHIVE` → `~/Documents/TarzanIQ Archive`. Separate from the data dir.
- Defaults: `archive_enabled=True`, `archive_long_edge=1600`, `archive_target_kb=150`, `archive_quality=80`.
- Manifest stores **time-of-day with sub-second precision** (`%H:%M:%S.%f`), never an EXIF date; the date always comes from the folder, re-supplied on reprocess.
- Delete behavior: deleting a day never touches the archive (keep-on-delete).
- Archiving must never crash a day's ingest (wrap in try/except, flag `archive_failed`).
- Keep the whole suite green (`test_engagements`, `test_server`, `test_e2e`, `dom_smoke`, new `test_archive`) after every task.
- No "built with / produced by" branding in any output. This repo is public — never commit photos, data, DBs, exports, models, or `.jxl` files.

---

## File Structure

- **Create** `tarzaniq/archive.py` — codec (`encode_jxl`, `decode_jxl`), `sha256_bytes`, path helpers (`day_archive_dir`, `manifest_path`), manifest I/O (`write_manifest`, `read_manifest`, `iter_archived`).
- **Modify** `tarzaniq/config.py` — add 5 `DEFAULTS` keys + `archive_dir()` resolver.
- **Modify** `tarzaniq/pipeline.py` — `import numpy as np` + `from . import archive`; archive-write in the ingest loop; `reprocess_day()`; `Job.kind`/`day_id`; `enqueue_reprocess()`; reprocess worker dispatch.
- **Modify** `tarzaniq/server.py` — `POST /api/reprocess`.
- **Modify** `tarzaniq/static/js/{pages,util}.js` — a "Reprocess from archive" button on the day page.
- **Modify** `requirements.txt` — add `pillow-jxl-plugin`.
- **Modify** `uninstall.sh`, `README.md` — note the archive (ops + privacy wording).
- **Create** `tests/test_archive.py` — unit + integration tests for the whole feature.
- **Modify** `tests/test_server.py` — `/api/reprocess` route smoke.

---

## Task 1: `archive.py` codec — encode, decode, hash

**Files:**
- Create: `tarzaniq/archive.py`
- Modify: `requirements.txt`
- Test: `tests/test_archive.py`

**Interfaces:**
- Produces:
  - `encode_jxl(bgr: np.ndarray, long_edge: int = 1600, quality: int = 80) -> bytes`
  - `decode_jxl(path: Path | str) -> np.ndarray` (BGR uint8)
  - `sha256_bytes(data: bytes) -> str`

- [ ] **Step 1: Add the codec dependency**

Edit `requirements.txt`, append:

```
pillow-jxl-plugin>=1.3   # JPEG XL encode/decode for the permanent photo archive (Feature A)
```

Install it into the venv:

Run: `.venv/bin/python -m pip install -r requirements.txt`
Expected: `pillow-jxl-plugin` installs (arm64 wheel).

- [ ] **Step 2: Write the failing test**

Create `tests/test_archive.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'tarzaniq.archive'`.

- [ ] **Step 4: Write minimal implementation**

Create `tarzaniq/archive.py`:

```python
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
```

(The remaining functions — paths and manifest — are added in Task 3.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — all `ok`, `ALL GREEN`.

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/archive.py tests/test_archive.py requirements.txt
git commit -m "feat(archive): JXL encode/decode + sha256 helpers

Add tarzaniq/archive.py with encode_jxl (downscale to <=1600px long edge,
never upscale, then JPEG-XL encode), decode_jxl (back to BGR ndarray for
reprocess), and sha256_bytes. pillow-jxl-plugin is lazy-imported so the
module loads without the wheel. Add pillow-jxl-plugin to requirements.txt.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: config — archive keys + `archive_dir()` resolver

**Files:**
- Modify: `tarzaniq/config.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Produces: `config.archive_dir() -> Path`; new `DEFAULTS` keys `archive_enabled` (bool), `archive_dir` (str), `archive_long_edge` (int), `archive_target_kb` (int), `archive_quality` (int).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final `print`/`sys.exit` block):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `DEFAULTS has archive_enabled` (key missing) / `AttributeError: ... 'archive_dir'`.

- [ ] **Step 3: Add the keys and resolver**

In `tarzaniq/config.py`, add to the `DEFAULTS` dict (after the `"sounds_enabled": True,` line, before the closing `}`):

```python
    # --- permanent JXL photo archive (Feature A) ---
    "archive_enabled": True,    # write a compressed JXL + manifest on ingest
    "archive_dir": "",          # "" => $TARZANIQ_ARCHIVE or ~/Documents/TarzanIQ Archive
    "archive_long_edge": 1600,  # max long edge of the archived copy (px)
    "archive_target_kb": 150,   # size intent; calibrate archive_quality to it
    "archive_quality": 80,      # JXL quality used at ingest
```

Add this resolver after `def config_path()` (before the `# load/save` section):

```python
def archive_dir() -> Path:
    """Permanent photo archive, SEPARATE from the data dir (may be an external
    drive). Precedence: config['archive_dir'] -> $TARZANIQ_ARCHIVE -> default."""
    cfg = load_config()
    override = cfg.get("archive_dir") or os.environ.get("TARZANIQ_ARCHIVE")
    if override:
        p = Path(override).expanduser()
    else:
        p = Path.home() / "Documents" / "TarzanIQ Archive"
    p.mkdir(parents=True, exist_ok=True)
    return p
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

- [ ] **Step 5: Verify the existing suite still passes**

Run: `.venv/bin/python tests/test_server.py`
Expected: PASS (settings coercion still works with the new keys).

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/config.py tests/test_archive.py
git commit -m "feat(config): archive settings + archive_dir() resolver

Add archive_enabled/archive_dir/archive_long_edge/archive_target_kb/
archive_quality to DEFAULTS (so they persist and are editable in Settings),
and an archive_dir() resolver separate from the data dir
(config -> \$TARZANIQ_ARCHIVE -> ~/Documents/TarzanIQ Archive).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `archive.py` — paths + manifest I/O

**Files:**
- Modify: `tarzaniq/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Produces:
  - `day_archive_dir(folder_name: str) -> Path`
  - `manifest_path(folder_name: str) -> Path`
  - `write_manifest(folder_name: str, header: dict, entries: list[dict]) -> None`
  - `read_manifest(folder_name: str) -> dict | None`
  - `iter_archived(folder_name: str) -> Iterator[tuple[Path, dict]]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final print/exit):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `AttributeError: module 'tarzaniq.archive' has no attribute 'day_archive_dir'`.

- [ ] **Step 3: Implement paths + manifest**

Append to `tarzaniq/archive.py`:

```python
# ---------------------------------------------------------------- layout

def day_archive_dir(folder_name: str) -> Path:
    return config.archive_dir() / folder_name


def manifest_path(folder_name: str) -> Path:
    return day_archive_dir(folder_name) / "manifest.json"


def write_manifest(folder_name: str, header: dict, entries: list) -> None:
    """Atomically write the per-day manifest (header fields + a `photos` list)."""
    d = day_archive_dir(folder_name)
    d.mkdir(parents=True, exist_ok=True)
    payload = dict(header)
    payload["photos"] = entries
    target = manifest_path(folder_name)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(target)


def read_manifest(folder_name: str):
    p = manifest_path(folder_name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def iter_archived(folder_name: str):
    """Yield (jxl_path, manifest_entry) for each archived photo, in manifest order."""
    man = read_manifest(folder_name)
    if not man:
        return
    d = day_archive_dir(folder_name)
    for entry in man.get("photos", []):
        yield d / entry["jxl_filename"], entry
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/archive.py tests/test_archive.py
git commit -m "feat(archive): on-disk per-day manifest + path helpers

day_archive_dir/manifest_path plus atomic write_manifest, read_manifest,
and iter_archived. Manifest is keyed/ordered by original filename + seq so
deletion detection survives reprocess.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: wire archiving into ingest

**Files:**
- Modify: `tarzaniq/pipeline.py` (imports; the Phase-2 loop ~lines 279-339; manifest write after the loop)
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `archive.sha256_bytes`, `archive.encode_jxl`, `archive.day_archive_dir`, `archive.write_manifest`; `config` archive keys.
- Produces: after a committed ingest, `<archive_dir>/<folder>/<stem>.jxl` files + `manifest.json`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final print/exit). This drives a real ingest through `AppState` + `MockEngine`, then asserts the archive was written:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `ingest wrote manifest` (read_manifest returns None; nothing archived yet).

- [ ] **Step 3: Add imports**

In `tarzaniq/pipeline.py`, change the import block. Add `numpy` and `archive`:

```python
import cv2
import numpy as np

from . import APP_VERSION, config, db, naming, exifutil, archive
```

(Replace the existing `import cv2` line and the existing `from . import APP_VERSION, config, db, naming, exifutil` line.)

- [ ] **Step 4: Set up archive state before the loop**

In `_run_job_inner`, immediately after the existing `decode_flag = (...)` assignment (~line 280) and before the `for idx, rec in enumerate(scan):` loop, add:

```python
        do_archive = bool(cfg.get("archive_enabled", True))
        arch_long = int(cfg.get("archive_long_edge", 1600))
        arch_q = int(cfg.get("archive_quality", 80))
        archive_entries = []
```

- [ ] **Step 5: Replace the decode + add the archive-write**

Replace this block inside the loop (currently ~lines 288-296):

```python
            img = cv2.imread(str(rec["path"]), decode_flag)
            flags = []
            if rec["src"] in ("mtime", "none"):
                flags.append("no_exif_time")
            observations = []
            if img is None:
                flags.append("decode_failed")
            else:
                observations = engine.analyze(img, {"filename": rec["filename"]})
```

with (single file read → sha + decode; then archive before analyze so `archive_failed` can be flagged on the stored record):

```python
            raw = None
            try:
                raw = rec["path"].read_bytes()
            except Exception:
                raw = None
            img = (cv2.imdecode(np.frombuffer(raw, np.uint8), decode_flag)
                   if raw is not None else None)
            flags = []
            if rec["src"] in ("mtime", "none"):
                flags.append("no_exif_time")

            if do_archive and img is not None and raw is not None:
                try:
                    jxl = archive.encode_jxl(img, arch_long, arch_q)
                    jxl_name = Path(rec["filename"]).stem + ".jxl"
                    adir = archive.day_archive_dir(job.name)
                    adir.mkdir(parents=True, exist_ok=True)
                    (adir / jxl_name).write_bytes(jxl)
                    archive_entries.append({
                        "original_filename": rec["filename"], "seq": rec["seq"],
                        "exif_time": rec["t"].strftime("%H:%M:%S.%f"),
                        "exif_source": rec["src"], "sha256": archive.sha256_bytes(raw),
                        "jxl_filename": jxl_name, "jxl_bytes": len(jxl)})
                except Exception:
                    flags.append("archive_failed")

            observations = []
            if img is None:
                flags.append("decode_failed")
            else:
                observations = engine.analyze(img, {"filename": rec["filename"]})
```

- [ ] **Step 6: Write the manifest after the loop**

Immediately after the `for idx, rec in enumerate(scan):` loop ends and before `# ---- wrap up analysis` / `eng_final = engager.finalize()`, add:

```python
        if do_archive and archive_entries:
            try:
                archive.write_manifest(job.name, {
                    "folder": job.name, "date": date_iso, "place": job.place,
                    "employee": job.employee, "archive_long_edge": arch_long,
                    "archive_target_kb": int(cfg.get("archive_target_kb", 150)),
                    "archive_quality": arch_q, "app_version": APP_VERSION,
                    "count": len(archive_entries),
                    "archived_at": datetime.now().isoformat()},
                    archive_entries)
            except Exception:
                pass
```

- [ ] **Step 7: Run the new test and the full suite**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

Run: `.venv/bin/python tests/test_e2e.py`
Expected: PASS (ingest still produces identical stats; archiving is additive). Note: `test_e2e` does not set `TARZANIQ_ARCHIVE`, so it writes to the default archive dir — harmless in a throwaway test environment, and the existing assertions are unchanged.

- [ ] **Step 8: Commit**

```bash
git add tarzaniq/pipeline.py tests/test_archive.py
git commit -m "feat(pipeline): archive each photo as JXL + manifest on ingest

In the Phase-2 decode loop, read each file once (sha256 + imdecode), then
encode a downscaled JXL to <archive>/<folder>/<stem>.jxl and collect a
manifest entry (original filename, seq, time-of-day, sha256, jxl bytes).
Write manifest.json after the loop. Archiving is wrapped so it can never
crash an ingest (flags 'archive_failed' instead). Additive: stats unchanged.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `reprocess_day()` — full pipeline from the archive

**Files:**
- Modify: `tarzaniq/pipeline.py` (add `reprocess_day` near `recompute_day`; `from datetime import date`)
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `archive.read_manifest`, `archive.iter_archived`, `archive.decode_jxl`; `db.day_row`, `db.commit_day`; `engine.analyze`; `SubjectTracker`, `Engager`, `compute_day_stats`, `build_day_record`, `export_day`.
- Produces: `reprocess_day(con, day_id, engine, cfg, progress=None) -> tuple[dict, int] | None` — returns `(stats, new_day_id)`, or `None` if the day is missing. Raises `FileNotFoundError` if no archive/manifest exists.

> **Note:** `commit_day` replaces the day by `UNIQUE(date,place,employee)`, so the row gets a **new** `id` (reprocess re-detects faces → new photo/subject rows; `replace_day_analysis` is *not* applicable). Hence the function returns the new id. With `MockEngine` the result is deterministic and must reproduce the original ingest's counts; with the real engine, lossy JXL + greedy clustering can drift (expected — formalized by Feature B).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final print/exit). It reuses the day ingested in Task 4:

```python
# ---- reprocess from the archive reproduces the MockEngine ingest ----
from tarzaniq.pipeline import reprocess_day  # noqa: E402

con = db.connect()
row = [d for d in db.all_days(con) if d["employee"] == "Ana"][0]
orig = __import__("json").loads(row["stats_json"])
stats2, new_id = reprocess_day(con, row["id"], MockEngine(ing_manifest),
                               config.load_config())
check("reprocess returns stats + new id", stats2 is not None and new_id is not None)
check("reprocess reproduces cold_persons",
      stats2["cold_persons"] == orig["cold_persons"], f"{stats2['cold_persons']} vs {orig['cold_persons']}")
check("reprocess reproduces warm_persons",
      stats2["warm_persons"] == orig["warm_persons"])
check("reprocess persisted one day still",
      len([d for d in db.all_days(con) if d["employee"] == "Ana"]) == 1)
check("reprocess no-archive raises",
      _raises(lambda: reprocess_day(con, 999999, MockEngine({}), config.load_config())))
con.close()
```

Also add this tiny helper near the top of `tests/test_archive.py` (after `def check`):

```python
def _raises(fn):
    try:
        fn()
        return False
    except Exception:
        return True
```

(For a non-existent day_id `reprocess_day` returns `None` rather than raising; replace the last check with a real archived-but-missing case is overkill — instead assert `None`:)

```python
check("reprocess missing day -> None",
      reprocess_day(con, 999999, MockEngine({}), config.load_config()) is None)
```

(Use this `-> None` check; drop the `_raises` helper if unused.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `ImportError: cannot import name 'reprocess_day'`.

- [ ] **Step 3: Implement `reprocess_day`**

In `tarzaniq/pipeline.py`, extend the datetime import:

```python
from datetime import datetime, date
```

Add at the end of the file (after `recompute_day`):

```python
# ------------------------------------------------------------------ reprocess

def reprocess_day(con, day_id, engine, cfg, progress=None):
    """Re-run the FULL face pipeline from the archived JXLs for one day.

    Unlike recompute_day (imageless, keeps identities), this re-decodes the
    archive and re-detects faces, so it produces fresh subject ids. Returns
    (stats, new_day_id); None if the day is missing. Raises FileNotFoundError
    if the day has no archive/manifest."""
    drow = db.day_row(con, day_id)
    if not drow:
        return None
    folder_name = Path(drow["source_folder"]).name if drow["source_folder"] \
        else f"{drow['date']}.{drow['place']}.{drow['employee']}"
    man = archive.read_manifest(folder_name)
    if not man:
        raise FileNotFoundError(
            f"No archive/manifest for day {day_id} ({folder_name})")

    day = date.fromisoformat(drow["date"])
    scan = []
    for jxl_path, entry in archive.iter_archived(folder_name):
        tt = datetime.strptime(entry["exif_time"], "%H:%M:%S.%f").time()
        scan.append({"path": jxl_path, "filename": entry["original_filename"],
                     "t": datetime.combine(day, tt), "seq": entry["seq"],
                     "src": entry.get("exif_source", "exif")})
    scan.sort(key=lambda r: (r["t"], r["filename"]))
    deletions = naming.detect_deletions([(r["filename"], r["t"]) for r in scan])

    tracker = SubjectTracker(cfg["face_match_threshold"])
    engager = Engager(config.engagement_params(cfg))
    photo_records = []
    n = len(scan)
    for idx, rec in enumerate(scan):
        try:
            img = archive.decode_jxl(rec["path"])
        except Exception:
            img = None
        observations = engine.analyze(img, {"filename": rec["filename"]}) \
            if img is not None else []
        sids = []
        for obs in observations:
            if obs.accepted:
                sid = tracker.assign(obs)
                if sid is not None and sid not in sids:
                    sids.append(sid)
        live = engager.step(idx, rec["t"], sids)
        flags = [] if img is not None else ["decode_failed"]
        if rec["src"] in ("mtime", "none"):
            flags.append("no_exif_time")
        detail = {"faces": [{
            "box": list(obs.box), "score": round(obs.score, 3),
            "blur": round(obs.blur, 1), "frac": round(obs.frac, 4),
            "sid": obs.sid, "reject": obs.reject_reason}
            for obs in observations], "exif_src": rec["src"]}
        photo_records.append({
            "filename": rec["filename"], "seq": rec["seq"], "t": rec["t"],
            "kind": live["kind"], "n_focus": len(sids),
            "n_rejected": sum(1 for o in observations if not o.accepted),
            "subjects": sids, "flags": flags, "detail": detail})
        if progress:
            progress(idx + 1, n)

    eng_final = engager.finalize()
    subj_meta = tracker.finalize()
    day_info = {"date": drow["date"], "place": drow["place"],
                "employee": drow["employee"], "weekday": drow["weekday"]}
    old_stats = json.loads(drow["stats_json"])
    stats = compute_day_stats(photo_records, eng_final, subj_meta, deletions,
                              day_info, old_stats.get("skipped_files", 0), 0)
    rec_out = build_day_record(
        drow["date"], drow["weekday"], drow["place"], drow["employee"],
        drow["source_folder"], drow["money_cash"], drow["money_card"], stats,
        config.engagement_params(cfg), photo_records, eng_final, subj_meta)
    new_id = db.commit_day(con, rec_out)
    try:
        export_day(rec_out, config.exports_dir() / f"{folder_name}.xlsx")
    except Exception:
        pass
    return stats, new_id
```

- [ ] **Step 4: Run the new test and the full suite**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN` (reprocess reproduces the ingest counts with MockEngine).

Run: `.venv/bin/python tests/test_e2e.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/pipeline.py tests/test_archive.py
git commit -m "feat(pipeline): reprocess_day — full pipeline from the JXL archive

Decode a day's archived JXLs in manifest order, re-run detection ->
identity -> demographics -> engagement, re-derive deletions, recompute
stats, and commit_day (full replace -> new day id). Reuses the date from
the day record (never the EXIF date). Deterministic under MockEngine
(reproduces ingest); the real engine may drift (lossy JXL + greedy
clustering), which Feature B will formalize.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: queue the reprocess job on the worker

**Files:**
- Modify: `tarzaniq/pipeline.py` (`Job.__init__`; `AppState.enqueue_reprocess`; `_run_job` dispatch; `_run_reprocess`)
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `reprocess_day`.
- Produces: `Job(folder, kind="ingest", day_id=None)` with `self.kind`/`self.day_id`; `AppState.enqueue_reprocess(day_ids) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before final print/exit):

```python
# ---- reprocess runs as a queued worker job ----
con = db.connect()
ana = [d for d in db.all_days(con) if d["employee"] == "Ana"][0]
con.close()
queued = st.enqueue_reprocess([ana["id"]])
check("enqueue_reprocess accepted", len(queued) == 1)
rj = _wait_done(queued[0]["id"])
check("reprocess job done", rj.status == "done", rj.message)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `AttributeError: 'AppState' object has no attribute 'enqueue_reprocess'`.

- [ ] **Step 3: Add `kind`/`day_id` to `Job`**

In `Job.__init__`, change the signature and add two fields:

```python
    def __init__(self, folder, kind="ingest", day_id=None):
        self.id = uuid.uuid4().hex[:10]
        self.folder = Path(folder)
        self.name = self.folder.name
        self.kind = kind            # "ingest" | "reprocess"
        self.day_id = day_id        # set for reprocess jobs
```

In `Job.brief()`, add `"kind": self.kind` to the returned dict (so the frontend can tell job types apart):

```python
        return {"id": self.id, "folder": str(self.folder), "name": self.name,
                "kind": self.kind,
                "status": self.status, "message": self.message,
```

- [ ] **Step 4: Add `enqueue_reprocess` and dispatch**

Add this method to `AppState` (after `enqueue`):

```python
    def enqueue_reprocess(self, day_ids):
        added = []
        con = db.connect()
        try:
            for did in day_ids:
                drow = db.day_row(con, did)
                if not drow:
                    continue
                folder_name = Path(drow["source_folder"]).name \
                    if drow["source_folder"] \
                    else f"{drow['date']}.{drow['place']}.{drow['employee']}"
                j = Job(folder_name, kind="reprocess", day_id=did)
                j.date, j.place, j.employee = \
                    drow["date"], drow["place"], drow["employee"]
                self.jobs.append(j)
                self.q.put(j)
                added.append(j.brief())
        finally:
            con.close()
        self.broadcast("queue", self.queue_brief())
        return added
```

In `_run_job`, dispatch on `kind`. Replace the `self._run_job_inner(job, con, cfg)` call inside the `try:` with:

```python
        try:
            if job.kind == "reprocess":
                self._run_reprocess(job, con, cfg)
            else:
                self._run_job_inner(job, con, cfg)
        finally:
```

Add the `_run_reprocess` method (after `_run_job`):

```python
    def _run_reprocess(self, job, con, cfg):
        job.status = "processing"
        self.broadcast("queue", self.queue_brief())

        def prog(i, n):
            job.progress, job.total = i, n
            if i % 25 == 0 or i == n:
                self.broadcast("status", {"job": job.brief()})

        try:
            result = reprocess_day(con, job.day_id, self.engine(), cfg, progress=prog)
        except FileNotFoundError as e:
            job.status, job.message = "error", str(e)
            return
        if result is None:
            job.status, job.message = "error", "Day not found"
            return
        stats, new_id = result
        job.result_day_id = new_id
        job.status = "done"
        job.message = "Reprocessed from archive"
        self.broadcast("committed", {"job": job.brief(),
                                     "stats": _summary_card(stats)})
```

- [ ] **Step 5: Run the new test and full suite**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

Run: `.venv/bin/python tests/test_e2e.py` and `.venv/bin/python tests/test_server.py`
Expected: PASS (Job.brief now includes `kind`; server route smokes unaffected).

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/pipeline.py tests/test_archive.py
git commit -m "feat(pipeline): run reprocess as a queued worker job

Job gains kind/day_id; AppState.enqueue_reprocess queues reprocess jobs
that ride the existing worker/queue/SSE machinery; _run_job dispatches on
kind and _run_reprocess streams progress + a committed event. Job.brief()
now reports kind so the dashboard can label job types.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `POST /api/reprocess` route

**Files:**
- Modify: `tarzaniq/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `state.enqueue_reprocess`, `db.all_days`.
- Produces: `POST /api/reprocess` — body `{day_id?}`; enqueues reprocess for that day (or all days) and returns `{ok, queued, jobs}`.

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, find where the Flask test client issues route smokes (search for `/api/recompute` or `client.post`). Add, alongside the other route smokes:

```python
r = client.post("/api/reprocess", json={"day_id": 999999})
check("reprocess route ok", r.status_code == 200 and r.get_json()["ok"] is True)
```

(If `test_server.py` builds the app with `create(engine_factory=lambda: MockEngine({}))`, this enqueues a reprocess for a non-existent day, which `enqueue_reprocess` simply skips — `queued` will be 0 and `ok` True. That's the smoke we want.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_server.py`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the route**

In `tarzaniq/server.py`, after `api_recompute` (~line 345), add:

```python
@app.route("/api/reprocess", methods=["POST"])
def api_reprocess():
    data = request.get_json(force=True, silent=True) or {}
    con = db.connect()
    try:
        if data.get("day_id"):
            ids = [int(data["day_id"])]
        else:
            ids = [d["id"] for d in db.all_days(con)]
    finally:
        con.close()
    added = state.enqueue_reprocess(ids)
    return jsonify({"ok": True, "queued": len(added), "jobs": added})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python tests/test_server.py`
Expected: PASS — `reprocess route ok`.

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/server.py tests/test_server.py
git commit -m "feat(server): POST /api/reprocess to queue archive reprocessing

Enqueues a reprocess job for one day (day_id) or all days, distinct from
the synchronous /api/recompute. Returns the queued job briefs.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: "Reprocess from archive" button on the day page

**Files:**
- Modify: `tarzaniq/static/js/pages.js` (the day-detail renderer), `tarzaniq/static/js/util.js` (if an API helper is needed)
- Test: `tests/dom_smoke.mjs` (keep green; optional new assertion)

**Interfaces:**
- Consumes: `POST /api/reprocess`.
- Produces: a button in the day view that triggers reprocessing.

- [ ] **Step 1: Locate the existing Recompute control**

Run: `grep -n "recompute" tarzaniq/static/js/pages.js`
Read the surrounding day-detail action block (it renders the Excel / Recompute / Delete buttons). The Reprocess button mirrors that exact pattern.

- [ ] **Step 2: Add the button + handler**

In the day-detail action area of `pages.js`, next to the existing Recompute button, add a Reprocess button. Mirror the existing button's markup/class. Wire its click to:

```javascript
// reprocess this day from the permanent photo archive (Feature A)
await API.post('/api/reprocess', { day_id: dayId });
toast('Reprocessing from archive…');   // use the existing toast/notify helper
```

Use the same `API`/`fetch` wrapper and day-id variable the surrounding renderer already uses (read the file to match exact names — e.g. `API.post`, `dayId`/`id`). If no `API.post` helper exists in `util.js`, add one mirroring the existing GET helper:

```javascript
API.post = (path, body) =>
  fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
               body: JSON.stringify(body || {})}).then(r => r.json());
```

- [ ] **Step 3: Run the DOM smoke test**

```bash
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/seed_demo.py
TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/run_demo_server.py --port 43991 &
SRV=$!; sleep 1
node tests/dom_smoke.mjs http://127.0.0.1:43991; kill $SRV
```

Expected: PASS — `ALL GREEN` (the new button must not break existing page rendering or assertions).

- [ ] **Step 4: Commit**

```bash
git add tarzaniq/static/js/pages.js tarzaniq/static/js/util.js
git commit -m "feat(ui): 'Reprocess from archive' button on the day page

Mirrors the existing Recompute control; POSTs /api/reprocess for the day so
its numbers can be rebuilt from the JXL archive.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: ops + docs (uninstall safety, privacy wording, requirements)

**Files:**
- Modify: `uninstall.sh`, `README.md`

**Interfaces:** none (docs/ops only).

- [ ] **Step 1: Make uninstall.sh print the preserved archive**

Run: `grep -n "TarzanIQ Data\|keep\|preserv\|rm -rf" uninstall.sh` and read the "what is kept" message block. Add a line that tells the user the archive dir is also preserved (uninstall only removes the app dir, never the archive). Example addition near where it prints the data-dir-is-kept message:

```bash
echo "Your photo archive (default: ~/Documents/TarzanIQ Archive, or \$TARZANIQ_ARCHIVE) is also kept."
```

- [ ] **Step 2: Update the README privacy wording**

In `README.md` Part 1 "Where things live", update the privacy bullet so it is accurate now that a compressed archive is kept. Replace the "photos are never copied and faces are never stored" sentence with:

```markdown
- **Privacy:** by default TarzanIQ keeps a small compressed copy (~150 KB JPEG XL)
  of every processed photo in a separate archive folder (default
  `~/Documents/TarzanIQ Archive`, configurable, can be an external drive) so the
  analysis can be re-run as the app improves. Face fingerprints still live only in
  RAM while processing; person identities reset every day. Turn archiving off in
  Settings if you don't want the copies.
```

In Part 2 "Status & roadmap", move Feature A from "in progress" to shipped wording once merged (optional — can be done in the PR).

- [ ] **Step 3: Run the full suite (nothing should change)**

Run: `./run_tests.sh`
Expected: `== all suites green ==`.

- [ ] **Step 4: Commit**

```bash
git add uninstall.sh README.md
git commit -m "docs(archive): uninstall preserves the archive + privacy wording

uninstall.sh now states the photo archive is kept (it lives outside the app
dir). README privacy note updated: TarzanIQ keeps a ~150 KB JXL per photo by
default (configurable/off in Settings).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the entire suite from a clean state:

```bash
./run_tests.sh && .venv/bin/python tests/test_archive.py
```

Expected: every suite `ALL GREEN` / `== all suites green ==`.

- [ ] Open a PR `feat/jxl-archive-2026-06-24` → `main`, summarizing the two stages (archive-on-ingest, reprocess) and linking the spec.

---

## Self-Review

**Spec coverage:** archive on ingest (Task 4) ✓; manifest with provenance — original filename/seq/time-of-day/sha256 (Tasks 3,4) ✓; configurable archive dir + `TARZANIQ_ARCHIVE` (Task 2) ✓; `archive_target_kb`/`long_edge`/`quality` config (Task 2) ✓; reprocess tier reusing build_day_record/commit_day (Task 5) ✓; queued + SSE (Task 6) ✓; `/api/reprocess` distinct from recompute (Task 7) ✓; Settings/dashboard control (Task 8) ✓; uninstall preserves archive + privacy copy (Task 9) ✓; keep-on-delete (no change to `api_day_delete` — delete never touches the archive, satisfied by construction) ✓; tests for roundtrip + reprocess + sequence preservation (Tasks 1,3,4,5) ✓. No DB migration (non-goal) ✓.

**Placeholder scan:** all code steps contain full code; the only "read the file then mirror" instruction is Task 8 (frontend), which points at a concrete existing control (`grep recompute`) and supplies the exact handler code.

**Type consistency:** `encode_jxl(bgr, long_edge, quality)`, `decode_jxl(path)`, `sha256_bytes(data)`, `day_archive_dir(folder_name)`, `write_manifest(folder_name, header, entries)`, `read_manifest`, `iter_archived` used identically in Tasks 1/3/4/5. `reprocess_day(con, day_id, engine, cfg, progress=None) -> (stats, new_id)|None` consistent across Tasks 5/6/7. `Job(folder, kind, day_id)` consistent across Tasks 6/7.
