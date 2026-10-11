"""Build the static site assets and the PDF from data/processed/analysis.json.

Outputs into site/: analysis.json, reviews.json, charts/*.svg, report.html, report.pdf
"""
import json
import shutil
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import charts  # noqa: E402

SITE = ROOT / "site"
_CH = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome"))
CHROMIUM = str(_CH[-1]) if _CH else None  # None -> Playwright's default browser

BIAS = ("Online reviews overrepresent customers with unusually positive or negative experiences, creating a "
        "potentially bimodal distribution that exaggerates apparent customer polarization relative to the broader customer base.")


# Theme -> hypothesised Silk Road Salts response. Hypotheses only; shown only when the theme is observed.
RESPONSES = {
    "Packaging / container failure": "Rigid, resealable tins/jars; test against pouch leakage complaints.",
    "Clumping / moisture": "Moisture-barrier packaging and desiccant lids; communicate storage guidance.",
    "Texture / crystal size": "Publish crystal-size specs per SKU; consistent sifting.",
    "Flavor / taste quality": "Small-batch infusions using whole botanicals; tasting notes on pack.",
    "Price / value": "Transparent per-ounce pricing; sampler sizes to lower trial cost.",
    "Small quantity / portion": "Show fill weight clearly; avoid oversized packaging.",
    "Shipping damage / delivery": "Protective secondary packaging for glass; ship-test before launch.",
    "Sourcing / authenticity / contaminants": "Provenance documentation and third-party purity testing per lot.",
    "Gifting": "Curated gift collections with educational provenance cards.",
}


def pct(v):
    return "N/A" if v is None else f"{v:.1f}%"


def sgn(v):
    return "N/A" if v is None else f"{v:+d}"


def cap_note(c):
    if not c.get("capped_stars"):
        return ""
    stars = "/".join(str(x) for x in c["capped_stars"])
    if c.get("comparable", True):
        return f"<br><span class=muted>{stars}&#9733; capped: NPS is a lower bound</span>"
    return f"<br><span class=muted><b>Not ranked:</b> {stars}&#9733; capped (see &sect;3)</span>"


def startup_text(a, reviews_by_id):
    """Returns list of (heading, html) blocks, generated from analysis values only."""
    scored = [c for c in a["competitors"] if c["nps"] is not None and c.get("comparable", True)]
    excl = [c for c in a["competitors"] if c["nps"] is not None and not c.get("comparable", True)]
    w = a["wedge"]
    if not scored:
        return [("Status", "<p><b>No startup conclusion is drawn.</b> No genuine reviews could be collected in this build "
                 "(collection endpoint blocked by network policy; see collection log). Every hypothesis below is untested.</p>"),
                ("Hypotheses to test once data exists (not findings)",
                 "<ul>" + "".join(f"<li>{escape(k)}: {escape(v)}</li>" for k, v in list(RESPONSES.items())[:5]) + "</ul>")]
    if not scored:
        return [("Status", "<p><b>No comparable competitor scores.</b> Every scored sample hit the retrieval cap in several star buckets.</p>")]
    lo = min(scored, key=lambda c: c["nps_exact"])
    lb = [c for c in scored if c.get("capped_stars")]
    small = [c for c in scored if c["below_min_n"]]
    ov = (f"<p>{len(scored)} of {len(a['competitors'])} competitors have comparable scores. Baseline NPS ranges from "
          f"{sgn(lo['nps'])} ({escape(lo['competitor'])}) to {sgn(max(c['nps'] for c in scored))} "
          f"({escape(max(scored, key=lambda c: c['nps_exact'])['competitor'])}).")
    if small:
        ov += " Below the " + str(a["min_n_target"]) + "-review target: " + "; ".join(f"{escape(c['competitor'])} (n={c['n']})" for c in small) + " (no comparable alternative ASIN found)."
    if lb:
        ov += " Lower bound only (5&#9733; bucket capped): " + "; ".join(f"{escape(c['competitor'])} ({sgn(c['nps'])})" for c in lb) + "."
    ov += "</p>"
    if excl:
        ov += ("<p><b>Not comparable:</b> " + "; ".join(
                   f"{escape(c['competitor'])} (sample NPS {sgn(c['nps'])}, n={c['n']}; capped buckets: {'/'.join(str(x) for x in c['capped_stars'])}&#9733;)" for c in excl) +
               ". The endpoint returns at most ~110&ndash;125 distinct reviews per star bucket, so for these heavily reviewed products the retrieved star mix is set by the cap, "
               "not by customers. Their sample scores are an artifact of retrieval and say nothing about loyalty; they are excluded from ranks and from the wedge test.</p>")
    blocks = [("1. Competitive overview", ov)]
    if w["status"] == "evaluated":
        cands = [c for c in scored if c["competitor"] in w["candidates"]]
        txt = "; ".join(f"{escape(c['competitor'])} (n={c['n']}, NPS {sgn(c['nps'])}, 95% CI {c['ci95_low']:+.0f} to {c['ci95_high']:+.0f})" for c in cands)
        blocks.append(("2. Entry wedge (measured)",
                       f"<p>Rule: retrieved volume &ge; median ({w['median_volume']:.0f}) and baseline NPS below median ({w['median_nps']:+.1f}). "
                       f"Qualifying: {txt}. Retrieved volume is a capped proxy for market activity, so this is a candidate wedge, not a proven one.</p>"))
    else:
        blocks.append(("2. Entry wedge",
                       "<p><b>No high-volume / low-loyalty wedge can be shown from this data.</b> Among the comparable products, none with at-or-above-median retrieved volume "
                       f"has below-median NPS. {escape(', '.join(w.get('excluded_not_comparable', [])) or 'No product')} could not be tested because of capped samples. "
                       "The entry case therefore rests on the dissatisfaction themes below, not on a measured weak incumbent.</p>"
                       if w["status"] == "no_classic_wedge" else
                       "<p><b>Wedge not evaluated:</b> fewer than three competitors have comparable scores.</p>"))
    top = [t for t in a["themes"] if t["mentions_detractor"] > 0][:3]
    rows = "".join(
        f"<tr><td>{escape(t['theme'])}</td><td class=n>{t['mentions_detractor']}</td><td class=n>{pct(t['pct_of_detractors'])}</td>"
        f"<td>{escape(', '.join(f'{k} ({v})' for k, v in t['detractor_mentions_by_competitor'].items()))}</td>"
        f"<td>{escape(RESPONSES[t['theme']])}</td></tr>" for t in top)
    blocks.append(("3. Customer dissatisfaction evidence &rarr; Silk Road response (hypothesis)",
                   f"<p>Keyword-rule coding of {a['detractor_total']} retrieved detractor (1&ndash;3&#9733;) reviews. A review can match several themes; "
                   "capped retrieval over-samples detractors of the not-comparable products, so counts show what complaints say, not how common they are among buyers; "
                   "rules are in pipeline/analyze.py and every match stores its review ID.</p>"
                   "<table><tr><th>Theme</th><th>Detractor reviews</th><th>% of detractors</th><th>Competitors</th><th>Proposed response (untested)</th></tr>"
                   f"{rows or '<tr><td colspan=5>No theme matched any detractor review.</td></tr>'}</table>"))
    ex = []
    for t in top[:2]:
        for rid in t["example_review_ids"][:1]:
            r = reviews_by_id[rid]
            ex.append(f"<li><i>&ldquo;{escape(trim(r['review_text']))}&rdquo;</i> &mdash; {r['rating']}&#9733;, {escape(r['competitor'])}, id {rid} ({escape(t['theme'])})</li>")
    if ex:
        blocks.append(("Representative complaint excerpts", "<ul>" + "".join(ex) + "</ul>"))
    blocks.append(("4. Positioning, target customer &amp; validation (proposals, not evidence)",
                   "<p><b>Target customer (assumption):</b> home cooks who already buy premium finishing salt and gift food items. "
                   "<b>Positioning (proposal):</b> globally inspired, botanically infused finishing salts with documented provenance in resealable rigid packaging, "
                   "addressing the measured complaint themes above. Prices and features are not yet tested.</p>"
                   "<ol><li><b>Smoke test:</b> landing page with 3 SKUs and a gift set; measure email sign-up rate from ~$200 of targeted ads.</li>"
                   "<li><b>Packaging test:</b> mail 20 home cooks a pouch vs. a resealable tin; survey clumping/spillage after 4 weeks.</li>"
                   "<li><b>Blind taste panel:</b> 15&ndash;20 participants compare an infused prototype vs. a leading competitor; ask a true NPS question.</li></ol>"
                   "<p><b>Key uncertainties:</b> retrieval caps, one SKU per brand, review volume &ne; sales, keyword coding misses sarcasm/negation, "
                   "and no evidence yet that customers will pay a premium for infusion or provenance.</p>"))
    return blocks


def trim(s, n=260):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: s.rfind(" ", 0, n)] + " …"


def build_html(a, reviews):
    by_id = {r["review_id"]: r for r in reviews}
    rows = "".join(
        f"<tr><td>{c['rank'] or '–'}</td><td>{escape(c['competitor'])}</td><td>{escape(c['product_name'])}<br><span class=muted>ASIN "
        f"<a href='{c['listing_url']}'>{c['asin']}</a></span>{cap_note(c)}</td><td class=n>{c['n']}</td><td class=n>{pct(c['promoter_pct'])}</td>"
        f"<td class=n>{pct(c['passive_pct'])}</td><td class=n>{pct(c['detractor_pct'])}</td><td class=n data-nps='{escape(c['competitor'])}'><b>{sgn(c['nps'])}</b></td>"
        f"<td class=n>{'N/A' if c['ci95_low'] is None else f'{c[chr(99)+'i95_low']:+.0f} to {c['ci95_high']:+.0f}'}</td></tr>"
        for c in a["competitors"])
    sens = "".join(
        f"<tr><td>{escape(c['competitor'])}</td><td class=n>{sgn(c['nps'])}</td><td class=n>{sgn(c['alt_nps'])}</td>"
        f"<td class=n>{'N/A' if c['delta_exact'] is None else f'+{c[chr(100)+'elta_exact']:.1f}'}</td><td class=n>{pct(c['four_star_pct'])}</td>"
        f"<td class=n>{c['rank'] or '–'} &rarr; {c['alt_rank'] or '–'}</td></tr>" for c in a["competitors"])
    ex_html = ""
    for label, key in (("5&#9733; Promoter", "promoter_5"), ("4&#9733; Passive", "passive_4"), ("1&ndash;3&#9733; Detractor", "detractor_1_3")):
        rid = a["excerpts"][key]
        if rid:
            r = by_id[rid]
            ex_html += (f"<div class=quote><b>{label}</b> &mdash; {escape(r['competitor'])}, {r['rating']}&#9733;, {r['review_date'] or 'date n/a'}, "
                        f"id {rid}, source: {escape(r['collection_source'])} (<a href='{r['source_product_url']}'>product page</a>)"
                        f"<br><i>&ldquo;{escape(trim(r['review_text'], 300))}&rdquo;</i></div>")
        else:
            ex_html += f"<div class=quote><b>{label}</b>: no genuine review available &mdash; none shown.</div>"
    no_data = "" if a["status"] == "ok" else (
        "<div class=alert><b>Data status: " + escape(a["status"]) + ".</b> Amazon US review collection via the Woot endpoint was blocked by the build "
        "environment's network policy (HTTP 403 at the egress proxy for www.woot.com and www.amazon.com). No reviews were fabricated or substituted; "
        "scores show N/A. See data/audits/collection_log.json.</div>")
    startup = "".join(f"<h3>{h}</h3>{b}" for h, b in startup_text(a, by_id))
    lim = "".join(f"<li>{escape(x)}</li>" for x in a["limitations"])
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Silk Road Salts | Loyalty Intelligence</title><style>
@page {{ size: Letter; margin: 0.6in 0.65in 0.7in; }}
body {{ font: 10pt/1.42 Helvetica, Arial, sans-serif; color:#1f2a44; background:#fff; margin:0 }}
h1 {{ font-size:17pt; margin:0 0 2pt }} h2 {{ font-size:13pt; color:#b0703c; border-bottom:1px solid #e4ddd0; padding-bottom:3pt; margin:12pt 0 6pt }}
h3 {{ font-size:10.5pt; margin:9pt 0 3pt }} p {{ margin:3pt 0 }} .muted {{ color:#6b6f76; font-size:8.5pt }}
table {{ border-collapse:collapse; width:100%; font-size:9pt; margin:5pt 0 }} th,td {{ border-bottom:1px solid #e4ddd0; padding:3pt 4pt; text-align:left; vertical-align:top }}
th {{ background:#f6f1e7 }} td.n {{ text-align:right; white-space:nowrap }} a {{ color:#1f2a44 }}
.page {{ break-after:page }} .page:last-child {{ break-after:auto }} svg {{ max-width:100%; height:auto }} .sm svg {{ width:64%; }} .sc svg {{ width:70%; }}
.quote {{ border-left:3px solid #b0703c; padding:3pt 8pt; margin:5pt 0; font-size:9pt; break-inside:avoid }}
.alert {{ background:#fbeee9; border:1px solid #a4483e; padding:6pt 8pt; margin:6pt 0; font-size:9.5pt }}
</style></head><body>
<section class=page><h1>Silk Road Salts | Loyalty Intelligence</h1>
<p class=muted>Review-Derived NPS for five specialty-salt competitors &middot; Amazon US written reviews &middot; analysis generated {a['generated_at'][:10]}</p>
{no_data}
<h2>1. Competitive Loyalty Analysis</h2>
<table><tr><th>Rank</th><th>Competitor</th><th>Product (Amazon US)</th><th>n</th><th>Promoter</th><th>Passive</th><th>Detractor</th><th>NPS</th><th>95% CI</th></tr>{rows}</table>
<p class=muted>{escape(a['comparability_note'])} Total analyzed reviews: {a['total_reviews']}. Source: Amazon US written reviews retrieved through Woot's public review endpoint (woot.com/review/Reviews/&lt;ASIN&gt;), using the open-source mrlong0129/amazon-review-scraper. Records are "source-retrieved", not independently matched to amazon.com permalinks.</p>
<h3>Bucket boundaries</h3><p><b>Promoter = 5&#9733;; Passive = 4&#9733;; Detractor = 1&ndash;3&#9733;.</b> NPS = %Promoters &minus; %Detractors, computed at full precision and rounded to a whole number. Five stars is the clearest written expression of enthusiasm; four-star reviews frequently carry reservations, mirroring the survey's 7&ndash;8 "passive" band; 1&ndash;3 stars signal dissatisfaction or materially qualified experience. These thresholds are judgment calls, so a sensitivity test follows. This is a <b>Review-Derived NPS</b>, not an official survey NPS.</p>
<div class=sm>{charts.bar(a)}</div>
</section>
<section class=page><h2>2. Methodology, Sensitivity &amp; Evidence</h2>
<h3>Alternative specification: 4&ndash;5&#9733; = Promoter, 1&ndash;3&#9733; = Detractor, no Passives</h3>
<table><tr><th>Competitor</th><th>Baseline NPS</th><th>Alternative NPS</th><th>Change (pts, exact)</th><th>4&#9733; share</th><th>Rank: base &rarr; alt</th></tr>{sens}</table>
<p class=muted>Ranks are given only for comparable samples ("&ndash;" = not ranked, see section 1). The exact change always equals the 4&#9733; share; displayed rounded values can differ by &plusmn;1 point due to rounding.</p>
<h3>Three classified excerpts (verbatim, from stored records)</h3>{ex_html}
<h3>Selection bias</h3><p><b>{BIAS}</b></p><ul>{lim}</ul></section>
<section class=page><h2>3. Where Should Silk Road Salts Compete?</h2>
<div class=sc>{charts.scatter(a)}</div>
<p class=muted>X-axis: {escape(a['volume_metric'])}.</p>
{startup}</section>
</body></html>"""


def main(processed=ROOT / "data/processed", csv_path=ROOT / "data/exports/reviews.csv", site=SITE):
    a = json.loads((processed / "analysis.json").read_text())
    reviews = json.loads((processed / "reviews.json").read_text())
    (site / "charts").mkdir(parents=True, exist_ok=True)
    shutil.copy(processed / "analysis.json", site / "analysis.json")
    shutil.copy(processed / "reviews.json", site / "reviews.json")
    shutil.copy(csv_path, site / "reviews.csv")
    (site / "charts/nps_baseline.svg").write_text(charts.bar(a))
    (site / "charts/nps_alternative.svg").write_text(charts.bar(a, "alt_nps", "Review-Derived NPS (alternative: 4-5 stars = promoter)"))
    (site / "charts/scatter.svg").write_text(charts.scatter(a))
    html = build_html(a, reviews)
    (site / "report.html").write_text(html)
    (site / "startup.html").write_text("".join(f"<h3>{h}</h3>{b}" for h, b in startup_text(a, {r['review_id']: r for r in reviews})))
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM)
        pg = b.new_page()
        pg.set_content(html, wait_until="load")
        pg.pdf(path=str(site / "report.pdf"), format="Letter", print_background=True, display_header_footer=True,
               header_template="<span></span>",
               footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#6b6f76'>Silk Road Salts | Loyalty Intelligence &middot; page <span class=pageNumber></span> of <span class=totalPages></span></div>",
               margin={"top": "0.6in", "bottom": "0.7in", "left": "0.65in", "right": "0.65in"})
        b.close()
    print(f"wrote {site / 'report.pdf'}")


if __name__ == "__main__":
    main()
