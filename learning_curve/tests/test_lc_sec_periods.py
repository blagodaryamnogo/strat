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
    assert not any("sum to" in i for i in s.notes())


def test_restatement_uses_latest_filing_and_is_disclosed():
    s = series("annual", n_years=6, restate_year=2019)
    fy19 = next(o for o in s.observations if o.label == "FY2019")
    assert fy19.primary.form == "10-K/A"
    assert fy19.restated_from
    assert any("revised" in i and "FY2019" in i for i in s.notes())


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
    assert any("differs from the value implied" in i for i in s.notes())


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


def _split_tags(facts, old_until="2020-09-30", new_from="2019-10-01"):
    """Re-tag older facts as CostOfGoodsSold, keeping an overlap of two fiscal years (like a real tag switch)."""
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    old = [dict(f) for f in usd if f["end"] <= old_until]
    facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"] = [f for f in usd if f["start"] >= "2018-10-01"]
    facts["facts"]["us-gaap"]["CostOfGoodsSold"] = {"label": "Cost of goods sold", "units": {"USD": old}}
    return facts


def test_recent_concept_preferred_and_verified_fill_extends_history():
    facts = _split_tags(syn.make_facts(n_years=8))
    cands = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")
    # The old tag has more years, but the tag still used in recent filings is chosen first
    assert cands[0].concept == "CostOfGoodsAndServicesSold" and cands[1].concept == "CostOfGoodsSold"
    assert len(cands[0].observations) == 6 and len(cands[1].observations) == 4
    filled = fin.fill_from_alternatives(cands[0], cands[1:])
    assert len(filled.observations) == 8 and not fin.contiguity_gaps(filled.observations)
    assert [o.primary.concept for o in filled.observations[:2]] == ["CostOfGoodsSold"] * 2
    assert filled.filled_from == ["CostOfGoodsSold"]
    assert any("identical values in 2 overlapping periods" in n for n in filled.notes())


def test_no_fill_when_alternative_values_differ():
    facts = _split_tags(syn.make_facts(n_years=8))
    for f in facts["facts"]["us-gaap"]["CostOfGoodsSold"]["units"]["USD"]:
        f["val"] = f["val"] * 1.05            # a different cost definition
    cands = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")
    filled = fin.fill_from_alternatives(cands[0], cands[1:])
    assert len(filled.observations) == 6 and filled.filled_from == []
    assert fin.concept_disagreements(cands[0], cands[1:])


def test_same_period_tagged_with_shifted_dates_is_merged():
    facts = syn.make_facts(n_years=5)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    fy = next(f for f in usd if f["start"] == "2017-10-01" and f["end"] == "2018-09-30")
    usd.append(dict(fy, start="2017-10-02", filed="2018-11-01", accn="0009999999-18-777777"))
    s = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", "annual")
    assert len(s.observations) == 5 and not fin.contiguity_gaps(s.observations)
    assert not any("Overlapping" in n for n in s.notes())


def test_sixteen_week_quarter_accepted():
    # 12/12/12/16-week fiscal year (as used by some retailers)
    f = lambda s, e, v, form, filed, accn: {"start": s, "end": e, "val": v, "form": form, "filed": filed,
                                            "accn": accn, "fy": 2024, "fp": "x"}
    rows = [f("2023-09-04", "2023-11-26", 84, "10-Q", "2023-12-20", "a1"),
            f("2023-11-27", "2024-02-18", 84, "10-Q", "2024-03-10", "a2"),
            f("2023-09-04", "2024-02-18", 168, "10-Q", "2024-03-10", "a2"),
            f("2024-02-19", "2024-05-12", 84, "10-Q", "2024-06-01", "a3"),
            f("2023-09-04", "2024-05-12", 252, "10-Q", "2024-06-01", "a3"),
            f("2023-09-04", "2024-09-01", 364, "10-K", "2024-10-10", "a4")]
    facts = {"facts": {"us-gaap": {"CostOfGoodsAndServicesSold": {"units": {"USD": rows}}}}}
    s = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", "quarterly")
    assert [o.days for o in s.observations] == [84, 84, 84, 112]
    assert s.observations[-1].value == 112 and s.observations[-1].label == "FY2024-Q4"


def test_unfinished_fiscal_year_quarters_are_labelled():
    facts = syn.make_facts(n_years=3)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    usd.append({"start": "2019-10-01", "end": "2019-12-31", "val": 5, "form": "10-Q", "filed": "2020-02-01",
                "accn": "0009999999-20-000001", "fy": 2020, "fp": "Q1"})
    s = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", "quarterly")
    assert s.observations[-1].label == "FY2020-Q1"


def test_notes_are_limited_to_the_window():
    s = series("annual", n_years=6, restate_year=2019)
    assert any("FY2019" in n for n in s.notes())
    assert not any("FY2019" in n for n in s.notes(date(2020, 10, 1), date(2022, 9, 30)))


def test_junk_quantity_units_are_ignored():
    facts = syn.make_facts(n_years=5)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    facts["facts"]["us-gaap"]["ShareBasedCompensationExpectedTerm"] = {"units": {"years": usd}}
    facts["facts"]["us-gaap"]["NumberOfReportableSegments"] = {"units": {"reportableSegment": usd}}
    assert [s.concept for s in fin.quantity_candidates(facts, "annual")] == ["SyntheticUnitsDelivered"]
