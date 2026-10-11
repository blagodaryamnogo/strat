"""Raw responses -> validated, deduplicated review records + audit report.

Sources read:
  data/raw/{ASIN}/combo_s*_o*.json   (Woot endpoint, written by collect.py)
  data/raw/manual/*.csv              (manually collected public reviews; see README)
Writes: data/processed/reviews.json, data/exports/reviews.csv, data/audits/audit.json
"""
import csv
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.products import PRODUCTS  # noqa: E402

FIELDS = ["review_id", "competitor", "product_name", "asin", "rating", "title", "review_text",
          "review_date", "author", "verified_purchase", "marketplace", "collection_source",
          "source_product_url", "direct_review_url", "collected_at", "verification_status", "raw_ref"]
MANUAL_COLS = ["asin", "rating", "title", "review_text", "review_date", "author",
               "verified_purchase", "source_name", "source_url", "collected_at"]


def norm_text(s):
    return re.sub(r"[^a-z0-9]", "", html.unescape(s or "").lower())


def parse_date(desc):
    m = re.search(r"on ([A-Z][a-z]+ \d{1,2}, \d{4})", desc or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_rating(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else None


def from_woot(rec, product, combo, path):
    return {
        "review_id": rec.get("Id") or rec.get("ReviewId") or None,
        "competitor": product["competitor"], "product_name": product["product_name"], "asin": product["asin"],
        "rating": parse_rating(rec.get("OverallRating")),
        "title": html.unescape(rec.get("Title") or "") or None,
        "review_text": rec.get("Text") or None,
        "review_date": parse_date(rec.get("OriginDescription")),
        "author": rec.get("Author") or None,
        "verified_purchase": rec.get("IsVerifiedPurchase"),
        "marketplace": "Amazon US",
        "collection_source": "Woot review endpoint (woot.com/review/Reviews/{ASIN}), Amazon US review data",
        "source_product_url": product["listing_url"],
        "direct_review_url": None,  # endpoint provides no permalink; never constructed
        "collected_at": combo["fetched_at"],
        "verification_status": "source_retrieved",
        "raw_ref": f"{path.relative_to(ROOT)}",
        "_star_filter": combo["star_filter"],
    }


def from_manual(row, path, lineno, by_asin):
    p = by_asin.get((row.get("asin") or "").strip())
    vp = (row.get("verified_purchase") or "").strip().lower()
    return {
        "review_id": None,
        "competitor": p["competitor"] if p else None, "product_name": p["product_name"] if p else None,
        "asin": (row.get("asin") or "").strip() or None,
        "rating": parse_rating(row.get("rating")),
        "title": row.get("title") or None, "review_text": row.get("review_text") or None,
        "review_date": row.get("review_date") or None, "author": row.get("author") or None,
        "verified_purchase": True if vp in ("true", "yes", "1") else False if vp in ("false", "no", "0") else None,
        "marketplace": "Amazon US",
        "collection_source": f"Manual transcription: {row.get('source_name') or 'unspecified'}",
        "source_product_url": p["listing_url"] if p else None,
        "direct_review_url": row.get("source_url") or None,
        "collected_at": row.get("collected_at") or None,
        "verification_status": "manually_recorded",
        "raw_ref": f"{path.relative_to(ROOT)}:{lineno}",
        "_star_filter": None,
    }


def build(raw_dir=ROOT / "data/raw", products=PRODUCTS):
    by_asin = {p["asin"]: p for p in products}
    candidates, rejected = [], []
    retrieved = {p["competitor"]: 0 for p in products}
    for p in products:
        for path in sorted((raw_dir / p["asin"]).glob("combo_*.json")):
            combo = json.loads(path.read_text())
            for rec in combo["reviews"]:
                retrieved[p["competitor"]] += 1
                candidates.append(from_woot(rec, p, combo, path))
    for path in sorted((raw_dir / "manual").glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                r = from_manual(row, path, i, by_asin)
                if r["competitor"]:
                    retrieved[r["competitor"]] += 1
                candidates.append(r)

    accepted, seen, text_seen = [], {}, {}
    dupes, uncertain, star_mismatch = 0, [], 0
    for r in candidates:
        reason = None
        if r["asin"] not in by_asin:
            reason = "unknown_or_mismatched_asin"
        elif r["rating"] not in (1, 2, 3, 4, 5):
            reason = "invalid_or_missing_rating"
        if reason:
            rejected.append({"reason": reason, "raw_ref": r["raw_ref"], "rating": r["rating"], "asin": r["asin"]})
            continue
        if r["_star_filter"] is not None and r["_star_filter"] != r["rating"]:
            star_mismatch += 1
        key = (r["asin"], r["author"] or "", norm_text(r["title"]), norm_text(r["review_text"])[:100])
        if key in seen:
            dupes += 1
            seen[key]["raw_refs"].append(r["raw_ref"])
            continue
        tkey = (r["asin"], norm_text(r["review_text"])[:100])
        if r["review_text"] and tkey in text_seen:
            uncertain.append({"raw_ref": r["raw_ref"], "possible_duplicate_of": text_seen[tkey]})
        r = {k: v for k, v in r.items() if k != "_star_filter"}
        if not r["review_id"]:
            r["review_id"] = "srs-" + hashlib.sha1("|".join(map(str, key)).encode()).hexdigest()[:12]
        r["raw_refs"] = [r.pop("raw_ref")]
        seen[key] = r
        text_seen.setdefault(tkey, r["review_id"])
        accepted.append(r)

    audit = {"generated_at": datetime.now(timezone.utc).isoformat(), "per_competitor": {},
             "uncertain_duplicates_flagged": uncertain, "rejected": rejected,
             "star_filter_mismatches": star_mismatch}
    for p in products:
        c = p["competitor"]
        mine = [r for r in accepted if r["competitor"] == c]
        audit["per_competitor"][c] = {
            "asin": p["asin"], "raw_records_retrieved": retrieved[c],
            "accepted_unique": len(mine),
            "duplicates_removed": retrieved[c] - len(mine) - sum(1 for x in rejected if x["asin"] == p["asin"]),
            "invalid_rejected": sum(1 for x in rejected if x["asin"] == p["asin"]),
            "missing_text": sum(1 for r in mine if not r["review_text"]),
            "missing_date": sum(1 for r in mine if not r["review_date"]),
            "independently_matched": sum(1 for r in mine if r["verification_status"] == "independently_matched"),
            "excluded_from_scoring": 0,
            "final_analyzed_n": len(mine),
        }
    audit["exact_duplicates_removed_total"] = dupes
    return accepted, audit


def main():
    accepted, audit = build()
    (ROOT / "data/processed/reviews.json").write_text(json.dumps(accepted, ensure_ascii=False, indent=1))
    (ROOT / "data/audits/audit.json").write_text(json.dumps(audit, indent=1))
    with (ROOT / "data/exports/reviews.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS[:-1] + ["raw_refs"])
        w.writeheader()
        for r in accepted:
            w.writerow({**r, "raw_refs": ";".join(r["raw_refs"])})
    print(json.dumps(audit["per_competitor"], indent=1))


if __name__ == "__main__":
    main()
