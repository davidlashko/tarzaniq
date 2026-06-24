"""Tests for the significance helpers (Feature C). Run: .venv/bin/python tests/test_significance.py"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tarzaniq import significance as S  # noqa: E402

fails = []
def check(label, cond, detail=""):
    print(("  ok    " if cond else "  FAIL  ") + label + ("" if cond else f"  {detail}"))
    if not cond: fails.append(label)

check("cdf(0)=0.5", abs(S.normal_cdf(0) - 0.5) < 1e-9)
check("cdf(1.96)~0.975", abs(S.normal_cdf(1.96) - 0.975) < 1e-3, str(S.normal_cdf(1.96)))
check("cdf(-1.96)~0.025", abs(S.normal_cdf(-1.96) - 0.025) < 1e-3)

lo, hi = S.wilson_interval(50, 100)
check("wilson contains p", lo < 0.5 < hi and 0 <= lo <= hi <= 1, f"{lo},{hi}")
check("wilson trials=0 -> (0,0)", S.wilson_interval(0, 0) == (0.0, 0.0))
lo_s, hi_s = S.wilson_interval(1, 2)
check("wilson wider for small n", (hi_s - lo_s) > (hi - lo))
lo0, hi0 = S.wilson_interval(0, 20)
check("wilson all-fail stays in [0,1]", 0.0 <= lo0 <= hi0 <= 1.0, f"{lo0},{hi0}")
check("wilson all-fail low==0", lo0 == 0.0, str(lo0))

# clearly different, large samples -> significant
t = S.two_proportion_test(80, 100, 40, 100)
check("big diff significant", t["significant"] and t["p_value"] < 0.01, str(t))
check("diff sign", t["diff"] > 0)
check("enough_data true", t["enough_data"] is True)
# identical -> not significant, p ~ 1
t2 = S.two_proportion_test(50, 100, 50, 100)
check("identical not significant", t2["significant"] is False and t2["p_value"] > 0.9, str(t2))
# tiny samples -> enough_data False (still computes)
t3 = S.two_proportion_test(3, 5, 1, 4)
check("tiny -> enough_data False", t3["enough_data"] is False)
# n=0 guarded
t4 = S.two_proportion_test(0, 0, 5, 10)
check("n=0 guarded", t4["z"] == 0.0 and t4["p_value"] == 1.0 and t4["significant"] is False, str(t4))

print("ALL GREEN" if not fails else f"{len(fails)} FAILURES: {fails}")
sys.exit(1 if fails else 0)
