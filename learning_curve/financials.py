"""Turn SEC companyfacts JSON into comparable, non-overlapping period values.

Rules (see METHODOLOGY.md):
* Periods are identified by their exact XBRL start/end dates, never by calendar
  year or by the filing's fiscal-period label.
* When the same period appears in several filings, the most recently filed value
  is used (this picks up restatements); earlier differing values are recorded.
* Annual values: duration 350-380 days, from 10-K / 20-F / 40-F family filings.
* Quarterly values: a reported three-month value when one exists; otherwise the
  difference between consecutive year-to-date values that share a start date
  (e.g. Q4 = fiscal-year total - nine-month YTD). Year-to-date values themselves
  are never used as quarters, so nothing is double-counted.
* One XBRL concept per series. Concepts are never spliced together.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"} | ANNUAL_FORMS

# Candidate COGS concepts, in order of preference when coverage ties.
COGS_CONCEPTS = [
    ("us-gaap", "CostOfGoodsAndServicesSold"),
    ("us-gaap", "CostOfRevenue"),
    ("us-gaap", "CostOfGoodsSold"),
    ("us-gaap", "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"),
    ("us-gaap", "CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization"),
    ("ifrs-full", "CostOfSales"),
]
REVENUE_CONCEPTS = [
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "Revenues"),
    ("us-gaap", "SalesRevenueNet"),
    ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    ("us-gaap", "SalesRevenueGoodsNet"),
    ("ifrs-full", "Revenue"),
]

QUARTER_DAYS = (75, 105)
HALF_DAYS = (165, 200)
NINE_DAYS = (255, 290)
ANNUAL_DAYS = (350, 380)
CONTIGUITY_TOLERANCE_DAYS = 7

_CURRENCY = re.compile(r"^[A-Z]{3}$")
# Count units that cannot be production or sales volumes.
NON_VOLUME_UNITS = {"shares", "pure", "segment", "segments", "employee", "employees", "position",
                    "positions", "subsidiary", "director", "plaintiff", "lawsuit", "claim", "patent"}


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(start: date, end: date) -> int:
    return (end - start).days + 1


def _in(n: int, rng: tuple[int, int]) -> bool:
    return rng[0] <= n <= rng[1]


def fiscal_year(end: date) -> int:
    """Fiscal-year number: the calendar year the year ends in, except that 52/53-week years
    ending in the first week of January belong to the preceding year."""
    return end.year - 1 if end.month == 1 and end.day <= 7 else end.year


@dataclass
class SourceFact:
    """One value exactly as the SEC companyfacts API reports it."""
    concept: str
    unit: str
    start: date
    end: date
    value: float
    form: str
    filed: str
    accession: str
    fy: int | None = None
    fp: str | None = None

    @property
    def days(self) -> int:
        return _days(self.start, self.end)


@dataclass
class Observation:
    """One period of a series, with the SEC facts it was taken or derived from."""
    start: date
    end: date
    value: float
    method: str                      # "reported" or "derived"
    sources: list[SourceFact]
    note: str = ""
    label: str = ""
    restated_from: list[tuple[float, str]] = field(default_factory=list)

    @property
    def days(self) -> int:
        return _days(self.start, self.end)

    @property
    def primary(self) -> SourceFact:
        return self.sources[0]


@dataclass
class Series:
    concept: str
    taxonomy: str
    label: str
    unit: str
    frequency: str                  # "annual" or "quarterly"
    observations: list[Observation]
    issues: list[str]


# ---------------------------------------------------------------------------
def concept_units(facts: dict, taxonomy: str, concept: str) -> dict[str, list[dict]]:
    return facts.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {})


def concept_label(facts: dict, taxonomy: str, concept: str) -> str:
    return facts.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("label") or concept


def _pick_unit(units: dict[str, list[dict]], monetary: bool) -> tuple[str | None, list[str]]:
    keys = [k for k in units if bool(_CURRENCY.match(k)) == monetary]
    if not keys:
        return None, []
    keys.sort(key=lambda k: -len(units[k]))
    return keys[0], keys[1:]


def _source_facts(raw: list[dict], concept: str, unit: str, forms: set[str]) -> list[SourceFact]:
    out = []
    for r in raw:
        if "start" not in r or r.get("form") not in forms or r.get("val") is None:
            continue
        out.append(SourceFact(concept=concept, unit=unit, start=_d(r["start"]), end=_d(r["end"]),
                              value=float(r["val"]), form=r["form"], filed=r.get("filed", ""),
                              accession=r.get("accn", ""), fy=r.get("fy"), fp=r.get("fp")))
    return out


def _latest_by_period(facts: list[SourceFact]) -> dict[tuple[date, date], Observation]:
    """Collapse duplicate reports of the same period to the most recently filed value."""
    groups: dict[tuple[date, date], list[SourceFact]] = defaultdict(list)
    for f in facts:
        groups[(f.start, f.end)].append(f)
    out = {}
    for key, fs in groups.items():
        fs.sort(key=lambda f: (f.filed, f.accession))
        latest = fs[-1]
        restated = []
        seen = set()
        for f in fs[:-1]:
            if abs(f.value - latest.value) > max(1.0, 1e-6 * abs(latest.value)) and f.value not in seen:
                restated.append((f.value, f.accession))
                seen.add(f.value)
        out[key] = Observation(start=key[0], end=key[1], value=latest.value, method="reported",
                               sources=[latest], restated_from=restated)
    return out


def _chain(obs: list[Observation], issues: list[str], kind: str) -> list[Observation]:
    """Keep a non-overlapping sequence, preferring the most recent period on conflict."""
    kept: list[Observation] = []
    for o in sorted(obs, key=lambda o: (o.end, o.start), reverse=True):
        if kept and o.end > kept[-1].start - timedelta(days=1) + timedelta(days=CONTIGUITY_TOLERANCE_DAYS):
            issues.append(f"Overlapping {kind} period {o.start}–{o.end} was skipped in favor of "
                          f"{kept[-1].start}–{kept[-1].end}.")
            continue
        kept.append(o)
    return sorted(kept, key=lambda o: o.end)


def annual_series(obs_by_period: dict, issues: list[str]) -> list[Observation]:
    annual = [o for o in obs_by_period.values()
              if _in(o.days, ANNUAL_DAYS) and o.primary.form in ANNUAL_FORMS]
    out = _chain(annual, issues, "annual")
    for o in out:
        o.label = f"FY{fiscal_year(o.end)}"
    return out


def quarterly_series(obs_by_period: dict, issues: list[str]) -> list[Observation]:
    quarters: dict[date, Observation] = {}
    for o in obs_by_period.values():
        if _in(o.days, QUARTER_DAYS):
            prev = quarters.get(o.end)
            if prev is None or o.primary.filed > prev.primary.filed:
                quarters[o.end] = o

    # Cumulative (year-to-date) values grouped by their common start date.
    by_start: dict[date, list[Observation]] = defaultdict(list)
    for o in obs_by_period.values():
        if any(_in(o.days, r) for r in (QUARTER_DAYS, HALF_DAYS, NINE_DAYS, ANNUAL_DAYS)):
            by_start[o.start].append(o)
    for start, cum in by_start.items():
        cum.sort(key=lambda o: o.end)
        for prev, cur in zip(cum, cum[1:]):
            q_start = prev.end + timedelta(days=1)
            if not _in(_days(q_start, cur.end), QUARTER_DAYS):
                continue
            derived_value = cur.value - prev.value
            existing = quarters.get(cur.end)
            if existing is not None and abs((existing.start - q_start).days) <= 5:
                if existing.method == "reported" and abs(existing.value - derived_value) > max(
                        1.0, 0.005 * abs(existing.value)):
                    issues.append(
                        f"Reported quarter ending {cur.end} ({existing.value:,.0f}) differs from the "
                        f"value implied by year-to-date filings ({derived_value:,.0f}); the reported "
                        f"three-month value was used.")
                continue
            quarters[cur.end] = Observation(
                start=q_start, end=cur.end, value=derived_value, method="derived",
                sources=[cur.primary, prev.primary],
                note=(f"{cur.days}-day YTD ({cur.primary.form} {cur.primary.accession}) − "
                      f"{prev.days}-day YTD ({prev.primary.form} {prev.primary.accession})"))
    out = _chain(list(quarters.values()), issues, "quarterly")

    # Label quarters by the fiscal year (annual period) that contains them.
    years = [o for o in obs_by_period.values() if _in(o.days, ANNUAL_DAYS)]
    for q in out:
        fy = next((y for y in years if y.start - timedelta(days=5) <= q.start and q.end <= y.end
                   + timedelta(days=5)), None)
        if fy is None:
            q.label = f"Q ending {q.end}"
        else:
            k = round(((q.end - fy.start).days + 1) / 91.3)
            q.label = f"FY{fiscal_year(fy.end)}-Q{min(max(k, 1), 4)}"
    _check_quarter_sums(out, years, issues)
    return out


def _unique_labels(obs: list[Observation]) -> None:
    seen: dict[str, int] = defaultdict(int)
    for o in obs:
        seen[o.label] += 1
    for o in obs:
        if seen[o.label] > 1:
            o.label = f"{o.label} ({o.end})"


def _check_quarter_sums(quarters: list[Observation], years: list[Observation], issues: list[str]):
    """Four quarters inside a fiscal year must add up to the reported annual total."""
    for y in years:
        qs = [q for q in quarters if y.start - timedelta(days=5) <= q.start and q.end <= y.end + timedelta(days=5)]
        if len(qs) == 4:
            total = sum(q.value for q in qs)
            if abs(total - y.value) > max(1.0, 0.005 * abs(y.value)):
                issues.append(f"Quarters in fiscal year ending {y.end} sum to {total:,.0f}, but the "
                              f"annual total is {y.value:,.0f}.")


def extract_series(facts: dict, taxonomy: str, concept: str, frequency: str,
                   monetary: bool = True, unit: str | None = None) -> Series:
    units = concept_units(facts, taxonomy, concept)
    issues: list[str] = []
    if unit is None:
        unit, others = _pick_unit(units, monetary)
        if others:
            issues.append(f"{concept} is also reported in {', '.join(others)}; only {unit} values are used.")
    raw = units.get(unit, []) if unit else []
    forms = ANNUAL_FORMS if frequency == "annual" else QUARTERLY_FORMS
    by_period = _latest_by_period(_source_facts(raw, concept, unit or "", forms))
    obs = annual_series(by_period, issues) if frequency == "annual" else quarterly_series(by_period, issues)
    _unique_labels(obs)
    for o in obs:
        if o.restated_from:
            prior = "; ".join(f"{v:,.0f} in {a}" for v, a in o.restated_from)
            issues.append(f"{o.label} ({o.end}): value was revised across filings; latest filed value "
                          f"{o.value:,.0f} used (earlier: {prior}).")
    return Series(concept=concept, taxonomy=taxonomy, label=concept_label(facts, taxonomy, concept),
                  unit=unit or "", frequency=frequency, observations=obs, issues=issues)


def candidate_series(facts: dict, concepts: list[tuple[str, str]], frequency: str) -> list[Series]:
    """All listed concepts that yield at least one observation, best first.

    Selection rule: most observations wins; ties are broken by the order of `concepts`.
    """
    found = []
    for rank, (tax, concept) in enumerate(concepts):
        if not concept_units(facts, tax, concept):
            continue
        s = extract_series(facts, tax, concept, frequency)
        if s.observations:
            found.append((rank, s))
    found.sort(key=lambda t: (-len(t[1].observations), t[0]))
    return [s for _, s in found]


def quantity_candidates(facts: dict, frequency: str) -> list[Series]:
    """Duration facts tagged in a non-monetary, non-share unit (possible unit volumes)."""
    out = []
    for tax, concepts in facts.get("facts", {}).items():
        for concept, body in concepts.items():
            for unit in body.get("units", {}):
                if _CURRENCY.match(unit) or "/" in unit or unit.lower() in NON_VOLUME_UNITS:
                    continue
                s = extract_series(facts, tax, concept, frequency, unit=unit)
                if len(s.observations) >= 3 and all(o.value > 0 for o in s.observations):
                    out.append(s)
    out.sort(key=lambda s: -len(s.observations))
    return out


def contiguity_gaps(obs: list[Observation]) -> list[str]:
    gaps = []
    for a, b in zip(obs, obs[1:]):
        gap = (b.start - a.end).days - 1
        if abs(gap) > CONTIGUITY_TOLERANCE_DAYS:
            gaps.append(f"No observation between {a.end} and {b.start} ({gap} days missing).")
    return gaps


def concept_disagreements(primary: Series, others: list[Series]) -> list[str]:
    """Report where alternative COGS concepts give different values for the same period."""
    notes = []
    by_end = {o.end: o.value for o in primary.observations}
    for s in others:
        diffs = [abs(o.value - by_end[o.end]) / abs(by_end[o.end])
                 for o in s.observations if o.end in by_end and by_end[o.end]]
        if diffs and max(diffs) > 0.005:
            notes.append(f"The company also reports {s.concept}, which differs from {primary.concept} "
                         f"by up to {max(diffs):.1%} for the same periods. The two concepts were not combined.")
    return notes
