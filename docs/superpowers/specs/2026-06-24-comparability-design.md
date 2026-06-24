# Feature B — Universal Comparability — Design Spec

- **Date:** 2026-06-24
- **Status:** Approved (design); pending spec review
- **Branch:** `feat/comparability-2026-06-24`
- **Builds on:** Feature A (JXL archive + `reprocess_day`), merged in PR #2.
- **Companion docs:** [HANDOFF.md](../../HANDOFF.md) §7.2, [ARCHITECTURE-REVIEW.md](../../ARCHITECTURE-REVIEW.md) §5.

## 1. Goal

Make every number in the app comparable to every other number **by construction**, so the owner
never has to wonder whether two days can be fairly compared. Stamp each committed day with a
**processing fingerprint**; keep the whole dataset at one "current" fingerprint; bring stale days
current automatically — cheap `recompute` for engagement-timing changes, expensive `reprocess`
(from Feature A's archive) for model/detection changes.

## 2. The processing fingerprint

Stored on each day as **components** (not one opaque hash), so the router can tell *what* changed:

| Component | Source | A change here means |
|---|---|---|
| `engagement_fp` | hash of the 5 timing params (`warm_gap_s`, `break_minutes`, `max_pitch_minutes`, `warm_session_gap_minutes`, `pose_gap_s`) | cheap **recompute** |
| `detection_fp` | hash of the 4 face params (`min_face_frac`, `min_face_blur`, `det_score_threshold`, `face_match_threshold`) | expensive **reprocess** |
| `model_version` | constant `MODEL_VERSION` (bump when ONNX models change) | expensive **reprocess** |
| `algo_version` | constant `ALGO_VERSION` (bump when engagement/stats/detection code changes shape/meaning) | expensive **reprocess** |

A day is **current** iff all four of its stored components equal the current values. The composite
`processing_fingerprint` string (e.g. `e<engagement_fp>-d<detection_fp>-m<model_version>-a<algo_version>`)
is stored for quick equality checks and display; `fp_components` (JSON) is stored for routing.

*(Rejected alternative: a single opaque hash — you can't route cheap-vs-expensive from it.)*

## 3. Routing: cheap vs expensive

Compare a stale day's stored components against the current ones:
- **Only `engagement_fp` differs** → **cheap path**: `recompute_day` (imageless, re-derive from
  stored photo/subject rows). Instant; works even on photo-less days.
- **`detection_fp` / `model_version` / `algo_version` differs** → **expensive path**:
  `reprocess_day` from the JXL archive. A day with **no archive** (`has_archive=0`) cannot take this
  path → it is marked **legacy-excluded** (see §6/§7).

Conservative by design: `algo_version` bumps always route to reprocess (code changed; reprocessing
from pixels is the thorough, safe path).

## 4. Schema v1 → v2 migration (`db.py`)

`connect()` gains a migration step gated on `meta.schema_version`:
- bump `SCHEMA_VERSION` 1 → 2;
- `ALTER TABLE days ADD COLUMN processing_fingerprint TEXT`, `fp_components TEXT` (JSON),
  `has_archive INTEGER DEFAULT 0`;
- **backfill** existing rows: leave `processing_fingerprint` NULL / sentinel (so they read as
  stale) and set `has_archive` by checking whether a manifest exists for the day's folder
  (`archive.read_manifest(...) is not None`);
- write `schema_version = 2`.

Idempotent and additive (`ADD COLUMN IF NOT EXISTS` isn't in SQLite, so guard each `ALTER` by
checking `PRAGMA table_info(days)`). Tested for fresh-boot (v2 created directly), v1→v2 upgrade
(columns added, data intact), and backup/restore across v2.

## 5. Fingerprint module (`tarzaniq/fingerprint.py`, new — isolated, unit-testable)

```
components(cfg) -> dict          # {engagement_fp, detection_fp, model_version, algo_version}
current() -> dict                # components(config.load_config())
fingerprint(components: dict) -> str    # the composite string
route(stored_components: dict, current_components: dict, has_archive: bool)
    -> "current" | "recompute" | "reprocess" | "legacy"
    # "current": all equal. "recompute": only engagement_fp differs.
    # "reprocess": a detection/model/algo component differs AND has_archive.
    # "legacy": a detection/model/algo component differs AND NOT has_archive.
```

Pure functions over config + the version constants; no I/O. `MODEL_VERSION` and `ALGO_VERSION`
live in `tarzaniq/__init__.py` next to `APP_VERSION`.

## 6. Stamping + the one critical fix

- `pipeline.build_day_record` computes and includes the fingerprint (string + components) so it
  lands on the day row.
- `db.commit_day` writes `processing_fingerprint`, `fp_components`, `has_archive` on every committed
  day (ingest **and** reprocess → current by construction). `has_archive` is computed at commit time
  by checking whether a manifest exists for the day's folder (`archive.read_manifest(folder) is not
  None`) — the same check the migration backfill uses, so ingest, reprocess, and Excel-import all
  set it correctly.
- **`db.replace_day_analysis` (the cheap recompute path) MUST also re-stamp `processing_fingerprint`
  + `fp_components` to current** — otherwise recomputed days stay flagged stale forever and
  re-queue endlessly. This is the highest-risk bug in the feature; a test pins it.

## 7. Auto-bring-current ("smart auto")

A `bring_current` orchestrator (in `pipeline.py`, using `fingerprint.route`):
1. Compute current components; query stale days (`processing_fingerprint != current` or NULL).
2. For each, decide route:
   - `recompute` → run cheap recompute (re-stamps fingerprint), synchronously and imageless — the
     same mechanism as the existing `/api/recompute`. Automatic, no prompt.
   - `reprocess` → enqueue a reprocess job on the existing worker/queue/SSE (Feature A's tier).
   - `legacy` → mark legacy-excluded (a flag the UI/agg read); not enqueued.
3. **Trigger:** `server.api_settings` (POST) computes the new fingerprint after `save_config`; if
   only timing changed it runs the cheap path immediately/automatically; if an
   expensive-class component changed it returns a summary (`{stale_n, est, needs_reprocess}`) so the
   UI can **prompt** ("N days need reprocessing, ~est — start now?") before enqueuing. A
   `POST /api/bring-current` endpoint performs the enqueue on confirmation, and the existing
   `/api/recompute` "recompute all" maps to the cheap path.
4. **Status:** a `GET`-able status (stale count, in-progress) + SSE progress drive the banner.

## 8. UI

- **"catching up" badge** on stale days that are queued/reprocessing (`fp != current` and not
  legacy). They remain visible **and included** in all comparisons; the badge clears automatically
  when the day becomes current. A banner shows progress ("12 days updating… 4 left") via existing
  SSE queue events.
- **"legacy" badge** on `has_archive=0` days whose detection/model/algo is behind current; these
  are the **only** days excluded from comparisons/leaderboards.
- **Settings**: show the current fingerprint + the four component versions, the stale-day count,
  and one **"Bring everything up to date"** control. Update the existing "old days keep their
  numbers until you recompute" copy (now auto-managed).

## 9. Aggregation (`agg.py`)

Minimal change: exclude **legacy** days from the comparison aggregations
(`overview`/`employee_summaries`/`places`/`patterns` leaderboards), while still listing them in
their own day view. **Catching-up days are NOT excluded** (owner's choice). A day is
legacy-excluded when `has_archive=0` AND its detection/model/algo component ≠ current. Keep `agg`'s
"reads only stats_json + scalar columns, instant" property — the new flag is a scalar column read.

## 10. Code shape & touch points

- **New:** `tarzaniq/fingerprint.py`; `MODEL_VERSION`/`ALGO_VERSION` in `__init__.py`.
- **`db.py`:** v2 migration; 3 new columns; write fingerprint in `commit_day`; re-stamp in
  `replace_day_analysis`; a `stale_days(con, current_fp)` query; `has_archive` backfill helper.
- **`pipeline.py`:** stamp in `build_day_record`; `bring_current` orchestrator; pass fingerprint
  through reprocess's `commit_day`.
- **`server.py`:** `api_settings` triggers cheap path / returns expensive summary;
  `POST /api/bring-current`; a status field on `/api/state` or a small `/api/comparability`.
- **`agg.py`:** legacy exclusion.
- **Frontend:** badges (`pages.js`/`jungle.css`), progress banner (`live.js`), Settings surface
  (`pages.js`).

## 11. Non-goals / out of scope

- No new inference or archive work (Feature A done). No automatic model downloading/upgrading.
- No change to the engagement spec rules or stats shape (those would be an `algo_version` bump,
  handled by the routing, not redefined here).
- No multi-fingerprint "compare across versions" views — the product keeps ONE current fingerprint.

## 12. Testing plan

Keep the whole suite green (`test_engagements`, `test_server`, `test_e2e`, `dom_smoke`,
`test_archive`). New tests:
- **Migration:** seed a v1 DB (no fingerprint columns) → `connect()` → assert columns added, data
  intact, `schema_version=2`; assert fresh-boot also yields v2; backup/restore across v2.
- **`fingerprint`:** `components`/`fingerprint` stable & order-independent; `route` returns
  recompute for a timing-only delta, reprocess for a face/model/algo delta, legacy when no archive,
  current when equal.
- **No infinite re-queue:** change a timing param → day stale → cheap recompute → day's fingerprint
  == current (the `replace_day_analysis` re-stamp).
- **End-to-end (MockEngine):** ingest a day (current fp); bump a face param → day stale & routes to
  reprocess; run bring-current → day current again & counts reproduced. A separate case: a
  photo-less day + a face change → routes to `legacy` and is excluded from `agg.overview`.
- **Extend `test_e2e`:** assert a freshly committed day is born `current`; recompute keeps it
  current.

## 13. Build / commit plan (two stages, one branch → one PR)

**Stage 1 — comparability engine (headless):** `__init__` version constants; `fingerprint.py`;
schema v2 migration + columns; stamp in `commit_day`/`build_day_record`; re-stamp in
`replace_day_analysis`; `stale_days` query; `bring_current` orchestrator; `agg` legacy exclusion;
all the above tests.

**Stage 2 — UX:** `api_settings` trigger + `/api/bring-current` + status; "catching up" + "legacy"
badges; progress banner; Settings surface; dom_smoke coverage.

Each stage is focused commits; the branch merges to `main` via PR.

## 14. Honest tradeoffs

- A real model upgrade over a large back-catalog is genuinely hours of reprocessing; the two-tier
  split keeps the common case (timing tweaks) instant and only model/detection changes pay the cost.
- During an expensive catch-up the dashboard transiently mixes old + new numbers (owner chose
  visible-with-badge over hide-until-ready); the "catching up" badge is the signal.
- Pre-archive / Excel-imported days can't be model-reprocessed — honestly marked **legacy** and
  excluded from comparisons rather than silently shown as comparable.
- `MODEL_VERSION`/`ALGO_VERSION` are developer-maintained constants; forgetting to bump one on a
  meaningful change would leave days falsely "current." Documented next to the constants.
