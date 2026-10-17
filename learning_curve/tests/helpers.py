"""Build Analysis objects from the SYNTHETIC company for tests."""
import financials as fin
import synthetic as syn
from analysis import METHOD_XBRL_UNITS, PeriodInput, build_analysis


def synthetic_analysis(freq="quarterly", n_years=6, method=METHOD_XBRL_UNITS, inputs=None, window=None,
                       scope=True, unit_definition="vehicles delivered", revenue=None, facts=None):
    facts = facts or syn.make_facts(n_years=n_years)
    cogs = fin.extract_series(facts, "us-gaap", "CostOfGoodsAndServicesSold", freq)
    qty = fin.extract_series(facts, "us-gaap", "SyntheticUnitsDelivered", freq, unit="Vehicle")
    win = cogs.observations if window is None else window(cogs.observations)
    return build_analysis(company=syn.NAME, ticker=syn.TICKER, cik=syn.CIK, frequency=freq, cogs=cogs,
                          window=win, unit_method=method, unit_definition=unit_definition,
                          scope_confirmed=scope, inputs=inputs, quantity=qty if method == METHOD_XBRL_UNITS
                          else None, revenue=revenue)


def user_inputs(freq="quarterly", n_years=6, source="Synthetic test value"):
    facts = syn.make_facts(n_years=n_years)
    qty = fin.extract_series(facts, "us-gaap", "SyntheticUnitsDelivered", freq, unit="Vehicle")
    return {o.end.isoformat(): PeriodInput(units=o.value, source=source) for o in qty.observations}
