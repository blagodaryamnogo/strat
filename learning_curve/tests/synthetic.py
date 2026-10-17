"""SYNTHETIC test data in SEC companyfacts format. Not any real company's financials.

The fictional company reports the way US filers typically do: three-month values for
Q1 and Q2, a nine-month year-to-date value only for Q3, and fiscal-year totals in the
10-K. Unit costs follow an exact 20% quarterly experience curve.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

B_20 = -math.log2(0.8)          # 0.321928...
A = 50_000.0
CIK = 9999999
TICKER = "ZZTEST"
NAME = "SYNTHETIC TEST CO (not a real company)"


def quarter_units(n_years: int) -> list[float]:
    return [1000.0 * (1.12 ** i) for i in range(4 * n_years)]


def _fact(start, end, val, form, filed, accn, fy, fp):
    return {"start": start.isoformat(), "end": end.isoformat(), "val": val, "accn": accn, "fy": fy,
            "fp": fp, "form": form, "filed": filed.isoformat()}


def make_facts(n_years: int = 8, first_fy: int = 2017, restate_year: int | None = None) -> dict:
    units = quarter_units(n_years)
    cum = 0.0
    q_units, q_cogs = [], []
    for u in units:
        cum += u
        q_units.append(u)
        q_cogs.append(round(u * A * cum ** (-B_20)))  # whole dollars, like real filings

    cogs, qty = [], []
    seq = 0
    for y in range(n_years):
        fy = first_fy + y
        fy_start = date(fy - 1, 10, 1)
        q_ends = [date(fy - 1, 12, 31), date(fy, 3, 31), date(fy, 6, 30), date(fy, 9, 30)]
        q_starts = [fy_start] + [e + timedelta(days=1) for e in q_ends[:3]]
        qc = q_cogs[4 * y:4 * y + 4]
        qu = q_units[4 * y:4 * y + 4]
        filings = []
        for k, fp in enumerate(["Q1", "Q2", "Q3"]):
            seq += 1
            filings.append(("10-Q", q_ends[k] + timedelta(days=35), f"0009999999-{fy % 100:02d}-{seq:06d}", fp))
        seq += 1
        filings.append(("10-K", q_ends[3] + timedelta(days=50), f"0009999999-{fy % 100:02d}-{seq:06d}", "FY"))
        for series, vals in ((cogs, qc), (qty, qu)):
            f1, f2, f3, fk = filings
            year_facts = [
                _fact(q_starts[0], q_ends[0], vals[0], f1[0], f1[1], f1[2], fy, "Q1"),
                _fact(q_starts[1], q_ends[1], vals[1], f2[0], f2[1], f2[2], fy, "Q2"),
                _fact(fy_start, q_ends[1], vals[0] + vals[1], f2[0], f2[1], f2[2], fy, "Q2"),
                _fact(fy_start, q_ends[2], sum(vals[:3]), f3[0], f3[1], f3[2], fy, "Q3"),
                _fact(fy_start, q_ends[3], sum(vals), fk[0], fk[1], fk[2], fy, "FY"),
            ]
            series.extend(year_facts)
            # The next year's filings repeat these periods as comparatives (exact duplicates).
            if y + 1 < n_years:
                for f in year_facts:
                    dup = dict(f)
                    dup.update(filed=(date.fromisoformat(f["filed"]) + timedelta(days=365)).isoformat(),
                               accn=f["accn"].replace(f"-{fy % 100:02d}-", f"-{(fy + 1) % 100:02d}-") + "C",
                               fy=fy + 1)
                    series.append(dup)
    if restate_year is not None:
        # A later 10-K/A revises one fiscal-year total; the newest value must be used.
        target = next(f for f in cogs if f["fp"] == "FY" and f["end"] == f"{restate_year}-09-30")
        r = dict(target)
        r.update(val=target["val"] + 1_000_000, form="10-K/A", filed="2030-01-15",
                 accn="0009999999-30-000001")
        cogs.append(r)
    return {"cik": CIK, "entityName": NAME, "facts": {
        "us-gaap": {
            "CostOfGoodsAndServicesSold": {"label": "Cost of Goods and Services Sold", "units": {"USD": cogs}},
            "SyntheticUnitsDelivered": {"label": "Units delivered (synthetic)", "units": {"Vehicle": qty}},
        },
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
            {"end": "2020-01-01", "val": 1, "accn": "x", "form": "10-K", "filed": "2020-01-02"}]}}},
    }}


def tickers_json() -> dict:
    return {"0": {"cik_str": CIK, "ticker": TICKER, "title": NAME}}


def submissions_json() -> dict:
    return {"cik": str(CIK), "name": NAME, "filings": {"recent": {
        "accessionNumber": [], "form": [], "filingDate": [], "primaryDocument": []}}}
