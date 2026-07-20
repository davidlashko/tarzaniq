# CLAUDE.md — TarzanIQ

Enduring spec for TarzanIQ. The full hand-off (history, decisions, and the current
feature brief) lives in [docs/HANDOFF.md](docs/HANDOFF.md) — read it before starting feature work.

## Working style
Dense, action-oriented, honest (say so when something won't work). No preamble.
**Never add "produced by / built with" attributions, footers, or branding to any
app output, exports, or UI.** (Git commit `Co-Authored-By` trailers are fine — that's
repo metadata, not product output.)

The product owner building this is referred to as **"Tbone"**.

## 1. The product
TarzanIQ is a **local-only macOS app** (Apple Silicon, limited RAM) for a street-photography
rental crew. Photographers roam a city taking **candid** photos of passers-by ("cold
shoots"), then approach the subject to pitch a **posed** shoot ("warm shoots") — the sale.
TarzanIQ ingests a day's photo folder per employee and works out, **from the photos alone**,
how each photographer performed: who they approached, who converted, when, where, against whom.
The point is **comparison and coaching**, surfaced in a friendly **8-bit jungle** dashboard
with an ape logo. Name is fixed: **TarzanIQ**.

Folder convention: `YY.MM.DD.Place.Name`. **Date comes from the folder name; only the
time comes from EXIF** (rental cameras have unreliable clocks — do NOT flag clock drift).

### Locked-in decisions
- **Conversion = warm_persons / cold_persons** is the honest revenue proxy and the headline
  metric everywhere. Per-shoot money can't be trusted (employees steal cash), so daily lump
  cash/card is informational only.
- **No race.** Keep **age + gender**, coarse and aggregate only.
- ~2000 JPEGs/employee/day, ~10 MB each, up to 5 employees/day, processed **sequentially**.
  JPEG only, no RAW.
- **Configurable** thresholds; **daily lump money** (skippable).
- **Core mined data lives in a separate folder** so reinstalling/upgrading never loses data.
- Not used in Brazil or the EU.

## 2. Domain logic — the engagement spec (must not regress)
Encoded in `tarzaniq/engagements.py`, locked by `tests/test_engagements.py` (13 spec tests).
Thresholds are config; the *rules* must keep the tests meaningful.
- **Cold shoot** = a new, in-focus face not seen today; must clear `min_face_frac` (size)
  and `min_face_blur` (sharpness). **7 rapid frames of one subject = 1 cold shoot.**
- **Warm shoot** = same subject reappearing **≥ `warm_gap_s` (5 s)** after their candid.
  Reappearing **later than `max_pitch_minutes` (10 min)** = a fresh re-approach (new cold).
- **Groups:** 2 faces in one frame = 2 cold marks; partial conversion is tracked.
- **Breaks:** gap **≥ `break_minutes` (20)** is a break, subtracted from "/hour" denominators;
  each break interval is stored.
- **Deletion detection** via filename sequence gaps (`tarzaniq/naming.py`, `detect_deletions`).
  **Sony wraps 9999 → 0001 (skipping 0000) — a clean wrap is NOT a deletion.** A jump > ~800
  is flagged suspicious, not counted as exact deletions.

Config defaults (`tarzaniq/config.py`): `warm_gap_s=5`, `break_minutes=20`, `max_pitch_minutes=10`,
`warm_session_gap_minutes=10`, `pose_gap_s=8`, `min_face_frac=0.055`, `min_face_blur=40`,
`det_score_threshold=0.78`, `face_match_threshold=0.36`, `preview_max_width=760`.

## 3. Architecture
- **Backend:** Python + **Flask**, bound to **127.0.0.1:43117 only** (nothing leaves the laptop).
  Vanilla-JS SPA frontend, no build step, Chart.js bundled.
- **Inference (OpenCV only):** YuNet face detection, SFace identity (cosine 0.36), age + gender
  GoogleNet ONNX. Models downloaded by `install.sh` with SHA-256 verification (~83 MB, never
  committed). **Models can't run without real photos** — the **MockEngine** path keeps the app
  and DOM smoke test runnable model-free. Keep that property.
- **Privacy:** compressed photo copies (~150 KB JXL) are archived to a separate configurable dir
  (default `~/Documents/TarzanIQ Archive`); face embeddings stay in RAM only; the data dir holds
  only derived stats; identity resets per day. Archiving is configurable and can be disabled.
- **Data dir** (`~/Documents/TarzanIQ Data/`, override `TARZANIQ_DATA`): `tarzaniq.db`, `exports/`
  (one styled `.xlsx`/day), `models/`, `logs/`, `backups/`. **Survives reinstalls — never write
  app code there, never commit it.**
- **DB is source of truth** (`tarzaniq/db.py`, schema v2; `processing_fingerprint`, `fp_components`,
  `has_archive` columns added in v1→v2 migration). Each Excel export also embeds the full
  day (chunked JSON in a Meta sheet) so the dataset rebuilds from exports if the DB is lost.
- **Pipeline** (`tarzaniq/pipeline.py`): job queue + worker thread, **SSE** to the dashboard,
  ask/answer prompts, pause flag, `caffeinate` during processing. Decodes at half-res.

## 4. Module map (do not rebuild — all green per hand-off)
`__init__.py` (v1.0.0 "Silverback", port 43117; `MODEL_VERSION`/`ALGO_VERSION` for fingerprinting) ·
`config.py` · `naming.py` · `exifutil.py` · `engagements.py` · `stats.py` (per-break intervals;
stats_version 2) · `engine.py` (`FaceEngine`/`MockEngine`/`SubjectTracker`/`annotate_preview`) ·
`db.py` (schema v2, `days UNIQUE(date,place,employee)` + `processing_fingerprint`/`fp_components`/
`has_archive`, cascade deletes, weekly backup, rename/replace, v1→v2 migration) ·
`excelio.py` (export + `import_day`) · `pipeline.py` (`Job`, `AppState`, prompts, `commit_day`,
`recompute_day`, `reprocess_day`, `bring_current`, `build_day_record`) ·
`archive.py` (JXL encode + per-day manifest; called by pipeline during ingest) ·
`fingerprint.py` (compute/compare `processing_fingerprint` from config + model + algo versions) ·
`significance.py` (two-proportion z-test + Wilson CIs for conversion comparisons) ·
`agg.py` (overview/leaderboard/detail/patterns/places) ·
`server.py` (`create(engine_factory=…)` + routes, `main()`).
Frontend: `static/js/{app,util,charts,live,pages}.js`, `static/css/jungle.css`, bundled pixel fonts.

## 5. Running & testing
```bash
# One-time setup (opencv/numpy wheels need CPython 3.11–3.12, NOT 3.14):
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
npm install                                  # jsdom, for the DOM smoke test

# Run the whole suite (3 Python suites + DOM smoke), one command:
./run_tests.sh

# Or individually:
.venv/bin/python tests/test_engagements.py   # 13 engagement-spec tests (pure Python)
.venv/bin/python tests/test_server.py        # naming edge cases + route smokes
.venv/bin/python tests/test_e2e.py           # 43 checks, synthetic day (needs piexif)

# DOM smoke = real SPA in jsdom vs a live MockEngine server on a seeded DB:
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/seed_demo.py
TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/run_demo_server.py --port 43991 &
node tests/dom_smoke.mjs http://127.0.0.1:43991
```
`requirements.txt` is the app's runtime deps; `requirements-dev.txt` adds test-only deps
(`piexif`). `tests/run_demo_server.py` boots the app with the **MockEngine** so the whole app
runs and every page renders **without** the ONNX models — this is what makes the frontend
testable. Keep that property.

## 6. Completed features (shipped)
All three features are implemented and merged. See `docs/` for original design docs (historical).
- **Feature A — permanent JXL photo archive:** each JPEG encoded to ~150 KB `.jxl` in a
  configurable archive dir during ingest; per-day manifest (filename, sequence, EXIF time, sha256).
  `reprocess` job tier re-runs the full pipeline from the archive.
- **Feature B — universal comparability:** schema v1→v2 migration; `processing_fingerprint` per
  day; `bring_current` auto-routes stale days to `recompute` or `reprocess` as needed.
- **Feature C — statistical significance:** two-proportion z-test + Wilson CIs on the Compare page
  (`significance.py`); exposed via `GET /api/compare/<a>/<b>`.

## 7. Conventions
- **Commits:** Conventional Commits (`feat(scope):`, `fix(scope):`, `chore:`, `docs:`),
  dense bodies explaining the *why* + verification. End with
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Branches:** `type/slug-YYYY-MM-DD`; feature work via PR to `main`; scaffolding direct to main.
- **Keep the whole test suite green** (`test_engagements`, `test_e2e`, `test_server`, `dom_smoke`)
  throughout every change.
- This repo is **private** (flipped from public 2026-06-28) — still never commit
  photos, data, DBs, exports, or models.
