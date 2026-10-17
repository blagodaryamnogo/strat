"""Learning-Curve Calculator — Streamlit interface.

Run locally:  streamlit run learning_curve/app.py
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import timedelta

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

import financials as fin
from analysis import (CAUSALITY_LIMITATION, METHOD_LABELS, METHOD_REVENUE_ASP, METHOD_USER_UNITS,
                      METHOD_XBRL_UNITS, MIN_OBSERVATIONS, WINDOW_LIMITATION, PeriodInput, build_analysis,
                      equation_text, fmt_b, fmt_pct, fmt_r2, methodology_text)
from charts import experience_curve_figure
from report import build_csv, build_pdf, report_filename
from sec_client import SECClient, SECError, latest_periodic_report, primary_documents

st.set_page_config(page_title="Learning-Curve Calculator", page_icon="📉", layout="wide")


def setting(name: str) -> str:
    """Read configuration from an environment variable or Streamlit secrets."""
    value = os.environ.get(name, "")
    if not value:
        try:
            value = st.secrets.get(name, "")
        except Exception:  # no secrets file
            value = ""
    return str(value).strip()


@st.cache_data(ttl=24 * 3600, show_spinner=False, max_entries=20)
def load_company(query: str, user_agent: str):
    client = SECClient(user_agent)
    info = client.lookup(query)
    facts = client.company_facts(info["cik"])
    try:
        subs = client.submissions(info["cik"])
    except SECError:
        subs = {}
    return info, facts, primary_documents(subs), latest_periodic_report(subs)


@st.cache_data(show_spinner=False, max_entries=40)
def series_for(cik: int, frequency: str, kind: str, _facts: dict):
    if kind == "cogs":
        return fin.candidate_series(_facts, fin.COGS_CONCEPTS, frequency)
    if kind == "revenue":
        return fin.candidate_series(_facts, fin.REVENUE_CONCEPTS, frequency)
    return fin.quantity_candidates(_facts, frequency)


def parse_upload(upload, observations, value_col: str) -> tuple[dict, list[str]]:
    """Read a user CSV (period_end, units|asp, source) and match rows to periods by end date (±10 days)."""
    msgs = []
    try:
        df = pd.read_csv(upload)
    except Exception as e:
        return {}, [f"Could not read the CSV file: {e}"]
    df.columns = [c.strip().lower() for c in df.columns]
    if "period_end" not in df.columns or value_col not in df.columns:
        return {}, [f"The CSV needs columns 'period_end', '{value_col}' and 'source'."]
    out = {}
    for _, row in df.iterrows():
        try:
            end = pd.to_datetime(row["period_end"]).date()
            value = float(str(row[value_col]).replace(",", ""))
        except Exception:
            msgs.append(f"Skipped unreadable CSV row: {row.to_dict()}")
            continue
        match = min(observations, key=lambda o: abs((o.end - end).days))
        if abs((match.end - end).days) > 10:
            msgs.append(f"CSV period ending {end} does not match any SEC reporting period; ignored.")
            continue
        src = row.get("source", "")
        out[match.end.isoformat()] = {"value": value, "source": "" if pd.isna(src) else str(src)}
    return out, msgs


def signature(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()


# ---------------------------------------------------------------------------
st.title("Learning-Curve Calculator")
st.markdown("Measure whether a company's costs decline with cumulative production.")

user_agent = setting("SEC_USER_AGENT")
app_url = setting("PUBLIC_APP_URL")
if not user_agent:
    with st.expander("SEC contact required", expanded=True):
        st.write("The SEC asks every API user to identify themselves. Enter your name and email; it is sent "
                 "only to SEC EDGAR in the request header. (Site owners can set SEC_USER_AGENT instead.)")
        user_agent = st.text_input("Your name and email", placeholder="Jane Doe jane@example.edu")

with st.form("lookup"):
    c1, c2, c3 = st.columns([2, 2, 1])
    ticker_in = c1.text_input("Public company ticker symbol", placeholder="e.g. TSLA",
                              help="US-listed company that files with the SEC. A numeric CIK also works.")
    freq_in = c2.radio("Data frequency", ["Annual", "Quarterly"], horizontal=True,
                       help="Quarterly values are reconstructed from 10-Q and 10-K filings without "
                            "double-counting year-to-date totals.")
    c3.write("")
    c3.write("")
    fetch = c3.form_submit_button("Retrieve SEC data", width="stretch")

if fetch:
    try:
        with st.spinner("Retrieving SEC EDGAR data…"):
            info, facts, docs, latest_report = load_company(ticker_in, user_agent)
        st.session_state["loaded"] = {"info": info, "facts": facts, "docs": docs, "latest": latest_report,
                                      "freq": freq_in.lower()}
        st.session_state.pop("calc_sig", None)
    except SECError as e:
        st.error(str(e))
        st.session_state.pop("loaded", None)

loaded = st.session_state.get("loaded")
if not loaded:
    st.caption("Data come from the SEC EDGAR Company Facts API. Unit volumes are needed as well: they are "
               "rarely tagged in SEC data, so you can enter them with their source.")
    st.stop()

info, facts, docs, freq = loaded["info"], loaded["facts"], loaded["docs"], loaded["freq"]
latest_report = loaded.get("latest")
company = facts.get("entityName") or info["title"] or info["ticker"]
cik = info["cik"]
st.subheader(f"{company} ({info['ticker']})")
st.caption(f"SEC CIK {cik} · {freq} data")

# ---- Step 1: COGS ----------------------------------------------------------
st.markdown("#### 1. Cost of goods sold from SEC filings")
cogs_candidates = series_for(cik, freq, "cogs", facts)
if not cogs_candidates:
    if freq == "quarterly" and series_for(cik, "annual", "cogs", facts):
        st.error("This company reports COGS only annually in SEC XBRL data (foreign filers using 20-F or "
                 "40-F do not file quarterly reports). Choose Annual and retrieve again.")
    else:
        st.error("This company does not report a cost-of-goods-sold concept in SEC XBRL data "
                 "(checked: " + ", ".join(c for _, c in fin.COGS_CONCEPTS) + "). Banks, insurers and some "
                 "service companies do not report COGS, and some companies use company-specific tags that "
                 "the SEC Company Facts API does not publish. An experience curve cannot be calculated from "
                 "its filings.")
    st.stop()
labels = [f"{s.concept} — {len(s.observations)} periods, {s.observations[0].end} to {s.observations[-1].end}"
          for s in cogs_candidates]
pick = st.selectbox("COGS concept (XBRL tag)", range(len(labels)), format_func=lambda i: labels[i],
                    help="Selected automatically: the candidate with the most periods, ties broken in the order "
                         "CostOfGoodsAndServicesSold, CostOfRevenue, CostOfGoodsSold. Concepts are never combined.")
others = [s for i, s in enumerate(cogs_candidates) if i != pick]
fill = st.checkbox("Fill missing periods from an alternative COGS tag when it reports identical values",
                   value=True, help="Companies sometimes switch XBRL tags (e.g. CostOfGoodsSold → "
                   "CostOfGoodsAndServicesSold). A missing period is filled only from a tag whose values match the "
                   "selected tag (within 0.5%) in at least two overlapping periods. Every row shows its own tag.")
cogs = fin.fill_from_alternatives(cogs_candidates[pick], others) if fill else cogs_candidates[pick]
if latest_report and cogs.observations[-1].end < latest_report - timedelta(days=200):
    st.warning(f"The latest {cogs.concept} value is for the period ending {cogs.observations[-1].end}, but the "
               f"company has filed reports through {latest_report}. Its recent filings probably use a "
               f"company-specific COGS tag, which the SEC Company Facts API does not publish, so recent "
               f"periods cannot be retrieved here.")
if len(cogs.observations) < MIN_OBSERVATIONS:
    st.error(f"Only {len(cogs.observations)} {freq} COGS observations are available; at least "
             f"{MIN_OBSERVATIONS} are required.")
    st.stop()

period_labels = [o.label for o in cogs.observations]
default_n = 10 if freq == "annual" else 20
# A requested range (from the "Set analysis period" button) is stored separately and applied by giving the
# slider a new key; writing a range select_slider's own state from a callback is lost on the next rerun.
window_key = f"window-{cik}-{freq}-{cogs.concept}-{fill}"
window_range = st.session_state.get(window_key + "-range")
if not window_range or any(lbl not in period_labels for lbl in window_range):
    window_range = (period_labels[max(0, len(period_labels) - default_n)], period_labels[-1])
window_ver = st.session_state.get(window_key + "-ver", 0)
start_label, end_label = st.select_slider(
    "Analysis period", options=period_labels, value=window_range, key=f"{window_key}-{window_ver}",
    help="Defaults to the most recent 10 fiscal years (annual) or 20 quarters (quarterly).")
i0, i1 = period_labels.index(start_label), period_labels.index(end_label)
window = cogs.observations[i0:i1 + 1]
concept_notes = fin.concept_disagreements(cogs_candidates[pick], others, window[0].start, window[-1].end)
for g in fin.contiguity_gaps(window):
    st.warning(g)
with st.expander(f"Retrieved COGS with SEC provenance ({len(window)} periods in window)"):
    st.dataframe(pd.DataFrame([{
        "Period": o.label, "Start": o.start, "End": o.end, f"COGS ({cogs.unit})": o.value,
        "How obtained": "Reported" if o.method == "reported" else "Derived: " + o.note,
        "Form": o.primary.form, "Filed": o.primary.filed, "Accession": o.primary.accession}
        for o in window]), hide_index=True, width="stretch")
    for note in cogs.notes(window[0].start, window[-1].end) + concept_notes:
        st.caption("• " + note)

# ---- Step 2: unit volumes --------------------------------------------------
st.markdown("#### 2. Unit volumes")
qty_candidates = series_for(cik, freq, "qty", facts)
method_options = [(METHOD_XBRL_UNITS, i) for i in range(len(qty_candidates))]
method_options += [(METHOD_USER_UNITS, None), (METHOD_REVENUE_ASP, None)]


def method_label(opt):
    m, i = opt
    if m == METHOD_XBRL_UNITS:
        q = qty_candidates[i]
        return f"Disclosed in SEC XBRL: {q.concept} ({q.unit}, {len(q.observations)} periods)"
    return {METHOD_USER_UNITS: "Enter or upload actual unit volumes (with source)",
            METHOD_REVENUE_ASP: "Estimate units = SEC revenue ÷ average selling price (you supply prices)"}[m]


if not qty_candidates:
    st.info("No production or sales volumes are tagged in this company's SEC XBRL data. Volumes are usually "
            "disclosed only in filing text (MD&A), earnings releases or investor presentations. Enter them "
            "below with their source, or estimate them from revenue and a documented average selling price.")
method, qty_idx = st.radio("Unit measurement method", method_options, format_func=method_label)
quantity = qty_candidates[qty_idx] if method == METHOD_XBRL_UNITS else None
st.caption(f"Method in use: **{METHOD_LABELS[method]}**")

revenue = None
if method == METHOD_REVENUE_ASP:
    rev_candidates = series_for(cik, freq, "revenue", facts)
    if not rev_candidates:
        st.error("No SEC revenue concept is available, so units cannot be estimated from revenue.")
        st.stop()
    rlabels = [f"{s.concept} — {len(s.observations)} periods" for s in rev_candidates]
    ri = st.selectbox("Revenue concept (XBRL tag)", range(len(rlabels)), format_func=lambda i: rlabels[i])
    revenue = rev_candidates[ri]

c1, c2 = st.columns(2)
unit_definition = c1.text_input(
    "What is one unit?", value=quantity.unit if quantity else "",
    placeholder="e.g. vehicles delivered", help="Shown on the chart axis and in the report.")
scope_confirmed = c2.checkbox(
    "Volumes cover all of the company's COGS (not one segment)",
    help="Consolidated COGS includes everything the company sells. If the volumes cover only part of it, "
         "leave this unticked; the result will be flagged as not company-wide.")
if quantity is not None:
    xbrl_ok = st.checkbox(f"I confirm that {quantity.concept} measures units produced or sold.")
    if not xbrl_ok:
        st.warning("Confirm that the SEC-tagged series is a production or sales volume before calculating.")

inputs: dict[str, PeriodInput] = {}
if method in (METHOD_USER_UNITS, METHOD_REVENUE_ASP):
    value_col = "units" if method == METHOD_USER_UNITS else "asp"
    value_head = "Units" if method == METHOD_USER_UNITS else f"Average selling price ({cogs.unit} per unit)"
    st.write(f"Enter **{value_head.lower()}** for every period in the window, with a source for each value "
             f"(filing, page or URL; or 'Assumption: …' for your own estimate).")
    upload = st.file_uploader(f"Optional: upload a CSV with columns period_end, {value_col}, source",
                              type=["csv"])
    template = pd.DataFrame({"period_end": [o.end for o in window], value_col: "", "source": ""})
    st.download_button("Download blank CSV template", template.to_csv(index=False).encode(),
                       file_name=f"{info['ticker']}_{freq}_{value_col}_template.csv", mime="text/csv")
    prefill, upload_msgs = ({}, [])
    if upload is not None:
        prefill, upload_msgs = parse_upload(upload, cogs.observations, value_col)
        for m in upload_msgs:
            st.warning(m)
    rev_by_end = {o.end: o.value for o in revenue.observations} if revenue else {}
    table = pd.DataFrame([{
        "Period": o.label, "Period end": o.end.isoformat(), "In window": o in window,
        f"COGS ({cogs.unit} m)": round(o.value / 1e6, 1),
        **({f"Revenue ({cogs.unit} m)": round(rev_by_end[o.end] / 1e6, 1) if o.end in rev_by_end else None}
           if revenue else {}),
        value_head: prefill.get(o.end.isoformat(), {}).get("value"),
        "Source": prefill.get(o.end.isoformat(), {}).get("source", "")}
        for o in reversed(cogs.observations)])
    upload_key = hashlib.sha1(upload.getvalue()).hexdigest()[:8] if upload is not None else "none"
    edited = st.data_editor(
        table, hide_index=True, width="stretch",
        key=f"editor-{cik}-{freq}-{cogs.concept}-{method}-{upload_key}",
        disabled=[c for c in table.columns if c not in (value_head, "Source")],
        column_config={value_head: st.column_config.NumberColumn(value_head, min_value=0.0, format="%,g"),
                       "Source": st.column_config.TextColumn("Source", width="large")})
    for _, row in edited.iterrows():
        v = row[value_head]
        if v is None or pd.isna(v):
            continue
        src = "" if pd.isna(row["Source"]) else str(row["Source"])
        inputs[row["Period end"]] = (PeriodInput(units=float(v), source=src) if method == METHOD_USER_UNITS
                                     else PeriodInput(asp=float(v), source=src))

    # Offer to fit the window to the periods the user actually supplied values for.
    filled = [i for i, o in enumerate(cogs.observations) if o.end.isoformat() in inputs]
    if filled and [o.end.isoformat() for o in window] != [cogs.observations[i].end.isoformat()
                                                          for i in range(filled[0], filled[-1] + 1)]:
        runs, run = [], [filled[0]]
        for i in filled[1:]:
            if i == run[-1] + 1:
                run.append(i)
            else:
                runs.append(run)
                run = [i]
        runs.append(run)
        best = max(runs, key=lambda r: (len(r), r[-1]))
        span = (period_labels[best[0]], period_labels[best[-1]])
        missing = [o.label for o in window if o.end.isoformat() not in inputs]
        if missing:
            st.info(f"You have values for {span[0]} – {span[1]} ({len(best)} periods), but the analysis "
                    f"period also includes {', '.join(missing)}. Every period in the window needs a value.")
            st.button(f"Set analysis period to {span[0]} – {span[1]}",
                      on_click=lambda: st.session_state.update({window_key + "-range": span,
                                                                window_key + "-ver": window_ver + 1}))

xbrl_blocked = quantity is not None and not xbrl_ok
current_sig = signature(cik, freq, cogs.concept, [o.end for o in window], method,
                        quantity.concept if quantity else "", revenue.concept if revenue else "",
                        unit_definition, scope_confirmed,
                        {k: (v.units, v.asp, v.source) for k, v in sorted(inputs.items())})

if st.button("Calculate Experience Curve", type="primary", disabled=xbrl_blocked):
    st.session_state["calc_sig"] = current_sig

if st.session_state.get("calc_sig") != current_sig:
    if "calc_sig" in st.session_state:
        st.info("Inputs changed since the last calculation. Click **Calculate Experience Curve** to update.")
    st.stop()

# ---- Results ---------------------------------------------------------------
an = build_analysis(company=company, ticker=info["ticker"], cik=cik, frequency=freq, cogs=cogs, window=window,
                    unit_method=method, unit_definition=unit_definition, scope_confirmed=scope_confirmed,
                    inputs=inputs, revenue=revenue, quantity=quantity, documents=docs,
                    extra_notes=concept_notes)
st.divider()
st.header(f"{an.company} ({an.ticker})")
if not an.ok:
    st.error("A defensible learning rate cannot be reported with the current data:\n\n"
             + "\n".join(f"- {e}" for e in an.errors))
    st.stop()

reg = an.regression
st.caption(f"{an.period_range} · {an.date_range} · {freq} · {METHOD_LABELS[an.unit_method]}")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Learning rate", fmt_pct(reg.learning_rate),
          help="1 − 2^(−b): the % change in unit cost for each doubling of cumulative units.")
m2.metric("Coefficient b", fmt_b(reg.b), help=f"Standard error {fmt_b(reg.se_b)}")
m3.metric("R²", fmt_r2(reg.r2), help="Fit of the log-log regression.")
m4.metric("Observations", reg.n)
st.markdown(f"**Regression equation:** {equation_text(reg)}, where N = cumulative {an.unit_definition}")

try:
    pdf_bytes = build_pdf(an, app_url or None)
    pdf_error = None
except Exception as e:  # report, don't crash the page
    pdf_bytes, pdf_error = None, f"The PDF report could not be generated: {e}"

if pdf_bytes:
    st.download_button("Export Report to PDF", pdf_bytes, file_name=report_filename(an), mime="application/pdf",
                       type="primary", key="pdf_top")
chart_col, _ = st.columns([3, 1])
fig = experience_curve_figure(an)
chart_col.pyplot(fig)
plt.close(fig)

st.markdown("#### Interpretation")
st.write(an.interpretation)
for w in an.warnings:
    st.warning(w)

st.markdown("#### Calculation table")
cur = an.currency
table = pd.DataFrame([{
    "Period": r["period"], "Start": r["start"], "End": r["end"], f"COGS ({cur})": r["cogs"],
    "Units": r["units"], "Cumulative units": r["cum_units"], f"Unit COGS ({cur})": r["unit_cost"],
    "In regression": r["in_regression"], "Units source": r["units_source"],
    "COGS tag": r["cogs_concept"], "COGS obtained": "Reported" if r["cogs_method"] == "reported"
    else "Derived: " + r["cogs_note"], "Form": r["cogs_form"], "Filed": r["cogs_filed"],
    "Accession": r["cogs_accession"], "SEC filing": r["cogs_url"]} for r in an.rows])
unit_fmt = "%,.0f" if all(float(r["units"]).is_integer() for r in an.rows if r["units"]) else "%,.2f"
st.dataframe(table, hide_index=True, width="stretch", column_config={
    f"COGS ({cur})": st.column_config.NumberColumn(format="%,.0f"),
    "Units": st.column_config.NumberColumn(format=unit_fmt),
    "Cumulative units": st.column_config.NumberColumn(format=unit_fmt),
    f"Unit COGS ({cur})": st.column_config.NumberColumn(format="%,.2f"),
    "SEC filing": st.column_config.LinkColumn("SEC filing", display_text="open filing")})

st.markdown("#### Data sources and limitations")
for para in methodology_text(an):
    st.markdown("- " + para)
st.markdown(f"- **{WINDOW_LIMITATION}**")
st.markdown(f"- {CAUSALITY_LIMITATION}")
st.markdown("- COGS is in nominal currency; inflation and input-price changes are not removed.")
for n in an.data_notes:
    st.caption("• " + n)

st.markdown("#### Export")
if pdf_error:
    st.error(pdf_error)
else:
    st.download_button("Export Report to PDF", pdf_bytes, file_name=report_filename(an),
                       mime="application/pdf", type="primary", key="pdf_bottom")
if not app_url:
    st.caption("PUBLIC_APP_URL is not configured, so the PDF states that the public tool link is missing.")
st.download_button("Download calculations (CSV)", build_csv(an),
                   file_name=report_filename(an).replace(".pdf", ".csv"), mime="text/csv")
st.caption(f"Input fingerprint {an.fingerprint} · generated {an.generated_at}")
