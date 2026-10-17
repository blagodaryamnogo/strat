"""PDF and CSV exports built from a finished Analysis (no re-fetching)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from analysis import (CAUSALITY_LIMITATION, DISCLAIMER, METHOD_LABELS, METHOD_REVENUE_ASP, WINDOW_LIMITATION,
                      Analysis, equation_text, fmt_b, fmt_pct, fmt_r2, fmt_units, methodology_text)
from charts import experience_curve_figure, figure_png

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
RULE = colors.HexColor("#cbd2d9")
HEAD_BG = colors.HexColor("#eef2f6")
LINK = "#1f5f8b"

BASE = ParagraphStyle("base", fontName="DejaVu", fontSize=9, leading=12.5, textColor=INK, alignment=TA_LEFT)
SMALL = ParagraphStyle("small", parent=BASE, fontSize=7, leading=9)
CELL = ParagraphStyle("cell", parent=BASE, fontSize=7, leading=8.6)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="DejaVu-Bold")
H1 = ParagraphStyle("h1", parent=BASE, fontName="DejaVu-Bold", fontSize=18, leading=22, spaceAfter=4)
H2 = ParagraphStyle("h2", parent=BASE, fontName="DejaVu-Bold", fontSize=12.5, leading=16, spaceBefore=10,
                    spaceAfter=5)
H3 = ParagraphStyle("h3", parent=BASE, fontName="DejaVu-Bold", fontSize=10, leading=13, spaceBefore=8,
                    spaceAfter=3)
H3K = ParagraphStyle("h3k", parent=H3, keepWithNext=1)
BULLET = ParagraphStyle("bullet", parent=BASE, leftIndent=10, bulletIndent=0, spaceAfter=2)

_URL = re.compile(r"(https?://[^\s<>&]+)")


def report_filename(an: Analysis, on: date | None = None) -> str:
    safe = re.sub(r"[^A-Za-z0-9-]", "", an.ticker.upper()) or "CIK" + str(an.cik)
    return f"Learning_Curve_{safe}_{(on or date.today()).isoformat()}.pdf"


def _p(text: str, style=BASE) -> Paragraph:
    return Paragraph(text, style)


def _txt(text: str, style=BASE) -> Paragraph:
    """Escape untrusted text and make any URLs in it clickable."""
    html = _URL.sub(lambda m: f'<link href="{m.group(1)}" color="{LINK}">{m.group(1)}</link>', escape(text or ""))
    return Paragraph(html, style)


def _link(url: str, label: str, style=CELL) -> Paragraph:
    return Paragraph(f'<link href="{escape(url)}" color="{LINK}">{escape(label)}</link>', style)


def _table(data, widths, header=True, align_right=()):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "DejaVu", 7), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3),
             ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("FONT", (0, 0), (-1, 0), "DejaVu-Bold", 7)]
    for c in align_right:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _bullets(items):
    return [Paragraph(escape(i), BULLET, bulletText="•") for i in items]


def build_pdf(an: Analysis, app_url: str | None) -> bytes:
    if not an.ok:
        raise ValueError("The analysis has no valid result to export.")
    buf = io.BytesIO()
    margin = 0.75 * inch
    doc = BaseDocTemplate(buf, pagesize=letter, leftMargin=margin, rightMargin=margin, topMargin=0.85 * inch,
                          bottomMargin=0.75 * inch, title=f"Learning-Curve Calculator — {an.ticker}",
                          author="Learning-Curve Calculator", subject="Experience-curve analysis")
    width = letter[0] - 2 * margin

    def header_footer(canvas, d):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(MUTED)
        top = letter[1] - 0.5 * inch
        canvas.drawString(margin, top, "Learning-Curve Calculator")
        canvas.drawRightString(letter[0] - margin, top, f"{an.company} ({an.ticker})")
        canvas.setStrokeColor(RULE)
        canvas.line(margin, top - 4, letter[0] - margin, top - 4)
        canvas.line(margin, 0.55 * inch, letter[0] - margin, 0.55 * inch)
        canvas.drawString(margin, 0.4 * inch, f"Generated {an.generated_at} · input fingerprint {an.fingerprint}")
        canvas.drawRightString(letter[0] - margin, 0.4 * inch, f"Page {d.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="main", onPage=header_footer,
                                       frames=[Frame(margin, doc.bottomMargin, width, doc.height, id="f")])])
    reg = an.regression
    story = []

    # Section 1: tool link
    story.append(_p("Learning-Curve Calculator", H1))
    if app_url:
        story.append(_p(f'<b>Public Tool URL:</b> <link href="{escape(app_url)}" color="{LINK}">'
                        f'<u>{escape(app_url)}</u></link>'))
    else:
        story.append(_p('<b>Public Tool URL:</b> <font color="#b42318">Not configured — this report is missing '
                        'the public link. Set PUBLIC_APP_URL in the app settings.</font>'))
    story.append(Spacer(1, 6))

    # Section 2: results
    story.append(_p("Analysis Results", H2))
    summary = [
        ("Company", f"{an.company} ({an.ticker}), SEC CIK {an.cik}"),
        ("Analysis period", f"{an.period_range} ({an.date_range})"),
        ("Data frequency", an.frequency.capitalize()),
        ("Learning rate", fmt_pct(reg.learning_rate)),
        ("Coefficient b", f"{fmt_b(reg.b)} (standard error {fmt_b(reg.se_b)})"),
        ("R² (log-log)", fmt_r2(reg.r2)),
        ("Observations", str(reg.n)),
        ("Regression equation", f"{equation_text(reg)}, where N = cumulative {an.unit_definition}"),
        ("Unit measurement", METHOD_LABELS[an.unit_method]),
        ("COGS concept", f"{an.cogs_concept} ({an.currency})"),
    ]
    story.append(_table([[_p(k, CELL_B), _txt(v, CELL)] for k, v in summary],
                        [1.45 * inch, width - 1.45 * inch], header=False))
    story.append(Spacer(1, 8))
    png = figure_png(experience_curve_figure(an), dpi=200)
    img = Image(io.BytesIO(png))
    chart_w = 0.88 * width
    img.drawWidth, img.drawHeight = chart_w, img.imageHeight * chart_w / img.imageWidth
    story.append(img)
    story.append(_p("Interpretation", H3))
    story.append(_txt(an.interpretation))
    if an.warnings:
        story.append(_p("Qualifications", H3K))
        story.extend(_bullets(an.warnings))

    # Section 3: data, sources, methodology
    story.append(PageBreak())
    story.append(_p("Data, Sources, and Methodology", H2))
    story.append(_p("Period-level calculation", H3))
    cur = an.currency
    head = ["Period", "Start", "End", f"COGS ({cur} m)", "Units", "Cumulative units", f"Unit COGS ({cur})", "Used"]
    rows = [head]
    for r in an.rows:
        rows.append([r["period"], r["start"], r["end"], f"{r['cogs'] / 1e6:,.1f}",
                     fmt_units(r["units"]) if r["units"] else "—",
                     fmt_units(r["cum_units"]) if r["cum_units"] else "—",
                     f"{r['unit_cost']:,.2f}" if r["unit_cost"] else "—",
                     "yes" if r["in_regression"] else "no"])
    story.append(_table(rows, [w * inch for w in (0.85, 0.75, 0.75, 1.0, 1.0, 1.05, 1.0, 0.6)],
                        align_right=(3, 4, 5, 6)))

    story.append(_p("SEC sources for COGS", H3))
    src = [["Period", "XBRL tag", "Value", "Form", "Filed", "Accession (link)", "How obtained"]]
    for r in an.rows:
        how = "Reported" if r["cogs_method"] == "reported" else "Derived: " + r["cogs_note"]
        src.append([_p(r["period"], CELL), _p(r["cogs_concept"], CELL), _p(f"{r['cogs']:,.0f}", CELL),
                    _p(r["cogs_form"], CELL), _p(r["cogs_filed"], CELL),
                    _link(r["cogs_url"], r["cogs_accession"]), _txt(how, CELL)])
    story.append(_table(src, [w * inch for w in (0.68, 1.45, 0.95, 0.42, 0.65, 1.4, 1.45)]))

    story.append(_p("Unit volume sources", H3))
    story.append(_txt(f"Method: {METHOD_LABELS[an.unit_method]}. Unit definition: {an.unit_definition}. "
                      f"Scope confirmed to match consolidated COGS: {'yes' if an.scope_confirmed else 'NO'}."))
    story.append(Spacer(1, 3))
    if an.unit_method == METHOD_REVENUE_ASP:
        u = [["Period", f"Revenue ({cur})", "Revenue accession", f"ASP ({cur})", "Estimated units", "ASP source"]]
        for r in an.rows:
            u.append([_p(r["period"], CELL), _p(f"{r['revenue']:,.0f}" if r["revenue"] else "—", CELL),
                      _link(r["revenue_url"], r["revenue_accession"]) if r.get("revenue_url") else _p("—", CELL),
                      _p(f"{r['asp']:,.2f}" if r["asp"] else "—", CELL),
                      _p(fmt_units(r["units"]) if r["units"] else "—", CELL), _txt(r["units_source"], CELL)])
        story.append(_table(u, [w * inch for w in (0.65, 0.95, 1.25, 0.7, 0.85, 2.6)]))
        story.append(Spacer(1, 3))
        story.append(_p(f"Revenue concept: {escape(an.revenue_concept)} (SEC XBRL). Average selling prices "
                        f"are user-supplied with the sources shown.", SMALL))
    else:
        u = [["Period", "Units", "Source"]]
        for r in an.rows:
            u.append([_p(r["period"], CELL), _p(fmt_units(r["units"]) if r["units"] else "—", CELL),
                      _link(r["units_url"], r["units_source"]) if r.get("units_url") else _txt(r["units_source"], CELL)])
        story.append(_table(u, [0.8 * inch, 1.1 * inch, width - 1.9 * inch]))

    story.append(_p("Methodology", H3))
    for para in methodology_text(an):
        story.append(_txt(para))
        story.append(Spacer(1, 3))
    story.append(KeepTogether([_p("Limitations", H3)] + _bullets([
        WINDOW_LIMITATION, CAUSALITY_LIMITATION,
        "COGS is in nominal currency; inflation and input-price changes are not removed.",
        "Consolidated COGS includes every product and service the company sells; unit volumes that cover only "
        "part of the business produce a misleading curve.",
    ] + (["Estimated units depend entirely on the supplied average selling prices."]
         if an.unit_method == METHOD_REVENUE_ASP else []))))
    if an.data_notes:
        story.append(_p("Data notes", H3))
        story.extend(_bullets(an.data_notes))
    story.append(_p("Automatic checks passed", H3))
    story.extend(_bullets([
        "No duplicated reporting periods; no gaps between consecutive periods in the window.",
        f"Every period has a duration consistent with {an.frequency} reporting.",
        "Every period has positive units with a documented source; non-positive COGS periods are excluded "
        "from the regression but their units still count toward cumulative volume.",
        f"At least 5 usable observations (n = {reg.n}).",
    ]))
    story.append(Spacer(1, 8))
    story.append(_p(f"Generated {an.generated_at}. Input fingerprint {an.fingerprint} (identical inputs give an "
                    f"identical fingerprint and identical results). {escape(DISCLAIMER)}", SMALL))
    doc.build(story)
    return buf.getvalue()


CSV_COLUMNS = ["period", "start", "end", "days", "cogs", "units", "cum_units", "unit_cost", "in_regression",
               "excluded_reason", "units_source", "revenue", "asp", "cogs_concept", "cogs_method", "cogs_form",
               "cogs_filed", "cogs_accession", "cogs_url", "cogs_note"]


def build_csv(an: Analysis) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in an.rows:
        w.writerow(r)
    return buf.getvalue().encode()
