# Silk Road Salts | Loyalty Intelligence

BYU STRAT 560 — review-derived Net Promoter Score for five specialty-salt competitors on Amazon US,
and a "Where Should Silk Road Salts Compete?" startup analysis.

## Current data status (live collection 2026-10-11)

1,264 distinct Amazon US written reviews retrieved through the Woot review endpoint (`make collect`), all traceable to
`data/raw/{ASIN}/combo_s*_o*.json`. The endpoint caps each star-filter x sort query at 100 reviews (~110-125 distinct
per star after four sort orders):

| Competitor | n | Capped star buckets | Treatment |
|---|---|---|---|
| The Spice Lab | 41 | none | ranked; below 50-review target |
| Jacobsen Salt Co. | 175 | 5★ | ranked; NPS is a lower bound |
| SaltWorks | 40 | none | ranked; below 50-review target |
| Maldon Salt | 511 | 5/4/3/1★ | **not ranked**: star mix set by the cap, NPS not comparable |
| Redmond Real Salt | 497 | 5/4/1★ | **not ranked**: star mix set by the cap, NPS not comparable |

Not-comparable samples keep their sample NPS in tables (for transparency) but are excluded from ranks, charts and the
wedge test (`sample_validity` in `pipeline/analyze.py`). No alternative ASIN was found for SaltWorks or The Spice Lab
(see `low_n_investigation` in `pipeline/products.py`). amazon.com remains blocked, so the true star distributions
cannot be used to reweight.

```bash
make collect   # live retrieval (needs network access to www.woot.com)
make all       # normalize -> analyze -> charts/PDF -> tests
```

### Fixing the capped scores: Amazon star histograms (hand-recorded)

Amazon's bot check blocks automated listing fetches, so each listing's star histogram is typed in by hand into
`data/raw/histograms/star_histograms.csv` (one pre-filled row per ASIN):

1. Open the row's `listing_url` in a browser, scroll to **Customer reviews**.
2. Enter the five bar percentages as whole numbers in `pct_5` … `pct_1` (type what Amazon shows; do not adjust them to sum to 100),
   the ratings count (e.g. `12,345 global ratings` → `12345`) in `total_ratings`, the average (e.g. `4.7`) in `average_rating`,
   today's date (`YYYY-MM-DD`) in `recorded_on`, and your name/initials in `recorded_by`. Optional: `notes` (e.g. which size/variant was selected).
3. `make all`.

Rows left blank are ignored; a partly filled row, a non-number, or percentages not summing to 97–103 are reported and not used.
**Only when all five rows are valid** does the headline switch to histogram NPS for every product (one basis for all;
ranks, charts, wedge and PDF follow, with total ratings as the volume axis). Until then everything stays on the written-review
sample. Histogram NPS carries up to ±2 points of rounding error and covers all ratings (including star-only), which the report states.

Alternative: put manually transcribed public reviews in `data/raw/manual/*.csv`
(columns in `data/raw/manual/TEMPLATE.csv.example`; records are labeled `manually_recorded`), then `make all`.

## Pipeline (single source of truth)

| Step | File | Output |
|---|---|---|
| Product/ASIN assignments + evidence | `pipeline/products.py` | — |
| Raw retrieval (upstream scraper's `fetch_reviews`, every star×sort response saved before dedup) | `pipeline/collect.py` | `data/raw/{ASIN}/combo_s*_o*.json`, `data/audits/collection_log.json` |
| Normalize, validate (rating 1–5, ASIN), dedup, audit | `pipeline/normalize.py` | `data/processed/reviews.json`, `data/exports/reviews.csv`, `data/audits/audit.json` |
| NPS engine (pure functions) | `pipeline/nps.py` | — |
| Scores, ranks, sensitivity, themes, excerpts, wedge | `pipeline/analyze.py` | `data/processed/analysis.json` |
| Charts (SVG), startup text, PDF (Chromium print) | `pipeline/report.py`, `pipeline/charts.py` | `site/` |
| Static web app (reads `site/analysis.json`) | `site/index.html`, `site/app.js` | — |

Scoring: 5★ Promoter, 4★ Passive, 1–3★ Detractor; NPS = %P − %D at full precision, rounded half away
from zero. Alternative: 4–5★ Promoter. Zero reviews → N/A. Ranks use displayed NPS; ties share a rank.

## Competitor products (ASINs search-corroborated; reviews retrieved and spot-checked against each product)

| Competitor | ASIN | Product |
|---|---|---|
| Maldon Salt | B00017028M | Sea Salt Flakes 8.5 oz |
| Jacobsen Salt Co. | B01M32JS5F | Pure Flake Sea Salt 4 oz |
| SaltWorks | B077NRHK1F | Pacific Blue Kosher Flake 8 oz pouch |
| The Spice Lab | B0030MZMIK | Cyprus White Flake Kosher Salt 8 oz |
| Redmond Real Salt | B071FNYFWW | Ancient Fine Sea Salt 16 oz (fine grain — not flake) |

## Tests

`make test` — engine math (all assignment cases), validation/dedup/audit reconciliation, data-change
propagation, production records trace to raw files, analysis = engine recompute, and Playwright checks that
dashboard table, sensitivity table, chart labels, strategic text and PDF text all show identical NPS values,
plus sort, toggle, filters, excerpts and PDF download with no JS errors. UI consistency is also exercised on a
synthetic fixture built in a temp directory (never written to `data/` or `site/`).

## Deploy (static; `site/` is the whole app)

- **GitHub Pages:** merge to `main`, then Settings → Pages → Source: *GitHub Actions* (`.github/workflows/pages.yml`).
- **Netlify:** drag `site/` onto app.netlify.com/drop, or connect the repo (`netlify.toml`).
- **Vercel:** import the repo (`vercel.json`, output directory `site`).

Local: `make serve` → http://localhost:8000

## Third-party code

`tools/amazon-review-scraper/` — MIT, commit ee3d80f; see `PROVENANCE.md`. Its instruction to hide data-source
names in reports is intentionally overridden.
