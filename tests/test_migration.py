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
