"""data/processed/reviews.json -> data/processed/analysis.json (the single source of truth).

Every number shown by the web app and the PDF is read from analysis.json.
Themes are deterministic keyword rules; each match stores review IDs so it can be audited.
"""
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.nps import classify, rank, score  # noqa: E402
from pipeline.products import COMPARABILITY_NOTE, PRODUCTS  # noqa: E402

LIMITATIONS = [
    "Review-derived NPS is not a survey of all purchasers; reviewers self-select (voluntary response bias).",
    "Possible fake or incentivized reviews (including Vine) are not removed; they are disclosed where flagged.",
    "The Woot endpoint returns at most 100 reviews per star-filter x sort combination; where a star bucket hits that cap, "
    "that bucket is under-collected. If capped buckets are mainly 5-star (typical for popular products) NPS is biased downward; "
    "if 1-3 star buckets are capped, upward. Cap hits are listed in the collection log.",
    "Written reviews only: star-only ratings (often the large majority of Amazon ratings) are not included.",
    "Product-level, not company-wide, loyalty: one SKU per brand.",
    "Review volume is not sales volume.",
    "Small differences in NPS (within the 95% intervals shown) should not be read as meaningful loyalty differences.",
]

MIN_N = 50  # assignment target; smaller samples are reported, and flagged

THEMES = {
    "Packaging / container failure": r"\b(leak\w*|spill\w*|broke\w*|torn|ripp\w*|seal\w*|zip\w*|lid|bag (was )?open|reseal\w*|packag\w*)\b",
    "Clumping / moisture": r"\b(clump\w*|caked?|hard(ened)? (as a )?rock|damp|wet|moist\w*|soggy)\b",
    "Texture / crystal size": r"\b(texture|crunch\w*|flak\w*|crumb\w*|dust|powder\w*|too (fine|coarse)|grain\w*)\b",
    "Flavor / taste quality": r"\b(taste[sd]?|flavou?r\w*|bitter|bland|metallic|chemical|salty)\b",
    "Price / value": r"\b(price\w*|expensive|overpriced|pricey|value|cost\w*|worth)\b",
    "Small quantity / portion": r"\b(small|tiny|half (full|empty)|not (much|a lot)|quantity|amount)\b",
    "Shipping damage / delivery": r"\b(arriv\w*|ship\w*|deliver\w*|damaged|crushed)\b",
    "Sourcing / authenticity / contaminants": r"\b(fake|counterfeit|authentic\w*|sourc\w*|origin|microplastic\w*|lead|heavy metal\w*|dirt|debris|grit\w*|sand|impurit\w*)\b",
    "Gifting": r"\b(gift\w*|present|stocking)\b",
}


def themes(reviews):
    det = [r for r in reviews if r["rating"] <= 3]
    out = []
    for name, pat in THEMES.items():
        rx = re.compile(pat, re.I)
        hits_all = [r for r in reviews if rx.search(f"{r['title'] or ''} {r['review_text'] or ''}")]
        hits_det = [r for r in hits_all if r["rating"] <= 3]
        by_comp = {}
        for r in hits_det:
            by_comp[r["competitor"]] = by_comp.get(r["competitor"], 0) + 1
        out.append({
            "theme": name, "pattern": pat,
            "mentions_all": len(hits_all), "mentions_detractor": len(hits_det),
            "pct_of_detractors": (len(hits_det) / len(det) * 100) if det else None,
            "detractor_mentions_by_competitor": by_comp,
            "review_ids_detractor": [r["review_id"] for r in hits_det],
            "example_review_ids": [r["review_id"] for r in sorted(hits_det, key=excerpt_key)[:2]],
        })
    out.sort(key=lambda t: -t["mentions_detractor"])
    return out, len(det)


def excerpt_key(r):
    txt = r["review_text"] or ""
    ok = 60 <= len(txt) <= 400
    return (not ok, r["verified_purchase"] is not True, -(int((r["review_date"] or "0000").replace("-", "")[:8] or 0)), r["review_id"])


def pick_excerpt(reviews, pred):
    pool = sorted([r for r in reviews if pred(r["rating"]) and r["review_text"]], key=excerpt_key)
    return pool[0]["review_id"] if pool else None


def build(reviews, products=PRODUCTS):
    comps = []
    scores = {}
    for p in products:
        mine = [r for r in reviews if r["competitor"] == p["competitor"]]
        s = score([r["rating"] for r in mine])
        scores[p["competitor"]] = s
        dates = sorted(r["review_date"] for r in mine if r["review_date"])
        comps.append({**{k: p[k] for k in ("competitor", "asin", "product_name", "package_size", "product_type", "listing_url")},
                      **s, "below_min_n": s["n"] < MIN_N,
                      "date_range": [dates[0], dates[-1]] if dates else None,
                      "collection_sources": sorted({r["collection_source"] for r in mine}),
                      "verification_counts": {v: sum(1 for r in mine if r["verification_status"] == v) for v in sorted({r["verification_status"] for r in mine})}})
    r_base, r_alt = rank(scores, "nps"), rank(scores, "alt_nps")
    for c in comps:
        c["rank"], c["alt_rank"] = r_base[c["competitor"]], r_alt[c["competitor"]]
        c["rank_change"] = (c["rank"] - c["alt_rank"]) if c["rank"] and c["alt_rank"] else None  # + = moved up
    scored = [c for c in comps if c["nps"] is not None]

    # Loyalty vs volume. Marketplace totals were not obtainable, so x = written reviews retrieved & scored.
    wedge = {"status": "insufficient_data", "rule": "volume >= median retrieved count AND baseline NPS < median NPS", "candidates": []}
    if len(scored) >= 3:
        mv = statistics.median(c["n"] for c in scored)
        mn = statistics.median(c["nps_exact"] for c in scored)
        wedge.update(median_volume=mv, median_nps=mn, status="evaluated",
                     candidates=[c["competitor"] for c in scored if c["n"] >= mv and c["nps_exact"] < mn])
        if not wedge["candidates"]:
            wedge["status"] = "no_classic_wedge"
    th, n_det = themes(reviews) if reviews else ([], 0)
    excerpts = {
        "promoter_5": pick_excerpt(reviews, lambda x: x == 5),
        "passive_4": pick_excerpt(reviews, lambda x: x == 4),
        "detractor_1_3": pick_excerpt(reviews, lambda x: x <= 3),
    }
    total = sum(c["n"] for c in comps)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if len(scored) == len(products) else ("partial" if scored else "no_data"),
        "total_reviews": total,
        "min_n_target": MIN_N,
        "competitors": sorted(comps, key=lambda c: (c["rank"] is None, c["rank"] or 0, c["competitor"])),
        "volume_metric": "Distinct written reviews retrieved and scored (NOT total Amazon ratings; marketplace totals could not be retrieved)",
        "wedge": wedge,
        "themes": th, "detractor_total": n_det,
        "excerpts": excerpts,
        "comparability_note": COMPARABILITY_NOTE,
        "limitations": LIMITATIONS,
    }


def main():
    reviews = json.loads((ROOT / "data/processed/reviews.json").read_text())
    a = build(reviews)
    (ROOT / "data/processed/analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1))
    for c in a["competitors"]:
        print(f"{c['competitor']:20} n={c['n']:4} NPS={c['nps']} alt={c['alt_nps']} rank={c['rank']}")
    print("status:", a["status"])


if __name__ == "__main__":
    main()
