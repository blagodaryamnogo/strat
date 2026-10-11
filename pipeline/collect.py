"""Collect raw Amazon US written reviews via the upstream scraper's Woot endpoint.

Uses the third-party script's own fetch_reviews() (no rewritten network code) and
replicates its `max` mode (5 star filters x 4 sort orders), but saves every
(star, sort) response *before* deduplication so star-bucket caps can be audited.

Usage:  python3 pipeline/collect.py [ASIN ...]      (default: all products)
Output: data/raw/{ASIN}/combo_s{star}_o{sort}.json, data/audits/collection_log.json
"""
import importlib.util
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.products import PRODUCTS  # noqa: E402

SCRAPER = ROOT / "tools/amazon-review-scraper/skills/amazon-review-scraper/scripts/amazon_review_scraper.py"
RAW = ROOT / "data/raw"
LOG = ROOT / "data/audits/collection_log.json"
PER_COMBO_CAP = 100  # documented upstream hard limit per (filter, sort)


def load_scraper():
    spec = importlib.util.spec_from_file_location("upstream_scraper", SCRAPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def preflight(asin):
    """One request to record the real HTTP outcome (the upstream code only prints errors)."""
    url = f"https://www.woot.com/review/Reviews/{asin}?filter=0&isVerified=false&sort=0&page=1"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}), timeout=15) as r:
            return {"ok": True, "status": r.status}
    except Exception as e:  # record the actual error verbatim
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def collect(asin, scraper):
    out = RAW / asin
    out.mkdir(parents=True, exist_ok=True)
    combos = []
    for star in [5, 4, 3, 2, 1]:
        for sort_val in [0, 1, 2, 3]:
            fetched_at = datetime.now(timezone.utc).isoformat()
            revs = scraper.fetch_reviews(asin, filter_val=star, sort_val=sort_val, delay=0.3)
            (out / f"combo_s{star}_o{sort_val}.json").write_text(json.dumps(
                {"asin": asin, "star_filter": star, "sort": sort_val, "fetched_at": fetched_at,
                 "endpoint": f"https://www.woot.com/review/Reviews/{asin}", "reviews": revs},
                ensure_ascii=False, indent=1))
            combos.append({"star": star, "sort": sort_val, "returned": len(revs),
                           "hit_cap": len(revs) >= PER_COMBO_CAP})
    return combos


def main(asins):
    scraper = load_scraper()
    log = json.loads(LOG.read_text()) if LOG.exists() else {"runs": []}
    run = {"started_at": datetime.now(timezone.utc).isoformat(), "method": "Woot review endpoint via mrlong0129/amazon-review-scraper fetch_reviews()", "products": []}
    for p in PRODUCTS:
        if asins and p["asin"] not in asins:
            continue
        pf = preflight(p["asin"])
        entry = {"competitor": p["competitor"], "asin": p["asin"], "preflight": pf}
        if pf["ok"]:
            entry["combos"] = collect(p["asin"], scraper)
            entry["raw_returned_total"] = sum(c["returned"] for c in entry["combos"])
        else:
            entry["combos"] = []
            entry["note"] = "Not collected: endpoint unreachable. No substitute data created."
        print(json.dumps({k: entry[k] for k in ("competitor", "asin", "preflight")}), file=sys.stderr)
        run["products"].append(entry)
    run["finished_at"] = datetime.now(timezone.utc).isoformat()
    log["runs"].append(run)
    LOG.write_text(json.dumps(log, indent=1))


if __name__ == "__main__":
    main(set(sys.argv[1:]))
