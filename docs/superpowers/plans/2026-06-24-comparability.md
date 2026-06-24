# Feature B — Universal Comparability — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stamp every day with a processing fingerprint, keep the whole dataset at one current fingerprint, and bring stale days current automatically — cheap recompute for timing changes, expensive reprocess (Feature A's archive) for face/model/algo changes; photo-less days that can't reprocess are flagged legacy and excluded from comparisons.

**Architecture:** A new pure `tarzaniq/fingerprint.py` computes per-day components (engagement_fp + detection_fp + model_version + algo_version) and routes a stale day to `current`/`recompute`/`reprocess`/`legacy`. A schema v1→v2 migration adds `processing_fingerprint`/`fp_components`/`has_archive` to `days`. `commit_day` stamps current; `replace_day_analysis` re-stamps (so recompute doesn't re-queue forever). A `bring_current` orchestrator routes stale days; `agg` excludes only legacy days.

**Tech Stack:** Python 3.11–3.12, SQLite (stdlib), Flask, vanilla-JS SPA. Tests are standalone scripts (NOT pytest), run via `.venv/bin/python tests/<name>.py`.

## Global Constraints

- Python 3.11–3.12 only; use `.venv/bin/python`. Tests are standalone scripts that exit non-zero on failure.
- Fingerprint components: `engagement_fp` (hash of the 5 timing params) → cheap recompute; `detection_fp` (hash of the 4 face params), `model_version`, `algo_version` → expensive reprocess.
- Timing params (5): `warm_gap_s`, `break_minutes`, `max_pitch_minutes`, `warm_session_gap_minutes`, `pose_gap_s`. Face params (4): `min_face_frac`, `min_face_blur`, `det_score_threshold`, `face_match_threshold`.
- A day with NO stored fingerprint (pre-Feature-B) routes to **recompute** (cheap re-derive + stamp), NOT reprocess — adopting fingerprints must not trigger a full back-catalog reprocess.
- A day routes to **legacy** only when a detection/model/algo component differs AND `has_archive` is false. Legacy is the ONLY class excluded from comparison aggregations. Catching-up (reprocess/recompute-pending) days stay included.
- `has_archive` is stored (not checked live) so `agg` stays instant; it is threaded through `build_day_record`→`commit_day` (the ingest manifest is written *after* commit, so it can't be detected by manifest-existence at commit time).
- `replace_day_analysis` MUST re-stamp the fingerprint or recomputed days re-queue forever.
- Schema migration must be idempotent and additive; fresh DBs get the columns via `_SCHEMA`, existing v1 DBs via guarded `ALTER TABLE`. Bump `SCHEMA_VERSION` to 2.
- Keep the whole suite green (`test_engagements`, `test_server`, `test_e2e`, `dom_smoke`, `test_archive`, new `test_fingerprint`/`test_migration`). No "built with/produced by" branding. Public repo — never commit data/models.

## File Structure

- **Create** `tarzaniq/fingerprint.py` — `components`, `current`, `fingerprint`, `route`, `is_comparable` (pure).
- **Modify** `tarzaniq/__init__.py` — add `MODEL_VERSION`, `ALGO_VERSION`.
- **Modify** `tarzaniq/db.py` — `SCHEMA_VERSION=2`; 3 new `days` columns in `_SCHEMA`; `_migrate()` in `connect()`; write fingerprint in `commit_day`; re-stamp in `replace_day_analysis`; `stale_days()` query.
- **Modify** `tarzaniq/pipeline.py` — thread `has_archive` + fingerprint through `build_day_record`; pass them at the 3 call sites; `bring_current()` orchestrator.
- **Modify** `tarzaniq/server.py` — `api_settings` triggers cheap path / returns expensive summary; `POST /api/bring-current`; comparability status.
- **Modify** `tarzaniq/agg.py` — exclude legacy days from comparison aggregations.
- **Modify** `tarzaniq/static/js/{pages,live}.js`, `static/css/jungle.css` — badges, banner, Settings surface.
- **Create** `tests/test_fingerprint.py`, `tests/test_migration.py`; extend `tests/test_e2e.py`.

---

## Task 1: fingerprint module + version constants

**Files:**
- Create: `tarzaniq/fingerprint.py`
- Modify: `tarzaniq/__init__.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Produces:
  - `MODEL_VERSION: str`, `ALGO_VERSION: str` (in `tarzaniq/__init__`)
  - `fingerprint.components(cfg: dict) -> dict` → `{engagement_fp, detection_fp, model_version, algo_version}`
  - `fingerprint.current() -> dict`
  - `fingerprint.fingerprint(components: dict) -> str`
  - `fingerprint.route(stored: dict | None, current: dict, has_archive: bool) -> str` ∈ {"current","recompute","reprocess","legacy"}
  - `fingerprint.is_comparable(stored: dict | None, current: dict, has_archive: bool) -> bool` (False iff route == "legacy")

- [ ] **Step 1: Write the failing test**

Create `tests/test_fingerprint.py`:

```python
"""Tests for the comparability fingerprint (Feature B). Run: .venv/bin/python tests/test_fingerprint.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TARZANIQ_DATA"] = str(Path(tempfile.mkdtemp(prefix="tq_fp_")) / "data")

from tarzaniq import config, fingerprint  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond:
        fails.append(label)


cfg = config.load_config()
comp = fingerprint.components(cfg)
check("components has 4 keys",
      set(comp) == {"engagement_fp", "detection_fp", "model_version", "algo_version"}, str(comp))
check("components stable", fingerprint.components(cfg) == comp)
check("fingerprint string composes",
      fingerprint.fingerprint(comp) ==
      f"e{comp['engagement_fp']}-d{comp['detection_fp']}-m{comp['model_version']}-a{comp['algo_version']}")

# timing change -> recompute
c2 = dict(cfg); c2["warm_gap_s"] = cfg["warm_gap_s"] + 1
check("timing change -> recompute",
      fingerprint.route(comp, fingerprint.components(c2), True) == "recompute")
# face change -> reprocess (with archive) / legacy (without)
c3 = dict(cfg); c3["min_face_frac"] = cfg["min_face_frac"] + 0.01
check("face change + archive -> reprocess",
      fingerprint.route(comp, fingerprint.components(c3), True) == "reprocess")
check("face change, no archive -> legacy",
      fingerprint.route(comp, fingerprint.components(c3), False) == "legacy")
# equal -> current
check("equal -> current", fingerprint.route(comp, comp, True) == "current")
# no stored fingerprint -> recompute (cheap stamp, not reprocess)
check("None stored -> recompute", fingerprint.route(None, comp, False) == "recompute")
# is_comparable: only legacy is excluded
check("legacy not comparable", fingerprint.is_comparable(comp, fingerprint.components(c3), False) is False)
check("reprocess-pending still comparable", fingerprint.is_comparable(comp, fingerprint.components(c3), True) is True)
check("None stored comparable", fingerprint.is_comparable(None, comp, False) is True)

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_fingerprint.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'tarzaniq.fingerprint'`.

- [ ] **Step 3: Add the version constants**

In `tarzaniq/__init__.py`, after the `APP_CODENAME = "Silverback"` line, add:

```python
# Comparability versions (Feature B). Bump MODEL_VERSION when the ONNX models
# change; bump ALGO_VERSION when engagement/stats/detection code changes the
# shape or meaning of outputs. Both feed the per-day processing fingerprint.
MODEL_VERSION = "1"
ALGO_VERSION = "1"
```

- [ ] **Step 4: Write `fingerprint.py`**

Create `tarzaniq/fingerprint.py`:

```python
"""Per-day processing fingerprint (Feature B).

Pure functions: given config + the model/algo version constants, compute the
four fingerprint components, and route a stale day to the cheapest valid path.
No I/O — see pipeline.bring_current for the orchestration.
"""

import hashlib
import json

from . import MODEL_VERSION, ALGO_VERSION, config

TIMING_KEYS = ("warm_gap_s", "break_minutes", "max_pitch_minutes",
               "warm_session_gap_minutes", "pose_gap_s")
FACE_KEYS = ("min_face_frac", "min_face_blur", "det_score_threshold",
             "face_match_threshold")


def _hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def components(cfg: dict) -> dict:
    return {
        "engagement_fp": _hash({k: cfg[k] for k in TIMING_KEYS}),
        "detection_fp": _hash({k: cfg[k] for k in FACE_KEYS}),
        "model_version": MODEL_VERSION,
        "algo_version": ALGO_VERSION,
    }


def current() -> dict:
    return components(config.load_config())


def fingerprint(comp: dict) -> str:
    return (f"e{comp['engagement_fp']}-d{comp['detection_fp']}"
            f"-m{comp['model_version']}-a{comp['algo_version']}")


def route(stored, current_comp: dict, has_archive: bool) -> str:
    """current | recompute | reprocess | legacy."""
    if stored and stored == current_comp:
        return "current"
    if stored:
        if (stored.get("detection_fp") != current_comp["detection_fp"]
                or stored.get("model_version") != current_comp["model_version"]
                or stored.get("algo_version") != current_comp["algo_version"]):
            return "reprocess" if has_archive else "legacy"
        return "recompute"          # only engagement_fp differs
    return "recompute"              # no stored fp (pre-Feature-B day): cheap stamp


def is_comparable(stored, current_comp: dict, has_archive: bool) -> bool:
    """A day is excluded from comparisons only when it is legacy."""
    return route(stored, current_comp, has_archive) != "legacy"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python tests/test_fingerprint.py`
Expected: PASS — `ALL GREEN`.

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/fingerprint.py tarzaniq/__init__.py tests/test_fingerprint.py
git commit -m "feat(fingerprint): per-day comparability fingerprint + routing

New pure tarzaniq/fingerprint.py: components() (engagement_fp/detection_fp/
model_version/algo_version), current(), fingerprint() string, and route()
(current/recompute/reprocess/legacy). Timing change -> recompute; face/model/
algo change -> reprocess (or legacy without an archive); unstamped days ->
recompute. MODEL_VERSION/ALGO_VERSION constants in __init__.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: schema v1 → v2 migration

**Files:**
- Modify: `tarzaniq/db.py` (`SCHEMA_VERSION`, `_SCHEMA` days table, `connect()` + `_migrate()`)
- Test: `tests/test_migration.py`

**Interfaces:**
- Produces: `days` rows gain `processing_fingerprint TEXT`, `fp_components TEXT`, `has_archive INTEGER DEFAULT 0`; `meta.schema_version == "2"` after connect; a `_has_archive_for(folder_name) -> bool` helper (lazy-imports archive).

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration.py`:

```python
"""Schema v1->v2 migration test (Feature B). Run: .venv/bin/python tests/test_migration.py"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = Path(tempfile.mkdtemp(prefix="tq_mig_")) / "data"
DATA.mkdir(parents=True)
os.environ["TARZANIQ_DATA"] = str(DATA)

from tarzaniq import config, db  # noqa: E402

fails = []


def check(label, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond:
        fails.append(label)


# --- build a minimal v1 DB by hand (no fingerprint columns, schema_version=1) ---
dbp = config.db_path()
con0 = sqlite3.connect(str(dbp))
con0.executescript("""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE days (
  id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, weekday TEXT NOT NULL,
  place TEXT NOT NULL, employee TEXT NOT NULL, source_folder TEXT,
  money_cash REAL, money_card REAL, stats_json TEXT NOT NULL, params_json TEXT NOT NULL,
  app_version TEXT, committed_at TEXT, UNIQUE(date, place, employee));
INSERT INTO meta(key,value) VALUES('schema_version','1');
INSERT INTO days(date,weekday,place,employee,stats_json,params_json)
  VALUES('2026-06-01','Monday','CityPark','Marko','{"conversion":0.5}','{}');
""")
con0.commit(); con0.close()

# --- connect() must migrate it to v2 in place ---
con = db.connect()
cols = {r["name"] for r in con.execute("PRAGMA table_info(days)")}
check("processing_fingerprint added", "processing_fingerprint" in cols)
check("fp_components added", "fp_components" in cols)
check("has_archive added", "has_archive" in cols)
sv = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"]
check("schema_version bumped to 2", sv == "2", sv)
row = con.execute("SELECT * FROM days WHERE date='2026-06-01'").fetchone()
check("existing data intact", row["employee"] == "Marko")
check("legacy day has_archive=0 (no manifest)", row["has_archive"] == 0)
check("legacy day fingerprint NULL", row["processing_fingerprint"] is None)
con.close()

# --- fresh DB also boots at v2 with the columns ---
DATA2 = Path(tempfile.mkdtemp(prefix="tq_mig2_")) / "data"
DATA2.mkdir(parents=True)
os.environ["TARZANIQ_DATA"] = str(DATA2)
import importlib  # noqa: E402
importlib.reload(config)  # re-resolve data_dir() to the new TARZANIQ_DATA
importlib.reload(db)
con2 = db.connect()
cols2 = {r["name"] for r in con2.execute("PRAGMA table_info(days)")}
check("fresh DB has fingerprint columns", {"processing_fingerprint", "fp_components", "has_archive"} <= cols2)
check("fresh DB schema_version=2",
      con2.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"] == "2")
con2.close()

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_migration.py`
Expected: FAIL — `processing_fingerprint added` (column missing; `connect()` doesn't migrate yet).

- [ ] **Step 3: Bump SCHEMA_VERSION and add columns to the fresh schema**

In `tarzaniq/db.py`, change `SCHEMA_VERSION = 1` to:

```python
SCHEMA_VERSION = 2
```

In `_SCHEMA`, in the `days` table, change the tail from:

```python
    app_version TEXT,
    committed_at TEXT,
    UNIQUE(date, place, employee)
);
```
to:
```python
    app_version TEXT,
    committed_at TEXT,
    processing_fingerprint TEXT,
    fp_components TEXT,
    has_archive INTEGER DEFAULT 0,
    UNIQUE(date, place, employee)
);
```

- [ ] **Step 4: Add the migration to `connect()`**

In `tarzaniq/db.py`, replace the body of `connect()` (the `cur = ... schema_version` block at the end) so it calls a migration. Replace:

```python
    con.executescript(_SCHEMA)
    cur = con.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cur.fetchone()
    if row is None:
        con.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),))
        con.commit()
    return con
```

with:

```python
    con.executescript(_SCHEMA)
    _migrate(con)
    return con
```

Then add these two module-level functions right after `connect()`:

```python
def _has_archive_for(folder_name: str) -> bool:
    from . import archive  # lazy: keeps db's top-level import light
    return archive.read_manifest(folder_name) is not None


def _migrate(con):
    """Bring an older DB up to SCHEMA_VERSION. Idempotent + additive."""
    row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),))
        con.commit()
        return
    ver = int(row["value"])
    if ver >= 2:
        return
    # v1 -> v2: add fingerprint/archive columns (guarded), backfill has_archive
    cols = {r["name"] for r in con.execute("PRAGMA table_info(days)")}
    if "processing_fingerprint" not in cols:
        con.execute("ALTER TABLE days ADD COLUMN processing_fingerprint TEXT")
    if "fp_components" not in cols:
        con.execute("ALTER TABLE days ADD COLUMN fp_components TEXT")
    if "has_archive" not in cols:
        con.execute("ALTER TABLE days ADD COLUMN has_archive INTEGER DEFAULT 0")
    for r in con.execute("SELECT id, source_folder, date, place, employee FROM days"):
        from pathlib import Path as _P
        folder = _P(r["source_folder"]).name if r["source_folder"] \
            else f"{r['date']}.{r['place']}.{r['employee']}"
        con.execute("UPDATE days SET has_archive=? WHERE id=?",
                    (1 if _has_archive_for(folder) else 0, r["id"]))
    con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    con.commit()
```

- [ ] **Step 5: Run the new test + the full suite**

Run: `.venv/bin/python tests/test_migration.py`
Expected: PASS — `ALL GREEN`.

Run: `.venv/bin/python tests/test_e2e.py` and `.venv/bin/python tests/test_server.py` and `.venv/bin/python tests/test_archive.py`
Expected: PASS (fresh DBs now boot at v2 with the new columns; existing flows unaffected).

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/db.py tests/test_migration.py
git commit -m "feat(db): schema v2 migration — fingerprint + has_archive columns

Bump SCHEMA_VERSION to 2; add processing_fingerprint/fp_components/has_archive
to days (in _SCHEMA for fresh DBs, via guarded ALTER for existing v1 DBs).
connect() now runs _migrate(): adds the columns and backfills has_archive by
checking for a per-day manifest. Idempotent and additive.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: stamp the fingerprint on commit

**Files:**
- Modify: `tarzaniq/pipeline.py` (`build_day_record` signature + return; the 3 call sites pass `has_archive`)
- Modify: `tarzaniq/db.py` (`commit_day` writes the 3 columns)
- Test: extend `tests/test_e2e.py`

**Interfaces:**
- Consumes: `fingerprint.current`, `fingerprint.fingerprint`.
- Produces: `build_day_record(..., has_archive=False)` adds `processing_fingerprint`, `fp_components`, `has_archive` to the returned dict; `commit_day` persists them. A freshly committed day is born `current`.

- [ ] **Step 1: Write the failing test**

In `tests/test_e2e.py`, after the existing `check("excel exported", ...)` block (right before the `# --- roundtrip` section), add:

```python
# ---- Feature B: a freshly committed day is born current ----
from tarzaniq import fingerprint as _fp  # noqa: E402
_d0 = db.all_days(con)[0]
_cur = _fp.current()
check("committed day stamped current",
      _d0["processing_fingerprint"] == _fp.fingerprint(_cur),
      _d0["processing_fingerprint"])
check("committed day fp_components match current",
      json.loads(_d0["fp_components"]) == _cur)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_e2e.py`
Expected: FAIL — `committed day stamped current` (column is None; nothing stamps yet). (`KeyError`/`None` mismatch.)

- [ ] **Step 3: Stamp in `build_day_record`**

In `tarzaniq/pipeline.py`, add the import (extend the existing `from . import ...` line to include `fingerprint`):

```python
from . import APP_VERSION, config, db, naming, exifutil, archive, fingerprint
```

Change `build_day_record`'s signature from:

```python
def build_day_record(date_iso, weekday, place, employee, source_folder,
                     cash, card, stats, params, photo_records, eng_final,
                     subj_meta):
```
to:
```python
def build_day_record(date_iso, weekday, place, employee, source_folder,
                     cash, card, stats, params, photo_records, eng_final,
                     subj_meta, has_archive=False):
```

Change its return dict from:

```python
    return {"date": date_iso, "weekday": weekday, "place": place,
            "employee": employee, "source_folder": source_folder,
            "money_cash": cash, "money_card": card, "stats": stats,
            "params": params, "photos": photos_out,
            "subjects": subjects_out, "engagements": engagements_out,
            "app_version": APP_VERSION}
```
to:
```python
    comp = fingerprint.current()
    return {"date": date_iso, "weekday": weekday, "place": place,
            "employee": employee, "source_folder": source_folder,
            "money_cash": cash, "money_card": card, "stats": stats,
            "params": params, "photos": photos_out,
            "subjects": subjects_out, "engagements": engagements_out,
            "app_version": APP_VERSION,
            "processing_fingerprint": fingerprint.fingerprint(comp),
            "fp_components": comp, "has_archive": bool(has_archive)}
```

- [ ] **Step 4: Pass `has_archive` at the 3 call sites**

In `_run_job_inner` (ingest), the `build_day_record(...)` call — append `has_archive`:

```python
        day_record = build_day_record(
            date_iso, job.date.strftime("%A"), job.place, job.employee,
            str(job.folder), money_cash, money_card, stats,
            config.engagement_params(cfg), photo_records, eng_final,
            subj_meta, has_archive=bool(do_archive and archive_entries))
```

In `reprocess_day`, the `build_day_record(...)` call (named `rec_out`) — reprocess always has an archive:

```python
    rec_out = build_day_record(
        drow["date"], drow["weekday"], drow["place"], drow["employee"],
        drow["source_folder"], drow["money_cash"], drow["money_card"], stats,
        config.engagement_params(cfg), photo_records, eng_final, subj_meta,
        has_archive=True)
```

In `recompute_day`, the `build_day_record(...)` call (named `rec`) — preserve the day's existing flag:

```python
    rec = build_day_record(drow["date"], drow["weekday"], drow["place"],
                           drow["employee"], drow["source_folder"],
                           drow["money_cash"], drow["money_card"], stats,
                           params, photo_records, eng_final, subj_meta,
                           has_archive=bool(drow["has_archive"]))
```

- [ ] **Step 5: Persist in `commit_day`**

In `tarzaniq/db.py` `commit_day`, change the days INSERT from:

```python
    cur = con.execute(
        "INSERT INTO days(date, weekday, place, employee, source_folder, "
        "money_cash, money_card, stats_json, params_json, app_version, "
        "committed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (d["date"], d["weekday"], d["place"], d["employee"],
         d.get("source_folder"), d.get("money_cash"), d.get("money_card"),
         json.dumps(d["stats"]), json.dumps(d["params"]),
         d.get("app_version"), datetime.now().isoformat()))
```
to:
```python
    fp_comp = d.get("fp_components")
    cur = con.execute(
        "INSERT INTO days(date, weekday, place, employee, source_folder, "
        "money_cash, money_card, stats_json, params_json, app_version, "
        "committed_at, processing_fingerprint, fp_components, has_archive) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["date"], d["weekday"], d["place"], d["employee"],
         d.get("source_folder"), d.get("money_cash"), d.get("money_card"),
         json.dumps(d["stats"]), json.dumps(d["params"]),
         d.get("app_version"), datetime.now().isoformat(),
         d.get("processing_fingerprint"),
         json.dumps(fp_comp) if fp_comp is not None else None,
         1 if d.get("has_archive") else 0))
```

- [ ] **Step 6: Run the extended test + full suite**

Run: `.venv/bin/python tests/test_e2e.py`
Expected: PASS — including the two new Feature-B checks.

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS (reprocess still commits; now stamps a fingerprint).

- [ ] **Step 7: Commit**

```bash
git add tarzaniq/pipeline.py tarzaniq/db.py tests/test_e2e.py
git commit -m "feat(pipeline): stamp the processing fingerprint on every commit

build_day_record now computes the current fingerprint + components and takes
has_archive; ingest passes (do_archive and archive_entries), reprocess passes
True, recompute preserves the day's flag. commit_day persists
processing_fingerprint/fp_components/has_archive, so every committed day
(ingest + reprocess) is current by construction.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: re-stamp on recompute (the no-infinite-requeue fix)

**Files:**
- Modify: `tarzaniq/db.py` (`replace_day_analysis` writes fingerprint)
- Modify: `tarzaniq/pipeline.py` (`recompute_day` passes the current fingerprint)
- Test: extend `tests/test_e2e.py`

**Interfaces:**
- Consumes: `fingerprint.current`/`fingerprint.fingerprint`.
- Produces: `replace_day_analysis(con, day_id, stats, params, photos_kinds, subjects, engagements, processing_fingerprint=None, fp_components=None)` — writes the fingerprint columns when provided. After `recompute_day`, the day's stored fingerprint equals current.

- [ ] **Step 1: Write the failing test**

In `tests/test_e2e.py`, find the recompute section (the `new_stats = recompute_day(con, day_id, params)` block). Right after the existing `check("recompute persisted", ...)` line, add:

```python
# ---- Feature B: recompute re-stamps the fingerprint (no infinite re-queue) ----
import importlib as _il  # noqa: E402
_cfgmod = _il.import_module("tarzaniq.config")
# write the changed param to config so fingerprint.current() reflects it
_cfg_now = _cfgmod.load_config(); _cfg_now["warm_gap_s"] = 60.0; _cfgmod.save_config(_cfg_now)
recompute_day(con, day_id, params)  # params already has warm_gap_s=60.0
_row = db.day_row(con, day_id)
from tarzaniq import fingerprint as _fp2  # noqa: E402
check("recompute re-stamps to current",
      _row["processing_fingerprint"] == _fp2.fingerprint(_fp2.current()),
      _row["processing_fingerprint"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_e2e.py`
Expected: FAIL — `recompute re-stamps to current` (recompute updates stats but not the fingerprint, so it still reads stale).

- [ ] **Step 3: Re-stamp in `replace_day_analysis`**

In `tarzaniq/db.py`, change `replace_day_analysis`'s signature from:

```python
def replace_day_analysis(con, day_id, stats, params, photos_kinds,
                         subjects, engagements):
```
to:
```python
def replace_day_analysis(con, day_id, stats, params, photos_kinds,
                         subjects, engagements,
                         processing_fingerprint=None, fp_components=None):
```

Change its first UPDATE from:

```python
    con.execute("UPDATE days SET stats_json=?, params_json=? WHERE id=?",
                (json.dumps(stats), json.dumps(params), day_id))
```
to:
```python
    con.execute("UPDATE days SET stats_json=?, params_json=?, "
                "processing_fingerprint=COALESCE(?, processing_fingerprint), "
                "fp_components=COALESCE(?, fp_components) WHERE id=?",
                (json.dumps(stats), json.dumps(params), processing_fingerprint,
                 json.dumps(fp_components) if fp_components is not None else None,
                 day_id))
```

- [ ] **Step 4: Pass the fingerprint from `recompute_day`**

In `tarzaniq/pipeline.py` `recompute_day`, change the `db.replace_day_analysis(...)` call from:

```python
    db.replace_day_analysis(con, day_id, stats, params, kinds_by_pid,
                            rec["subjects"], rec["engagements"])
```
to:
```python
    db.replace_day_analysis(con, day_id, stats, params, kinds_by_pid,
                            rec["subjects"], rec["engagements"],
                            processing_fingerprint=rec["processing_fingerprint"],
                            fp_components=rec["fp_components"])
```

(`rec` already carries the current fingerprint because `build_day_record` computes it in Task 3.)

- [ ] **Step 5: Run the extended test + full suite**

Run: `.venv/bin/python tests/test_e2e.py`
Expected: PASS — including `recompute re-stamps to current`.

Run: `.venv/bin/python tests/test_archive.py` and `.venv/bin/python tests/test_server.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/db.py tarzaniq/pipeline.py tests/test_e2e.py
git commit -m "fix(db): recompute re-stamps the fingerprint (no infinite re-queue)

replace_day_analysis now also writes processing_fingerprint/fp_components
(COALESCE-guarded), and recompute_day passes the current fingerprint from the
rebuilt record. Without this, a cheaply-recomputed day would stay flagged
stale forever and re-queue endlessly.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: stale-day query + bring_current orchestrator

**Files:**
- Modify: `tarzaniq/db.py` (`stale_days` query)
- Modify: `tarzaniq/pipeline.py` (`bring_current` + route helper)
- Test: extend `tests/test_archive.py` (uses MockEngine + a real archive)

**Interfaces:**
- Consumes: `fingerprint.current/route`, `db.all_days`, `recompute_day`, `AppState.enqueue_reprocess`.
- Produces:
  - `db.stale_days(con, current_fp_str) -> list[dict]` — days whose `processing_fingerprint != current_fp_str` (or NULL).
  - `pipeline.bring_current(state, con, enqueue_reprocess=True) -> dict` → `{recomputed, reprocess_queued, reprocess_pending, legacy, current}`. Cheap recomputes ALWAYS run inline (re-stamp). Reprocess-class days are enqueued via `state.enqueue_reprocess` only when `enqueue_reprocess=True` (else counted as `reprocess_pending`, NOT enqueued — this is how the settings-save preview avoids silently launching hours of work). Legacy days are never enqueued.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final print/sys.exit). Reuses `st` (AppState+MockEngine), the committed "Ana" day with an archive, `config`, `db`, `archive`, `check`:

```python
# ---- Feature B: bring_current routes stale days ----
from tarzaniq import fingerprint as _fpb  # noqa: E402
from tarzaniq.pipeline import bring_current  # noqa: E402

con = db.connect()
# everything currently committed should be current
cur_fp = _fpb.fingerprint(_fpb.current())
check("no stale days initially", len(db.stale_days(con, cur_fp)) == 0,
      str([d["date"] for d in db.stale_days(con, cur_fp)]))

# change a FACE param in config -> Ana (has archive) should route to reprocess
_c = config.load_config(); _c["min_face_frac"] = _c["min_face_frac"] + 0.01
config.save_config(_c)
new_fp = _fpb.fingerprint(_fpb.current())
stale = db.stale_days(con, new_fp)
check("face change makes days stale", len(stale) >= 1)
res = bring_current(st, con)
check("bring_current queued a reprocess for the archived day", res["reprocess_queued"] >= 1, str(res))
con.close()

# restore config so later/other runs aren't affected
_c2 = config.load_config(); _c2["min_face_frac"] = _c2["min_face_frac"] - 0.01
config.save_config(_c2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `ImportError: cannot import name 'bring_current'` / `AttributeError: ... 'stale_days'`.

- [ ] **Step 3: Add `stale_days` to db.py**

In `tarzaniq/db.py`, after `all_days`, add:

```python
def stale_days(con, current_fp):
    """Days whose stored fingerprint != the current one (NULL counts as stale)."""
    return [dict(r) for r in con.execute(
        "SELECT * FROM days WHERE processing_fingerprint IS NULL "
        "OR processing_fingerprint != ? ORDER BY date ASC", (current_fp,))]
```

- [ ] **Step 4: Add `bring_current` to pipeline.py**

In `tarzaniq/pipeline.py`, add after `recompute_day` (before the reprocess section):

```python
# ------------------------------------------------------------------ comparability

def bring_current(state, con, enqueue_reprocess=True):
    """Route every stale day to the cheapest valid path so the dataset
    converges to one current fingerprint. Cheap recomputes always run inline
    (and re-stamp). Reprocess-class days are queued on the worker only when
    enqueue_reprocess is True (the settings-save preview passes False so it can
    prompt before launching hours of work). Photo-less model/detection-behind
    days are left legacy (excluded by agg)."""
    cur = fingerprint.current()
    cur_fp = fingerprint.fingerprint(cur)
    params = config.engagement_params(config.load_config())
    out = {"recomputed": 0, "reprocess_queued": 0, "reprocess_pending": 0,
           "legacy": 0, "current": 0}
    reprocess_ids = []
    for d in db.stale_days(con, cur_fp):
        stored = json.loads(d["fp_components"]) if d["fp_components"] else None
        decision = fingerprint.route(stored, cur, bool(d["has_archive"]))
        if decision == "recompute":
            try:
                recompute_day(con, d["id"], params)
                out["recomputed"] += 1
            except Exception:
                pass
        elif decision == "reprocess":
            reprocess_ids.append(d["id"])
        elif decision == "legacy":
            out["legacy"] += 1
        else:
            out["current"] += 1
    if reprocess_ids and enqueue_reprocess:
        state.enqueue_reprocess(reprocess_ids)
        out["reprocess_queued"] = len(reprocess_ids)
    else:
        out["reprocess_pending"] = len(reprocess_ids)
    return out
```

- [ ] **Step 5: Run the new test + full suite**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

Run: `.venv/bin/python tests/test_e2e.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tarzaniq/db.py tarzaniq/pipeline.py tests/test_archive.py
git commit -m "feat(pipeline): bring_current orchestrator + stale_days query

db.stale_days lists days whose fingerprint != current. pipeline.bring_current
routes each: cheap recompute inline (re-stamps), reprocess-class days queued
on the worker, photo-less model-change days left legacy. Returns per-route
counts.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: exclude legacy days from comparisons (agg)

**Files:**
- Modify: `tarzaniq/agg.py`
- Test: extend `tests/test_archive.py`

**Interfaces:**
- Consumes: `fingerprint.current/is_comparable`.
- Produces: `agg.overview`/`employee_summaries`/`places`/`patterns` operate on `_comparable_days(con)` (legacy days excluded); `day_detail` and `db.all_days` are unchanged (legacy days still viewable/listable).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_archive.py` (before the final print/sys.exit):

```python
# ---- Feature B: legacy (photo-less, model-behind) days are excluded from comparisons ----
import json as _json3  # noqa: E402
from tarzaniq import agg as _agg  # noqa: E402
con = db.connect()
days_before = _agg.overview(con)["total"]["days"]
all_before = len(db.all_days(con))
# Insert a photo-less day with a stale detection fingerprint and no archive.
_stale_comp = dict(_fpb.current()); _stale_comp["detection_fp"] = "deadbeef0000"
con.execute("INSERT INTO days(date,weekday,place,employee,source_folder,"
            "stats_json,params_json,app_version,committed_at,"
            "processing_fingerprint,fp_components,has_archive) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("2020-01-01", "Wednesday", "OldBazaar", "LegacyAnn", None,
             _json3.dumps({"conversion": 0.5, "cold_persons": 2, "warm_persons": 1,
                           "photos_total": 5, "shoot_s": 100.0, "span_s": 200.0,
                           "weekday": "Wednesday", "cold_events": 1,
                           "warm_dur_avg_s": 1.0, "pitch_avg_s": 1.0, "poses_avg": 1.0,
                           "hot_streak": 1, "suspected_deletions": 0, "hourly": [],
                           "gender_count": {}, "gender_warm": {}, "age_count": {}, "age_warm": {}}),
             "{}", "1.0.0", "2020-01-01T00:00:00",
             _fpb.fingerprint(_stale_comp), _json3.dumps(_stale_comp), 0))
con.commit()
ov = _agg.overview(con)
check("legacy day excluded from overview totals (count unchanged)",
      ov["total"]["days"] == days_before, f"{days_before} -> {ov['total']['days']}")
check("legacy employee absent from leaderboard",
      all(s["employee"] != "LegacyAnn" for s in ov["leaderboard"]))
# but it IS still listed by db.all_days (viewable), so the row really exists
check("legacy day still listed by all_days",
      len(db.all_days(con)) == all_before + 1
      and "2020-01-01" in [d["date"] for d in db.all_days(con)])
con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_archive.py`
Expected: FAIL — `legacy day not in overview day count` (agg still includes it).

- [ ] **Step 3: Add the comparable-days filter in agg.py**

In `tarzaniq/agg.py`, add the import and a helper near the top (after `from . import db`):

```python
from . import db, fingerprint


def _comparable_days(con, **kw):
    """All days except legacy ones (photo-less + model/detection behind current).
    Used by the comparison aggregations; day_detail/all_days are unfiltered."""
    cur = fingerprint.current()
    out = []
    for d in db.all_days(con, **kw):
        stored = json.loads(d["fp_components"]) if d["fp_components"] else None
        if fingerprint.is_comparable(stored, cur, bool(d["has_archive"])):
            out.append(d)
    return out
```

(Change the existing `from . import db` line to the `from . import db, fingerprint` above.)

Then swap the `db.all_days(con...)` calls in the comparison aggregations to `_comparable_days(con...)`:
- `overview`: `days = db.all_days(con)` → `days = _comparable_days(con)`
- `employee_detail`: `days = db.all_days(con)` → `days = _comparable_days(con)`
- `places`: `days = db.all_days(con)` → `days = _comparable_days(con)`
- `patterns`: `days = db.all_days(con, employee=employee or None, place=place or None)` → `days = _comparable_days(con, employee=employee or None, place=place or None)`

Leave `day_detail` (single day) untouched — a legacy day is still fully viewable.

- [ ] **Step 4: Run the new test + full suite**

Run: `.venv/bin/python tests/test_archive.py`
Expected: PASS — `ALL GREEN`.

Run: `.venv/bin/python tests/test_e2e.py` (its agg-smoke asserts unchanged — none of its days are legacy)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/agg.py tests/test_archive.py
git commit -m "feat(agg): exclude legacy days from comparison aggregations

overview/employee_detail/places/patterns now read _comparable_days (legacy =
photo-less + detection/model/algo behind current). day_detail and all_days are
unchanged, so legacy days stay viewable and listed — just out of leaderboards
and rollups. Catching-up days remain included.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: server — auto-trigger, bring-current endpoint, status

**Files:**
- Modify: `tarzaniq/server.py`
- Test: extend `tests/test_server.py`

**Interfaces:**
- Consumes: `pipeline.bring_current`, `fingerprint.current/fingerprint`, `db.stale_days`.
- Produces:
  - `api_settings` (POST): after `save_config`+`reload_config`, run the cheap path automatically (`bring_current(..., enqueue_reprocess=False)`) and return a `comparability` summary `{recomputed, reprocess_pending, legacy}` so the UI can prompt for the expensive path.
  - `POST /api/bring-current`: runs `bring_current` (cheap inline + queue reprocess) and returns its counts.
  - `GET /api/comparability`: `{current_fingerprint, stale, by_route:{recompute,reprocess,legacy}}` for the badge/banner.

- [ ] **Step 1: Write the failing test**

In `tests/test_server.py`, alongside the other route smokes (near the `/api/reprocess` smoke), add two checks using the **same request helpers the surrounding smokes already use** (read the top of `test_server.py` — Feature A's reprocess smoke used a `post(...)` helper and there is a GET helper for the data routes; match those exact names):

```python
j = get("/api/comparability")
check("comparability route shape",
      "current_fingerprint" in j and "stale" in j and "by_route" in j, str(j))
r = post("/api/bring-current", {})
check("bring-current ok", r.get("ok") is True, str(r))
```

If the file's GET helper has a different name (e.g. `api`/`g`/`get_json`), use that; the assertion content stays the same.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python tests/test_server.py`
Expected: FAIL — 404 on `/api/comparability`.

- [ ] **Step 3: Add the routes + trigger**

In `tarzaniq/server.py`, add `fingerprint` and `bring_current` to imports:

```python
from . import APP_NAME, APP_VERSION, APP_CODENAME, DEFAULT_PORT, config, db
from . import agg, fingerprint
from .pipeline import AppState, recompute_day, bring_current
```

In `api_settings`, after `state.reload_config()` (POST branch), add an automatic cheap-path catch-up + a summary. Replace the POST branch body:

```python
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        cfg = config.load_config()
        for k, v in data.items():
            if k in config.DEFAULTS:
                want = type(config.DEFAULTS[k])
                try:
                    cfg[k] = bool(v) if want is bool else want(v)
                except Exception:
                    pass
        config.save_config(cfg)
        state.reload_config()
        # Feature B (smart auto): run the cheap path now; do NOT enqueue the
        # expensive reprocess — report how many days WOULD need it so the UI can
        # prompt the user, who then confirms via POST /api/bring-current.
        con = db.connect()
        try:
            res = bring_current(state, con, enqueue_reprocess=False)
        finally:
            con.close()
        out = dict(config.load_config())
        out["_data_dir"] = str(config.data_dir())
        out["comparability"] = {"recomputed": res["recomputed"],
                                "reprocess_pending": res["reprocess_pending"],
                                "legacy": res["legacy"]}
        return jsonify(out)
    out = dict(config.load_config())
    out["_data_dir"] = str(config.data_dir())
    return jsonify(out)
```

So a settings save: applies cheap timing changes instantly (recomputed inline) and, if a face/model/algo change made days need the expensive path, returns `reprocess_pending` WITHOUT enqueuing — the dashboard (Task 8) shows the "N days need reprocessing — start now?" prompt and only then calls `/api/bring-current`.

Add the two new routes after `api_recompute` (`/api/bring-current` enqueues, using `bring_current`'s default `enqueue_reprocess=True`):

```python
@app.route("/api/bring-current", methods=["POST"])
def api_bring_current():
    con = db.connect()
    try:
        res = bring_current(state, con)
    finally:
        con.close()
    return jsonify({"ok": True, **res})


@app.route("/api/comparability")
def api_comparability():
    con = db.connect()
    try:
        cur = fingerprint.current()
        cur_fp = fingerprint.fingerprint(cur)
        stale = db.stale_days(con, cur_fp)
        by = {"recompute": 0, "reprocess": 0, "legacy": 0}
        for d in stale:
            stored = json.loads(d["fp_components"]) if d["fp_components"] else None
            r = fingerprint.route(stored, cur, bool(d["has_archive"]))
            if r in by:
                by[r] += 1
        return jsonify({"current_fingerprint": cur_fp,
                        "stale": len(stale), "by_route": by})
    finally:
        con.close()
```

- [ ] **Step 4: Run the new smoke + full suite**

Run: `.venv/bin/python tests/test_server.py`
Expected: PASS — comparability + bring-current smokes.

Run: `.venv/bin/python tests/test_e2e.py` and `.venv/bin/python tests/test_archive.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/server.py tests/test_server.py
git commit -m "feat(server): auto cheap-catch-up on settings + bring-current/comparability

POST /api/settings now runs bring_current after saving (cheap recomputes
inline, reprocess-class days queued) and returns a comparability summary.
New POST /api/bring-current and GET /api/comparability (current fingerprint,
stale count, by-route breakdown) back the dashboard badge/banner.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: dashboard — catching-up + legacy badges, progress banner, Settings surface

**Files:**
- Modify: `tarzaniq/static/js/pages.js`, `tarzaniq/static/js/live.js`, `tarzaniq/static/css/jungle.css`
- Test: `tests/dom_smoke.mjs` (keep green; add a light assertion if the seed exposes stale days)

**Interfaces:**
- Consumes: `GET /api/comparability`, `GET /api/day/<id>` (now carries `processing_fingerprint`/`has_archive` via the day row).

> This task reads the real SPA and mirrors its existing patterns. The dashboard is dependency-free vanilla JS; match the `el()`/`API`/`PIX`/`charts` helpers already in use.

- [ ] **Step 1: Surface the day's comparability in `day_detail`**

`agg.day_detail` returns a `day` dict whitelisting specific columns. Add the new fields so the day page can badge. In `tarzaniq/agg.py` `day_detail`, extend the whitelist tuple:

```python
    return {"day": {k: d[k] for k in ("id", "date", "weekday", "place",
                                      "employee", "money_cash", "money_card",
                                      "source_folder", "committed_at",
                                      "app_version", "processing_fingerprint",
                                      "has_archive")},
```

- [ ] **Step 2: Add a comparability banner + badges in the SPA**

Read `tarzaniq/static/js/pages.js` (overview + day renderers) and `live.js`. Then:
- On the **overview** page, fetch `GET /api/comparability`; if `stale > 0`, render a small banner: `"{stale} days updating… ({by_route.reprocess} reprocessing, {by_route.recompute} recomputing)"`. If `by_route.legacy > 0`, note `"{legacy} legacy days excluded from comparisons"`. Mirror the existing banner/toast styling.
- On the **day** page, if the day's `processing_fingerprint` ≠ the overview's `current_fingerprint` (fetch `/api/comparability` or compare), show a **"catching up"** pill; if `has_archive` is false and it's behind on detection, show a **"legacy"** pill. Use the existing pill/badge CSS class (search `jungle.css` for an existing badge/totem class; add `.badge-catchup` / `.badge-legacy` if none fits).

Provide the exact handler using the existing `API.get`:

```javascript
// overview comparability banner
const cmp = await API.get('/api/comparability');
if (cmp.stale > 0) {
  // render banner el(...) mirroring existing overview header elements
}
```

- [ ] **Step 3: Settings surface**

In the Settings renderer of `pages.js`, add a small "Comparability" section showing `current_fingerprint`, the stale count, and a **"Bring everything up to date"** button wired to `API.post('/api/bring-current', {})` then refresh. Update the existing "old days keep their numbers until you recompute" copy to reflect auto-management.

- [ ] **Step 4: Run the DOM smoke test**

```bash
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/seed_demo.py
TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/run_demo_server.py --port 43991 >/tmp/tq_srv.log 2>&1 &
SRV=$!; sleep 2
node tests/dom_smoke.mjs http://127.0.0.1:43991; RC=$?; kill $SRV; exit $RC
```
Expected: `ALL GREEN` — the new banner/badges/Settings section must not break any existing page render or assertion. (Seeded demo days are all current, so the banner is absent; that's fine.)

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/agg.py tarzaniq/static/js/pages.js tarzaniq/static/js/live.js tarzaniq/static/css/jungle.css
git commit -m "feat(ui): comparability banner, catching-up/legacy badges, settings control

Overview shows a 'N days updating…' banner from /api/comparability; the day
page badges catching-up and legacy days; Settings gains a Comparability
section with the current fingerprint, stale count, and a 'Bring everything up
to date' button. day_detail now surfaces processing_fingerprint/has_archive.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Full suite from clean state:

```bash
./run_tests.sh && .venv/bin/python tests/test_fingerprint.py && .venv/bin/python tests/test_migration.py && .venv/bin/python tests/test_archive.py
```
Expected: every suite `ALL GREEN` / `== all suites green ==`.

- [ ] Open a PR `feat/comparability-2026-06-24` → `main`, summarizing the engine + UX stages and linking the spec.

---

## Self-Review

**Spec coverage:** fingerprint components + routing (Task 1) ✓; schema v1→v2 migration + columns (Task 2) ✓; stamp on commit, ingest/reprocess current-by-construction, has_archive threaded (Task 3) ✓; replace_day_analysis re-stamp / no-infinite-requeue (Task 4) ✓; stale query + bring_current routing cheap/expensive/legacy (Task 5) ✓; agg legacy exclusion, catching-up included (Task 6) ✓; smart-auto trigger + bring-current + status endpoints (Task 7) ✓; badges + banner + Settings surface (Task 8) ✓; tests for migration/fingerprint/no-requeue/legacy-exclusion/end-to-end (Tasks 1,2,4,5,6) ✓. Non-goals respected (no new inference; one current fingerprint).

**Placeholder scan:** all code steps carry full code. Task 8 (frontend) is the only "read the file then mirror" task — it points at concrete helpers (`API`, `el`, existing badge CSS) and supplies the fetch calls; exact markup follows the existing renderers by necessity (35 KB SPA).

**Type consistency:** `components()`/`current()`/`fingerprint()`/`route()`/`is_comparable()` signatures consistent across Tasks 1/5/6/7. `build_day_record(..., has_archive=False)` consistent across Task 3's three call sites. `replace_day_analysis(..., processing_fingerprint=None, fp_components=None)` consistent across Tasks 4. `bring_current(state, con) -> {recomputed,reprocess_queued,legacy,current}` consistent across Tasks 5/7. `db.stale_days(con, current_fp)` consistent across Tasks 5/7.

**Smart-auto fidelity:** the spec's "smart auto" runs cheap timing changes automatically but PROMPTS before an expensive reprocess. The plan honors this: `api_settings` calls `bring_current(..., enqueue_reprocess=False)` (cheap recomputes run inline; expensive days are only counted as `reprocess_pending`), and the dashboard prompts and then calls `POST /api/bring-current` (which enqueues). `bring_current`'s `enqueue_reprocess` flag is the single switch between preview and execute.
