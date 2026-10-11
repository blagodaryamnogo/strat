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
    "The Woot endpoint returns at most 100 reviews per star-filter x sort combination (about 110-125 distinct reviews per star "
    "after combining four sort orders). Where several star buckets hit that cap, the retrieved star mix is set by the cap, not by "
    "customers, so that product's NPS is shown for transparency but is NOT ranked or used in the wedge. "
    "Where only the 5-star bucket is capped, the NPS is a lower bound. Per-product cap hits are listed in the tables; raw counts are in data/audits/collection_log.json.",
    "Written reviews only: star-only ratings (often the large majority of Amazon ratings) are not included.",
    "Product-level, not company-wide, loyalty: one SKU per brand.",
    "Review volume is not sales volume.",
    "Small differences in NPS (within the 95% intervals shown) should not be read as meaningful loyalty differences.",
]

CAP = 100  # upstream per (star filter x sort) limit; see pipeline/collect.py

MIN_N = 50  # assignment target; smaller samples are reported, and flagged

THEMES = {
    "Packaging / container failure": r"\b(leak\w*|spill\w*|torn|ripp\w*|(un)?seal(ed)?|zip\w*|lid|bag (was )?open|reseal\w*|broken open|"
                                     r"(damaged|crushed|smashed|poor|bad|cheap|flimsy|terrible) packaging|packaging (was |is )?(damaged|crushed|smashed|poor|bad|terrible|flimsy))\b",
    "Clumping / moisture": r"\b(clump\w*|caked|hard(ened)? (as a )?rock|damp|wet|moist\w*|soggy)\b",
    "Texture / crystal size": r"\b(texture|not (very |at all )?flak(y|ey)|no flakes|(crushed|broken|tiny|small) (salt|flakes|crystals)|"
                              r"crumb\w*|dust|powder\w*|too (fine|coarse))\b",
    "Flavor / taste quality": r"\b(taste[sd]?|flavou?r\w*|bitter|bland|metallic|chemical)\b",
    "Price / value": r"\b(price\w*|expensive|overpriced|pricey|value|cost\w*|worth)\b",
    "Small quantity / portion": r"\b((small|tiny|little) (box|bag|package|container|jar|pouch|amount)|half (full|empty)|"
                                r"not (much|a lot) (of )?salt|quantity|only \d+(\.\d+)? ?(oz|ounces?))\b",
    "Shipping damage / delivery": r"\b(arrived (damaged|broken|open\w*|crushed|smashed|leaking|torn)|damaged|crushed|smashed|ship(ping|ped) (box|damage)|"
                                  r"(box|package|container) (was |were )?(open\w*|broken|crushed|damaged))\b",
    "Sourcing / authenticity / contaminants": r"\b(fake|counterfeit|authentic\w*|sourc\w*|microplastic\w*|lead content|heavy metal\w*|dirt|debris|"
                                              r"grit\w*|sand|impurit\w*|rocks?|pebbles?|stones?)\b",
    "Gifting": r"\b(gift\w*|stocking stuffer)\b",
}


def load_caps(log_path=ROOT / "data/audits/collection_log.json"):
    """{asin: {"capped_stars": [...], "uneven_stars": [...]}} from the latest run that collected each ASIN."""
    out = {}
    if not log_path.exists():
        return out
    for run in json.loads(log_path.read_text())["runs"]:
        for e in run["products"]:
            if not e.get("combos"):
                continue
            by_star = {}
            for c in e["combos"]:
                by_star.setdefault(c["star"], []).append(c["returned"])
            out[e["asin"]] = {
                "capped_stars": sorted((s for s, v in by_star.items() if max(v) >= CAP), reverse=True),
                # sorts of the same star bucket returning different counts = a request failed mid-pagination
                "uneven_stars": sorted((s for s, v in by_star.items() if len(set(v)) > 1), reverse=True),
            }
    return out


def sample_validity(capped):
    """complete: nothing capped. promoters_capped: only 5-star capped, so observed NPS is a lower bound.
    capped_mixed: a 1-4 star bucket also capped, so the star mix reflects the retrieval cap, not customers;
    the NPS is shown for transparency but not ranked or used in the wedge."""
    if not capped:
        return "complete"
    return "promoters_capped" if set(capped) == {5} else "capped_mixed"


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


def build(reviews, products=PRODUCTS, caps=None):
    caps = caps or {}
    comps = []
    scores = {}
    for p in products:
        mine = [r for r in reviews if r["competitor"] == p["competitor"]]
        s = score([r["rating"] for r in mine])
        cap = caps.get(p["asin"], {"capped_stars": [], "uneven_stars": []})
        validity = sample_validity(cap["capped_stars"])
        if validity != "capped_mixed":
            scores[p["competitor"]] = s
        dates = sorted(r["review_date"] for r in mine if r["review_date"])
        comps.append({**{k: p[k] for k in ("competitor", "asin", "product_name", "package_size", "product_type", "listing_url")},
                      **s, "below_min_n": s["n"] < MIN_N,
                      "capped_stars": cap["capped_stars"], "uneven_stars": cap["uneven_stars"],
                      "sample_validity": validity, "comparable": validity != "capped_mixed",
                      "date_range": [dates[0], dates[-1]] if dates else None,
                      "collection_sources": sorted({r["collection_source"] for r in mine}),
                      "verification_counts": {v: sum(1 for r in mine if r["verification_status"] == v) for v in sorted({r["verification_status"] for r in mine})}})
    r_base, r_alt = rank(scores, "nps"), rank(scores, "alt_nps")
    for c in comps:
        c["rank"], c["alt_rank"] = r_base.get(c["competitor"]), r_alt.get(c["competitor"])
        c["rank_change"] = (c["rank"] - c["alt_rank"]) if c["rank"] and c["alt_rank"] else None  # + = moved up
    scored = [c for c in comps if c["nps"] is not None and c["comparable"]]

    # Loyalty vs volume. Marketplace totals were not obtainable, so x = written reviews retrieved & scored.
    wedge = {"status": "insufficient_data", "rule": "volume >= median retrieved count AND baseline NPS < median NPS (comparable samples only)",
             "candidates": [], "excluded_not_comparable": [c["competitor"] for c in comps if c["nps"] is not None and not c["comparable"]]}
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
        "status": "ok" if all(c["nps"] is not None for c in comps) else ("partial" if any(c["nps"] is not None for c in comps) else "no_data"),
        "total_reviews": total,
        "min_n_target": MIN_N,
        "competitors": sorted(comps, key=lambda c: (c["rank"] is None, c["rank"] or 0, c["competitor"])),
        "volume_metric": "Distinct written reviews retrieved and scored (NOT total Amazon ratings; marketplace totals could not be retrieved)",
        "wedge": wedge,
        "themes": th, "detractor_total": n_det,
        "excerpts": excerpts,
        "comparability_note": COMPARABILITY_NOTE,
        "limitations": LIMITATIONS + [
            f"{c['competitor']}: {'/'.join(str(x) for x in c['capped_stars'])}-star bucket(s) hit the retrieval cap, so "
            + ("its NPS is not comparable and is not ranked." if not c["comparable"] else "its NPS is a lower bound.")
            for c in comps if c["capped_stars"]],
    }


def main():
    reviews = json.loads((ROOT / "data/processed/reviews.json").read_text())
    a = build(reviews, caps=load_caps())
    (ROOT / "data/processed/analysis.json").write_text(json.dumps(a, ensure_ascii=False, indent=1))
    for c in a["competitors"]:
        print(f"{c['competitor']:20} n={c['n']:4} NPS={c['nps']} alt={c['alt_nps']} rank={c['rank']} alt_rank={c['alt_rank']} {c['sample_validity']} capped={c['capped_stars']}")
    print("status:", a["status"])


if __name__ == "__main__":
    main()
