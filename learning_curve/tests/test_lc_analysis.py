"""Test 3: data gaps and invalid inputs produce clear errors; valid data reproduce the known curve."""
import pytest

import financials as fin
import synthetic as syn
from analysis import (METHOD_REVENUE_ASP, METHOD_USER_UNITS, PeriodInput, WINDOW_LIMITATION,
                      fit_quality, interpret, methodology_text)
from helpers import synthetic_analysis, user_inputs


def test_quarterly_synthetic_recovers_twenty_percent():
    an = synthetic_analysis("quarterly")
    assert an.ok, an.errors
    assert an.regression.b == pytest.approx(0.32193, abs=2e-4)   # COGS rounded to whole dollars
    assert an.regression.learning_rate == pytest.approx(0.20, abs=2e-4)
    assert an.regression.r2 == pytest.approx(1.0, abs=1e-6)
    assert an.regression.n == 24
    cum = 0
    for r in an.rows:
        cum += r["units"]
        assert r["cum_units"] == pytest.approx(cum)
        assert r["unit_cost"] == pytest.approx(r["cogs"] / r["units"])


def test_annual_synthetic_runs_and_is_deterministic():
    a1, a2 = synthetic_analysis("annual"), synthetic_analysis("annual")
    assert a1.ok and a1.regression.n == 6
    assert a1.fingerprint == a2.fingerprint and a1.regression.b == a2.regression.b


def test_user_units_path_matches_xbrl_path():
    a = synthetic_analysis("quarterly", method=METHOD_USER_UNITS, inputs=user_inputs())
    b = synthetic_analysis("quarterly")
    assert a.ok and a.regression.b == pytest.approx(b.regression.b)


def test_missing_units_block_the_result():
    inputs = user_inputs()
    inputs.pop(sorted(inputs)[5])
    an = synthetic_analysis(method=METHOD_USER_UNITS, inputs=inputs)
    assert not an.ok and an.regression is None
    assert any("missing for" in e for e in an.errors)


def test_zero_or_negative_units_block_the_result():
    inputs = user_inputs()
    k = sorted(inputs)[3]
    inputs[k] = PeriodInput(units=0, source="x")
    an = synthetic_analysis(method=METHOD_USER_UNITS, inputs=inputs)
    assert not an.ok and any("positive number" in e for e in an.errors)


def test_missing_source_blocks_the_result():
    inputs = user_inputs()
    inputs[sorted(inputs)[0]] = PeriodInput(units=5, source="  ")
    an = synthetic_analysis(method=METHOD_USER_UNITS, inputs=inputs)
    assert not an.ok and any("source is required" in e for e in an.errors)


def test_missing_unit_definition_blocks_the_result():
    an = synthetic_analysis(unit_definition="")
    assert not an.ok and any("one unit" in e for e in an.errors)


def test_too_few_observations_block_the_result():
    an = synthetic_analysis("annual", window=lambda obs: obs[-4:])
    assert not an.ok and any("at least 5" in e for e in an.errors)


def test_gap_in_window_blocks_the_result():
    an = synthetic_analysis("quarterly", window=lambda obs: obs[:5] + obs[6:])
    assert not an.ok and any("Missing period" in e for e in an.errors)


def test_negative_cogs_period_excluded_but_units_still_cumulate():
    facts = syn.make_facts(n_years=6)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    for f in usd:
        if f["end"] == "2018-12-31" and f["start"] == "2018-10-01":
            f["val"] = -5
    an = synthetic_analysis("quarterly", facts=facts)
    assert an.ok
    bad = next(r for r in an.rows if r["end"] == "2018-12-31")
    assert not bad["in_regression"] and bad["cum_units"] > 0
    assert an.regression.n == 23
    assert any("not positive" in w for w in an.warnings)


def test_revenue_asp_method_and_constant_price_warning():
    facts = syn.make_facts(n_years=6)
    usd = facts["facts"]["us-gaap"]["CostOfGoodsAndServicesSold"]["units"]["USD"]
    facts["facts"]["us-gaap"]["Revenues"] = {"label": "Revenues",
                                             "units": {"USD": [dict(f, val=f["val"] * 1.5) for f in usd]}}
    rev = fin.extract_series(facts, "us-gaap", "Revenues", "annual")
    inputs = {o.end.isoformat(): PeriodInput(asp=40_000, source="Assumption: synthetic") for o in rev.observations}
    an = synthetic_analysis("annual", method=METHOD_REVENUE_ASP, inputs=inputs, revenue=rev, facts=facts)
    assert an.ok
    assert all(r["units"] == pytest.approx(r["revenue"] / 40_000) for r in an.rows)
    assert any("same average selling price" in w for w in an.warnings)
    assert any("estimates" in w for w in an.warnings)
    # Constant ASP and constant margin: unit cost is constant, so b ~ 0
    assert abs(an.regression.b) < 1e-6
    assert fit_quality(an.regression.r2) == "weak"


def test_revenue_asp_requires_revenue_for_every_period():
    an = synthetic_analysis("annual", method=METHOD_REVENUE_ASP, inputs={}, revenue=None)
    assert not an.ok and any("revenue" in e.lower() for e in an.errors)


def test_scope_mismatch_is_flagged():
    an = synthetic_analysis(scope=False)
    assert an.ok
    assert any("Scope mismatch" in w for w in an.warnings)
    assert "scope" in an.interpretation


def test_interpretation_is_cautious_and_sentence_count():
    an = synthetic_analysis()
    text = an.interpretation
    assert 3 <= text.count(". ") + 1 <= 6
    assert "fell by about 20.0%" in text and "strong (R² = 1.000)" in text
    assert "association" in text and "benchmark" in text


def test_negative_rate_interpretation_says_costs_rose():
    an = synthetic_analysis("annual")
    an.regression.b = -0.2
    an.regression.learning_rate = 1 - 2 ** 0.2
    an.regression.r2 = 0.3
    text = interpret(an)
    assert "rose by about" in text and "opposite" in text and "weak" in text


def test_methodology_mentions_window_limitation_constant():
    assert "beginning of the selected data window" in WINDOW_LIMITATION
    assert any("Cumulative units" in p for p in methodology_text(synthetic_analysis()))
