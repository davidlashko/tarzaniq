# TarzanIQ 🦍📷

Street-photo intelligence for camera-rental crews. Point it at a day's photo folder and it works
out — **from the photos alone** — how many people each photographer approached, how many said yes
to a posed shoot, and when, where, and against whom. No cloud, no accounts: everything runs and
stays on one Mac.

> **This README has two parts.**
> **Part 1 — Using TarzanIQ** is for the person running the crew: plain English, no code, a
> step-by-step install and daily routine.
> **Part 2 — For developers** is the technical reference (architecture, API, setup, testing).

---

# Part 1 · Using TarzanIQ

*No programming needed. If you can copy photos into a folder, you can run this.*

## What it does, in one minute

Your photographers roam the city taking quick **candid** photos of strangers ("cold shoots"),
then walk up and pitch a **posed** photo on the spot ("warm shoots") — that's the sale. TarzanIQ
looks at a day's photos and figures out who got approached, who said yes, and how each
photographer is really doing — so you can **compare and coach** them. It shows everything in a
friendly 8-bit jungle dashboard.

The honest score is **conversion = posed ÷ candid**. Cash can't be trusted (pockets leak), but a
posed person in the photos is proof a sale happened. Bananas don't lie.

## Install (one time, ~5 minutes)

1. Put the `TarzanIQ` folder anywhere (Downloads is fine).
2. Open **Terminal** (press ⌘-Space, type "Terminal", Enter).
3. Type `bash ` (the word *bash* and a space), then **drag `install.sh` into the Terminal
   window** so its path appears, and press **Enter**.
4. Wait for the ape. The installer builds the Python environment, downloads the four face models
   (~83 MB, checksum-verified), and creates the **TarzanIQ.app** droplet plus the Finder
   right-click action.

After it finishes you can delete the downloaded folder — the app now lives in
`~/Library/Application Support/TarzanIQ`, and your data lives separately (see "Where things live").

> **If you see "Permission denied":** the file was probably double-clicked instead of run with
> `bash`. Redo step 3 (type `bash ` first, then drag the file in). Nothing is locked to a specific
> machine — "binds to this Mac" only means the dashboard is private to your computer.

## The daily routine

1. **Copy the day's photos** off the camera into a folder named exactly like this:

   ```
   YY.MM.DD.Place.Name      →      26.06.07.CityPark.Marko
   ```

   The **date comes from the folder name** (rental cameras keep the time but often get the date
   wrong). Place and Name should match what you used before — if TarzanIQ sees a new one, it asks
   whether it's genuinely new or a typo.

2. **Hand the folder to TarzanIQ**, any of these ways:
   - **Right-click the folder** in Finder → Quick Actions → *Analyze with TarzanIQ*, or
   - **Drag the folder onto TarzanIQ.app**, or
   - Open the dashboard and click **+ Add day folder**.

3. **Watch the live view** if you like — `space` pauses, `◀ ▶` step through photos, `Esc` returns
   to live. A 2,000-photo day takes roughly **8–12 minutes** on an M-series MacBook Air. You can
   queue several folders; they run one after another, and the Mac won't fall asleep mid-job.

4. **Finish the day.** TarzanIQ asks for the day's **money** (one cash and one card number for the
   whole day — skip if you don't track it) and whether to **add the day to the dataset**. Say yes:
   bananas fall, an Excel file named like the folder appears in `~/Documents/TarzanIQ Data/exports`,
   and every chart updates.

## What the numbers mean

| Term | Meaning |
|---|---|
| **Cold shoot** | A new face, in focus, candid. Seven rapid frames of one person still count as **one**. Two people in a frame = two cold marks. |
| **Warm shoot** | The same person reappearing **5 s–10 min** after their candid — a posed sale. Later than 10 min counts as a fresh re-approach (a new cold). |
| **Conversion** | Warm ÷ cold. **The headline score.** |
| **Hunting** | Average time between one mark and the next. |
| **Pitch** | Gap between someone's candid and their posed shoot starting. |
| **Breaks** | Gaps of 20+ min with no shooting; subtracted from "per-hour" stats. |
| **Suspected deletions** | Jumps in the photo file numbering. (Sony cameras roll 9999 → 0001; TarzanIQ knows that's normal.) |

All thresholds live in **Settings**, in plain language. Changing them doesn't rewrite history
until you press **Recompute** (no photos needed — the numbers are re-derived from stored data and
the Excel files refresh).

## First run — 10-minute calibration

Faces, light, and lenses differ. After your first processed day:

1. Open the day and check the overlays on a few frames: green boxes should sit on **subjects**,
   not on background passers-by.
2. Too many background faces counted? Nudge **Minimum face size** up. Sharp subjects being
   skipped? Nudge the **Sharpness gate** down.
3. One person split into two marks → raise **Same-person strictness** slightly; two people merged
   into one → lower it.
4. Glance at the gender split on a day you remember. Age buckets are coarse by design (the model
   thinks in ranges like 25–32) — great for patterns, not for identifying anyone.

Then press **Recompute** to apply.

## Where things live

```
~/Documents/TarzanIQ Data/
  tarzaniq.db      ← the dataset (source of truth)
  exports/         ← one styled Excel per day, named like the folder
  models/          ← the four downloaded face models
  backups/         ← automatic weekly DB copies (last 8 kept)
  logs/
```

- **Privacy:** by default TarzanIQ keeps a small compressed copy (~150 KB JPEG XL)
  of every processed photo in a separate archive folder (default
  `~/Documents/TarzanIQ Archive`, configurable, can be an external drive) so the
  analysis can be re-run as the app improves. Face fingerprints still live only in
  RAM while processing; person identities reset every day. Turn archiving off in
  Settings if you don't want the copies.
- **Backups for free:** every Excel export carries the full day's data inside it. Lost the
  database? Settings → *Rebuild from Excel exports*.
- Reinstalling or updating the app never touches the data folder.

## If something's off

| Symptom | Fix |
|---|---|
| Right-click action missing | Relaunch Finder (⌥-right-click its Dock icon → Relaunch) or log out/in. The droplet app works meanwhile. |
| "Folder name doesn't match" | The name must be `YY.MM.DD.Place.Name` — dots between, no spaces. Extra dots in the place are fine (`26.06.07.City.Park.Marko` → place "City Park"). |
| Dashboard won't open | Something else may be using port 43117. Check `~/Documents/TarzanIQ Data/logs/server.log`. |
| A model download failed | Re-run `install.sh` — finished models are skipped, broken ones are re-fetched and checksum-verified. |
| Two people merged / one split | See calibration above, then Recompute the day. |

## Honest fine print

- Age and gender are *model guesses* — reliable across hundreds of approaches, not for any single
  person.
- Identity matching is good at street distance with clear faces; sunglasses, masks, and extreme
  angles can split a person into two marks. It's consistent day-to-day, which is what comparisons
  need.
- The bundled models are open research models (OpenCV Zoo / ONNX Model Zoo). If TarzanIQ ever
  becomes more than an internal tool, read their licenses.

---

# Part 2 · For developers

A local-only **Flask** app with a dependency-free vanilla-JS SPA. The whole pipeline runs
on-device; nothing is sent anywhere (the server binds to `127.0.0.1:43117` only). This repo is
**public — it ships code only**: no photos, data, databases, Excel exports, or ML models are ever
committed.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11–3.12, Flask, SQLite (stdlib `sqlite3`) |
| Inference | OpenCV only — YuNet (face detection), SFace (identity, cosine 0.36), GoogleNet ONNX (age + gender) |
| Data / exports | `openpyxl` (styled Excel + embedded JSON), Pillow (EXIF) |
| Frontend | Vanilla JS SPA, **no build step**, Chart.js + pixel fonts bundled offline |
| Tests | Standalone Python scripts + a jsdom DOM smoke test (Node) |
| Packaging | `install.sh`: venv, SHA-256-verified model download, AppleScript droplet + Finder Quick Action |

> Models cannot run without real photos, so the image pipeline has a **MockEngine** twin. It lets
> the whole app boot and every page render model-free — this is what makes the frontend testable
> in CI. Keep that property.

## Status & roadmap

- **v1.0.0 "Silverback"** — shipped. Full ingest → stats → dashboard → Excel pipeline; test suite
  green (`test_engagements`, `test_server`, `test_e2e`, `dom_smoke`).
- **Feature A — permanent JXL photo archive** — in progress. Keep a ~150 KB JXL of every photo +
  a per-day manifest, and a `reprocess` tier that re-runs the full pipeline from the archive. Spec:
  [docs/superpowers/specs/2026-06-24-jxl-archive-design.md](docs/superpowers/specs/2026-06-24-jxl-archive-design.md).
- **Feature B — universal comparability** — planned. Stamp each day with a processing fingerprint
  and auto-bring stale days current so every number is comparable by construction. See
  [docs/HANDOFF.md](docs/HANDOFF.md) §7.2.

## Quick start (development)

```bash
git clone https://github.com/davidlashko/tarzaniq.git
cd tarzaniq

# opencv/numpy wheels need CPython 3.11–3.12 (NOT 3.13/3.14)
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
npm install                                   # jsdom, for the DOM smoke test

# run the whole test suite (3 Python suites + DOM smoke), one command:
./run_tests.sh

# run the app locally against the real models (must be installed first via install.sh):
.venv/bin/python -m tarzaniq.server --port 43117   # then open http://127.0.0.1:43117

# or run it model-free on a seeded demo DB (no models needed):
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/seed_demo.py
TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/run_demo_server.py --port 43991
```

The data directory defaults to `~/Documents/TarzanIQ Data` and is overridable with
`$TARZANIQ_DATA` (the tests use a throwaway dir under `/tmp`).

## Project structure

```
tarzaniq/                       # repo root
├── tarzaniq/                   # the Python package (the app)
│   ├── __init__.py             # APP_VERSION "1.0.0", codename "Silverback", port 43117
│   ├── config.py               # tunable DEFAULTS + on-disk path resolvers
│   ├── naming.py               # folder/filename parsing, deletion detection (Sony wrap aware)
│   ├── exifutil.py             # EXIF time-of-day (date comes from the folder name)
│   ├── engagements.py          # cold/warm engagement rules (the spec, pixel-blind)
│   ├── stats.py                # per-day stats derivation (stats_version 2)
│   ├── engine.py               # FaceEngine / MockEngine / SubjectTracker / annotate_preview
│   ├── db.py                   # SQLite schema (v1) + accessors + weekly backup
│   ├── excelio.py              # styled Excel export + import (full day embedded as JSON)
│   ├── pipeline.py             # job queue, worker thread, SSE, prompts, ingest + recompute
│   ├── agg.py                  # read-tier aggregations (reads only stats_json + scalar cols)
│   ├── server.py               # Flask routes; create(engine_factory=…) + main()
│   └── static/                 # SPA: js/{app,util,charts,live,pages}, css, img, vendor, fonts
├── tests/                      # test suites + seed_demo.py + run_demo_server.py
├── docs/                       # HANDOFF.md, ARCHITECTURE-REVIEW.md, superpowers/specs/
├── install.sh / uninstall.sh   # macOS install (models, droplet, Quick Action) / uninstall
├── gen_assets.py               # regenerate pixel-art logo/icons
├── requirements.txt            # runtime deps
├── requirements-dev.txt        # + test-only deps (piexif)
├── package.json                # jsdom (DOM smoke test)
├── run_tests.sh                # one-command full suite
└── CLAUDE.md                   # enduring project spec
```

## Architecture & data flow

```
folder "YY.MM.DD.Place.Name"
  → server.py  POST /api/enqueue        → pipeline.AppState (queue + single worker thread)
  → pipeline   Phase 1: scan            → exifutil (time) + naming (seq, detect_deletions)
               Phase 2: decode loop     → engine.FaceEngine.analyze → SubjectTracker.assign
                                          → engagements.Engager.step (live cold/warm labels)
               finalize                 → stats.compute_day_stats → build_day_record
  → db.commit_day                       → SQLite (source of truth, UNIQUE(date,place,employee))
  → excelio.export_day                  → styled .xlsx (full day embedded as JSON for recovery)

read tier (instant, no images):
  server.py data routes → agg.* (overview / employee / places / patterns / day) → static/js SPA
  live updates over SSE: GET /api/process/stream
```

Two re-derivation tiers: **`recompute`** (imageless — re-derives engagement math from stored rows
after a threshold change) exists today; **`reprocess`** (re-runs the full pipeline from the JXL
archive) arrives with Feature A. Full module-level map and Feature A/B hook points:
[docs/ARCHITECTURE-REVIEW.md](docs/ARCHITECTURE-REVIEW.md).

## Data model (SQLite, schema v1)

| Table | Holds |
|---|---|
| `meta` | schema version + housekeeping |
| `days` | one row per committed day; `stats_json`, money, source folder, `UNIQUE(date, place, employee)` |
| `photos` | per-photo rows (filename, sequence, time, kind) — enables imageless `recompute` |
| `subjects` | per-day subject rows (age/gender guesses, photo counts) — identities reset daily |
| `engagements` | derived cold/warm/pose events for the day timeline |
| `names`, `places` | the employee/place registries (with typo-mapping) |

Cascade deletes from `days`; a weekly backup keeps the last 8 copies.

## HTTP API (localhost only)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Dashboard SPA |
| `GET` | `/api/ping` | Health check |
| `POST` | `/api/enqueue` | Queue one or more day folders for processing |
| `GET` | `/api/state` | Current processing state + queue |
| `POST` | `/api/process/pause` | Toggle the pause flag |
| `POST` | `/api/process/cancel` | Cancel the current/queued job |
| `POST` | `/api/prompt/answer` | Answer an ask/answer prompt (new name/place, duplicate, money, commit) |
| `GET` | `/api/process/stream` | Server-Sent Events stream (frames, status, queue, prompts) |
| `POST` | `/api/pickfolder` | Native macOS folder picker |
| `GET` | `/api/overview` | Leaderboard + totals |
| `GET` | `/api/employee/<name>` | Employee detail (skills radar, history) |
| `GET` | `/api/places` | Place ranking + employee×place matrix |
| `GET` | `/api/patterns` | Weekday×hour heatmap + demographics |
| `GET` | `/api/day/<id>` | Day detail (timeline, subjects) |
| `DELETE` | `/api/day/<id>` | Delete a day (Excel export stays on disk) |
| `POST` | `/api/day/<id>/money` | Edit a day's cash/card totals |
| `GET` | `/api/export/<id>` | Download / refresh the day's Excel |
| `POST` | `/api/import` | Rebuild a day from an Excel export |
| `GET` `POST` | `/api/settings` | Read / update configuration |
| `GET` | `/api/registry` | Names + places registries |
| `POST` | `/api/registry/rename` | Rename an employee or place |
| `POST` | `/api/recompute` | Re-derive engagement stats from stored rows (no images) |
| `GET` | `/api/days` | List all committed days |

## Configuration

All keys live in `config.DEFAULTS` and are editable in **Settings** (plain-language labels). Keys
absent from `DEFAULTS` are silently dropped on save — add new ones there.

| Key | Default | Meaning |
|---|---|---|
| `warm_gap_s` | 5.0 | Min delay between shots of one subject to count as a warm shoot |
| `break_minutes` | 20.0 | Gap that counts as "off the clock" (subtracted from /hr) |
| `max_pitch_minutes` | 10.0 | Reappearing later than this = a new cold, not warm |
| `warm_session_gap_minutes` | 10.0 | Gap that splits a subject's warm shooting into sessions |
| `pose_gap_s` | 8.0 | Pause that separates pose clusters within a warm session |
| `min_face_frac` | 0.055 | Min face-box width as a fraction of image width |
| `min_face_blur` | 40.0 | Sharpness floor (Laplacian variance on the face crop) |
| `det_score_threshold` | 0.78 | YuNet detection-confidence floor |
| `face_match_threshold` | 0.36 | SFace cosine similarity to merge into an existing subject |
| `preview_enabled` | true | Stream annotated preview frames |
| `preview_max_width` | 760 | Max preview width (px) |
| `decode_reduced` | true | Decode JPEGs at half resolution (fast, plenty for faces) |
| `sounds_enabled` | true | UI sound effects |

## Testing

```bash
./run_tests.sh                                   # everything

# or individually:
.venv/bin/python tests/test_engagements.py       # 13 engagement-spec tests (pure Python)
.venv/bin/python tests/test_server.py            # naming edge cases + route smokes
.venv/bin/python tests/test_e2e.py               # synthetic day, prompts, Excel roundtrip, recompute
# DOM smoke: seed a demo DB, boot the MockEngine server, then run dom_smoke.mjs (see Quick start)
```

Each Python suite is a standalone script that exits non-zero on failure. The DOM smoke test boots
the **real SPA in jsdom** against a live MockEngine server on a seeded 30-day demo DB and asserts
every page renders, the leaderboard orders correctly, and all five prompt modals work.

## Conventions

- **Commits:** [Conventional Commits](https://www.conventionalcommits.org) (`feat(scope):`,
  `fix(scope):`, `chore:`, `docs:`) with dense bodies explaining the *why* + verification.
- **Branches:** `type/slug-YYYY-MM-DD`; feature work lands via PR to `main`; scaffolding/docs go
  straight to `main`.
- **Keep the whole suite green** through every change.
- **No "built with / produced by" attributions** in any app output, export, or UI.
- **Never commit** photos, data, databases, exports, or models — this repo is public.

See [CLAUDE.md](CLAUDE.md) for the full enduring spec and [docs/HANDOFF.md](docs/HANDOFF.md) for
project history and the current feature briefs.

---

*v1.0.0 "Silverback" — runs at http://127.0.0.1:43117, localhost-only.*
