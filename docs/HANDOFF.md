> **Status (2026-06-25):** Features A, B, and C are now implemented and merged — this document is the original pre-implementation planning record; see README.md / CLAUDE.md for current truth.

# TarzanIQ — Claude Code Hand-off

## How to use this document

This is the full context for continuing **TarzanIQ** in VS Code with Claude Code. The existing codebase is in the repo (unzip `TarzanIQ.zip` if it isn't already). Read this top to bottom once, then start on **§7 (the two new features)** — that's the actual work. Everything before it is so you don't rebuild or break what already exists and passes tests.

Suggestion: keep **§1–§5** as a `CLAUDE.md` in the repo root (enduring spec Claude Code auto-loads), and treat **§6–§9** as the working brief for this round.

The owner (call him by name in commits if you like; the business owner he's building this for is **"Tbone"**) prefers dense, action-oriented work, honest assessment including when something won't work, and no preamble. Don't add "produced for / built by" attributions, footers, or branding to any output.

---

## 1. The product

Tbone runs a street-photography rental crew. Photographers rent cameras, roam a city, and take **candid** photos of passers-by ("cold shoots"). They then approach the subject and pitch a **posed** shoot on the spot ("warm shoots"), which is the sale. TarzanIQ is a **local macOS app** (Apple Silicon, M-series MacBook Air, limited RAM — battery is fine, he plugs in) that ingests a day's photo folder per employee and works out, **from the photos alone**, how each photographer performed: how many people they approached, how many converted, when, where, and against whom.

The whole point is **comparison and coaching** — who's best, who needs work, which spots and hours convert, surfaced in a dashboard that's friendly, clever, sometimes cute, in an **8-bit jungle theme** with an ape logo. Name is fixed: **TarzanIQ**.

### Original feature brief (owner's words, lightly edited)

The owner's original spec described: a per-day photo folder named `YY.MM.DD.Place.Name`, run by right-clicking it in Finder; error on bad folder format; prompt for unseen names/places. Facial recognition assigns **per-day** subject IDs (reset every day — no cross-day identity). Age and sex inferred. **Auto-export an Excel file per day**, named like the folder. **Date comes from the folder name; only the time comes from EXIF** (rental cameras frequently have the wrong date). Live viewer with overlays, spacebar pause, arrow navigation. Prompt for the day's lump cash/card money (skippable) and a commit Y/N. Comparisons vs the employee's own history and vs the team average. Warm-shoots-per-hour by day-of-week and hour. Demographic breakdowns and conversion by demographic. Mined data must **survive a reinstall**.

### Decisions the owner locked in (his words, condensed)

- **Date from folder name, time from EXIF.** Do **not** flag clock drift.
- **Money can't be attributed per shoot** — employees steal a lot, so daily cash/card totals are unreliable and per-shoot revenue is impossible. **The honest revenue proxy is the cold→warm conversion ratio.** This is the headline metric, everywhere.
- **Nix race entirely.** Keep **age and gender** (coarse, aggregate).
- ~**2000 JPEGs per employee per day, ~10 MB each, up to 5 employees/day**, processed **sequentially** (folder-by-folder, so employee count barely matters to the design). JPEG only, no RAW.
- Each employee keeps one camera body per day (may switch, but the folder tag makes that irrelevant).
- **Configurable** break + warm-shoot thresholds. **Daily lump money.**
- **Core mined data lives in a separate folder** so uninstalling/upgrading the app never loses data.
- Not used in Brazil or the EU (relaxes the biometric-law posture, but see §7.1 — the new photo archive changes the privacy story regardless).
- Runs on **M-series MacBook Air with limited RAM**. User-friendly above all. **8-bit jungle graphics.**

---

## 2. Domain logic — the engagement spec (must not regress)

These rules are encoded in `tarzaniq/engagements.py` and locked by `tests/test_engagements.py` (13 spec tests). Changing thresholds is fine (they're config); changing the *rules* must keep the tests meaningful.

- **Cold shoot** = a new, in-focus face that hasn't been seen today. A face counts as a subject only if it clears `min_face_frac` (size) and `min_face_blur` (sharpness) — this filters background passers-by.
- **7 rapid frames of one subject = 1 cold shoot** (not seven).
- **Warm shoot** = the same subject reappearing **≥ `warm_gap_s` (default 5 s)** after their candid. If they reappear **later than `max_pitch_minutes` (default 10 min)**, it's a fresh **re-approach** (a new cold shoot), not a warm one.
- **Conversion = warm_persons / cold_persons.** Headline metric.
- **Groups:** 2 people in one cold frame = 2 cold marks; if both pose, that's 2 warm. Partial conversion (one of two) is fine and tracked (solo vs group conversion).
- **Breaks:** a gap of **≥ `break_minutes` (default 20)** between photos = a break; subtracted from "/hour" denominators. Stats store each break's start/end interval (for the day timeline).
- **Deletion detection** via filename sequence gaps. **Sony wraps 9999 → 0001 (skipping 0000)** — a clean wrap is **not** a deletion. A jump > ~800 is flagged as suspicious, not counted as exact deletions. (`tarzaniq/naming.py`, `detect_deletions`.)
- **Derived also:** hunting time (gap between marks), pitch time (candid → first warm frame), pose estimate per warm shoot, hot streak, dry spell, hourly buckets, place- and demographic-level rollups.

**Config defaults** (`tarzaniq/config.py`): `warm_gap_s=5`, `break_minutes=20`, `max_pitch_minutes=10`, `warm_session_gap_minutes=10`, `pose_gap_s=8`, `min_face_frac=0.055`, `min_face_blur=40`, `det_score_threshold=0.78`, `face_match_threshold=0.36`, `preview_max_width=760`, plus `preview_enabled`, `decode_reduced`, `sounds_enabled` bools.

---

## 3. Architecture as built

- **Backend:** Python + **Flask**, bound to **127.0.0.1:43117 only** (nothing leaves the laptop). Vanilla-JS SPA frontend (no build step) with Chart.js bundled.
- **Inference (OpenCV only):** YuNet face detection, SFace identity (cosine threshold 0.36), age + gender GoogleNet ONNX (Levi-Hassner age buckets; gender treated as unknown below 0.58 confidence). Models are downloaded by `install.sh` onto the Mac (see §8) — **they cannot run in a sandbox without real photos**, so the image pipeline is the one untestable-in-container part.
- **Privacy model as originally built:** face embeddings live in RAM only during processing; **only derived stats are persisted**; identity resets per day. ⚠️ **§7.1 changes this** — we will now also persist compressed photos.
- **Data directory** (`~/Documents/TarzanIQ Data/`, override `TARZANIQ_DATA`): `tarzaniq.db`, `exports/` (one styled `.xlsx` per day, named like the folder), `models/`, `logs/`, `backups/` (weekly, keep 8). Survives reinstalls.
- **DB is source of truth.** Each Excel export also carries the full day inside it (chunked JSON in a Meta sheet, ≤30k chars/cell) so the dataset can be rebuilt from exports if the DB is lost. Per-photo subject rows are stored, which enables **recompute** (re-deriving engagement stats after a threshold change **without images**).
- **Pipeline** (`tarzaniq/pipeline.py`): a job queue + worker thread, **SSE** broadcast to the dashboard, ask/answer prompt protocol, pause flag, `caffeinate` during processing. Decodes JPEGs at `IMREAD_REDUCED_COLOR_2` (half-res) → ~0.25 s/photo → ~8–12 min for 2000.
- **Install** (`install.sh`): venv at `~/Library/Application Support/TarzanIQ`, AppleScript droplet `TarzanIQ.app`, a Finder **Quick Action** ("Analyze with TarzanIQ"), `caffeinate` during runs.

---

## 4. What already exists and passes tests — do not rebuild

**Backend (all green):** `__init__.py` (v1.0.0 "Silverback", port 43117), `config.py`, `naming.py`, `exifutil.py`, `engagements.py`, `stats.py` (now also stores per-break intervals; `stats_version` 2), `engine.py` (`FaceEngine`/`MockEngine`/`SubjectTracker`/`annotate_preview`), `db.py` (schema **v1**: meta / days `UNIQUE(date,place,employee)` / photos / subjects / engagements / names / places, cascade deletes, weekly backup, rename employee/place, replace-day), `excelio.py` (export with live Excel formulas + div-guards, Photos/Subjects/Engagements/Hourly/Meta sheets, jungle styling; `import_day` reads Meta back), `pipeline.py` (`Job`, `AppState`, prompts, `commit_day`, `recompute_day` from stored rows, `build_day_record`), `agg.py` (overview/leaderboard, employee detail with radar axes, patterns heatmap, places matrix, day detail), `server.py` (`create(engine_factory=…)` + all routes; `main()` with `--port`).

**Tests (all green):**
- `tests/test_engagements.py` — 13 engagement-spec tests.
- `tests/test_e2e.py` — 43 checks: synthetic 14-JPEG day with a deliberately wrong EXIF date (proves folder date wins), full prompt flow, stats, Excel roundtrip, duplicate-replace, name add/typo-map, recompute persistence, agg smoke.
- `tests/test_server.py` — naming edge cases (incl. Sony wrap) + route smokes.
- `tests/dom_smoke.mjs` — boots the **real SPA in jsdom** against a live server on a **seeded 30-day demo DB** (`tests/seed_demo.py`), renders every page, asserts the leaderboard ordering matches planted skill levels, exercises all five prompt modals, the live HUD, the vine progress bar, and the timeline. **ALL GREEN.**

**Frontend (syntax-checked + DOM-smoke-rendered):** `static/css/jungle.css` (full 8-bit theme: night/moss/vine/leaf/banana/bark/bone palette, pixel borders, totems, CRT-scanline live frame, climbing-ape vine progress bar, modal, heatmap grid, timeline, banana-rain confetti, reduced-motion + mobile), bundled pixel fonts (VT323 + Press Start 2P, offline), and 5 JS files:
- `util.js` — API helpers, formatters, **canvas pixel-icon factory**, toasts, banana confetti, WebAudio bleeps.
- `charts.js` — Chart.js jungle theming, radar/line/bar/donut builders, CSS-grid heatmap.
- `live.js` — SSE stream, live "field camera" with frame buffer + pause/step (space/◀▶/Esc), vine progress, queue chips, **all five prompt modals** (new_name, new_place, duplicate_day, money, commit).
- `pages.js` — Overview (leaderboard ranked by conversion), Apes list, Ape profile (skills radar vs troop-middle ring + coach note), Compare (head-to-head radar + mirrored bars), Places (ranked + emp×place heat matrix), Patterns (weekday×hour heatmap, demographics, conversion-by-demographic), Day detail (one-vine timeline of cold/warm/break, field notes, money editor, subjects table, Excel/Recompute/Delete), Settings (plain-language thresholds, registry rename, Excel re-import).
- `app.js` — hash router + boot.

Pixel-art assets (`gen_assets.py`): smiling gorilla logo + banana, full icon set, favicon. `install.sh` / `uninstall.sh` / `README.md` / `requirements.txt` exist.

---

## 5. Running it locally (for Claude Code)

```bash
# unit + integration tests
python3 tests/test_engagements.py
python3 tests/test_e2e.py
python3 tests/test_server.py

# DOM smoke needs a live server on a seeded DB:
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo python3 tests/seed_demo.py
# launcher that injects MockEngine (real face models aren't needed to serve pages):
#   server.create(engine_factory=lambda: MockEngine({})); app.run(port=43991)
TARZANIQ_DATA=/tmp/tq_demo python3 path/to/run_demo_server.py &   # MockEngine, port 43991
npm i jsdom            # if needed
node tests/dom_smoke.mjs http://127.0.0.1:43991
```

The MockEngine lets the whole app run and every page render **without** the ONNX models. Keep this property — it's what makes the frontend testable in CI.

---

# 6. The two new features (this round's work)

These two are **deeply linked** — read both before starting. Feature A (keep a photo archive) is precisely what makes Feature B (everything always comparable) achievable. Build A first, then B on top.

> One-line summary of the change: **stop throwing the photos away.** Today only derived numbers are stored. We will keep a permanent, heavily-compressed copy of every photo so we can *reprocess the entire history* whenever the models or logic improve — and use that to guarantee that every number in the app is always directly comparable to every other number.

---

## 7.1 Feature A — permanent JXL photo archive

### Goal (owner's words)
> "Instead of just creating a datastring, I want it to compress the photos into a ~150 KB file in JXL format and keep them in a permanent archive, so that as we add features we can rerun and retrain on all previous files."

**Interpretation to confirm:** each source photo → one **JPEG XL (.jxl)** file targeted at **~150 KB**, stored permanently in a per-day archive. ("a 150 KB file" = per photo, not one file for the whole day — 2000 photos can't share one file.) The archive becomes the substrate the pipeline can re-run against later.

### Why this is the right move
The original design deliberately discarded photos (privacy + space). But "rerun and retrain as we add features" is impossible without the pixels — `recompute` can only re-derive engagement math from already-extracted subject rows; it cannot run a *better face model*, add expression detection, or fix a detection bug on historical days. The archive fixes that, and it's the foundation for Feature B.

### Design
- **Layout:** `…/TarzanIQ Data/archive/<YY.MM.DD.Place.Name>/<original-filename>.jxl` plus a per-day `manifest.json` (or DB rows). The archive should be a **configurable path, separate from the DB data dir** — it will dwarf everything else (see storage math) and the owner may want it on an external drive.
- **Preserve provenance — critical:**
  - **Original filename + sequence integer.** Deletion detection (§2) depends on the filename sequence; if you rename to `0001.jxl`, `0002.jxl` you destroy it. Keep the original name (`DSC09998.JPG` → `DSC09998.jxl`) or store the sequence in the manifest.
  - **EXIF capture time** (time-of-day is load-bearing; date still comes from the folder).
  - A **content hash** (sha256) per photo for dedupe/integrity and to detect re-ingest of the same SD card.
- **Encoding:** prefer a pip route so it stays in the venv — **`pillow-jxl-plugin`** (registers a Pillow JXL plugin) or **`imagecodecs`** (libjxl-backed). Fallback: a `cjxl` binary (`brew install jpeg-xl`, or bundle a static build) shelled out from the pipeline. **You must verify an arm64 wheel installs on his actual Mac — I could not verify this in-sandbox.** Nice perk: macOS 14+ shows `.jxl` natively in Finder/Preview, so the archive is human-viewable.
- **Hitting ~150 KB:** image codecs target *quality/distance*, not bytes, so don't expect exact 150 KB. Recommended: **downscale to a fixed long edge** (e.g. ~1600 px — already more than the half-res pipeline uses) **+ a tuned quality/distance** that lands ≈150 KB, and **make the target a config value** (`archive_target_kb`, default 150). Avoid depending on `cjxl --target_size`/`--target_bpp`; they're historically flaky. An optional one-step size check + single distance nudge is fine; don't build a slow binary-search.
- **Wire it into ingest:** during the existing decode loop in `pipeline.py`, after decoding each JPEG, also encode + write the archived JXL and its manifest entry. The original 10 MB JPEGs are **not** copied — the JXL replaces them as the retained copy.
- **New job tier — reprocess from archive** (distinct from existing `recompute`):
  - `recompute` (exists): re-derive engagement stats from stored subject rows. No images. Fast. For **threshold** changes.
  - **`reprocess` (new):** decode the archived JXLs and re-run the **full** face → identity → demographics → engagement pipeline. Slow (~archive-decode + inference). For **model / detection-logic / new-visual-feature** changes. This is the thing the owner is asking for ("rerun and retrain on all previous files").

### Storage reality — flag this to the owner
- 150 KB × 2000 ≈ **~293 MB per employee-day**; worst case 5 employees ≈ **~1.5 GB/day**; order **hundreds of GB/year** with daily use.
- But that's **~1.5 % of the originals** (10 MB × 2000 ≈ 20 GB/employee-day) — a **~65× reduction**. The real win to tell him: **he can stop hoarding 10 MB originals / wipe SD cards** and still keep a fully retrainable history. Recommend a dedicated/external drive and the configurable archive path.

### Honest tradeoffs to surface (don't bury these)
- JXL re-encoding here is **lossy and permanent** for already-archived days. If he later wishes he'd kept more detail, the old data is stuck at 150 KB.
- **150 KB is plenty for the current half-res face pipeline**, but it **bounds future visual features** (finer identity matching, expression/emotion, sharpness analysis). Since storage is cheap and the archive is the point, it's worth asking whether ~300–500 KB is a better default — but **150 KB is his stated choice; implement it as the default and make it configurable.** Note that changing the target later doesn't upgrade already-archived photos.
- The **privacy story changes**: TarzanIQ now stores images of employees *and* members of the public. The README's "faces are never stored" section must be rewritten, and the owner should decide on retention/consent language. (He's previously worked through model-release/content-rights questions across jurisdictions, so flag it and let him handle the legal side — don't give legal advice.)

---

## 7.2 Feature B — universal comparability

### Goal (owner's words)
> "I want to be able to make every piece of data comparable to every other piece of data. I don't want to have to worry whether or not it's comparable."

### The actual problem
Derived metrics depend on configuration. Tighten `face_match_threshold`, raise `min_face_frac`, or swap in a better model, and **cold/warm counts shift**. A day processed last month under old settings is then **apples-to-oranges** against a day processed today. The owner never wants to be in the position of wondering whether two numbers can be fairly compared.

### The insight that solves it
Because Feature A keeps the **full photo archive**, you can **always reprocess everything to the *current* configuration**. Comparability stops being something to reason about and becomes **true by construction**: keep the whole dataset at one current "processing fingerprint," and reprocess anything stale up to it.

### Design
- **Processing fingerprint** — stamp every committed day with a single string combining:
  - `config_version` — hash of all engagement/detection params that affect output.
  - `model_version` — which ONNX models + versions produced it.
  - `algo_version` — pipeline/code version when outputs change shape or meaning.
  Store it on the `days` row (DB **schema v1 → v2 migration**). This tells the system which days are **stale** vs the current fingerprint.
- **Archive = canonical; derived stats = a cache keyed by fingerprint.** The numbers in the DB are a materialized view of "archive processed under fingerprint X."
- **The invariant the owner wants:** the live dataset is always at **one current fingerprint**. When config/models change:
  - **Engagement-only change** (e.g. `warm_gap_s`, `break_minutes`): use the **cheap path** — `recompute` from stored rows, no images. Covers the *majority* of tweaks. (Already built — just needs to update the fingerprint + clear staleness.)
  - **Model / detection / visual change:** use the **expensive path** — `reprocess` from the JXL archive (Feature A).
  - Either way: mark stale days, **bring them current automatically as a background job queue with visible progress**, so he never manages it by hand.
- **UI guarantee — pick one, lean toward the first:**
  1. **Keep everything at one fingerprint, always.** Simplest mental model, exactly matches "don't want to worry." Comparisons are valid because there's only ever one version live.
  2. If mixed versions exist *transiently* during a big reprocess, **badge stale days and exclude them from comparisons/leaderboards until they catch up** ("12 days updating… 4 left"), then they rejoin automatically.
- Internally you may distinguish **config-invariant** metrics (raw photo counts, timestamps — always comparable) from **config-sensitive** ones, but **the default UX must not ask him to reason about which is which.** Default surface = "everything's current."

### Honest tradeoff to surface
Full `reprocess` of a large back-catalog is **expensive** — 200 archived days could be **30+ hours** of compute. That's exactly why the **two-tier split matters**: most changes are engagement-level and take the cheap, imageless path; only genuine model/visual changes pay the full cost. The archive's small, fast-to-decode JXLs keep even the expensive path as cheap as it can be. Background processing + a clear progress indicator is what delivers "never worry about comparability" without freezing the app for hours. Be upfront with him that "tweak a setting → instantly recompare everything" is instant for engagement thresholds and *background-and-eventual* for model changes.

### What already exists vs what's new (don't rebuild)
- **Exists:** `recompute` (cheap, imageless re-derivation) and the Settings "recompute all days" button.
- **New:** fingerprint stamping + staleness tracking (schema v2), the `reprocess`-from-archive tier (needs Feature A), the background job queue + progress UX, and the comparison guarantee in the UI.

---

## 8. Suggested build order

1. **Verify JXL encode on his Mac.** Confirm `pillow-jxl-plugin` (or `imagecodecs`) installs an arm64 wheel and round-trips a JPEG → ~150 KB JXL → decode-to-ndarray. Pick the fallback (`cjxl`) only if wheels fail. Add to `requirements.txt`.
2. **Archive on ingest.** Extend the `pipeline.py` decode loop to write `<archive>/<folder>/<origname>.jxl` + `manifest.json` (origname, sequence, EXIF time, sha256, target_kb). Add `archive_dir` + `archive_target_kb` to config. **Add a test:** archive roundtrip (encode → decode → re-run detection on a synthetic image via MockEngine; assert manifest integrity + sequence preserved).
3. **Schema v2 migration.** Add `processing_fingerprint` (and components) to `days`; add archive-presence flags. Write the migration so existing v1 DBs upgrade cleanly; bump and test backup/restore.
4. **`reprocess` job tier.** New pipeline path that reads the archive and runs the full inference pipeline; reuse `build_day_record`/`commit_day` via `replace_day_analysis`. Background queue + SSE progress (mirror the existing job/queue/SSE machinery). **Add a test** with MockEngine over a seeded archive.
5. **Comparability layer.** Compute + store the fingerprint on commit; compute staleness vs current; auto-enqueue stale days (cheap path if engagement-only, else reprocess); expose status. Enforce the UI guarantee (§7.2). **Add a test:** change a param → days marked stale → cheap recompute brings them current → fingerprints match.
6. **Settings + dashboard.** Surface `archive_target_kb`, `archive_dir`, archive size/used, and a single **"Bring everything up to date"** control with progress. Keep it plain-language.
7. **README + privacy rewrite.** Update the data-retention/privacy section (photos are now stored, compressed), the storage expectations (~1.5 % of originals, recommend a dedicated drive), and the new reprocess/upgrade flow.
8. **Keep the whole existing suite green** throughout (`test_engagements`, `test_e2e`, `test_server`, `dom_smoke`).

---

## 9. Environment notes & gotchas

- **Install "Permission denied" (already hit once):** almost always because the `.sh` was double-clicked or run as `./install.sh` without the exec bit, or macOS quarantine on a downloaded zip. Fix: run **`bash install.sh`** (drag the file into Terminal after typing `bash `), and if needed `chmod +x install.sh uninstall.sh && xattr -dr com.apple.quarantine .`. **Nothing in the app is machine-locked** — the README's "binds to this Mac" line only means the server listens on `127.0.0.1` (localhost), true on any Mac.
- **Models** download at install with **SHA-256 verification** (finished ones are skipped on re-run):
  - `face_detection_yunet_2023mar.onnx` — `github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` — `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` (232,589 B)
  - `face_recognition_sface_2021dec.onnx` — `…/models/face_recognition_sface/face_recognition_sface_2021dec.onnx` — `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` (38,696,353 B)
  - `age_googlenet.onnx` — `github.com/onnx/models/raw/main/validated/vision/body_analysis/age_gender/models/age_googlenet.onnx` — `fa2a3228e425056aa2b080b3afd3cf607327c86616e952602ed67b5fc16ab356` (23,960,165 B)
  - `gender_googlenet.onnx` — `…/age_gender/models/gender_googlenet.onnx` — `af24a4eaa9eaf70913cc9a337a0387c86f11549cbd9bbc16bffeefcdcf88cbf4` (23,935,566 B)
- **The face models can't be exercised without real photos** — keep the **MockEngine** path working so the app and the DOM smoke test run model-free.
- **The droplet `TarzanIQ.app` and the Finder Quick Action couldn't be compiled in the prior sandbox** (`osacompile`/`iconutil` are macOS-only) — they're built from standard patterns but get their first real test on his Mac. If the right-click action doesn't appear, relaunch Finder; the droplet and the dashboard's "Add Day" button do the same job.
- **Footprint:** the repo is small (~500 KB) on purpose — the weight (OpenCV/NumPy/etc. + ~83 MB models) is installed on the Mac, not shipped. With Feature A, also tell him the **archive** footprint (hundreds of GB/year) and that it can live on an external drive.
- **Data dir survives reinstalls;** never write app code there. The archive should be configurable and ideally separate.

---

*Current version: TarzanIQ v1.0.0 "Silverback". Server: http://127.0.0.1:43117, localhost-only.*
