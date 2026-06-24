# Feature A — Permanent JXL Photo Archive — Design Spec

- **Date:** 2026-06-24
- **Status:** Approved (design); pending spec review
- **Branch:** `feat/jxl-archive-2026-06-24`
- **Companion docs:** [HANDOFF.md](../../HANDOFF.md) §7.1, [ARCHITECTURE-REVIEW.md](../../ARCHITECTURE-REVIEW.md) §4

## 1. Goal

Stop discarding the photos. During ingest, in addition to the derived stats, save a
heavily-compressed **JPEG XL (`.jxl`)** copy of every photo to a permanent, configurable
archive, plus a per-day `manifest.json`. Add a new **`reprocess`** job tier that re-runs the
*full* face pipeline from that archive — so as models/logic improve we can re-derive history
from the pixels, not just re-run the engagement math on stored rows (`recompute`).

This is the substrate Feature B (universal comparability) builds on. **Feature A is purely
additive and schema-free** — no DB migration here (that is deliberately Feature B's step).

## 2. Decisions locked in

| Decision | Choice | Why |
|---|---|---|
| Codec | `pillow-jxl-plugin` (Pillow JXL plugin) | Verified: installs arm64 wheel on the target Mac; encode ~130–190 ms, decode ~15–20 ms/photo; decoded array feeds straight into the cv2/FaceEngine path. |
| Archive resolution | ~**1600 px** long edge (downscale, never upscale) | Owner chose "moderate": plenty for face work + future visual features, still small. |
| Target size | ~**150 KB**/photo, configurable | Owner's stated choice; calibrate `archive_quality` to land near it on real photos (no per-photo binary search). |
| Delete behavior | **Keep the archive** | Dashboard "Delete day" removes stats only; archived JXLs are never destroyed by a click. Manual deletion only. |
| Archive tracking | Per-day **`manifest.json` on disk**, not the DB | Portable, human-readable, survives DB loss; keeps Feature A schema-free. DB archive-presence flags arrive with Feature B's v2 migration. |
| Archive location | `~/Documents/TarzanIQ Archive/` default; `TARZANIQ_ARCHIVE` env override; `archive_dir` config | Separate from the data dir so it can live on an external drive (it dwarfs everything else). |
| Decode source for the 1600 px copy | Reuse the half-res frame the pipeline already decodes, then downscale | Avoids a second full-res decode of the 10 MB JPEG → fast ingest. Matches "moderate" (a 2nd full-res decode is what "maximum" would have needed). |

## 3. Non-goals (explicitly deferred to Feature B)

- No DB schema migration (`schema_version` stays 1).
- No `processing_fingerprint`, staleness tracking, or auto-bring-current queue.
- No change to the synchronous `/api/recompute` path.
- `reprocess` is **manually triggered** in Feature A (a button / route); Feature B wires it into
  the automatic comparability queue.

## 4. Architecture

### 4.1 New module: `tarzaniq/archive.py` (isolated, unit-testable)

Owns the codec + filesystem layout so `pipeline.py` stays orchestration-only.

```
encode_jxl(bgr, long_edge=1600, quality=80) -> bytes
    # downscale (area interp) so max(h,w) <= long_edge (never upscale), RGB, JXL-encode in memory.
sha256_bytes(data: bytes) -> str
day_archive_dir(folder_name: str) -> Path        # <archive_dir>/<folder_name>/
manifest_path(folder_name: str) -> Path
write_manifest(folder_name, header: dict, entries: list[dict]) -> None   # atomic (tmp+rename)
read_manifest(folder_name) -> dict | None
iter_archived(folder_name) -> Iterator[(jxl_path: Path, entry: dict)]    # in seq/time order, for reprocess
```

### 4.2 `config.py` additions

New keys in `DEFAULTS` (keys absent from `DEFAULTS` are silently dropped by `load_config`/
`save_config`/`api_settings` — so they MUST be added here):

| Key | Default | Notes |
|---|---|---|
| `archive_enabled` | `True` | Master on/off for archiving on ingest. |
| `archive_dir` | `""` | Empty → use `archive_dir()` resolver default. |
| `archive_long_edge` | `1600` | Max long edge of the stored copy. |
| `archive_target_kb` | `150` | Intent/documentation; we calibrate `archive_quality` to it. |
| `archive_quality` | `80` (calibrate on real photos) | JXL quality used at ingest. |

New path resolver `archive_dir()` modeled on `data_dir()` but **separate**: precedence
`config['archive_dir']` → `$TARZANIQ_ARCHIVE` → `~/Documents/TarzanIQ Archive`. NOT added to
`data_dir()`'s subdir list.

### 4.3 Ingest integration (`pipeline.py` Phase 2 decode loop)

Today the loop `cv2.imread`s each file (and the original is read once). Change to:

1. `data = path.read_bytes()` — **single** read.
2. `sha = archive.sha256_bytes(data)`.
3. `bgr = cv2.imdecode(np.frombuffer(data, uint8), flag)` with the same `IMREAD_REDUCED_COLOR_2`
   flag the pipeline uses today (preserves current detection behavior exactly).
4. (existing) `FaceEngine.analyze` → `SubjectTracker.assign` → `Engager.step` → per-photo record.
5. **If `archive_enabled`** and not cancelled/paused (reuse the existing `run_flag.wait()` +
   cancel check that already guards the loop body): `jxl = archive.encode_jxl(bgr,
   archive_long_edge, archive_quality)`; write to `day_archive_dir(folder)/<origname>.jxl`;
   append a manifest entry `{original_filename, seq, exif_time, exif_source, sha256, jxl_filename,
   jxl_bytes}`.
6. After the loop, on success: `archive.write_manifest(folder, header, entries)` (atomic).

Notes:
- **Original filenames are preserved** (`DSC09998.JPG` → `DSC09998.jxl`) — deletion detection
  (`naming.detect_deletions`, Sony 9999→0001 wrap) depends on the filename sequence; renaming
  would silently corrupt it.
- `exif_time` stores **time-of-day** semantics (from `exifutil`), NOT a capture date — the date
  always comes from the folder name. Reprocess re-supplies the folder date.
- Cancelled mid-day: orphan JXLs with no manifest. Harmless; a re-ingest overwrites. (No cleanup
  in v1; documented.)
- The original 10 MB JPEGs are **not** copied — the JXL is the retained copy.

### 4.4 Reprocess tier (`pipeline.py` + `server.py`)

A new **queued** job that reuses the existing worker thread / `queue.Queue` / SSE fan-out, so it
streams progress like ingest (and is pause/cancel-able).

- `Job` gains a `kind` ("ingest" | "reprocess"); `AppState._worker`/`_run_job` dispatch on it.
- `reprocess_day(con, day_id)`: load `day_row` → derive folder name from `source_folder` →
  `archive.read_manifest(folder)`; if absent, fail loudly ("no archive for this day"). For each
  archived photo in seq/time order: decode JXL → BGR → the **same** Phase-2 inference body
  (`FaceEngine.analyze → SubjectTracker.assign → demographics → Engager.step`) → re-run
  `naming.detect_deletions` from manifest seqs → `stats.compute_day_stats` →
  `build_day_record` → `db.commit_day` (replace by `UNIQUE(date,place,employee)`; **does not
  touch the JXL files**) → re-export Excel.
- **Reuses verbatim:** `FaceEngine`/`MockEngine` (no signature change — they take a BGR array),
  `SubjectTracker`, `engagements`, `stats`, `build_day_record`, `commit_day`.
- New route `POST /api/reprocess` (enqueues a reprocess job for a `day_id`, or all days). The SSE
  events (`queue`/`committed`/`job_done`) and the frontend queue chips learn the new job kind.
- Must feed photos in the same `(t, filename)` sort order as ingest, or labels/conversion diverge.

## 5. Manifest format (example)

```json
{
  "folder": "26.05.18.CityPark.Marko",
  "date": "2026-05-18", "place": "CityPark", "employee": "Marko",
  "archive_long_edge": 1600, "archive_target_kb": 150, "archive_quality": 80,
  "app_version": "1.0.0", "count": 1873, "archived_at": "2026-05-18T09:14:02",
  "photos": [
    {"original_filename": "DSC09998.JPG", "seq": 9998, "exif_time": "14:03:11",
     "exif_source": "exif", "sha256": "…", "jxl_filename": "DSC09998.jxl", "jxl_bytes": 152314}
  ]
}
```

## 6. Privacy / docs / ops changes

- **README + in-app copy:** the "faces are never stored" claim becomes false; reword to describe
  the compressed archive. (Owner uses the app locally with subject permission and considers the
  exact wording non-critical — so: accurate but light, no legal language.)
- **`uninstall.sh`:** add the archive dir to the explicitly-preserved set (today it only spares the
  data dir) and print it, or uninstall would silently destroy a "permanent" archive.
- **`install.sh`:** `pillow-jxl-plugin` installs via `requirements.txt`; optionally pre-create the
  default archive dir. Keep the `TARZANIQ_DATA`/`TARZANIQ_ARCHIVE` contract in lockstep with
  Python (two sources of truth, like `TARZANIQ_DATA` already is).
- **`requirements.txt`:** add `pillow-jxl-plugin`.

## 7. Accepted tradeoffs

- Ingest is ~3–4 min slower per 2000-photo day (sequential encode). Acceptable for v1.
- The 1600 px copy is downscaled from the half-res working frame (slightly softer than a
  full-res→1600 px decode); accepted as the "moderate" tier in exchange for fast ingest.
- 150 KB JXL is lossy + permanent; raising the target later does not upgrade already-archived days.
- Reprocess is not bit-identical to the original run (greedy clustering + lossy re-encode → maybe
  different subject IDs / slightly different counts). Expected; formalized by Feature B.

## 8. Testing plan

Keep the whole existing suite green (`test_engagements`, `test_server`, `test_e2e`, `dom_smoke`).
New tests:
- **`tests/test_archive.py`** (new): `encode_jxl` downscales + round-trips to an ndarray;
  `sha256_bytes` stable; `write_manifest`/`read_manifest` roundtrip; encoding a synthetic image
  then decoding and running `MockEngine` detection works; **original filename + seq preserved** so
  `detect_deletions` still works off the manifest.
- **Reprocess test** (in test_archive or test_e2e): seed a small archive (synthetic images +
  manifest), run `reprocess_day` with `MockEngine`, assert the full pipeline re-runs and a day is
  committed; assert honestly that subject IDs may differ from the original ingest.
- **Extend `test_e2e`**: assert JXL files + `manifest.json` are written on ingest with the right
  count and preserved sequence.

## 9. Build / commit plan (two stages, one branch → one PR)

**Stage 1 — archive on ingest:** `archive.py`; `config.py` keys + `archive_dir()`;
`requirements.txt`; wire into the ingest loop; `test_archive.py`; extend `test_e2e`; README/privacy
wording; `uninstall.sh`/`install.sh`. Suite green.

**Stage 2 — reprocess tier:** `Job.kind` + worker dispatch; `reprocess_day`; `/api/reprocess`;
frontend queue-chip/SSE awareness + a minimal Settings "Reprocess this day" control; reprocess
test. Suite green.

Each stage is a focused commit set; the branch merges to `main` via PR.

## 10. Feature B hooks (out of scope, noted for continuity)

The schema v1→v2 migration will add `processing_fingerprint` + archive-presence flags to `days`;
the cheap path (`replace_day_analysis`) must then also re-stamp the fingerprint or stale days
re-queue forever; `reprocess_day` becomes the comparability queue's "expensive path."
