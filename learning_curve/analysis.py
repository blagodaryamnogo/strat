"""Experience-curve dataset assembly, validation, regression and interpretation.

Everything here is pure Python with no Streamlit or network dependency, so the
same functions drive the app, the PDF report and the tests.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import numpy as np
from scipy import stats

import financials as fin
from financials import Observation, Series, contiguity_gaps
from sec_client import filing_document_url

MIN_OBSERVATIONS = 5
RECOMMENDED_OBSERVATIONS = 8

METHOD_USER_UNITS = "user_units"
METHOD_REVENUE_ASP = "revenue_asp"
METHOD_XBRL_UNITS = "xbrl_units"
METHOD_SEGMENT_UNITS = "segment_units"
METHOD_LABELS = {
    METHOD_SEGMENT_UNITS: "Direct segment unit volumes reported in SEC filings (each figure cited)",
    METHOD_XBRL_UNITS: "Direct unit volumes disclosed in SEC XBRL data",
    METHOD_USER_UNITS: "Direct unit volumes entered or uploaded by the user",
    METHOD_REVENUE_ASP: "Estimated units = SEC revenue ÷ user-supplied average selling price",
}

WINDOW_LIMITATION = ("Cumulative production is measured from the beginning of the selected data window, "
                     "not from the company's founding. True lifetime cumulative production is generally "
                     "unavailable.")
CAUSALITY_LIMITATION = ("The regression estimates an association between cumulative units and unit cost; "
                        "it is not proof of a causal learning effect. Input prices, inflation, product mix, "
                        "accounting choices and capacity utilization can all move unit costs.")
DISCLAIMER = ("This report was produced by an educational tool from SEC XBRL data and user-supplied inputs. "
              "Figures should be checked against the cited filings before being relied on.")


class AnalysisError(Exception):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


# ---------------------------------------------------------------------------
# Regression
@dataclass
class Regression:
    b: float
    a: float
    r2: float
    n: int
    se_b: float
    learning_rate: float

    @property
    def progress_ratio(self) -> float:
        return 2 ** (-self.b)


def fit_experience_curve(cumulative_units, unit_cost) -> Regression:
    """OLS of ln(unit cost) on ln(cumulative units): ln C = ln A - b ln N."""
    x = np.asarray(cumulative_units, dtype=float)
    y = np.asarray(unit_cost, dtype=float)
    if x.shape != y.shape:
        raise AnalysisError(["Cumulative units and unit costs have different lengths."])
    if len(x) < 3:
        raise AnalysisError(["At least three observations are needed to fit a regression."])
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and np.all(x > 0) and np.all(y > 0)):
        raise AnalysisError(["Regression inputs must be positive, finite numbers."])
    lx, ly = np.log(x), np.log(y)
    if np.ptp(lx) == 0:
        raise AnalysisError(["Cumulative units do not vary, so no curve can be fitted."])
    res = stats.linregress(lx, ly)
    b = -float(res.slope)
    r2 = float(res.rvalue) ** 2 if np.isfinite(res.rvalue) else 0.0
    if not np.isfinite(b):
        raise AnalysisError(["The regression did not produce a finite coefficient."])
    return Regression(b=b, a=float(math.exp(res.intercept)), r2=r2, n=len(x),
                      se_b=float(res.stderr), learning_rate=1 - 2 ** (-b))


# ---------------------------------------------------------------------------
# Formatting shared by app, chart, CSV and PDF so every output shows the same numbers
def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def fmt_b(x: float) -> str:
    return f"{x:.4f}"


def fmt_r2(x: float) -> str:
    return f"{x:.3f}"


def fmt_num(x: float, digits: int = 4) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    if x == 0:
        return "0"
    mag = math.floor(math.log10(abs(x)))
    if mag >= 9 or mag < -3:
        return f"{x:.{digits - 1}e}"
    decimals = max(0, digits - 1 - mag)
    return f"{x:,.{decimals}f}"


def fmt_units(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.2f}"


def fmt_money(x: float, currency: str = "USD") -> str:
    sym = "$" if currency == "USD" else currency + " "
    return f"{sym}{x:,.2f}" if abs(x) < 1e6 else f"{sym}{x:,.0f}"


def equation_text(reg: Regression, label: str = "Unit COGS") -> str:
    sign = "−" if reg.b >= 0 else "+"
    return f"{label} = {fmt_num(reg.a)} × N^({sign}{fmt_b(abs(reg.b))})"


# ---------------------------------------------------------------------------
@dataclass
class PeriodInput:
    units: float | None = None
    asp: float | None = None
    source: str = ""
    source_url: str = ""
    exclude_reason: str = ""      # set: units count toward cumulative volume, period excluded from the fit


@dataclass
class Analysis:
    company: str
    ticker: str
    cik: int
    frequency: str
    cogs_concept: str
    cogs_label: str
    currency: str
    unit_method: str
    unit_definition: str
    scope_confirmed: bool
    rows: list[dict]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    data_notes: list[str] = field(default_factory=list)
    regression: Regression | None = None
    interpretation: str = ""
    revenue_concept: str = ""
    quantity_concept: str = ""
    cogs_filled_from: list[str] = field(default_factory=list)
    cost_basis: str = "consolidated"          # or "segment"
    subject_company: str = ""                 # private company the comparable is evaluated for
    comparable_reason: str = ""
    comparability_note: str = ""
    segment: str = ""                         # e.g. "Salt segment" when cost_basis == "segment"
    extra_limitations: list[str] = field(default_factory=list)   # data-specific, from the segment CSV
    units_note: str = ""
    implications: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    @property
    def cost_name(self) -> str:
        """Short name of the cost measure: 'COGS' for consolidated XBRL data, else the segment measure."""
        return "COGS" if self.cost_basis == "consolidated" else "segment cost"

    @property
    def unit_cost_label(self) -> str:
        return "Unit COGS" if self.cost_basis == "consolidated" else "Unit cost"

    @property
    def ok(self) -> bool:
        return self.regression is not None and not self.errors

    @property
    def regression_rows(self) -> list[dict]:
        return [r for r in self.rows if r["in_regression"]]

    @property
    def date_range(self) -> str:
        if not self.rows:
            return ""
        return f"{self.rows[0]['start']} to {self.rows[-1]['end']}"

    @property
    def period_range(self) -> str:
        if not self.rows:
            return ""
        return f"{self.rows[0]['period']} – {self.rows[-1]['period']}"

    @property
    def fingerprint(self) -> str:
        keys = ["period", "start", "end", "cogs", "units", "cogs_accession", "units_source", "asp"]
        payload = json.dumps([[str(r.get(k)) for k in keys] for r in self.rows]
                             + [self.unit_method, self.cogs_concept, self.frequency, self.cost_basis])
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _obs_provenance(prefix: str, o: Observation, cik: int, docs: dict[str, str]) -> dict:
    p = o.primary
    return {
        f"{prefix}_concept": p.concept,
        f"{prefix}_method": o.method,
        f"{prefix}_form": p.form,
        f"{prefix}_filed": p.filed,
        f"{prefix}_accession": p.accession,
        f"{prefix}_url": filing_document_url(cik, p.accession, docs.get(p.accession)),
        f"{prefix}_note": o.note,
        f"{prefix}_other_accessions": ", ".join(s.accession for s in o.sources[1:]),
    }


def build_analysis(*, company: str, ticker: str, cik: int, frequency: str, cogs: Series,
                   window: list[Observation], unit_method: str, unit_definition: str,
                   scope_confirmed: bool, inputs: dict[str, PeriodInput] | None = None,
                   revenue: Series | None = None, quantity: Series | None = None,
                   documents: dict[str, str] | None = None,
                   extra_notes: list[str] | None = None, cost_basis: str = "consolidated",
                   framing: dict[str, str] | None = None) -> Analysis:
    """Assemble the period table, run every data check and fit the curve if the data allow."""
    inputs = inputs or {}
    documents = documents or {}
    an = Analysis(company=company, ticker=ticker, cik=cik, frequency=frequency,
                  cogs_concept=cogs.concept, cogs_label=cogs.label, currency=cogs.unit or "USD",
                  unit_method=unit_method, unit_definition=(unit_definition or "").strip(),
                  scope_confirmed=scope_confirmed, rows=[],
                  revenue_concept=revenue.concept if revenue else "", cogs_filled_from=list(cogs.filled_from),
                  quantity_concept=quantity.concept if quantity else "", cost_basis=cost_basis,
                  **{k: (v or "").strip() for k, v in (framing or {}).items()
                     if k in ("subject_company", "comparable_reason", "comparability_note", "segment")},
                  extra_limitations=[x.strip() for x in (framing or {}).get("limitations", "").split("|") if x.strip()],
                  units_note=(framing or {}).get("units_scale_note", "").strip())
    errors, warnings = an.errors, an.warnings
    an.data_notes.extend(extra_notes or [])
    if window:
        an.data_notes.extend(cogs.notes(window[0].start, window[-1].end))

    if unit_method not in METHOD_LABELS:
        errors.append("Choose how unit volumes are measured.")
    if not window:
        errors.append("No COGS observations fall in the selected period.")
        return an
    ends = [o.end for o in window]
    if len(set(ends)) != len(ends):
        errors.append("The selected data contain duplicated reporting periods.")
    errors.extend(f"Missing period: {g} Cumulative units would be understated. Choose a window that "
                  f"starts after the gap." for g in contiguity_gaps(window))
    rng = fin.ANNUAL_DAYS if frequency == "annual" else fin.QUARTER_DAYS
    for o in window:
        if not rng[0] <= o.days <= rng[1]:
            if inputs.get(o.end.isoformat(), PeriodInput()).exclude_reason:
                warnings.append(f"{o.label} covers {o.days} days, not a full {frequency} period: its units count "
                                f"toward cumulative volume, but it is excluded from the regression.")
            else:
                errors.append(f"{o.label} covers {o.days} days, which is inconsistent with {frequency} data.")
    if not an.unit_definition:
        errors.append("Describe what one unit is (for example 'vehicles delivered').")

    rev_by_end = {o.end: o for o in revenue.observations} if revenue else {}
    qty_by_end = {o.end: o for o in quantity.observations} if quantity else {}
    if unit_method == METHOD_REVENUE_ASP and revenue is None:
        errors.append("No SEC revenue series is available for the revenue ÷ price method.")
    if unit_method == METHOD_XBRL_UNITS and quantity is None:
        errors.append("No SEC-tagged unit volume series was selected.")

    missing_units, missing_source, missing_rev = [], [], []
    cumulative = 0.0
    for o in window:
        key = o.end.isoformat()
        inp = inputs.get(key, PeriodInput())
        row = {"period": o.label, "start": o.start.isoformat(), "end": key, "days": o.days,
               "cogs": o.value, **_obs_provenance("cogs", o, cik, documents),
               "units": None, "units_source": "", "revenue": None, "asp": None,
               "cum_units": None, "unit_cost": None, "in_regression": False, "excluded_reason": ""}
        units, invalid = None, False
        if unit_method in (METHOD_USER_UNITS, METHOD_SEGMENT_UNITS):
            units = inp.units
            row["units_source"] = (inp.source or "").strip()
            if inp.source_url:
                row["units_url"] = inp.source_url
            if units is not None and not row["units_source"]:
                missing_source.append(o.label)
        elif unit_method == METHOD_REVENUE_ASP:
            rev = rev_by_end.get(o.end)
            if rev is None or abs((rev.start - o.start).days) > 5:
                missing_rev.append(o.label)
            else:
                row["revenue"] = rev.value
                row.update(_obs_provenance("revenue", rev, cik, documents))
                row["asp"] = inp.asp
                row["units_source"] = (inp.source or "").strip()
                if inp.asp is not None and not row["units_source"]:
                    missing_source.append(o.label)
                if inp.asp is not None and inp.asp > 0 and rev.value > 0:
                    units = rev.value / inp.asp
                elif inp.asp is not None:
                    errors.append(f"{o.label}: revenue and average selling price must be positive.")
                    invalid = True
        elif unit_method == METHOD_XBRL_UNITS:
            q = qty_by_end.get(o.end)
            if q is not None and abs((q.start - o.start).days) <= 5:
                units = q.value
                prov = _obs_provenance("units", q, cik, documents)
                row["units_source"] = (f"SEC XBRL {q.primary.concept} ({q.primary.unit}), "
                                       f"{q.primary.form} {q.primary.accession}")
                row["units_url"] = prov["units_url"]
        if invalid:
            pass
        elif units is None:
            missing_units.append(o.label)
        elif not (isinstance(units, (int, float)) and math.isfinite(units) and units > 0):
            errors.append(f"{o.label}: units must be a positive number (got {units:g}).")
            units = None
        if units is not None:
            cumulative += units
            row["units"] = units
            row["cum_units"] = cumulative
            if o.value > 0:
                row["unit_cost"] = o.value / units
                row["in_regression"] = not inp.exclude_reason
                row["excluded_reason"] = inp.exclude_reason
            else:
                row["excluded_reason"] = "COGS is zero or negative"
                warnings.append(f"{o.label}: COGS is not positive ({o.value:,.0f}); its units count toward "
                                f"cumulative volume but the period is excluded from the regression.")
        an.rows.append(row)

    if missing_rev:
        errors.append(f"SEC revenue ({revenue.concept if revenue else 'n/a'}) is missing for: "
                      f"{', '.join(missing_rev)}.")
    if missing_units:
        what = {"user_units": "Unit volumes", "segment_units": "Unit volumes", "revenue_asp": "Average selling prices",
                "xbrl_units": "SEC-tagged unit volumes"}.get(unit_method, "Unit volumes")
        errors.append(f"{what} are missing for: {', '.join(missing_units)}. Every period in the window "
                      f"needs a value because each one adds to cumulative production. Either add values for "
                      f"these periods or move the Analysis period slider so it covers only periods you have "
                      f"values for.")
    if missing_source:
        errors.append(f"A source is required for every user-supplied value; missing for: "
                      f"{', '.join(missing_source)}.")

    if unit_method == METHOD_REVENUE_ASP:
        asps = {r["asp"] for r in an.rows if r["asp"] is not None}
        if len(asps) == 1 and len(an.rows) > 1:
            warnings.append("The same average selling price is used for every period. Estimated units are "
                            "then proportional to revenue, so unit cost reduces to a scaled COGS-to-revenue "
                            "ratio and the learning rate mostly reflects margin changes.")
        warnings.append("Units are estimates (revenue ÷ average selling price), not observed production.")
    if not scope_confirmed:
        warnings.append(f"Scope mismatch: the unit volumes were not confirmed to cover the same activity as "
                        f"the {'consolidated COGS' if cost_basis == 'consolidated' else 'segment cost'}. The "
                        f"result is not a valid experience curve for that activity without qualification.")

    n_valid = sum(r["in_regression"] for r in an.rows)
    if not errors and n_valid < MIN_OBSERVATIONS:
        errors.append(f"Only {n_valid} usable observations; at least {MIN_OBSERVATIONS} are required.")
    if errors:
        return an
    if n_valid < RECOMMENDED_OBSERVATIONS:
        warnings.append(f"Only {n_valid} observations: the estimate is sensitive to individual periods.")

    reg_rows = an.regression_rows
    try:
        an.regression = fit_experience_curve([r["cum_units"] for r in reg_rows],
                                             [r["unit_cost"] for r in reg_rows])
    except AnalysisError as e:
        errors.extend(e.messages)
        return an
    an.interpretation = interpret(an)
    an.implications = implications(an) if an.subject_company else ""
    return an


# ---------------------------------------------------------------------------
def fit_quality(r2: float) -> str:
    if r2 >= 0.80:
        return "strong"
    if r2 >= 0.50:
        return "moderate"
    return "weak"


def interpret(an: Analysis) -> str:
    reg = an.regression
    lr = reg.learning_rate
    quality = fit_quality(reg.r2)
    freq = "annual" if an.frequency == "annual" else "quarterly"
    subject = f"{an.company}'s {an.segment + ' ' if an.segment else ''}{an.unit_cost_label.lower()}"
    s = []
    if lr > 0:
        s.append(f"Across {reg.n} {freq} observations ({an.date_range}), {subject} fell by "
                 f"about {fmt_pct(lr)} for each doubling of cumulative units (b = {fmt_b(reg.b)}).")
    else:
        s.append(f"Across {reg.n} {freq} observations ({an.date_range}), {subject} rose by "
                 f"about {fmt_pct(-lr)} for each doubling of cumulative units (b = {fmt_b(reg.b)}), the "
                 f"opposite of an experience-curve effect.")
    if quality == "strong" and lr > 0:
        s.append(f"The log-log fit is strong (R² = {fmt_r2(reg.r2)}), so a declining cost curve is visible "
                 f"in the data, although the relationship is an association rather than proof that "
                 f"cumulative volume caused the decline.")
    elif quality == "strong":
        s.append(f"The log-log fit is strong (R² = {fmt_r2(reg.r2)}), meaning costs rose consistently as "
                 f"volume accumulated; no experience curve is visible.")
    elif quality == "moderate":
        s.append(f"The fit is moderate (R² = {fmt_r2(reg.r2)}), so the evidence is inconclusive and the "
                 f"pattern should not be treated as a reliable experience curve.")
    else:
        s.append(f"The fit is weak (R² = {fmt_r2(reg.r2)}): cumulative volume explains little of the "
                 f"variation in unit cost, so these data do not show a meaningful experience curve.")
    if lr > 0 and quality == "strong":
        position = ("within" if 0.10 <= lr <= 0.30 else "below" if lr < 0.10 else "above")
        s.append(f"The rate is {position} the commonly cited 10–30% range, but without a verified industry "
                 f"benchmark its strength relative to competitors cannot be determined; if rivals have "
                 f"accumulated less volume, the curve would favor strategies that build share and scale "
                 f"to hold a cost advantage.")
    else:
        s.append("On this evidence, cumulative volume alone should not be treated as a durable source of "
                 "cost advantage, and the company's position relative to its industry cannot be "
                 "determined without a verified benchmark.")
    lims = ["costs are nominal (not inflation-adjusted)",
            "cumulative units are counted only from the start of the selected window"]
    if an.unit_method == METHOD_REVENUE_ASP:
        lims.append("units are estimated from revenue and assumed prices")
    if not an.scope_confirmed:
        lims.append(f"the unit volumes may not match the scope of the {an.cost_name}")
    if volume_tracks_time(an):
        lims.append("because volume per period was fairly stable, cumulative volume rose almost in step with "
                    "time, so the fit cannot separate volume effects from cost changes over time")
    s.append("Key limitations: " + ", ".join(lims[:-1]) + ", and " + lims[-1] + ".")
    return " ".join(s)


def volume_tracks_time(an: Analysis) -> bool:
    """True when cumulative units grow almost linearly with elapsed time (correlation ≥ 0.98), i.e. volume per
    period is roughly stable, so ln N is close to a function of time alone."""
    rows = an.regression_rows
    if len(rows) < 3:
        return False
    t = np.array([(date.fromisoformat(r["end"]) - date.fromisoformat(an.rows[0]["start"])).days for r in rows], float)
    n = np.array([r["cum_units"] for r in rows], float)
    return bool(np.corrcoef(t, n)[0, 1] >= 0.98)


def implications(an: Analysis) -> str:
    """What the comparable's curve does and does not imply for the private company being evaluated."""
    reg, lr, quality = an.regression, an.regression.learning_rate, fit_quality(an.regression.r2)
    comp = f"{an.company}{' (' + an.segment + ')' if an.segment else ''}"
    s = []
    if lr > 0 and quality == "strong":
        s.append(f"{comp} shows evidence consistent with production-related cost declines: unit cost fell "
                 f"about {fmt_pct(lr)} per doubling of cumulative volume with a strong fit (R² = {fmt_r2(reg.r2)}).")
        s.append("If that pattern reflects learning rather than other factors, producers with more accumulated "
                 "volume would hold a cost advantage, which favors scale and share-building strategies in that "
                 "market.")
    else:
        detail = (f"unit cost rose about {fmt_pct(-lr)} per doubling of cumulative volume (R² = {fmt_r2(reg.r2)})"
                  if lr <= 0 else f"the fit is {quality} (R² = {fmt_r2(reg.r2)})")
        s.append(f"{comp} does not show evidence of production-related cost advantages over this window: {detail}, "
                 f"so the data do not establish a meaningful experience-curve advantage.")
        s.append("Accumulated volume therefore does not appear to give the comparable a learning-driven cost lead "
                 "that would by itself shut out smaller competitors; any scale advantage would have to come from "
                 "other sources (such as fixed-cost absorption, purchasing or logistics), which this analysis "
                 "does not measure.")
    s.append(f"The measured rate should not be assumed to transfer to {an.subject_company}. "
             + (an.comparability_note or "Differences in product mix, branding, pricing and manufacturing scale "
                "mean the comparable is only an imperfect industry reference."))
    s.append(f"This analysis does not predict the learning rate {an.subject_company} will achieve.")
    return " ".join(s)


def methodology_text(an: Analysis) -> list[str]:
    freq_rule = (
        "Annual values are fiscal-year durations (350–380 days) taken from 10-K, 20-F or 40-F filings."
        if an.frequency == "annual" else
        "Quarterly values use the reported three-month figure when one exists; otherwise the quarter is "
        "derived as the difference between consecutive year-to-date values with the same fiscal-year start "
        "(for example, Q4 = fiscal-year total from the 10-K minus nine-month year-to-date from the Q3 10-Q). "
        "Year-to-date totals are never used as quarters, and four quarters are checked against the annual "
        "total where both are available.")
    calc = (f"Cumulative units N(t) = sum of units from the first period in the window through period t. "
            f"Unit cost C(t) = period {an.cost_name} ÷ period units. The model C = A·N^(−b) is fitted by ordinary "
            f"least squares of ln C on ln N. Learning rate = 1 − 2^(−b); R² is from the log-space regression.")
    units = f"Unit volumes: {METHOD_LABELS.get(an.unit_method, '')}. Unit definition: {an.unit_definition or '—'}."
    if an.cost_basis == "segment":
        excluded = [r for r in an.rows if r["excluded_reason"]]
        return [
            f"Cost measure: {an.cogs_label}. Segment figures are not published in the SEC Company Facts API "
            f"(it holds only consolidated facts), so each value was transcribed from the segment note or MD&A of "
            f"the cited 10-K/10-KT (CIK {an.cik}); the table above gives the form, filing date, accession number "
            f"and derivation for every figure. Costs and units are for the same segment.",
            "When a period appears in several filings, the most recently filed figure is used so that "
            "restatements are reflected; differences from earlier filings are listed under data notes.",
            units,
            calc + (" Periods that are not full fiscal years (" + ", ".join(r["period"] for r in excluded)
                    + ") add their units to N but are excluded from the regression, so cumulative volume has no "
                    "gap and every regression observation covers a full year." if excluded else ""),
        ]
    return [
        f"COGS is the SEC XBRL concept {an.cogs_concept} ({an.cogs_label}) in {an.currency}, taken from the "
        f"SEC Company Facts API for CIK {an.cik}. Periods are identified by their exact start and end dates; "
        f"fiscal-year labels use the calendar year in which the fiscal year ends (52/53-week years ending in "
        f"the first week of January are assigned to the prior year), so a label may differ from the "
        f"company's own naming; the dates are authoritative.",
        freq_rule,
        "When a period is reported in several filings, the most recently filed value is used so that "
        "restatements are reflected; earlier differing values are listed under data notes.",
        "Concept selection rule: among the candidate COGS concepts (CostOfGoodsAndServicesSold, CostOfRevenue, "
        "CostOfGoodsSold, the excluding-D&A variants and IFRS CostOfSales), concepts still used in the latest "
        "filings come first, then the one with the most observations, ties broken in that order. A period "
        "missing under the selected concept is taken from an alternative concept only if that concept reports "
        "identical values (within 0.5%) in at least two overlapping periods; each row shows its own tag."
        + (f" Periods filled this way here: from {', '.join(an.cogs_filled_from)}." if an.cogs_filled_from
           else " No periods were filled from alternative concepts in this analysis."),
        units,
        calc,
    ]
