"""Dashboard/PDF consistency and functional UI tests (Playwright + Chromium).

`synthetic_site` builds a throwaway site in a temp dir from a SYNTHETIC fixture so the
agreement checks run on non-empty numbers. Nothing synthetic is written to data/ or site/.
`real_site` tests the actual deployable site/ directory.
"""
import functools
import http.server
import json
import re
import shutil
import sys
import threading
from pathlib import Path

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import analyze, normalize, report  # noqa: E402
from pipeline.products import PRODUCTS  # noqa: E402

pw = pytest.importorskip("playwright.sync_api")


def serve(directory):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    h.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def build_synthetic(tmp, hists=None):
    raw = tmp / "raw"
    mix = [(30, 10, 10), (20, 15, 15), (12, 3, 25), (45, 4, 1), (8, 8, 4)]  # TEST FIXTURE ONLY
    for p, (a, b, c) in zip(PRODUCTS, mix):
        d = raw / p["asin"]; d.mkdir(parents=True)
        recs = [{"Author": f"{p['asin']}-{i}", "Title": "t", "Text": f"TEST FIXTURE review {i} the bag arrived torn" if s <= 3 else f"TEST FIXTURE review {i} great flavor",
                 "OverallRating": s, "OriginDescription": "Reviewed in the United States on May 1, 2025", "IsVerifiedPurchase": True}
                for i, s in enumerate([5] * a + [4] * b + [2] * c)]
        (d / "combo_s0_o0.json").write_text(json.dumps({"star_filter": 0, "fetched_at": "x", "reviews": recs}))
    orig = normalize.ROOT
    normalize.ROOT = tmp
    try:
        acc, _ = normalize.build(raw)
    finally:
        normalize.ROOT = orig
    proc = tmp / "processed"; proc.mkdir()
    a = analyze.build(acc, hists=hists)
    (proc / "analysis.json").write_text(json.dumps(a)); (proc / "reviews.json").write_text(json.dumps(acc))
    (tmp / "r.csv").write_text("x\n")
    site = tmp / "site"; site.mkdir()
    for f in ("index.html", "app.js", "style.css"):
        shutil.copy(ROOT / "site" / f, site / f)
    report.main(proc, tmp / "r.csv", site)
    return site, a


@pytest.fixture(scope="module")
def synthetic_site(tmp_path_factory):
    return build_synthetic(tmp_path_factory.mktemp("synthetic"))


@pytest.fixture(scope="module")
def synthetic_hist_site(tmp_path_factory):
    # TEST FIXTURE ONLY: invented histograms to exercise the histogram-headline path
    shapes = [(80, 10, 4, 2, 4), (70, 12, 6, 4, 8), (60, 15, 10, 5, 10), (85, 8, 3, 1, 3), (50, 20, 10, 8, 12)]
    hists = {p["asin"]: {"pct": dict(zip((5, 4, 3, 2, 1), sh)), "pct_sum": sum(sh), "total_ratings": 100 * (i + 1) ** 3,
                         "average_rating": None, "recorded_on": "2025-01-01", "recorded_by": "TEST FIXTURE", "notes": "", "raw_ref": "fixture"}
             for i, (p, sh) in enumerate(zip(PRODUCTS, shapes))}
    return build_synthetic(tmp_path_factory.mktemp("synthetic_hist"), hists)


@pytest.fixture(scope="module")
def browser(synthetic_site, synthetic_hist_site):  # build PDF first: two sync_playwright loops cannot nest
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=report.CHROMIUM)
        yield b
        b.close()


def open_page(browser, site):
    srv = serve(site)
    page = browser.new_page(accept_downloads=True)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html")
    page.wait_for_selector("#comp-table tbody tr")
    return page, errors, srv


def fmt(v):
    return "N/A" if v is None else f"{v:+d}"


def check_consistency(page, site, a):
    # dashboard table
    for c in a["competitors"]:
        row = page.locator(f"#comp-table tbody tr[data-c='{c['competitor']}']")
        assert row.locator("td[data-nps]").inner_text().strip() == fmt(c["nps"]).replace("+0", "0")
    # sensitivity table
    sens = page.locator("#sens-table tbody tr")
    assert sens.count() == len(a["competitors"])
    for i, c in enumerate(a["competitors"]):
        cells = sens.nth(i).locator("td")
        h = c["headline"]
        assert cells.nth(1).inner_text() == fmt(h["nps"]).replace("+0", "0") and cells.nth(2).inner_text() == fmt(h["alt_nps"]).replace("+0", "0")
        if a["primary_metric"] == "histogram":
            row = page.locator(f"#comp-table tbody tr[data-c='{c['competitor']}']")
            assert row.locator("td[data-hist] b").inner_text() == fmt(c["histogram"]["nps"]).replace("+0", "0")
    # chart labels
    svg = (site / "charts/nps_baseline.svg").read_text()
    for c in a["competitors"]:
        if c["headline"]["comparable"]:
            assert f">{c['headline']['nps']:+d}</text>" in svg
        elif c["nps"] is not None:  # capped sample: named in the footnote, no bar
            assert f">{c['competitor']}</text>" not in svg and c["competitor"] in svg
    # PDF
    text = "".join(pg.extract_text() for pg in PdfReader(site / "report.pdf").pages)
    for c in a["competitors"]:
        assert re.search(rf"{re.escape(c['competitor'].split()[0])}.*?{re.escape(fmt(c['nps']) if c['nps'] is not None else 'N/A')}", text, re.S)
    # strategic text uses the same numbers
    startup = (site / "startup.html").read_text()
    for c in a["competitors"]:
        if c["competitor"] in a["wedge"].get("candidates", []):
            assert f"NPS {fmt(c['headline']['nps'])}" in startup
    if a["primary_metric"] == "histogram":
        for c in a["competitors"]:
            assert re.search(rf"{re.escape(c['competitor'].split()[0])}.*?{re.escape(fmt(c['histogram']['nps']))}", text, re.S)


def test_synthetic_consistency_and_ui(browser, synthetic_site):
    site, a = synthetic_site
    page, errors, srv = open_page(browser, site)
    check_consistency(page, site, a)
    # sort
    page.click("#comp-table th[data-k='n']")
    first_n = page.locator("#comp-table tbody tr").first.locator("td").nth(2).inner_text()
    assert int(first_n) == max(c["n"] for c in a["competitors"])
    # calculation detail
    page.locator("#comp-table tbody tr").first.locator("td").first.click()
    assert "Baseline NPS =" in page.inner_text("#calc")
    # toggle
    page.click("#m-alt")
    assert "nps_alternative" in page.get_attribute("#chart-sens", "src")
    # filters
    total = len(json.loads((site / "reviews.json").read_text()))
    page.select_option("#f-star", "4")
    n4 = sum(c["star_counts"]["4"] if "4" in c["star_counts"] else c["star_counts"][4] for c in a["competitors"])
    assert page.inner_text("#r-count").startswith(f"{n4} of {total}")
    page.select_option("#f-star", "")
    page.select_option("#f-bucket", "detractor")
    assert page.inner_text("#r-count").startswith(f"{sum(c['detractors'] for c in a['competitors'])} of")
    # excerpts: exactly 3, each a stored record
    assert page.locator("#excerpts .quote").count() == 3
    # PDF download
    with page.expect_download() as d:
        page.click("#pdf-link")
    assert d.value.path().read_bytes()[:4] == b"%PDF"
    assert not errors, errors
    srv.shutdown()


def test_synthetic_histogram_headline(browser, synthetic_hist_site):
    site, a = synthetic_hist_site
    assert a["primary_metric"] == "histogram" and all(c["rank"] for c in a["competitors"])
    page, errors, srv = open_page(browser, site)
    check_consistency(page, site, a)
    assert page.locator("#comp-table th", has_text="Amazon histogram NPS").count() == 1
    assert "Amazon histogram" in page.inner_text("#kpis")
    assert 3 <= len(PdfReader(site / "report.pdf").pages) <= 4
    assert not errors, errors
    srv.shutdown()


def test_real_site(browser):
    site = ROOT / "site"
    a = json.loads((site / "analysis.json").read_text())
    assert a == json.loads((ROOT / "data/processed/analysis.json").read_text())
    page, errors, srv = open_page(browser, site)
    check_consistency(page, site, a)
    for sec in ("overview", "competitors", "method", "explorer", "opportunity", "export"):
        assert page.locator(f"#{sec}").is_visible()
    assert page.locator("#chart-main").evaluate("i => i.complete && i.naturalWidth > 0")
    page.click("#m-alt"); page.click("#m-base")
    for href in page.locator("#comp-table a").evaluate_all("as => as.map(a => a.href)"):
        assert href.startswith("https://www.amazon.com/dp/")
    with page.expect_download() as d:
        page.click("#pdf-link")
    assert d.value.path().read_bytes()[:4] == b"%PDF"
    assert 3 <= len(PdfReader(site / "report.pdf").pages) <= 4
    assert not errors, errors
    srv.shutdown()
