"""Test 4: real SEC EDGAR retrieval. Needs network access to sec.gov and SEC_USER_AGENT set.

Run:  SEC_USER_AGENT="Your Name you@example.edu" pytest learning_curve/tests/test_lc_live.py -v
Skipped automatically when SEC cannot be reached.
"""
import os
import re

import pytest

import financials as fin
from sec_client import SECClient, SECError, filing_index_url

UA = os.environ.get("SEC_USER_AGENT", "")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    if "@" not in UA:
        pytest.skip("SEC_USER_AGENT not set")
    c = SECClient(UA, cache_dir=str(tmp_path_factory.mktemp("sec")))
    try:
        c.lookup("AAPL")
    except SECError as e:
        pytest.skip(f"SEC EDGAR not reachable: {e}")
    return c


def _raw(facts, s, o):
    """The companyfacts entry an observation claims to come from."""
    rows = facts["facts"][s.taxonomy][s.concept]["units"][s.unit]
    p = o.primary
    return [r for r in rows if r["accn"] == p.accession and r["start"] == p.start.isoformat()
            and r["end"] == p.end.isoformat()]


def test_apple_annual_cogs_traces_to_source(client):
    info = client.lookup("AAPL")
    assert info["cik"] == 320193
    facts = client.company_facts(info["cik"])
    s = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")[0]
    assert len(s.observations) >= 5
    for o in s.observations:
        raw = _raw(facts, s, o)
        assert raw and raw[0]["val"] == o.value and raw[0]["form"] == o.primary.form
        assert o.primary.form.startswith("10-K")
        assert re.fullmatch(r"\d{10}-\d{2}-\d{6}", o.primary.accession)
        assert filing_index_url(320193, o.primary.accession).startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    # Apple's FY2023 10-K reports total cost of sales of $214,137 million (fiscal year ended 2023-09-30)
    fy23 = next(o for o in s.observations if o.end.isoformat() == "2023-09-30")
    assert fy23.value == 214_137_000_000


def test_apple_quarters_sum_to_annual(client):
    facts = client.company_facts(320193)
    concept = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")[0].concept
    q = fin.extract_series(facts, "us-gaap", concept, "quarterly")
    a = fin.extract_series(facts, "us-gaap", concept, "annual")
    fy23 = next(o for o in a.observations if o.end.isoformat() == "2023-09-30")
    quarters = [o for o in q.observations if fy23.start <= o.start and o.end <= fy23.end]
    assert len(quarters) == 4
    assert sum(o.value for o in quarters) == fy23.value
    assert quarters[-1].method == "derived" and quarters[-1].primary.form.startswith("10-K")
    assert not any("sum to" in i for i in q.notes())


def test_tesla_lookup_and_quarterly_series(client):
    info = client.lookup("TSLA")
    facts = client.company_facts(info["cik"])
    s = fin.candidate_series(facts, fin.COGS_CONCEPTS, "quarterly")[0]
    assert len(s.observations) >= 20
    assert all(75 <= o.days <= 105 for o in s.observations)
    print(f"TSLA {s.concept}: {len(s.observations)} quarters; gaps: {fin.contiguity_gaps(s.observations)}")


def test_nvidia_tag_switch_is_filled_only_from_verified_identical_tag(client):
    facts = client.company_facts(1045810)
    cands = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")
    s = fin.fill_from_alternatives(cands[0], cands[1:])
    window = s.observations[-10:]
    assert not fin.contiguity_gaps(window)
    fy19 = next(o for o in s.observations if o.end.isoformat() == "2019-01-27")
    # NVIDIA tagged FY2019 cost of revenue only as CostOfGoodsAndServicesSold ($4,545 million)
    assert fy19.primary.concept != cands[0].concept and fy19.value == 4_545_000_000


def test_costco_sixteen_week_fourth_quarters(client):
    facts = client.company_facts(909832)
    s = fin.candidate_series(facts, fin.COGS_CONCEPTS, "quarterly")[0]
    window = s.observations[-20:]
    assert not fin.contiguity_gaps(window)
    q4s = [o for o in window if o.label.endswith("Q4")]
    assert q4s and all(o.days in (112, 119) and o.method == "derived" for o in q4s)   # 16- or 17-week Q4


def test_tesla_end_to_end_with_10k_delivery_figures(client):
    """Deliveries as stated in Tesla's 10-K MD&A text (FY2020-FY2024); see README for citations."""
    from analysis import METHOD_USER_UNITS, PeriodInput, build_analysis
    facts = client.company_facts(1318605)
    cogs = fin.candidate_series(facts, fin.COGS_CONCEPTS, "annual")[0]
    window = [o for o in cogs.observations if 2020 <= o.end.year <= 2024]
    deliveries = {"2020-12-31": 499_647, "2021-12-31": 936_222, "2022-12-31": 1_313_851,
                  "2023-12-31": 1_808_581, "2024-12-31": 1_789_000}
    an = build_analysis(company="Tesla, Inc.", ticker="TSLA", cik=1318605, frequency="annual", cogs=cogs,
                        window=window, unit_method=METHOD_USER_UNITS, unit_definition="vehicles delivered",
                        scope_confirmed=False, inputs={k: PeriodInput(units=v, source="Tesla 10-K MD&A")
                                                       for k, v in deliveries.items()})
    assert an.ok, an.errors
    assert [r["cogs"] for r in an.rows] == [24_906e6, 40_217e6, 60_609e6, 79_113e6, 80_240e6]
    assert an.regression.b == pytest.approx(0.0371, abs=5e-5)
    assert an.regression.r2 == pytest.approx(0.414, abs=5e-4)
    assert any("Scope mismatch" in w for w in an.warnings)


# ---- Compass Minerals Salt segment: every figure in the example CSV against its cited filing ----------
def _filing_text(client, cik, accession, cache):
    import html as _html
    import re as _re
    import requests
    from sec_client import filing_document_url, primary_documents
    if accession not in cache:
        docs = primary_documents(client.submissions(cik))
        url = filing_document_url(cik, accession, docs.get(accession))
        raw = requests.get(url, headers={"User-Agent": client.user_agent}, timeout=120).text
        cache[accession] = _re.sub(r"\s+", " ", _html.unescape(_re.sub(r"<[^>]+>", " ", raw)))
    return cache[accession]


def _header_dates(header):
    """Period-end dates named in a table header, in column order (bare years mean December 31)."""
    from datetime import date as _date
    months = {"September": 9, "December": 12}
    out = []
    for m in re.finditer(r"(September|December) (\d{1,2}), (\d{4})|(?<![\d,])(20\d{2})(?![\d,])", header):
        out.append(_date(int(m.group(3)), months[m.group(1)], int(m.group(2))) if m.group(1)
                   else _date(int(m.group(4)), 12, 31))
    return out


def test_compass_salt_csv_figures_match_cited_filings(client):
    from pathlib import Path
    from datetime import date as _date
    from segment_data import parse_segment_csv
    csv_path = Path(__file__).resolve().parents[1] / "examples" / "cmp_salt_segment_2015_2025.csv"
    import csv as _csv
    rows = list(_csv.DictReader(l for l in csv_path.read_text().splitlines() if not l.startswith("#")))
    series, inputs, meta, errors = parse_segment_csv(csv_path.read_bytes(), 1227654, {})
    assert not errors
    cache = {}
    num = r"\(?\s*[\d,]+\.?\d*\s*\)?"
    for r in rows:
        end = _date.fromisoformat(r["period_end"])
        sales, sh, op, total = (float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+\.\d)M", r["cost_derivation"]))
        text = _filing_text(client, 1227654, r["cost_accession"], cache)
        found = False
        for m in re.finditer(r"((?:Fiscal Year Ended (?:September|December) \d{2}, \d{4})|(?:Nine Months Ended "
                             r"September 30, \d{4})|(?<![\d,.$])(?:20\d{2}))\s+Salt\s+Plant Nutrition[^$]{0,120}?"
                             r"Total\s+Sales to external customers(?: \(b\))?\s*\$\s*(" + num + ")", text):
            if float(m.group(2).replace(",", "")) != sales or end not in _header_dates(m.group(1)):
                continue
            block = text[m.start():m.start() + 1600]
            got_sh = re.search(r"Shipping and handling cost\s*\$?\s*(" + num + ")", block).group(1)
            got_op = re.search(r"Operating (?:earnings|income) \(loss\)(?:\s*\([a-z]\))*\s*\$?\s*(" + num + ")", block).group(1)
            if float(got_sh.replace(",", "")) == sh and float(got_op.replace(",", "")) == op:
                found = True
        assert found, f"{r['period_label']}: Salt sales/S&H/operating earnings not found in {r['cost_accession']}"
        # Tons: the MD&A Salt Segment Results table of the cited filing, column for this period end
        text = _filing_text(client, 1227654, r["units_accession"], cache)
        kt = int(float(r["units"]) / 1000)
        ok = False
        for m in re.finditer(r"SALT SEGMENT RESULTS(.{0,200}?)Salt Sales \(in millions\).{0,400}?Total tons sold "
                             r"((?:[\d,]+\s+){1,4})", text):
            dates = _header_dates(m.group(1))
            tons = [int(x.replace(",", "")) for x in m.group(2).split()]
            ok |= any(d == end and t == kt for d, t in zip(dates, tons))
        assert ok, f"{r['period_label']}: {kt:,} thousand tons not found for {end} in {r['units_accession']}"
