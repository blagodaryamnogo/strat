"""Deterministic review-derived NPS engine. Pure functions, no I/O.

Baseline:     5 = Promoter, 4 = Passive, 1-3 = Detractor.
Alternative:  4-5 = Promoter, 1-3 = Detractor (no Passives).
NPS is computed at full precision, then rounded half away from zero for display.
Ranks use the displayed (rounded) NPS so the table never shows an order the
numbers don't support; equal displayed scores share a rank (1, 2, 2, 4).
"""
import math

VALID = {1, 2, 3, 4, 5}


def classify(rating, method="baseline"):
    if rating not in VALID:
        raise ValueError(f"invalid rating {rating!r}")
    if rating == 5:
        return "promoter"
    if rating == 4:
        return "promoter" if method == "alternative" else "passive"
    return "detractor"


def round_half_away(x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def score(ratings):
    """ratings: iterable of ints. Invalid values are excluded and counted, never scored."""
    ratings = list(ratings)
    valid = [r for r in ratings if isinstance(r, int) and not isinstance(r, bool) and r in VALID]
    invalid = len(ratings) - len(valid)
    n = len(valid)
    counts = {s: valid.count(s) for s in (5, 4, 3, 2, 1)}
    base = {"n": n, "invalid_excluded": invalid, "star_counts": counts}
    if n == 0:
        return {**base, "promoter_pct": None, "passive_pct": None, "detractor_pct": None,
                "four_star_pct": None, "nps_exact": None, "nps": None,
                "alt_nps_exact": None, "alt_nps": None, "delta_exact": None,
                "ci95_low": None, "ci95_high": None}
    p, pa, d = counts[5], counts[4], counts[3] + counts[2] + counts[1]
    pp, pap, dp = p / n * 100, pa / n * 100, d / n * 100
    nps_exact = pp - dp
    alt_exact = (p + pa) / n * 100 - dp
    # Normal-approximation 95% CI for NPS (multinomial variance); indicative only.
    fp, fd = p / n, d / n
    se = 100 * math.sqrt(max(fp + fd - (fp - fd) ** 2, 0) / n)
    return {**base, "promoters": p, "passives": pa, "detractors": d,
            "promoter_pct": pp, "passive_pct": pap, "detractor_pct": dp,
            "four_star_pct": pap,
            "nps_exact": nps_exact, "nps": round_half_away(nps_exact),
            "alt_nps_exact": alt_exact, "alt_nps": round_half_away(alt_exact),
            "delta_exact": alt_exact - nps_exact,
            "ci95_low": max(-100.0, nps_exact - 1.96 * se), "ci95_high": min(100.0, nps_exact + 1.96 * se)}


def rank(scores, key="nps"):
    """scores: {name: score_dict}. Returns {name: rank or None}; standard competition ranking."""
    vals = {k: v[key] for k, v in scores.items() if v[key] is not None}
    return {k: (1 + sum(1 for o in vals.values() if o > vals[k]) if k in vals else None) for k in scores}
