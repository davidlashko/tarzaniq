# Feature C — Statistical Significance on Comparisons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Tell the user whether a difference in conversion between photographers is statistically real (two-proportion z-test) or noise, and show Wilson confidence intervals — on the Compare page.

**Architecture:** A new pure `tarzaniq/significance.py` (stdlib `math` only) provides `normal_cdf`, `wilson_interval`, `two_proportion_test`. `agg` adds a `conversion_ci` to each employee summary and a `compare_significance(con, a, b)`. A `GET /api/compare/<a>/<b>` route serves it; the Compare page renders a plain-language verdict.

**Tech Stack:** Python 3.11–3.12 (stdlib `math` — NO scipy/numpy for this), Flask, vanilla-JS SPA. Tests are standalone scripts (NOT pytest), run via `.venv/bin/python tests/<name>.py`.

## Global Constraints

- No new dependencies — `significance.py` uses only stdlib `math`.
- Conversion = warm_persons / cold_persons (a proportion). The two-proportion z-test is pooled, two-sided; significant at p < 0.05. `MIN_TRIALS = 30` is the "enough_data" floor.
- `wilson_interval(successes, trials, z=1.96)` clamped to [0,1]; `trials == 0` → `(0.0, 0.0)`.
- `two_proportion_test` guards n==0 / zero pooled variance → `z=0.0, p_value=1.0, significant=False`.
- `compare_significance` uses `agg._comparable_days` (legacy days excluded), consistent with Feature B.
- `agg` must stay instant (counts only; no extra DB/I/O). Additive UI only; no "built with/produced by" branding. Keep the whole suite green (incl. dom_smoke).

## File Structure
- **Create** `tarzaniq/significance.py` — `normal_cdf`, `wilson_interval`, `two_proportion_test`, `MIN_TRIALS`.
- **Modify** `tarzaniq/agg.py` — `conversion_ci` in `employee_summaries`; new `compare_significance`.
- **Modify** `tarzaniq/server.py` — `GET /api/compare/<a>/<b>`.
- **Modify** `tarzaniq/static/js/pages.js` — Compare-page significance line.
- **Create** `tests/test_significance.py`; extend `tests/test_e2e.py`, `tests/test_server.py`.

---

## Task 1: significance.py

**Files:** Create `tarzaniq/significance.py`; Test `tests/test_significance.py`
**Interfaces — Produces:** `normal_cdf(z)->float`, `wilson_interval(successes,trials,z=1.96)->(low,high)`, `two_proportion_test(s1,n1,s2,n2)->dict`, `MIN_TRIALS=30`.

- [ ] **Step 1: Write the failing test** — create `tests/test_significance.py`:

```python
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
```

- [ ] **Step 2: Run → FAIL** (`ModuleNotFoundError: tarzaniq.significance`). Run: `.venv/bin/python tests/test_significance.py`

- [ ] **Step 3: Implement** — create `tarzaniq/significance.py`:

```python
"""Statistical significance for conversion comparisons (Feature C).

Conversion is a proportion (warm out of cold approaches), so we use a pooled
two-proportion z-test for head-to-head significance and the Wilson score
interval for confidence bounds. Stdlib math only — math.erf gives the normal CDF.
"""

import math

MIN_TRIALS = 30  # below this the normal approximation is shaky -> "need more data"


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def wilson_interval(successes: int, trials: int, z: float = 1.96):
    """Wilson score confidence interval for a proportion, clamped to [0, 1]."""
    if trials <= 0:
        return (0.0, 0.0)
    p = successes / trials
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (p + z2 / (2 * trials)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return (max(0.0, center - half), min(1.0, center + half))


def two_proportion_test(s1: int, n1: int, s2: int, n2: int) -> dict:
    """Pooled two-proportion z-test (two-sided) comparing s1/n1 vs s2/n2."""
    p1 = s1 / n1 if n1 else 0.0
    p2 = s2 / n2 if n2 else 0.0
    out = {"p1": p1, "p2": p2, "diff": p1 - p2, "z": 0.0, "p_value": 1.0,
           "significant": False, "enough_data": (n1 >= MIN_TRIALS and n2 >= MIN_TRIALS)}
    if n1 <= 0 or n2 <= 0:
        return out
    pool = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        return out
    z = (p1 - p2) / se
    out["z"] = z
    out["p_value"] = 2.0 * (1.0 - normal_cdf(abs(z)))
    out["significant"] = out["p_value"] < 0.05
    return out
```

- [ ] **Step 4: Run → PASS.** Run: `.venv/bin/python tests/test_significance.py` (Expected `ALL GREEN`).

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/significance.py tests/test_significance.py
git commit -m "feat(significance): two-proportion z-test + Wilson CI (stdlib only)

New tarzaniq/significance.py: normal_cdf (via math.erf), wilson_interval
(clamped, trials=0 safe), two_proportion_test (pooled two-sided, n=0 guarded,
enough_data floor at MIN_TRIALS=30). No new dependencies.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: agg — conversion CI + compare_significance

**Files:** Modify `tarzaniq/agg.py`; Test extend `tests/test_e2e.py`
**Interfaces — Consumes:** `significance.wilson_interval/two_proportion_test`. **Produces:** each `employee_summaries` value gains `conversion_ci: (low, high)`; `agg.compare_significance(con, a, b) -> dict | None`.

- [ ] **Step 1: Write the failing test** — in `tests/test_e2e.py`, in the agg-smoke section (near `emp = agg.employee_detail(con2, "Marko")`), add:

```python
# ---- Feature C: conversion CI + compare significance ----
_sums = agg.employee_summaries(db.all_days(con2))
_one = next(iter(_sums.values()))
check("summary has conversion_ci", isinstance(_one.get("conversion_ci"), tuple)
      and len(_one["conversion_ci"]) == 2, str(_one.get("conversion_ci")))
_cmp = agg.compare_significance(con2, "Marko", "Petar")
check("compare_significance shape", _cmp is not None and "test" in _cmp
      and "significant" in _cmp["test"] and "a_ci" in _cmp and "b_ci" in _cmp, str(_cmp))
check("compare missing employee -> None",
      agg.compare_significance(con2, "Marko", "NoSuchApe") is None)
```

- [ ] **Step 2: Run → FAIL** (`summary has conversion_ci`). Run: `.venv/bin/python tests/test_e2e.py`

- [ ] **Step 3: Implement** — in `tarzaniq/agg.py`:

Change the import line `from . import db, fingerprint` to:
```python
from . import db, fingerprint, significance
```

In `employee_summaries`, inside the `out[emp] = { ... }` dict, add a `conversion_ci` key (place it right after the `"conversion": ...` line):
```python
            "conversion_ci": significance.wilson_interval(warm_p, cold_p),
```

Add a new function after `employee_summaries` (before `radar_percentiles`):
```python
def compare_significance(con, a, b):
    """Head-to-head conversion significance (two-proportion z-test) + Wilson CIs.
    None if either employee has no comparable days."""
    sums = employee_summaries(_comparable_days(con))
    if a not in sums or b not in sums:
        return None
    sa, sb = sums[a], sums[b]
    test = significance.two_proportion_test(
        sa["warm_persons"], sa["cold_persons"],
        sb["warm_persons"], sb["cold_persons"])
    return {"a": a, "b": b,
            "a_conv": sa["conversion"], "b_conv": sb["conversion"],
            "a_ci": sa["conversion_ci"], "b_ci": sb["conversion_ci"],
            "a_cold": sa["cold_persons"], "a_warm": sa["warm_persons"],
            "b_cold": sb["cold_persons"], "b_warm": sb["warm_persons"],
            "test": test}
```

- [ ] **Step 4: Run → PASS.** Run: `.venv/bin/python tests/test_e2e.py` (Expected `ALL GREEN`). Also `.venv/bin/python tests/test_server.py` (employee/overview routes use employee_summaries — must stay green).

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/agg.py tests/test_e2e.py
git commit -m "feat(agg): conversion CI per employee + compare_significance

employee_summaries gains conversion_ci (Wilson on warm/cold). New
compare_significance(con,a,b) runs the two-proportion test on conversion over
comparable (non-legacy) days and returns both CIs. None if either is missing.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: server — /api/compare/<a>/<b>

**Files:** Modify `tarzaniq/server.py`; Test extend `tests/test_server.py`
**Interfaces — Consumes:** `agg.compare_significance`. **Produces:** `GET /api/compare/<a>/<b>` → the dict, 404 if None.

- [ ] **Step 1: Write the failing test** — in `tests/test_server.py`, alongside the other GET smokes (use the file's existing GET helper name), add:

```python
j = get("/api/compare/Marko/Ana")
check("compare route shape (or 404 if seed lacks them)",
      (isinstance(j, dict) and ("test" in j or "error" in j)), str(j))
```

(test_server's seeded/empty DB may not have both employees; accept either the populated dict or an error envelope — the smoke just confirms the route is wired and returns valid JSON without 500.)

- [ ] **Step 2: Run → FAIL** (404 / no route). Run: `.venv/bin/python tests/test_server.py`

- [ ] **Step 3: Implement** — in `tarzaniq/server.py`, after the `api_employee` route (`@app.route("/api/employee/<name>")`), add:

```python
@app.route("/api/compare/<a>/<b>")
def api_compare(a, b):
    con = db.connect()
    try:
        out = agg.compare_significance(con, a, b)
        if out is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(out)
    finally:
        con.close()
```

- [ ] **Step 4: Run → PASS.** Run: `.venv/bin/python tests/test_server.py` (Expected `ALL GREEN`).

- [ ] **Step 5: Commit**

```bash
git add tarzaniq/server.py tests/test_server.py
git commit -m "feat(server): GET /api/compare/<a>/<b> — conversion significance

Serves agg.compare_significance (two-proportion test + Wilson CIs); 404 when
either employee has no comparable days. Connection closed in finally.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Compare-page significance line

**Files:** Modify `tarzaniq/static/js/pages.js` (the `pageCompare` renderer); Test `tests/dom_smoke.mjs` (keep green)
**Interfaces — Consumes:** `GET /api/compare/<a>/<b>`.

- [ ] **Step 1: Read the Compare renderer.** `grep -n "pageCompare" tarzaniq/static/js/pages.js` and read it (it fetches `/api/employee/<a>` and `/api/employee/<b>`, builds a "Head to head" panel). Note the helpers (`el`, `API.get`, `fmt.pct`, panel classes).

- [ ] **Step 2: Add the significance line.** In `pageCompare(a, b)`, after the existing data fetch, also fetch `const sig = await API.get('/api/compare/' + encodeURIComponent(a) + '/' + encodeURIComponent(b)).catch(() => null);`. Build a significance element and include it in the "Head to head" panel (mirror the existing `el(...)` panel/legend style):

```javascript
function sigLine(sig, a, b) {
  if (!sig || !sig.test) return '';
  const pct = v => (v == null ? '—' : Math.round(v * 100) + '%');
  const ci = c => c ? ` (${Math.round(c[0]*100)}–${Math.round(c[1]*100)}%)` : '';
  const t = sig.test;
  const leader = t.diff >= 0 ? a : b;
  let verdict, cls;
  if (!t.enough_data) { verdict = 'Not enough data yet to call it (need ≥30 approaches each)'; cls = 'air'; }
  else if (t.significant) { verdict = `${leader} is ahead — statistically significant (p = ${t.p_value.toFixed(2)})`; cls = 'warm'; }
  else { verdict = `Not statistically significant (p = ${t.p_value.toFixed(2)})`; cls = 'air'; }
  return el('div', { class: 'sig' },
    el('div', { class: 'sigrates' },
      `${a} ${pct(sig.a_conv)}${ci(sig.a_ci)}  ·  ${b} ${pct(sig.b_conv)}${ci(sig.b_ci)}`),
    el('span', { class: 'badge badge-' + cls }, verdict));
}
```

Wire `sigLine(sig, a, b)` into the "Head to head" panel children (after `mbox`/legend). Add minimal CSS for `.sig`/`.sigrates` to `jungle.css` if needed (mirror existing small-text/badge styles); reuse `.badge` + an existing colour modifier (e.g. `.badge-warm`/`.badge-air`, or add them if absent).

- [ ] **Step 3: DOM smoke.** Run:
```bash
rm -rf /tmp/tq_demo && TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/seed_demo.py
TARZANIQ_DATA=/tmp/tq_demo .venv/bin/python tests/run_demo_server.py --port 43991 >/tmp/tq_srv.log 2>&1 &
SRV=$!; sleep 2
node tests/dom_smoke.mjs http://127.0.0.1:43991; RC=$?; kill $SRV; exit $RC
```
Expected `ALL GREEN` (the seeded demo has multiple apes, so the Compare page renders the new line; it must not break any existing assertion). If dom_smoke navigates to a compare route, confirm it still passes; otherwise the line is exercised only on the compare page render.

- [ ] **Step 4: Commit**

```bash
git add tarzaniq/static/js/pages.js tarzaniq/static/css/jungle.css
git commit -m "feat(ui): conversion significance line on the Compare page

Compare now shows both conversion rates with Wilson CIs and a plain-language
verdict from /api/compare (significant / not significant / not enough data).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification
- [ ] `./run_tests.sh && .venv/bin/python tests/test_significance.py && .venv/bin/python tests/test_archive.py` → all green.
- [ ] PR `feat/significance-2026-06-25` → `main`, self-merge.

## Self-Review
**Spec coverage:** significance module (Task 1) ✓; conversion_ci + compare_significance over comparable days (Task 2) ✓; /api/compare route (Task 3) ✓; Compare-page verdict line (Task 4) ✓; tests for the math + agg + route + dom (Tasks 1–4) ✓. Non-goals respected (conversion-only; no deps).
**Placeholder scan:** all code complete; Task 4 reads the real renderer and supplies the exact `sigLine` helper.
**Type consistency:** `wilson_interval(successes,trials)`/`two_proportion_test(s1,n1,s2,n2)`/`compare_significance(con,a,b)` consistent across Tasks 1–3; the route returns the Task-2 dict the Task-4 UI reads (`test`, `a_conv`, `a_ci`, …).
