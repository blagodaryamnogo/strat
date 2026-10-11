"""Unit + integrity tests. Synthetic data here is for testing only and never written to data/."""
import html
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import analyze, normalize  # noqa: E402
from pipeline.nps import classify, rank, round_half_away, score  # noqa: E402
from pipeline.products import PRODUCTS  # noqa: E402


def mk(p, pa, d):
    return [5] * p + [4] * pa + [2] * d


# ---------- scoring ----------
def test_60_20_20():
    assert score(mk(60, 20, 20))["nps"] == 40

def test_10_10_80():
    assert score(mk(10, 10, 80))["nps"] == -70

def test_all_four_star():
    s = score([4] * 100)
    assert (s["nps"], s["alt_nps"]) == (0, 100)

def test_all_five():
    assert score([5] * 7)["nps"] == 100

def test_all_detractors():
    assert score([1, 2, 3, 3])["nps"] == -100

def test_zero_reviews_is_na_not_zero():
    s = score([])
    assert s["nps"] is None and s["alt_nps"] is None and s["n"] == 0

def test_invalid_ratings_excluded_and_counted():
    s = score([5, 0, 6, None, "5", 4.0, True, 1])
    assert s["n"] == 2 and s["invalid_excluded"] == 6 and s["nps"] == 0

def test_classify_boundaries():
    assert [classify(r) for r in (5, 4, 3, 1)] == ["promoter", "passive", "detractor", "detractor"]
    assert classify(4, "alternative") == "promoter"
    with pytest.raises(ValueError):
        classify(0)

def test_small_sample_full_precision():
    s = score([5, 5, 4])  # 66.67 - 0
    assert s["nps"] == 67 and abs(s["nps_exact"] - 200 / 3) < 1e-12
    s = score([5, 1, 4])  # 33.33 - 33.33 = 0
    assert s["nps_exact"] == 0 and s["nps"] == 0

def test_delta_equals_four_star_pct():
    for data in (mk(3, 7, 2), [4] * 3 + [5], mk(11, 13, 17)):
        s = score(data)
        assert abs(s["delta_exact"] - s["four_star_pct"]) < 1e-9

def test_rounding_half_away_from_zero():
    assert [round_half_away(x) for x in (2.5, -2.5, 0.49, -0.5)] == [3, -3, 0, -1]
    assert score([5, 4])["nps"] == 50 and score(mk(1, 6, 1))["nps"] == 0

def test_percentages_sum_to_100():
    s = score(mk(13, 7, 9))
    assert abs(s["promoter_pct"] + s["passive_pct"] + s["detractor_pct"] - 100) < 1e-9

def test_rank_ties_and_none():
    sc = {"A": {"nps": 40}, "B": {"nps": 40}, "C": {"nps": 10}, "D": {"nps": None}}
    assert rank(sc) == {"A": 1, "B": 1, "C": 3, "D": None}

def test_rank_matches_displayed_order():
    sc = {k: score(v) for k, v in {"A": mk(60, 20, 20), "B": mk(10, 10, 80), "C": [5] * 5}.items()}
    r = rank(sc)
    order = sorted(sc, key=lambda k: -sc[k]["nps"])
    assert [r[k] for k in order] == [1, 2, 3]


# ---------- pipeline (synthetic raw fixtures in tmp_path) ----------
def write_combo(raw, asin, star, reviews):
    d = raw / asin
    d.mkdir(parents=True, exist_ok=True)
    (d / f"combo_s{star}_o0.json").write_text(json.dumps(
        {"asin": asin, "star_filter": star, "sort": 0, "fetched_at": "2026-01-01T00:00:00Z", "reviews": reviews}))


def rev(author, rating, text):
    return {"Author": author, "Title": f"t-{author}", "Text": text, "OverallRating": rating,
            "OriginDescription": "Reviewed in the United States on March 3, 2025", "IsVerifiedPurchase": True}


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr(normalize, "ROOT", tmp_path)
    raw = tmp_path / "raw"
    a = PRODUCTS[0]["asin"]
    write_combo(raw, a, 5, [rev("x", 5, "great salt crunchy flakes"), rev("y", 5, "love it")])
    write_combo(raw, a, 1, [rev("z", 1, "bag arrived torn and leaking"), rev("x", 5, "great salt crunchy flakes"), rev("bad", 9, "nope")])
    return raw


def test_dedup_invalid_and_audit(synthetic):
    acc, audit = normalize.build(synthetic)
    c = audit["per_competitor"][PRODUCTS[0]["competitor"]]
    assert c["raw_records_retrieved"] == 5
    assert c["accepted_unique"] == 3 and c["duplicates_removed"] == 1 and c["invalid_rejected"] == 1
    assert c["raw_records_retrieved"] == c["accepted_unique"] + c["duplicates_removed"] + c["invalid_rejected"]
    assert all(r["review_date"] == "2025-03-03" and r["direct_review_url"] is None for r in acc)
    dup = [r for r in acc if r["author"] == "x"][0]
    assert len(dup["raw_refs"]) == 2


def test_data_change_propagates(synthetic):
    acc, _ = normalize.build(synthetic)
    a1 = analyze.build(acc)
    c1 = a1["competitors"][0]
    assert c1["n"] == 3 and c1["nps"] == round_half_away((2 - 1) / 3 * 100)
    acc.append({**acc[0], "review_id": "extra", "rating": 1})
    c2 = analyze.build(acc)["competitors"][0]
    assert c2["n"] == 4 and c2["nps"] == 0  # 50% promoters - 50% detractors
    # theme rule finds the packaging complaint and stores the review id
    pk = [t for t in a1["themes"] if t["theme"].startswith("Packaging")][0]
    assert pk["mentions_detractor"] == 1 and len(pk["review_ids_detractor"]) == 1


# ---------- production dataset integrity (runs against real data/) ----------
PROD = ROOT / "data/processed/reviews.json"
ANALYSIS = ROOT / "data/processed/analysis.json"


def test_production_records_trace_to_raw():
    recs = json.loads(PROD.read_text())
    asins = {p["asin"]: p["competitor"] for p in PRODUCTS}
    for r in recs:
        assert r["rating"] in (1, 2, 3, 4, 5)
        assert asins[r["asin"]] == r["competitor"]
        assert r["verification_status"] in ("source_retrieved", "manually_recorded", "independently_matched")
        for ref in r["raw_refs"]:
            path = ROOT / ref.split(":")[0]
            assert path.is_file() and str(path).startswith(str(ROOT / "data/raw"))
            if path.suffix == ".json":
                texts = {html.unescape(x.get("Text") or "") for x in json.loads(path.read_text())["reviews"]}
                assert r["review_text"] in texts or r["review_text"] is None


def test_production_has_no_test_fixtures():
    assert not any("tmp" in ref or "pytest" in ref for r in json.loads(PROD.read_text()) for ref in r["raw_refs"])


def test_analysis_matches_engine_recompute():
    recs = json.loads(PROD.read_text())
    a = json.loads(ANALYSIS.read_text())
    assert a["total_reviews"] == len(recs)
    for c in a["competitors"]:
        s = score([r["rating"] for r in recs if r["competitor"] == c["competitor"]])
        assert (c["n"], c["nps"], c["alt_nps"]) == (s["n"], s["nps"], s["alt_nps"])
    audit = json.loads((ROOT / "data/audits/audit.json").read_text())
    for c in a["competitors"]:
        assert audit["per_competitor"][c["competitor"]]["final_analyzed_n"] == c["n"]


def test_cap_validity_excludes_capped_samples_from_ranks(tmp_path):
    log = tmp_path / "log.json"
    combos = lambda counts: [{"star": s, "sort": o, "returned": n} for s, n in counts.items() for o in range(4)]
    log.write_text(json.dumps({"runs": [{"products": [
        {"asin": PRODUCTS[0]["asin"], "combos": combos({5: 100, 4: 100, 3: 100, 2: 40, 1: 100})},
        {"asin": PRODUCTS[1]["asin"], "combos": combos({5: 100, 4: 9, 3: 5, 2: 2, 1: 7})},
        {"asin": PRODUCTS[2]["asin"], "combos": combos({5: 20, 4: 3, 3: 1, 2: 1, 1: 2})}]}]}))
    caps = analyze.load_caps(log)
    assert caps[PRODUCTS[0]["asin"]]["capped_stars"] == [5, 4, 3, 1]
    assert [analyze.sample_validity(caps[p["asin"]]["capped_stars"]) for p in PRODUCTS[:3]] == ["capped_mixed", "promoters_capped", "complete"]
    recs = [{"competitor": p["competitor"], "rating": r, "review_id": f"{p['asin']}{i}", "title": "", "review_text": "x",
             "verified_purchase": True, "review_date": "2025-01-01", "collection_source": "s", "verification_status": "source_retrieved"}
            for p in PRODUCTS for i, r in enumerate([5, 5, 4, 1])]
    a = analyze.build(recs, caps=caps)
    by = {c["competitor"]: c for c in a["competitors"]}
    assert by[PRODUCTS[0]["competitor"]]["rank"] is None and by[PRODUCTS[0]["competitor"]]["nps"] == 25
    assert by[PRODUCTS[1]["competitor"]]["rank"] == 1 and PRODUCTS[0]["competitor"] in a["wedge"]["excluded_not_comparable"]
