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
