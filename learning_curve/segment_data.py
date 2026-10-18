"""Segment-level cost and unit data transcribed from SEC filings, with a citation for every figure.

Segment figures are not in the SEC Company Facts API (it publishes only consolidated, non-dimensional
facts), so they are supplied as a CSV in which each row cites the filing (form, accession number, filing
date) for the cost figure and for the unit figure. Lines starting with '#' carry report metadata as
'# key: value'. See examples/cmp_salt_segment_2015_2025.csv.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date

from analysis import PeriodInput
from financials import Observation, Series, SourceFact
from sec_client import filing_document_url

REQUIRED = ["period_label", "period_start", "period_end", "segment_cost", "units", "cost_form",
            "cost_accession", "cost_filed", "cost_derivation", "units_form", "units_accession",
            "units_location", "include_in_regression"]
META_KEYS = ["segment", "cost_measure", "unit_definition", "units_scale_note", "subject_company",
             "comparable_reason", "comparability_note", "limitations"]   # limitations: items separated by "|"
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")


def parse_segment_csv(data: bytes, cik: int, documents: dict[str, str] | None = None):
    """Return (series, inputs, meta, errors). Nothing is returned for use if any row is invalid."""
    documents = documents or {}
    text = data.decode("utf-8-sig")
    meta = {k: "" for k in META_KEYS}
    body = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            key, _, value = line.lstrip()[1:].partition(":")
            if key.strip() in meta:
                meta[key.strip()] = value.strip()
        elif line.strip():
            body.append(line)
    errors: list[str] = []
    rows = list(csv.DictReader(io.StringIO("\n".join(body))))
    if not rows:
        return None, {}, meta, ["The segment CSV has no data rows."]
    missing = [c for c in REQUIRED if c not in rows[0]]
    if missing:
        return None, {}, meta, [f"The segment CSV is missing columns: {', '.join(missing)}."]
    if not meta["cost_measure"]:
        errors.append("Add a '# cost_measure: …' line describing the segment cost figure.")

    observations, inputs, issues = [], {}, []
    for n, r in enumerate(rows, start=2):
        label = (r["period_label"] or "").strip() or f"row {n}"
        try:
            start, end = date.fromisoformat(r["period_start"].strip()), date.fromisoformat(r["period_end"].strip())
            cost = float(r["segment_cost"].replace(",", ""))
            units = float(r["units"].replace(",", ""))
        except ValueError as e:
            errors.append(f"{label}: unreadable date or number ({e}).")
            continue
        if end <= start:
            errors.append(f"{label}: period_end must be after period_start.")
        if cost <= 0 or units <= 0:
            errors.append(f"{label}: segment cost and units must be positive.")
        for col in ("cost_accession", "units_accession"):
            if not _ACCESSION.match(r[col].strip()):
                errors.append(f"{label}: {col} '{r[col]}' is not an SEC accession number (##########-##-######).")
        for col in ("cost_form", "cost_filed", "cost_derivation", "units_form", "units_location"):
            if not r[col].strip():
                errors.append(f"{label}: {col} is required.")
        include = r["include_in_regression"].strip().lower()
        if include not in ("yes", "no"):
            errors.append(f"{label}: include_in_regression must be 'yes' or 'no'.")
        reason = (r.get("exclusion_reason") or "").strip()
        if include == "no" and not reason:
            errors.append(f"{label}: give an exclusion_reason for a period left out of the regression.")
        derivation = r["cost_derivation"].strip()
        fact = SourceFact(concept=meta["cost_measure"], unit="USD", start=start, end=end, value=cost,
                          form=r["cost_form"].strip(), filed=r["cost_filed"].strip(),
                          accession=r["cost_accession"].strip())
        observations.append(Observation(start=start, end=end, value=cost,
                                        method="derived" if derivation.lower().startswith("derived") else "reported",
                                        sources=[fact], note=derivation, label=label))
        accn = r["units_accession"].strip()
        inputs[end.isoformat()] = PeriodInput(
            units=units,
            source=f"{r['units_form'].strip()} {accn}, {r['units_location'].strip()}",
            source_url=filing_document_url(cik, accn, documents.get(accn)) if _ACCESSION.match(accn) else "",
            exclude_reason=reason if include == "no" else "")
        if (r.get("restatement_note") or "").strip():
            issues.append((end, f"{label}: {r['restatement_note'].strip()}"))
    if errors:
        return None, {}, meta, errors
    observations.sort(key=lambda o: o.end)
    if len({o.end for o in observations}) != len(observations):
        return None, {}, meta, ["The segment CSV contains duplicated reporting periods."]
    series = Series(concept=meta["cost_measure"], taxonomy="segment", label=meta["cost_measure"], unit="USD",
                    frequency="annual", observations=observations, issues=issues)
    return series, inputs, meta, []
