"""Test 2: annual vs quarterly reconstruction from SYNTHETIC companyfacts data."""
from datetime import date


import financials as fin
import synthetic as syn


def series(freq, **kw):
    facts = syn.make_facts(**kw)
    return fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", freq)


def test_annual_uses_only_fiscal_year_totals_without_duplicates():
    s = series("annual", n_years=8)
    assert len(s.observations) == 8
    assert all(o.primary.form == "10-K" and 360 <= o.days <= 370 for o in s.observations)
    assert [o.label for o in s.observations] == [f"FY{y}" for y in range(2017, 2025)]
    # Values are the 10-K totals, i.e. the sum of the four synthetic quarters
    facts = syn.make_facts(n_years=8)
    q = [f for f in facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
         if f["fp"] == "FY" and f["form"] == "10-K" and not f["accn"].endswith("C")]
    assert [o.value for o in s.observations] == [f["val"] for f in q]
    assert not fin.contiguity_gaps(s.observations)


def test_quarterly_reconstruction_does_not_double_count_ytd():
    s = series("quarterly", n_years=8)
    obs = s.observations
    assert len(obs) == 32
    assert all(75 <= o.days <= 105 for o in obs)
    assert not fin.contiguity_gaps(obs)
    expected = []
    cum = 0.0
    for u in syn.quarter_units(8):
        cum += u
        expected.append(round(u * syn.A * cum ** (-syn.B_20)))
    assert [o.value for o in obs] == expected
    methods = [o.method for o in obs[:4]]
    assert methods == ["reported", "reported", "derived", "derived"]   # Q3 = 9M-6M, Q4 = FY-9M
    assert obs[3].primary.form == "10-K" and obs[3].sources[1].form == "10-Q"
    assert [o.label for o in obs[:4]] == ["FY2017-Q1", "FY2017-Q2", "FY2017-Q3", "FY2017-Q4"]
    annual = series("annual", n_years=8).observations
    for y, fy in enumerate(annual):
        assert sum(o.value for o in obs[4 * y:4 * y + 4]) == fy.value
    assert not any("sum to" in i for i in s.issues)


def test_restatement_uses_latest_filing_and_is_disclosed():
    s = series("annual", n_years=6, restate_year=2019)
    fy19 = next(o for o in s.observations if o.label == "FY2019")
    assert fy19.primary.form == "10-K/A"
    assert fy19.restated_from
    assert any("revised" in i and "FY2019" in i for i in s.issues)


def test_missing_ytd_creates_visible_gap_not_a_filled_value():
    facts = syn.make_facts(n_years=4)
    rows = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    # Drop every report of FY2019's nine-month YTD: Q3 and Q4 of FY2019 can no longer be derived
    facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"] = [
        r for r in rows if not (r["start"] == "2018-10-01" and r["end"] == "2019-06-30")]
    s = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", "quarterly")
    assert len(s.observations) == 14
    gaps = fin.contiguity_gaps(s.observations)
    assert len(gaps) == 1 and "2019-03-31" in gaps[0]


def test_direct_quarter_conflicting_with_ytd_is_flagged():
    facts = syn.make_facts(n_years=3)
    facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"].append(
        {"start": "2017-04-01", "end": "2017-06-30", "val": 1, "accn": "0009999999-17-999999", "fy": 2017,
         "fp": "Q3", "form": "10-Q", "filed": "2017-08-05"})
    s = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", "quarterly")
    assert any("differs from the value implied" in i for i in s.issues)


def test_concept_selection_prefers_coverage_then_priority():
    facts = syn.make_facts(n_years=6)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    facts["facts"]["us-gaap"]["CostOfRevenue"] = {"label": "Cost of revenue", "units": {
        "USD": [dict(f, val=f["val"] * 1.1) for f in usd if f["fy"] >= 2019]}}
    cands = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")
    assert [c.concept for c in cands] == ["CostOfGoodsAndServicesSold", "CostOfRevenue"]
    notes = fin.concept_disagreements(cands[0], cands[1:])
    assert notes and "not combined" in notes[0]


def test_quantity_candidates_find_non_monetary_duration_series():
    facts = syn.make_facts(n_years=5)
    q = fin.quantity_candidates(facts, "annual")
    assert [s.concept for s in q] == ["SyntheticUnitsDelivered"]
    assert q[0].unit == "Vehicle"


def test_fiscal_year_label_for_52_53_week_years():
    assert fin.fiscal_year(date(2021, 1, 2)) == 2020
    assert fin.fiscal_year(date(2022, 12, 31)) == 2022
    assert fin.fiscal_year(date(2024, 1, 31)) == 2024
