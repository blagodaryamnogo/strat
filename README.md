# Silk Road Salts | Loyalty Intelligence

BYU STRAT 560 — review-derived Net Promoter Score for five specialty-salt competitors on Amazon US,
and a "Where Should Silk Road Salts Compete?" startup analysis.

## Current data status: NO REVIEWS COLLECTED (blocked)

The build environment's network policy denies `www.woot.com` and `www.amazon.com` (HTTP 403 at the egress
proxy; logged in `data/audits/collection_log.json`). No reviews were fabricated or substituted, so every
score shows **N/A** and no startup conclusion is drawn. Everything downstream is built and tested and will
populate automatically once genuine reviews exist:

```bash
make collect   # needs network access to www.woot.com
make all       # normalize -> analyze -> charts/PDF -> tests
```

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

## Competitor products (ASINs are search-corroborated candidates; live listing not reachable from the build)

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
