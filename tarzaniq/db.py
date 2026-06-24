"""SQLite data layer. The DB is the source of truth and lives in the
data folder (survives reinstalls). Per-photo subject assignments are
kept so engagement logic can be re-run when thresholds change, without
ever touching the original photos again.

No embeddings, no crops, no pixels are stored — derived stats only.
"""

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import config

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,              -- ISO yyyy-mm-dd
    weekday TEXT NOT NULL,
    place TEXT NOT NULL,
    employee TEXT NOT NULL,
    source_folder TEXT,
    money_cash REAL,
    money_card REAL,
    stats_json TEXT NOT NULL,
    params_json TEXT NOT NULL,       -- engagement params used
    app_version TEXT,
    committed_at TEXT,
    processing_fingerprint TEXT,
    fp_components TEXT,
    has_archive INTEGER DEFAULT 0,
    UNIQUE(date, place, employee)
);
CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    seq INTEGER,
    t TEXT NOT NULL,                 -- ISO datetime
    kind TEXT,
    n_focus INTEGER,
    n_rejected INTEGER,
    subjects TEXT,                   -- JSON list of subject ids
    flags TEXT,                      -- JSON list of strings
    detail TEXT                      -- JSON: faces detail, extensible
);
CREATE INDEX IF NOT EXISTS idx_photos_day ON photos(day_id);
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    local_id INTEGER NOT NULL,
    gender TEXT, gender_conf REAL,
    age_bucket TEXT, age_est REAL,
    photo_count INTEGER,
    did_warm INTEGER,
    pitch_s REAL,
    warm_sessions INTEGER,
    warm_photos INTEGER,
    warm_duration_s REAL,
    poses_est INTEGER,
    reapproached INTEGER,
    first_seen TEXT, last_seen TEXT
);
CREATE INDEX IF NOT EXISTS idx_subjects_day ON subjects(day_id);
CREATE TABLE IF NOT EXISTS engagements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- 'cold' | 'warm'
    start TEXT, end TEXT,
    duration_s REAL,
    members TEXT,                    -- JSON list (cold) or single id (warm)
    n_members INTEGER,
    n_converted INTEGER,
    photos INTEGER,
    poses INTEGER,
    reapproach INTEGER
);
CREATE INDEX IF NOT EXISTS idx_eng_day ON engagements(day_id);
CREATE TABLE IF NOT EXISTS names (
    name TEXT PRIMARY KEY, active INTEGER DEFAULT 1, added_at TEXT
);
CREATE TABLE IF NOT EXISTS places (
    place TEXT PRIMARY KEY, active INTEGER DEFAULT 1, added_at TEXT
);
"""


def connect():
    p = config.db_path()
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(_SCHEMA)
    _migrate(con)
    return con


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


def backup_if_due():
    """Weekly DB copy into backups/, keep the last 8. Cheap insurance."""
    try:
        src = config.db_path()
        if not src.exists():
            return
        bdir = config.data_dir() / "backups"
        backups = sorted(bdir.glob("tarzaniq-*.db"))
        if backups:
            newest = backups[-1].stat().st_mtime
            if time.time() - newest < 7 * 86400:
                return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(src, bdir / f"tarzaniq-{stamp}.db")
        for old in sorted(bdir.glob("tarzaniq-*.db"))[:-8]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------- registry

def known_names(con):
    return [r["name"] for r in con.execute(
        "SELECT name FROM names WHERE active=1 ORDER BY name")]


def known_places(con):
    return [r["place"] for r in con.execute(
        "SELECT place FROM places WHERE active=1 ORDER BY place")]


def add_name(con, name):
    con.execute("INSERT OR IGNORE INTO names(name, added_at) VALUES(?,?)",
                (name, datetime.now().isoformat()))
    con.execute("UPDATE names SET active=1 WHERE name=?", (name,))
    con.commit()


def add_place(con, place):
    con.execute("INSERT OR IGNORE INTO places(place, added_at) VALUES(?,?)",
                (place, datetime.now().isoformat()))
    con.execute("UPDATE places SET active=1 WHERE place=?", (place,))
    con.commit()


def rename_employee(con, old, new):
    add_name(con, new)
    con.execute("UPDATE days SET employee=? WHERE employee=?", (new, old))
    con.execute("UPDATE days SET stats_json=REPLACE(stats_json, ?, ?) "
                "WHERE employee=?",
                (f'"employee": "{old}"', f'"employee": "{new}"', new))
    con.execute("DELETE FROM names WHERE name=?", (old,))
    con.commit()


def rename_place(con, old, new):
    add_place(con, new)
    con.execute("UPDATE days SET place=? WHERE place=?", (new, old))
    con.execute("DELETE FROM places WHERE place=?", (old,))
    con.commit()


# ---------------------------------------------------------------- days

def find_day(con, date_iso, place, employee):
    cur = con.execute(
        "SELECT id FROM days WHERE date=? AND place=? AND employee=?",
        (date_iso, place, employee))
    row = cur.fetchone()
    return row["id"] if row else None


def delete_day(con, day_id):
    con.execute("DELETE FROM days WHERE id=?", (day_id,))
    con.commit()


def commit_day(con, day_record):
    """day_record: dict with date/place/employee/stats/params/photos/
    subjects/engagements/money/source_folder/app_version. Replaces any
    existing day with the same (date, place, employee)."""
    d = day_record
    existing = find_day(con, d["date"], d["place"], d["employee"])
    if existing:
        con.execute("DELETE FROM days WHERE id=?", (existing,))
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
    day_id = cur.lastrowid

    con.executemany(
        "INSERT INTO photos(day_id, filename, seq, t, kind, n_focus, "
        "n_rejected, subjects, flags, detail) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(day_id, p["filename"], p.get("seq"), p["t"], p.get("kind"),
          p.get("n_focus", 0), p.get("n_rejected", 0),
          json.dumps(p.get("subjects", [])), json.dumps(p.get("flags", [])),
          json.dumps(p.get("detail", {})))
         for p in d["photos"]])

    con.executemany(
        "INSERT INTO subjects(day_id, local_id, gender, gender_conf, "
        "age_bucket, age_est, photo_count, did_warm, pitch_s, warm_sessions, "
        "warm_photos, warm_duration_s, poses_est, reapproached, first_seen, "
        "last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(day_id, s["local_id"], s.get("gender"), s.get("gender_conf"),
          s.get("age_bucket"), s.get("age_est"), s.get("photo_count"),
          1 if s.get("did_warm") else 0, s.get("pitch_s"),
          s.get("warm_sessions"), s.get("warm_photos"),
          s.get("warm_duration_s"), s.get("poses_est"),
          1 if s.get("reapproached") else 0,
          s.get("first_seen"), s.get("last_seen"))
         for s in d["subjects"]])

    con.executemany(
        "INSERT INTO engagements(day_id, kind, start, end, duration_s, "
        "members, n_members, n_converted, photos, poses, reapproach) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(day_id, e["kind"], e.get("start"), e.get("end"),
          e.get("duration_s"), json.dumps(e.get("members")),
          e.get("n_members"), e.get("n_converted"), e.get("photos"),
          e.get("poses"), 1 if e.get("reapproach") else 0)
         for e in d["engagements"]])

    add_name(con, d["employee"])
    add_place(con, d["place"])
    con.commit()
    return day_id


def update_money(con, day_id, cash, card):
    con.execute("UPDATE days SET money_cash=?, money_card=? WHERE id=?",
                (cash, card, day_id))
    con.commit()


# ---------------------------------------------------------------- queries

def day_row(con, day_id):
    r = con.execute("SELECT * FROM days WHERE id=?", (day_id,)).fetchone()
    return dict(r) if r else None


def all_days(con, employee=None, place=None, date_from=None, date_to=None):
    q = "SELECT * FROM days WHERE 1=1"
    args = []
    if employee:
        q += " AND employee=?"; args.append(employee)
    if place:
        q += " AND place=?"; args.append(place)
    if date_from:
        q += " AND date>=?"; args.append(date_from)
    if date_to:
        q += " AND date<=?"; args.append(date_to)
    q += " ORDER BY date ASC, employee ASC"
    return [dict(r) for r in con.execute(q, args)]


def day_photos(con, day_id):
    return [dict(r) for r in con.execute(
        "SELECT * FROM photos WHERE day_id=? ORDER BY t ASC, seq ASC",
        (day_id,))]


def day_subjects(con, day_id):
    return [dict(r) for r in con.execute(
        "SELECT * FROM subjects WHERE day_id=? ORDER BY local_id ASC",
        (day_id,))]


def day_engagements(con, day_id):
    return [dict(r) for r in con.execute(
        "SELECT * FROM engagements WHERE day_id=? ORDER BY start ASC",
        (day_id,))]


def replace_day_analysis(con, day_id, stats, params, photos_kinds,
                         subjects, engagements,
                         processing_fingerprint=None, fp_components=None):
    """Used by recompute: update analysis results in place, keep photos
    rows (only their kind changes) and money."""
    con.execute("UPDATE days SET stats_json=?, params_json=?, "
                "processing_fingerprint=COALESCE(?, processing_fingerprint), "
                "fp_components=COALESCE(?, fp_components) WHERE id=?",
                (json.dumps(stats), json.dumps(params), processing_fingerprint,
                 json.dumps(fp_components) if fp_components is not None else None,
                 day_id))
    for pid, kind in photos_kinds:
        con.execute("UPDATE photos SET kind=? WHERE id=?", (kind, pid))
    con.execute("DELETE FROM subjects WHERE day_id=?", (day_id,))
    con.execute("DELETE FROM engagements WHERE day_id=?", (day_id,))
    con.executemany(
        "INSERT INTO subjects(day_id, local_id, gender, gender_conf, "
        "age_bucket, age_est, photo_count, did_warm, pitch_s, warm_sessions, "
        "warm_photos, warm_duration_s, poses_est, reapproached, first_seen, "
        "last_seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(day_id, s["local_id"], s.get("gender"), s.get("gender_conf"),
          s.get("age_bucket"), s.get("age_est"), s.get("photo_count"),
          1 if s.get("did_warm") else 0, s.get("pitch_s"),
          s.get("warm_sessions"), s.get("warm_photos"),
          s.get("warm_duration_s"), s.get("poses_est"),
          1 if s.get("reapproached") else 0,
          s.get("first_seen"), s.get("last_seen"))
         for s in subjects])
    con.executemany(
        "INSERT INTO engagements(day_id, kind, start, end, duration_s, "
        "members, n_members, n_converted, photos, poses, reapproach) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(day_id, e["kind"], e.get("start"), e.get("end"),
          e.get("duration_s"), json.dumps(e.get("members")),
          e.get("n_members"), e.get("n_converted"), e.get("photos"),
          e.get("poses"), 1 if e.get("reapproach") else 0)
         for e in engagements])
    con.commit()
