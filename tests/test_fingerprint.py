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
