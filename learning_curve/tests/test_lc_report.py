"""Tests 5 and 6: PDF structure/content and consistency across app values, table, chart, CSV and PDF."""
import csv
import io

import pytest
from pypdf import PdfReader

from analysis import METHOD_USER_UNITS, equation_text, fmt_b, fmt_pct, fmt_r2
from charts import experience_curve_figure
from helpers import synthetic_analysis, user_inputs
from report import build_csv, build_pdf, report_filename

URL = "https://example-learning-curve.streamlit.app"   # test value only


def pdf_text(data: bytes):
    reader = PdfReader(io.BytesIO(data))
    return reader, "\n".join(p.extract_text() for p in reader.pages)


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_pdf_structure_text_chart_and_sources(freq):
    an = synthetic_analysis(freq)
    data = build_pdf(an, URL)
    assert data[:5] == b"%PDF-"
    reader, text = pdf_text(data)
    flat = " ".join(text.split())
    assert 2 <= len(reader.pages) <= 6
    for needle in ["Learning-Curve Calculator", f"Public Tool URL: {URL}", "Analysis Results",
                   "Data, Sources, and Methodology", "Interpretation", "Methodology", "Limitations",
                   "Period-level calculation", "SEC sources for COGS", "Unit volume sources",
                   fmt_pct(an.regression.learning_rate), fmt_b(an.regression.b), fmt_r2(an.regression.r2),
                   "CostOfGoodsAndServicesSold", an.company, freq.capitalize(),
                   "Cumulative production is measured from the beginning of the selected data window",
                   "not from the company's founding", an.generated_at, an.fingerprint]:
        assert needle in flat, needle
    for r in an.rows:                                   # every period and accession is present
        assert r["period"] in flat and r["cogs_accession"] in flat
    links = [a.get_object()["/A"]["/URI"] for p in reader.pages for a in p.get("/Annots", [])
             if a.get_object().get("/A", {}).get("/URI")]
    assert URL in links
    assert all(any(r["cogs_url"] == l for l in links) for r in an.rows)
    images = sum(len(p.images) for p in reader.pages)
    assert images == 1


def test_pdf_without_url_says_link_missing():
    _, text = pdf_text(build_pdf(synthetic_analysis("annual"), None))
    assert "missing the public link" in " ".join(text.split())
    assert "http" not in text.split("Analysis Results")[0]


def test_pdf_refuses_invalid_analysis():
    an = synthetic_analysis(unit_definition="")
    with pytest.raises(ValueError):
        build_pdf(an, URL)


def test_report_filename_convention():
    from datetime import date
    assert report_filename(synthetic_analysis("annual"), date(2026, 10, 17)) == "Learning_Curve_ZZTEST_2026-10-17.pdf"


def test_values_agree_across_chart_table_csv_and_pdf():
    an = synthetic_analysis("quarterly", method=METHOD_USER_UNITS, inputs=user_inputs())
    reg = an.regression
    # Chart plots exactly the regression rows and the fitted line uses the reported coefficients
    fig = experience_curve_figure(an)
    ax = fig.axes[0]
    pts = ax.collections[0].get_offsets()
    assert [tuple(p) for p in pts] == [(r["cum_units"], r["unit_cost"]) for r in an.regression_rows]
    line = ax.lines[0]
    x, y = line.get_xdata(), line.get_ydata()
    assert y[0] == pytest.approx(reg.a * x[0] ** (-reg.b))
    assert equation_text(reg) in line.get_label()
    assert fmt_pct(reg.learning_rate) in ax.texts[-1].get_text() and fmt_r2(reg.r2) in ax.texts[-1].get_text()
    # CSV rows match the analysis rows
    rows = list(csv.DictReader(io.StringIO(build_csv(an).decode())))
    assert len(rows) == len(an.rows)
    for c, r in zip(rows, an.rows):
        assert float(c["cogs"]) == r["cogs"] and float(c["units"]) == r["units"]
        assert float(c["unit_cost"]) == pytest.approx(r["unit_cost"], rel=1e-12)
        assert c["cogs_accession"] == r["cogs_accession"]
    # PDF shows the same headline numbers and table values
    _, text = pdf_text(build_pdf(an, URL))
    flat = " ".join(text.split())
    for v in (fmt_pct(reg.learning_rate), fmt_b(reg.b), fmt_r2(reg.r2), equation_text(reg)):
        assert v in flat, v
    for r in an.rows:
        assert f"{r['unit_cost']:,.2f}" in flat and f"{r['cogs'] / 1e6:,.1f}" in flat
        assert "Synthetic test value" in flat
