"""Amazon star-rating histograms, transcribed by hand from each listing.

Input: data/raw/histograms/star_histograms.csv (one row per ASIN; competitor/asin/listing_url are
pre-filled, everything else is typed from the live listing). A row whose pct_* fields are all
blank counts as "not entered" and is not an error; a partly filled or inconsistent row is an
error and is not used. Nothing here is estimated: a missing value stays missing.

Amazon shows whole-number percentages that may not sum to exactly 100; shares are
normalized by their sum, and the rounding uncertainty is disclosed with the score.
"""
import csv
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/raw/histograms/star_histograms.csv"
STARS = (5, 4, 3, 2, 1)
REQUIRED = [f"pct_{s}" for s in STARS] + ["total_ratings", "recorded_on", "recorded_by"]


def _int(v):
    v = (v or "").strip().replace(",", "").rstrip("%")
    return int(v) if re.fullmatch(r"\d+", v) else None


def load(path=PATH, products=None):
    """Returns ({asin: histogram}, [error strings])."""
    from pipeline.products import PRODUCTS
    known = {p["asin"] for p in (products or PRODUCTS)}
    out, errors = {}, []
    if not path.exists():
        return out, errors
    with path.open(newline="", encoding="utf-8") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            asin = (row.get("asin") or "").strip()
            if not any((row.get(k) or "").strip() for k in REQUIRED):
                continue  # not entered yet
            where = f"{path.name}:{line} ({asin or 'no ASIN'})"
            if asin not in known:
                errors.append(f"{where}: ASIN is not one of the analyzed products"); continue
            missing = [k for k in REQUIRED if not (row.get(k) or "").strip()]
            if missing:
                errors.append(f"{where}: missing {', '.join(missing)}"); continue
            pct = {s: _int(row[f"pct_{s}"]) for s in STARS}
            total = _int(row["total_ratings"])
            bad = [f"pct_{s}" for s, v in pct.items() if v is None or v > 100] + ([] if total else ["total_ratings"])
            if bad:
                errors.append(f"{where}: not a whole number in range: {', '.join(bad)}"); continue
            s = sum(pct.values())
            if not 97 <= s <= 103:
                errors.append(f"{where}: percentages sum to {s}, expected about 100 (check for a typo)"); continue
            try:
                rec_on = date.fromisoformat(row["recorded_on"].strip()).isoformat()
            except ValueError:
                errors.append(f"{where}: recorded_on must be YYYY-MM-DD"); continue
            avg = (row.get("average_rating") or "").strip()
            out[asin] = {"pct": pct, "pct_sum": s, "total_ratings": total,
                         "average_rating": float(avg) if re.fullmatch(r"\d(\.\d)?", avg) else None,
                         "recorded_on": rec_on, "recorded_by": row["recorded_by"].strip(),
                         "notes": (row.get("notes") or "").strip(), "raw_ref": f"data/raw/histograms/{path.name}:{line}"}
    return out, errors


def score(h):
    """NPS from shares normalized to the entered sum. Each displayed % is rounded by Amazon (+/-0.5 pt),
    so the detractor share (3 values) and promoter share (1 value) carry up to +/-2 pts of rounding error."""
    tot = h["pct_sum"]
    share = {s: h["pct"][s] / tot * 100 for s in STARS}
    det = share[3] + share[2] + share[1]
    nps_exact, alt_exact = share[5] - det, share[5] + share[4] - det
    return {"promoter_pct": share[5], "passive_pct": share[4], "detractor_pct": det,
            "nps_exact": nps_exact, "alt_nps_exact": alt_exact, "rounding_error_pts": 2}
