<!-- Generated review artifact: a code-grounded architecture map + Feature A/B
     integration plan, produced from a parallel read of every module. Companion
     to docs/HANDOFF.md. Update as the codebase evolves. -->
> **Status (2026-06-25):** Features A, B, and C are now implemented and merged — this document is the original pre-implementation planning record; see README.md / CLAUDE.md for current truth.

# TarzanIQ — Architecture Review & Feature A/B Integration Plan

## 1. What TarzanIQ is

TarzanIQ is a local-only macOS Flask app (localhost-bound, 127.0.0.1:43117) that ingests a day's folder of street-photography JPEGs per employee and derives — from the photos alone — how each photographer performed: candid "cold shoots," posed re-approach "warm shoots," and the headline metric **conversion = warm_persons / cold_persons**. It runs an OpenCV face pipeline (YuNet detect → SFace identity → GoogleNet age/gender), persists only derived stats per day, and renders an 8-bit jungle-themed vanilla-JS SPA. **Current state:** v1.0.0 "Silverback", DB schema v1, stats_version 2, CONFIG_VERSION 1; full test suite green; privacy contract today is "no embeddings, no crops, no pixels stored — derived stats only." Both Feature A (JXL archive) and Feature B (comparability fingerprint) are greenfield — no archive, manifest, fingerprint, sha256, reprocess tier, or migration ladder exists yet.

## 2. Architecture & data flow (one day's photos)

```
Finder right-click / Add Day
  └─ server.py: POST /api/enqueue ──────────────────────► pipeline.AppState.enqueue(folders)
       parses folder "YY.MM.DD.Place.Name" via naming.parse_folder_name → Job objects on queue.Queue
  └─ pipeline.AppState._worker (single daemon thread) ──► _run_job → _run_job_inner(job, con, cfg)
       Phase 1 (scan, no decode):
         per file → exifutil.read_time_of_day (header-only, time-of-day; date discarded)
                  → naming.filename_seq (prefix, int)
                  → exifutil.combine(folder_date, tod, subsec) → sortable datetime
         chronological sort by (t, filename); naming.detect_deletions (Sony 9999→0001 wrap)
       Phase 2 (heavy decode loop, ~lines 282-339):
         per photo → cv2.imread (IMREAD_REDUCED_COLOR_2 if decode_reduced)
                   → engine.FaceEngine.analyze(bgr, meta) → [FaceObs] (embedding RAM-only)
                   → engine.SubjectTracker.assign(obs)  (greedy cosine clustering, threshold 0.36)
                   → engagements.Engager.step(i, t, subjects)  (live cold/warm/mixed/air label)
                   → build per-photo detail/photo_records
                   → optional engine.annotate_preview → SSE 'frame' broadcast
         finalize: Engager.finalize() + SubjectTracker.finalize()
                 → stats.compute_day_stats(...) → flat stats dict (stats_version=2, conversion)
         prompts (ask/answer, blocks worker): money, commit
  └─ pipeline.build_day_record(...) → day_record dict (stamps app_version)
  └─ db.commit_day(con, day_record) ──► SQLite at config.db_path() (deletes+reinserts by
       UNIQUE(date,place,employee); bulk-inserts photos/subjects/engagements; registers name/place)
  └─ excelio.export_day(day_record, out_path) ──► styled .xlsx in exports/, Meta sheet =
       full day_record as MAX_CELL-chunked JSON (rebuildable via import_day)

READ TIER (instant, no images):
  server.py data routes open fresh db.connect() per request → agg.*
    agg._stats(day) = json.loads(day['stats_json'])  ← single chokepoint, all rollups funnel here
    agg.overview / employee_detail / places / patterns / day_detail (day_detail alone also reads
      db.day_engagements + day_subjects + day-metadata columns)
  → frontend pages.js (pageOverview/pageApe/pageCompare/pagePlaces/pagePatterns/pageDay/pageSettings)
  → live.js EventSource('/api/process/stream') for SSE (hello/frame/status/queue/prompt/committed/job_done)

RECOMPUTE (imageless re-derivation, threshold changes):
  server.py POST /api/recompute → pipeline.recompute_day(con, day_id, params)
    reads db.day_photos + day_subjects → engagements.analyze() + stats.compute_day_stats()
    → db.replace_day_analysis (rewrites stats/params, updates only photo.kind, replaces
      subjects/engagements; KEEPS photo rows + money) → re-export Excel
```

## 3. Module-by-module map

- **`__init__.py`** — package constants: `APP_NAME`, `APP_VERSION="1.0.0"`, `APP_CODENAME="Silverback"`, `DEFAULT_PORT=43117`. Canonical home for the new `MODEL_VERSION`/`ALGO_VERSION` fingerprint constants alongside `APP_VERSION`.
- **`config.py`** — all tunables + on-disk layout. `DEFAULTS` (single source of every editable key), `CONFIG_VERSION=1`, `data_dir()`/`db_path()`/`exports_dir()`/`models_dir()`/`config_path()`, `load_config()`/`save_config()` (both strictly filter to DEFAULTS keys), `engagement_params(cfg)` (9-key per-day snapshot: 5 timing + 4 face thresholds).
- **`naming.py`** — folder/filename parsing. `JPEG_EXTS`, `parse_folder_name`→(date,place,employee) (raises `FolderNameError`), `filename_seq`→(prefix,int), `detect_deletions`→{suspected_deletions,gaps,prefixes} with Sony 9999→0001 wrap + >800 card-reset guard.
- **`exifutil.py`** — time-of-day only (date deliberately discarded). `read_time_of_day(path)`→(time, subsec, source) header-only via PIL with mtime/none fallback; `combine(day, tod, subsec)`→datetime.
- **`engagements.py`** — the engagement brain (pixel-blind; consumes subject IDs). `Engager(params)` with `.step()` (live labels = final labels invariant), `.live_counts()`, `.finalize()`; `analyze(photos, params)` batch wrapper. Reusable verbatim by both Feature B paths.
- **`stats.py`** — sole engagement→stats derivation, pure (no I/O). `compute_day_stats(...)`→flat dict tagged `stats_version=2` (conversion, shoot/span/break math, hunt/close/hold metrics, hourly buckets, demographic Counters); `fmt_dur`/`fmt_pct` (imported by excelio).
- **`engine.py`** — stateless CV/inference. `MODEL_FILES` (yunet/sface/age/gender), `FaceEngine(models_dir,cfg)` + `.analyze(bgr,meta)`→[FaceObs] (embeddings RAM-only, discarded), `MockEngine` (identical signature, manifest-driven, the CI seam), `SubjectTracker(match_threshold=0.36)` greedy same-day clustering, `annotate_preview`, `subject_color`.
- **`pipeline.py`** — orchestration + app state. `AppState(engine_factory)` (queue, single worker thread, SSE fan-out, ask/answer prompts, pause Event, `reload_config`), `Job`, `_run_job_inner` (two-phase ingest), `build_day_record`, `recompute_day` (imageless path).
- **`db.py`** — SQLite source of truth in `data_dir()`. `SCHEMA_VERSION=1`, `_SCHEMA` (meta/days/photos/subjects/engagements/names/places), `connect()` (CREATE IF NOT EXISTS only — **no migration ladder**), `commit_day` (delete+reinsert by natural key), `replace_day_analysis` (in-place, keeps photos+money), read accessors `day_row/all_days/day_photos/day_subjects/day_engagements`, registry `rename_employee`/`rename_place`, `backup_if_due`.
- **`excelio.py`** — portable archive/disaster-recovery. `export_day` (themed workbook + Meta sheet = chunked `json.dumps(day_record, default=str)`, stamps app_version), `import_day` (rebuilds full day_record from Meta).
- **`agg.py`** — pure read tier, reads **only** stats_json + scalar columns ("years render instantly, no photo re-scans"). `overview/employee_detail/places/patterns/day_detail`, `employee_summaries`, `day_axes`/`RADAR_AXES`, `_stats` (the chokepoint), `_patterns_for`. Accesses fixed stats keys with `[]` indexing (not `.get()`).
- **`server.py`** — Flask HTTP boundary, single module-global `AppState`. Process routes (enqueue/state/pause/cancel/prompt/stream-SSE/pickfolder), data routes (overview/employee/places/patterns/day GET+DELETE/days/export/import), settings routes (`/api/settings`, `/api/registry`, rename, `/api/recompute`).
- **Frontend** (`static/`) — dependency-free vanilla-JS SPA, strict load order `util.js→charts.js→live.js→pages.js→app.js`, globals on `window`, hash-routed via `app.js:ROUTES`. `util.js` (API client, el(), fmt, PIX pixel icons, Sfx), `charts.js` (Chart.js jungle theme, killCharts on every route), `live.js` (`Live.connect()` EventSource, 250-frame ring buffer, `renderModal` prompt switchboard keyed on `p.type`), `pages.js` (8 page renderers, `SETTING_DEFS` drives settings form), `jungle.css` (8-bit theme, status→CSS-class coupling).
- **Ops** — `install.sh` (canonical dir contract duplicated from config.py: `DATA=${TARZANIQ_DATA:-~/Documents/TarzanIQ Data}`, pre-creates models/logs/exports/backups, `fetch_model` sha256+size-verifies 4 ONNX, emits launch.sh HERE-doc, builds droplet + Quick Action, hardcodes PORT=43117), `uninstall.sh` (rm APPDIR + droplets, **preserves DATA**), `gen_assets.py` (pre-committed pixel art, NOT run by install), `requirements.txt` (opencv/numpy/flask/openpyxl/pillow), `README.md` (privacy "faces never stored" prose).

## 4. Feature A — JXL archive integration plan

**Goal:** during ingest, after decoding each JPEG, also encode a ~150 KB `.jxl` to a configurable archive dir separate from the DB data dir, with a per-day manifest (original filename, sequence int, EXIF capture time, sha256). New `reprocess` job tier decodes archived JXLs and re-runs the FULL pipeline.

**config.py:**
- Add to `DEFAULTS`: `archive_dir` (path string), `archive_target_kb` (default 150), plus any JXL distance/long-edge tuning keys. **Critical: keys not in DEFAULTS are silently dropped by both `load_config` (lines 78-79) and `save_config` (line 87)** — if you skip this they never persist or load.
- Add a new `archive_dir()` resolver modeled on `data_dir()` but configurable and **separate** from the DB root (honor a new `TARZANIQ_ARCHIVE` env var paralleling `TARZANIQ_DATA`). Do **not** add the archive to `data_dir()`'s hardcoded subdir list (exports/models/logs/backups) — the spec wants it separate and possibly on an external drive.
- `load_config` silently swallows corrupt JSON → defaults; an archive-path that fails to load would silently fall back, sending JXLs to the wrong place. Consider erroring loudly for path-critical keys.

**pipeline.py:**
- `_run_job_inner` Phase 2 decode loop (~282-339): after `cv2.imread`, encode the decoded BGR → ~150 KB JXL, write to `<archive>/<folder>/<origname>.jxl`, compute sha256 of original JPEG bytes (new work — not computed anywhere today), append a manifest entry. **Reuse existing `rec['filename']`, `rec['seq']`, `rec['t']` from Phase 1** — these are exactly the manifest's filename / sequence-integer / EXIF-capture-time fields, and sourcing them here preserves the deletion-detection sequence. **Decode-source decision:** `decode_reduced` (IMREAD_REDUCED_COLOR_2) halves resolution; if you archive the reduced frame, reprocess inputs differ from a full-res decode — decide whether to archive full-res or the reduced frame (spec recommends a fixed ~1600px long edge, larger than the half-res pipeline). **Honor the existing `run_flag.wait()` pause + cancel check (lines 283-286) before the JXL encode** so encoding doesn't run on a cancelled/paused job, and beware slowing the hot loop.
- `build_day_record` (~406-447): carry archive-presence info / manifest reference so `commit_day` can persist Feature B's archive-presence flags.
- **New `reprocess(con, day_id)` function** — sibling to `recompute_day`, NOT a variant of it. It must decode archived JXLs and re-run the full `FaceEngine.analyze → SubjectTracker.assign → demographics → Engager.step` body (i.e. the Phase 2 inference path, run over archived images instead of the source folder), then **re-run `naming.detect_deletions` from the manifest** (recompute reuses stored deletion values; reprocess can/should re-derive them). Reprocess produces NEW photo/subject/engagement rows, so it likely needs `commit_day`-style replacement, NOT `replace_day_analysis` (which only mutates `photo.kind` and keeps existing photo rows). **The cv2.imread → decoded BGR contract means `FaceEngine.analyze` needs no signature change** — just feed it JXL-decoded frames.
- `AppState._worker`/`_run_job`/`Job.status`: add a worker-dispatch branch for the `reprocess` tier distinct from normal ingest and recompute. The single-threaded worker with blocking prompts means a long reprocess will block normal ingest — dispatch/concurrency may need rethinking (see Open Questions).
- **Chronological-order invariant:** reprocess MUST feed archived photos in the same `(t, filename)` sort order as ingest (pipeline.py:265) or Engager live/final labels and conversion diverge.

**db.py:**
- `_SCHEMA` photos table already persists filename+seq (lines 39-51); add per-photo archive columns (jxl path, sha256) and/or a new manifest table.
- `commit_day` (~194-211): persist the manifest fields alongside the existing photos bulk-insert. **`commit_day` deletes any existing day by UNIQUE(date,place,employee) before reinsert (lines 191-193)** — on reprocess this must be transactional with the manifest write and **must NOT delete the JXL files on disk**.
- `day_photos`/`day_subjects`: reprocess needs to locate archived JXLs per day — read from the new manifest/columns.

**excelio.py:** Meta sheet (lines 281-287) serializes the whole day_record via `json.dumps(..., default=str)`, so new archive fields flow through automatically; the human Photos sheet (lines 200-215) may want an archived/jxl column. `import_day` must reconcile archive-presence flags (imported days may have no local archive).

**server.py:** Add a `/api/reprocess` endpoint distinct from `/api/recompute` (the prompt explicitly distinguishes the two) that enqueues image-based reprocess jobs via `state` rather than calling `recompute_day`. `api_settings` (POST) is the only config-write path — the new `archive_dir`/`archive_target_kb` keys must be added to `DEFAULTS` or this handler silently drops them (it `pass`es on unknown keys). `api_day_delete` (DELETE) currently only calls `db.delete_day` with no archive awareness — deletion semantics for the permanent archive must be decided. `agg.day_detail`'s hardcoded field whitelist must be extended to surface archive presence/manifest info.

**Provenance requirements (non-negotiable):** manifest stores **original filename** (`DSC09998.JPG`→`DSC09998.jxl`, never renumbered) so `detect_deletions`' prefix-grouping + Sony wrap arithmetic still applies; **sequence integer from `naming.filename_seq`** (the exact function ingest uses); **EXIF time-of-day semantics from `exifutil`** (store time-of-day, NOT raw EXIF datetime — camera date is wrong by design; reprocess re-supplies the folder date); **sha256** of original bytes for dedupe/integrity/SD-card re-ingest detection.

**Reuse for the reprocess tier:** `engine.FaceEngine.analyze` (no change), `engine.SubjectTracker` (no change), `engagements.Engager`/`analyze` (no change), `stats.compute_day_stats` (the convergence point, same signature as ingest), and the Phase 2 loop body of `_run_job_inner`. **New:** archive write, manifest, sha256, JXL codec, the `reprocess` dispatch.

## 5. Feature B — comparability / fingerprint integration plan

**Goal:** stamp every committed day with `processing_fingerprint = config_version + model_version + algo_version`. Schema v1→v2 adds it + archive-presence flags to `days`. Stale days (fingerprint ≠ current) auto-brought-current via a background queue: cheap path (recompute, imageless) for engagement-only changes, expensive path (reprocess from archive) for model/detection changes. UI guarantee: live dataset always at ONE current fingerprint.

**Fingerprint components — define new constants (none exist today; only `CONFIG_VERSION`):**
- `config_version` — hash of all output-affecting params. **Use `engagement_params(cfg)` carefully: it returns BOTH 5 timing AND 4 face-filter thresholds, but `Engager` only consumes the 5 timing ones.** A change to the 4 face thresholds (min_face_frac/min_face_blur/det_score_threshold/face_match_threshold) is NOT an engagement-math change — it requires the expensive **reprocess** path, not cheap recompute. The path-routing classifier must partition params by which stage consumes them.
- `model_version` — derive from `engine.MODEL_FILES` set/versions (the model swap is what forces reprocess). Put it near `MODEL_FILES`; keep in sync with the install.sh sha256/size pins.
- `algo_version` — bump whenever `engagements.Engager.step()`/`finalize()` classification logic OR `stats.compute_day_stats` shape/meaning changes (stored days computed under old logic become stale). `stats_version=2` is a sibling concept the fingerprint generalizes — do not conflate. Home these constants in `__init__.py` alongside `APP_VERSION` as the canonical "current" values.

**Schema v1→v2 migration (db.py) — no migration ladder exists:** `connect()` (lines 93-105) only runs `CREATE TABLE IF NOT EXISTS` and seeds `meta.schema_version`. **Adding columns to `_SCHEMA` will NOT migrate existing v1 DBs.** Implement explicit migration in `connect()` gated on `meta.schema_version`: bump `SCHEMA_VERSION` 1→2, `ALTER TABLE days ADD COLUMN processing_fingerprint` (+ component columns + archive-presence flags), then write the new version to meta. Test fresh-DB boot (test_server relies on it) AND v1-upgrade. Bump/test backup_if_due restore against v2.

**Stamping:**
- `pipeline.build_day_record` — compute and embed the fingerprint so `commit_day` persists it on the days row.
- `db.commit_day` INSERT INTO days (lines 194-202) — write `processing_fingerprint` + archive flags on every committed day.
- `db.replace_day_analysis` (UPDATE days, line 293) — **the cheap bring-current path writes here and MUST also update `processing_fingerprint` to current** (today it only sets stats_json/params_json). **If recompute_day is reused as the cheap path without re-stamping the fingerprint, stale days stay flagged stale forever → infinite re-queue.** This is the easiest-to-miss bug in the whole feature.
- `excelio.export_day` should stamp the fingerprint in the Meta sheet; `import_day`-ed days arrive with a (possibly stale) fingerprint and must be enqueued for bring-current after `db.commit_day` (server.py import flow).

**Staleness detection + routing:**
- `db.all_days` needs a stale-day query (`WHERE processing_fingerprint != current`) to feed the background queue.
- `server.py api_settings` (POST, which calls `state.reload_config`) is the natural trigger: on config change, recompute the current fingerprint and enqueue stale days — cheap recompute if only engagement-timing params changed, else reprocess. `pipeline.AppState.reload_config` (rebuilds engine) is where a model/algo version change is detectable.
- **Routing rule:** engagement-timing-only delta → cheap `recompute_day` (imageless, the majority of tweaks); face-threshold OR model OR algo delta → expensive `reprocess` from archive.

**Background queue + SSE reuse:** the bring-current queue rides the **existing `AppState` worker/queue/SSE machinery** — enqueue cheap-path recompute jobs vs expensive-path reprocess jobs through the same worker. Progress arrives via existing `queue`/`committed`/`job_done` SSE events; `live.js` `queueChips()`/`updateNavDot()`/`renderQueue` and the `Job.status` enum + the cancellable/busy status lists (live.js:78, 145) + jungle.css status classes (lines 263-268) must learn the new job state(s) or chips render unstyled/non-cancellable. **`api_recompute` swallows all per-day exceptions (`except Exception: pass`)** — as the cheap bring-current path this silently loses failures; the caller can't tell which days remain stale. Fix the error reporting.

**UI guarantee (spec leans toward option 1 — keep everything at one fingerprint):** `agg` does **zero** fingerprint filtering today; every aggregator funnels through `_stats` and assumes uniform comparability. If the background queue ever leaves mixed-fingerprint rows live, every aggregate (conversion, percentiles, leaderboard) **silently mixes incomparable numbers with no error** — the danger is silent wrong stats, not a crash. Either trust by-construction (option 1) or filter/flag stale days at the `db.all_days` callsites inside `overview`/`employee_summaries`/`places`/`patterns`/`day_detail` (option 2, transient badging). `pages.js:pageOverview` is where a "N days updating… 4 left" banner attaches; `pages.js:pageDay` footer (already shows source_folder/committed_at/app_version) is where the per-day fingerprint + archive flags + bring-current action surface; `pages.js:pageSettings` save copy ("Old days keep their numbers until you recompute") becomes wrong under auto-bring-current and must change.

**Reuse:** `recompute_day` IS the cheap path (just add fingerprint re-stamping); the new `reprocess` (Feature A) IS the expensive path; the existing `/api/recompute` button and Settings "recompute all" map to the cheap path; the worker/queue/SSE bus is reused wholesale. **New:** fingerprint constants, the migration, staleness query, the routing classifier, the auto-enqueue trigger, the UI comparability surfacing.

## 6. Invariants & regression risks to protect

- **Engagement spec (13 tests in test_engagements.py):** cold = new in-focus face clearing min_face_frac/min_face_blur; 7 rapid frames = 1 cold; warm = same subject ≥ `warm_gap_s` (5s) after candid; > `max_pitch_minutes` (10min) = fresh re-approach not warm; conversion = warm_persons/cold_persons; groups tracked solo vs group; breaks ≥ `break_minutes` (20). Changing thresholds is fine (config); changing the **rules** must keep tests meaningful and **bump `algo_version`** in lockstep.
- **`Engager.step()` == `analyze()` equivalence** (`test_incremental_matches_batch`) — live labels must equal final labels. Any engagement-logic change must update BOTH the streaming and batch paths in lockstep or this breaks; `algo_version` is meaningless otherwise.
- **Sony 9999→0001 wrap** (naming.py:76-89): `diff %10000`, extra `-1` on wrap (0000 unused), `>800` jump = card reset (not counted). Clean wrap is NOT a deletion. Feature A archiving must store **original filenames** so this exact arithmetic still applies; renaming archived files silently corrupts `suspected_deletions` (test_e2e pins deletions=3; test_server pins wrap behavior).
- **Folder-date vs EXIF-time:** date comes from the folder name via `parse_folder_name`; only time-of-day from EXIF; clock drift NOT flagged. `test_e2e.make_jpg` writes a deliberately WRONG EXIF date (2020:01:05) to prove folder date wins. Feature A's manifest must store EXIF **time-of-day** semantics, NOT raw EXIF datetime as capture date; reprocess must re-supply the folder date (the archived JXL alone cannot recover the correct day).
- **MockEngine testability:** `AppState(engine_factory=...)` and `server.create(engine_factory=...)` let the whole app + DOM smoke run model-free (the real FaceEngine.analyze / ONNX / alignCrop / embedding-clustering path is NEVER exercised by tests — only `mock_sid`). Preserve this; the reprocess tier must accept MockEngine too.
- **Reprocess is NOT bit-identical to ingest** — two stacked reasons the "every number comparable by construction" guarantee must explicitly accept: (1) `SubjectTracker.assign` is greedy/order-dependent and embeddings are discarded, so reprocess produces FRESH clusterings with DIFFERENT subject ids than the original run (recompute_day's "identities can't change" guarantee does NOT hold for reprocess); (2) ~150 KB JXL re-encode is lossy, so detection/blur/embedding/demographics drift vs the original JPEG even at an identical fingerprint. Treat reprocessed days as "current by construction," accepting drift.
- **`agg` reads ONLY stats_json + scalar columns** ("years render instantly"). Keep all image/heavy work in the pipeline/worker; never leak reprocess work into the read tier. Aggregators index fixed stats keys with `[]` (not `.get()`) — any stats_json shape change breaks every rollup with KeyError; keep additions backward-tolerant.
- **`replace_day_analysis` vs `commit_day` semantics:** recompute/cheap-path → `replace_day_analysis` (keeps photo rows + money, must NOT touch archive manifest, MUST update fingerprint). Reprocess that re-detects faces → new rows → `commit_day` semantics. Pick the right path per tier.
- **Privacy contract reversal:** `db.py`/`engine.py`/`__init__.py` docstrings + README + `pages.js:703` ("photos are never stored") + pageDay delete copy ("Excel stays on disk") all promise no pixels stored. Feature A reverses this deliberately (separate configurable archive dir outside `data_dir`). Reconcile docs/UI copy — do not silently violate.
- **DON'T-REBUILD list (all green, §4 of handoff):** the entire engagement engine, stats math, FaceEngine/SubjectTracker, db schema/commit/recompute, excelio roundtrip, agg rollups, server routes, the whole SPA + jungle theme, install/uninstall/assets. Build A then B **on top**; keep the existing suite green throughout.
- **Frontend invariants:** strict script load order util→charts→live→pages→app; all globals bare top-level (no module system); `killCharts()` runs every route (new charts MUST go through `mkChart()` or leak); `Live.refresh()` only re-renders on hash `/live` or `''`; `renderModal` keys on `p.type` with a raw-JSON fallback (new prompt types must be added or they fall through); frames ring buffer hard-capped at 250, base64 JPEG (NOT the archived JXL).
- **Path contract is duplicated, not shared:** install.sh hardcodes DATA, PORT=43117, 4 model URLs/sha256/sizes, folder format — all re-derived independently in Python. A configurable archive dir means TWO sources of truth (shell `TARZANIQ_ARCHIVE` + Python `archive_dir()`) kept in lockstep, like `TARZANIQ_DATA` already is. `fetch_model` sha256/size pins must move with any `model_version` bump AND `engine.MODEL_FILES` together.
- **`uninstall.sh` `rm -rf APPDIR` spares DATA by hand** — the new permanent archive dir MUST be explicitly added to the KEPT set (lines 6-7, 21-22) and printed, or uninstall silently destroys it, violating Feature A's "permanent archive" promise and breaking Feature B's expensive path after reinstall.
- **`rename_employee` does raw string REPLACE on stats_json** (db.py:157-159) — fragile JSON surgery; new stats_json fields containing the employee value could corrupt it.

## 7. Test strategy

**Green now (no pytest harness — each test is a standalone script with its own check()/fails/`sys.exit`; CI invokes each by name; seed_demo MUST run before dom_smoke):**
- `test_engagements.py` — 13 spec cases (cold/warm/mixed/air, group conversion, reapproach, session/pose splitting, breaks, hunting) + the load-bearing batch-vs-incremental equivalence.
- `test_e2e.py` — full ingest via MockEngine, deliberately-wrong EXIF date, the entire prompt state machine, stats assertions, Excel export→import roundtrip, duplicate-replace, name add/typo-map, and recompute (lines 213-224: warm_gap_s=60 drops warm_persons 3→1 while cold_persons stays 5, persisted via replace_day_analysis) + agg smoke. The single most important contract for BOTH features.
- `test_server.py` — Flask route smokes (ping/state/overview/settings GET+POST coercion/enqueue/registry/patterns/places, chart.umd.js served) + naming unit tests (parse_folder_name, detect_deletions incl. Sony wrap + multi-prefix, filename_seq) + fresh-DB boot.
- `dom_smoke.mjs` — real SPA in jsdom against a live MockEngine server on the `seed_demo.py` 30-day DB; renders every page + all 5 prompt modals; asserts leaderboard[0]==Marko, days>=25, >2 .tlblock.

**Untested ground (greenfield for A/B):** real FaceEngine/ONNX/alignCrop/embedding path (never tested — mock only); db migration/schema versioning (none exists); compute_day_stats edge cases (empty day, no cold events, dry_spell/hot_streak/hourly boundaries); backup_if_due; rename_employee stats_json REPLACE; excelio MAX_CELL boundary + live formula cells; SSE/pause/cancel; archive/manifest/sha256/JXL/reprocess/fingerprint (do not exist).

**New tests the build order calls for:**
1. **JXL roundtrip** (verify arm64 wheel on his Mac first): encode → decode-to-ndarray → re-run MockEngine detection; assert manifest integrity (origname, sequence preserved, EXIF time, sha256) and that sequence still drives `detect_deletions`.
2. **Schema v1→v2 migration:** seed a v1 DB, run `connect()`, assert columns added + data intact + `meta.schema_version` bumped; assert fresh-DB boot still works (test_server depends on it); backup/restore across v2.
3. **`reprocess` tier:** MockEngine over a seeded archive → asserts full pipeline re-runs, deletion scan re-derived, and (honestly) that subject ids may differ from original ingest — anchor the determinism risk.
4. **Comparability loop:** change a param → days marked stale → cheap recompute brings them current → fingerprints match (and confirm no infinite re-queue — i.e. fingerprint actually re-stamped in `replace_day_analysis`). Add a face-threshold-change case that routes to reprocess, not recompute.
5. **Extend existing tests:** test_e2e to assert JXL files + manifest are written on ingest and to assert fingerprint stamping/refresh after recompute; seed_demo to set the current fingerprint on synthesized days (else dom_smoke's "one current fingerprint" guarantee breaks).

**Test scaffolding gap:** `seed_demo.py` synthesizes days entirely imageless (no decode/engine/EXIF/sha256), so it **cannot exercise the JXL archive or reprocess** — Feature A needs a NEW image-producing fixture. Changing seed_demo's record shape for fingerprint/archive flags can shift the counts/ordering dom_smoke asserts (rng seed 7, Marko #1, days>=25) — adjust carefully.

## 8. Open questions / ambiguities to resolve before building

1. **`archive_target_kb` default — 150 vs 300-500.** Owner's stated choice is 150 KB; spec flags that 150 KB is plenty for the current half-res face pipeline but **bounds future visual features** (finer identity, expression, sharpness) and changing it later does NOT upgrade already-archived photos (lossy + permanent). Implement 150 as default + configurable, but confirm whether he wants to start higher given the archive is the whole point.
2. **JXL codec & arm64 verification.** `pillow-jxl-plugin` vs `imagecodecs` (libjxl) vs shelled-out `cjxl` fallback. **Must verify an arm64 wheel actually installs and round-trips on his M-series Mac — unverifiable in-sandbox.** Decode performance gates the expensive reprocess path. Add the chosen dep to requirements.txt AND possibly install.sh provisioning.
3. **Archive decode source: full-res ~1600px vs the half-res (`decode_reduced` / IMREAD_REDUCED_COLOR_2) frame.** Archiving the reduced frame makes reprocess inputs differ from a full-res decode and caps future features; archiving ~1600px costs bytes. Pick one and document it.
4. **Archive path location & default.** Spec wants a configurable path separate from `data_dir`, ideally an external drive given hundreds of GB/year. Decide the default (a sibling `archive/` under data root? a prompt at first run?) and the env var name (`TARZANIQ_ARCHIVE`).
5. **Fingerprint hashing details.** Exactly which params hash into `config_version` (and is the 9-key `engagement_params` the right input, given 4 of those keys are face-stage not engagement-stage?); how `model_version` is derived (MODEL_FILES names + sha256?); the string format of the composite fingerprint; partitioning logic for cheap-vs-expensive routing.
6. **UI mixed-version policy (transient).** Option 1 (always one fingerprint, simplest, matches "don't want to worry") vs option 2 (badge + exclude stale days during a big reprocess, then auto-rejoin). Spec leans option 1; confirm, since a 200-day reprocess can be 30+ hours and the app can't freeze.
7. **Worker concurrency.** The single daemon worker with blocking synchronous prompts means a long background reprocess blocks normal prompt-driven ingest. Decide: separate worker/queue for bring-current jobs, priority/preemption, or accept serialization with clear UX.
8. **Deletion semantics with a permanent archive.** When a day is deleted via the UI (`DELETE /api/day/<id>`), are the archived JXLs + manifest also removed or retained? This affects the "permanent archive" promise and whether reprocess of a deleted-then-re-ingested SD card is possible (sha256 dedupe). Surface to owner.
9. **Privacy/retention/consent language.** Feature A now stores images of employees AND the public; README "faces are never stored" and in-app copy must be rewritten. Owner handles the legal/retention/consent decision (not us) — but the copy can't ship factually wrong.
10. **Reprocess non-determinism acceptance.** Confirm the owner accepts that reprocess yields fresh (different) subject ids and slightly different counts than the original ingest (greedy clustering + lossy JXL), so "comparable by construction" means "all at one fingerprint," not "bit-identical to the first run."
