"""Segment cost basis: CSV validation, bridging periods, regression and the framed PDF.

Uses the real Compass Minerals Salt-segment file in examples/ (figures transcribed from SEC filings and
verified against those filings by test_lc_live.py)."""
import io
from pathlib import Path

import numpy as np
import pytest
from pypdf import PdfReader

from analysis import METHOD_SEGMENT_UNITS, build_analysis, equation_text, fmt_b, fmt_pct, fmt_r2
from report import build_pdf
from segment_data import parse_segment_csv

CSV = Path(__file__).resolve().parents[1] / "examples" / "cmp_salt_segment_2015_2025.csv"
CIK = 1227654


def load(data=None):
    return parse_segment_csv(data if data is not None else CSV.read_bytes(), CIK, {})


def analysis(data=None, **kw):
    series, inputs, meta, errors = load(data)
    assert not errors, errors
    framing = {k: meta[k] for k in ("subject_company", "comparable_reason", "comparability_note", "segment",
                                     "limitations", "units_scale_note")}
    framing.update(kw.pop("framing", {}))
    return build_analysis(company="Compass Minerals International, Inc.", ticker="CMP", cik=CIK, frequency="annual",
                          cogs=series, window=series.observations, unit_method=METHOD_SEGMENT_UNITS,
                          unit_definition=meta["unit_definition"], scope_confirmed=True, inputs=inputs,
                          cost_basis="segment", framing=framing, **kw)


def test_example_csv_parses_with_citations():
    series, inputs, meta, errors = load()
    assert errors == [] and len(series.observations) == 11
    assert meta["subject_company"] == "Silk Road Salts" and meta["segment"] == "Salt segment"
    for o in series.observations:
        assert o.method == "derived" and o.note.startswith("Derived: Salt sales $")
        assert o.primary.accession.startswith("0001227654-")
    tp = inputs["2021-09-30"]
    assert tp.exclude_reason and tp.units == 8_510_000
    assert sum(1 for i in inputs.values() if i.exclude_reason) == 1


def test_derived_costs_equal_their_stated_components():
    import re
    series, *_ = load()
    for o in series.observations:
        sales, sh, op, total = (float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+\.\d)M", o.note))
        assert round(sales - sh - op, 1) == total and o.value == pytest.approx(total * 1e6)


@pytest.mark.parametrize("old,new,msg", [
    (",0001227654-18-000031,2018-02-27,", ",1227654-18-31,2018-02-27,", "not an SEC accession number"),
    (",no,Nine-month transition period (fiscal year-end changed from December 31 to September 30); not comparable "
     "with full-year unit costs,", ",no,,", "exclusion_reason"),
    ("FY2016,2016-01-01,2016-12-31,396800000", "FY2016,2016-01-01,2016-12-31,-1", "must be positive"),
])
def test_invalid_rows_are_rejected(old, new, msg):
    text = CSV.read_text()
    assert old in text
    series, inputs, meta, errors = load(text.replace(old, new, 1).encode())
    assert series is None and any(msg in e for e in errors)


def test_transition_period_counts_toward_cumulative_but_not_the_fit():
    an = analysis()
    assert an.ok, an.errors
    tp = next(r for r in an.rows if r["period"].startswith("TP2021"))
    prev = next(r for r in an.rows if r["period"] == "FY2020")
    nxt = next(r for r in an.rows if r["period"] == "FY2022")
    assert not tp["in_regression"] and tp["excluded_reason"]
    assert nxt["cum_units"] == prev["cum_units"] + tp["units"] + nxt["units"]
    assert an.regression.n == 10
    assert any("273 days" in w for w in an.warnings)


def test_regression_matches_independent_calculation():
    an = analysis()
    cost = np.array([394.7, 396.8, 410.6, 470.0, 454.9, 400.6, 339.1, 542.2, 515.8, 464.1, 564.1]) * 1e6
    tons = np.array([11069, 11113, 10600, 11627, 10923, 9440, 8510, 12575, 11320, 9314, 10848]) * 1e3
    use = np.array([1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1], bool)
    x, y = np.log(np.cumsum(tons))[use], np.log(cost / tons)[use]
    slope, _ = np.polyfit(x, y, 1)
    assert an.regression.b == pytest.approx(-slope, rel=1e-9)
    assert an.regression.r2 == pytest.approx(np.corrcoef(x, y)[0, 1] ** 2, rel=1e-9)
    assert an.regression.learning_rate < 0           # costs rose; not converted to a positive rate


def test_interpretation_and_implications_are_cautious():
    an = analysis()
    assert "rose by about" in an.interpretation and "opposite of an experience-curve effect" in an.interpretation
    assert "Salt segment unit cost" in an.interpretation
    assert "does not show evidence of production-related cost advantages" in an.implications
    assert "should not be assumed to transfer to Silk Road Salts" in an.implications
    assert "does not predict" in an.implications


def test_framed_pdf_title_sections_and_citations():
    an = analysis()
    reader = PdfReader(io.BytesIO(build_pdf(an, None)))
    flat = " ".join(" ".join(p.extract_text() for p in reader.pages).split())
    for needle in ["Experience-Curve Analysis: Silk Road Salts",
                   "Public Comparable: Compass Minerals International, Inc. (CMP)",
                   "missing the public link", "Learning-Curve Results", "Why this comparable",
                   "Sources and Strategic Implications", "What this means for Silk Road Salts",
                   "SEC sources for segment cost", "Unit-cost methodology", "Assumptions and limitations",
                   "beginning of the selected data window", "McCormick", "Goderich",
                   fmt_pct(an.regression.learning_rate), fmt_b(an.regression.b), fmt_r2(an.regression.r2),
                   equation_text(an.regression, an.unit_cost_label), "TP2021 (9 mo)"]:
        assert needle in flat, needle
    for r in an.rows:
        assert r["cogs_accession"] in flat and f"{r['unit_cost']:,.2f}" in flat
    assert len(reader.pages) <= 5
    assert sum(len(p.images) for p in reader.pages) == 1
