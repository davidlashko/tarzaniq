# Feature C — Statistical Significance on Comparisons — Design Spec

- **Date:** 2026-06-25
- **Status:** Approved (owner asked for it directly; building autonomously)
- **Branch:** `feat/significance-2026-06-25`
- **Builds on:** Feature B comparisons (employee summaries, Compare page).

## 1. Goal

When the dashboard compares photographers, tell the user whether a difference in the headline
metric (**conversion = warm_persons / cold_persons**) is *statistically real* or just small-sample
noise. Conversion is a proportion, so: a **two-proportion z-test** for head-to-head significance,
and a **Wilson score confidence interval** for each rate. No new dependencies — implemented with
stdlib `math` (`erf` gives the normal CDF).

## 2. Why these tests

- **Conversion is a proportion** (warm out of cold approaches). Comparing two proportions → the
  two-sample **z-test for proportions** (pooled), two-sided p-value.
- **Wilson interval** (not the normal approximation) is the correct CI for a proportion at the
  small samples a single day/photographer produces — it stays inside [0,1] and behaves at the
  extremes (0% / 100%).
- These make the comparison honest: "Marko 62% vs Ana 48%" might be noise if each only approached
  a handful of people. The app should say so.

## 3. The module — `tarzaniq/significance.py` (new, pure, no deps beyond `math`)

```
normal_cdf(z: float) -> float                       # 0.5*(1+erf(z/sqrt(2)))
wilson_interval(successes: int, trials: int, z: float = 1.96) -> (low, high)
    # Wilson score CI for a proportion; clamped to [0,1]; (0.0, 0.0) when trials == 0.
two_proportion_test(s1, n1, s2, n2) -> dict
    # {p1, p2, diff (p1-p2), z, p_value (two-sided), significant (p < 0.05),
    #  enough_data (both n >= MIN_TRIALS)}
    # Guards: n==0 or zero pooled variance -> z=0.0, p_value=1.0, significant=False.
MIN_TRIALS = 30   # below this, flag enough_data=False ("need more data") but still compute
```

Pure functions over counts; no I/O; unit-tested against known values.

## 4. Aggregation wiring — `tarzaniq/agg.py`

- **`employee_summaries`**: add `conversion_ci: [low, high]` per employee = `wilson_interval(warm_persons, cold_persons)`. Cheap (uses the cold/warm totals already summed). Zero extra DB/I/O — preserves the instant-read property.
- **New `compare_significance(con, a, b) -> dict`**: builds `employee_summaries(_comparable_days(con))`, then returns
  `{a, b, a_conv, b_conv, a_ci, b_ci, a_cold, a_warm, b_cold, b_warm, test: two_proportion_test(a_warm, a_cold, b_warm, b_cold)}`.
  Returns `None` if either employee is absent. Uses `_comparable_days` so legacy days don't pollute the test (consistent with Feature B).

## 5. Server — `tarzaniq/server.py`

- **`GET /api/compare/<a>/<b>`** → `compare_significance(con, a, b)`; 404 if either is missing. (Mirrors the existing `/api/employee/<name>` route style.)

## 6. Dashboard — `tarzaniq/static/js/pages.js`

On the **Compare** page, under "Head to head", add a significance line fetched from
`/api/compare/<a>/<b>`:
- Both rates with CIs: `"Marko 62% (54–70%) · Ana 48% (40–56%)"`.
- Verdict: if `test.significant` → `"Difference is statistically significant (p = 0.03)"` (use the
  leader's name); else if `!test.enough_data` → `"Not enough data yet to call it (need ≥30 approaches each)"`;
  else → `"Difference is not statistically significant (p = 0.21)"`.
- Style with the existing panel/badge classes; a small "p=" pill. Additive only.

(Optional, if cheap: show the conversion CI on the Ape profile headline too — but the Compare page
is the required surface.)

## 7. Non-goals

- No significance on non-proportion metrics (warm/hr etc.) in v1 — conversion is the headline and
  the only true proportion. (The two-proportion test is wrong for rates; keep scope honest.)
- No multiple-comparison correction across the whole leaderboard (would need care; out of scope).
- No new dependencies (no scipy/numpy for this — stdlib `math` only).

## 8. Testing

New `tests/test_significance.py` (standalone script): `normal_cdf` against known values
(cdf(0)=0.5, cdf(1.96)≈0.975); `wilson_interval` sane (contains p, within [0,1], trials=0 → (0,0),
wider for small n); `two_proportion_test` (clearly-different large samples → significant, p small;
identical → not significant, p≈1; tiny samples → enough_data False; n=0 guarded). Extend `test_e2e`
to assert `employee_summaries` carries `conversion_ci`. Add a `/api/compare/<a>/<b>` smoke to
`test_server`. Keep the whole suite green; dom_smoke stays green with the new Compare line.

## 9. Build plan (one branch → one PR)

1. `significance.py` + `test_significance.py`.
2. `agg`: `conversion_ci` in summaries + `compare_significance` + tests.
3. server `/api/compare/<a>/<b>` + smoke.
4. Compare-page significance line + dom_smoke.

## 10. Honest notes

- The two-proportion z-test assumes independent approaches; in reality a photographer's day has
  structure, so treat p-values as a guide, not gospel — hence the plain-language verdicts and the
  "need more data" guard rather than a bare number.
- `MIN_TRIALS=30` is a pragmatic floor for the normal approximation; below it the Wilson CI is still
  shown (it degrades gracefully) but the head-to-head verdict says "not enough data."
