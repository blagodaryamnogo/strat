# Learning-Curve Calculator

Measure whether a company's costs decline with cumulative production.

A single-page Streamlit app. It pulls a public company's cost of goods sold (COGS) from SEC EDGAR, combines it with
unit volumes that have a documented source, and fits the experience curve `Unit cost = A × N^(−b)`. The app then
reports the learning rate (`1 − 2^(−b)`), `b` and R², draws a log-log chart, writes a short interpretation and
exports a PDF report. Every number traces back to an SEC filing or to an input whose source the user has documented.

```
learning_curve/
  app.py          Streamlit page (inputs, results, downloads)
  sec_client.py   SEC EDGAR HTTP client: User-Agent, disk cache, rate limit, errors
  financials.py   XBRL fact selection, annual / quarterly reconstruction, provenance
  analysis.py     dataset checks, regression, interpretation, shared number formatting
  charts.py       log-log chart (used by the app and the PDF)
  report.py       PDF (ReportLab) and CSV exports
  tests/          automated tests (synthetic fixtures + optional live SEC test)
  METHODOLOGY.md  data-selection and calculation rules
```

## Run locally

```bash
cd strat                                   # repository root
python -m venv .venv && source .venv/bin/activate
pip install -r learning_curve/requirements.txt
export SEC_USER_AGENT="Your Name your.email@byu.edu"     # required by SEC fair-access rules
export PUBLIC_APP_URL="https://your-app.streamlit.app"   # optional; printed in the PDF
streamlit run learning_curve/app.py
```

You can also copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (it is git-ignored) instead of
exporting variables. If `SEC_USER_AGENT` is not set, the page asks the visitor for a name and email.

## Tests

```bash
pip install -r learning_curve/requirements-dev.txt
python -m pytest learning_curve/tests -v
# Live SEC retrieval test (needs internet access to sec.gov):
SEC_USER_AGENT="Your Name you@byu.edu" python -m pytest learning_curve/tests/test_lc_live.py -v
```

| Test file | What it checks |
|---|---|
| `test_lc_math.py` | A known 20% curve returns b = 0.32193, learning rate = 20%, R² = 1. Negative rates stay negative. Invalid regression inputs are rejected. |
| `test_lc_sec_periods.py` | 10-Q year-to-date values vs 10-K totals: Q3 = 9M − 6M, Q4 = FY − 9M, no double counting, quarters sum to the annual total. Also covers duplicate comparatives, restatements, gaps, conflicting values and the concept-selection rule. |
| `test_lc_analysis.py` | Missing, zero or unsourced units, too few observations, period gaps and negative COGS give clear errors or disclosed exclusions. Also tests the revenue ÷ price method, the constant-price warning, scope-mismatch flags and the interpretation wording. |
| `test_lc_report.py` | PDF sections, text, clickable URL and filing links, the embedded chart and the file name. Chart, CSV and PDF values must match the analysis. |
| `test_lc_app.py` | Drives the real Streamlit page offline (synthetic SEC responses served from the disk cache). The displayed metrics must equal the analysis values, and the page must refuse to report a learning rate without units. |
| `test_lc_live.py` | Apple's annual COGS traces to the raw SEC facts, FY2023 equals $214,137M, and the four FY2023 quarters sum to the annual total. Also checks a Tesla quarterly series. Skipped when sec.gov is unreachable. |

The synthetic fixture (`tests/synthetic.py`) is labeled "SYNTHETIC TEST CO (not a real company)" and exists only
in tests.

## Deploy publicly on Streamlit Community Cloud

1. Push this repository to GitHub (already done if you are reading this on GitHub).
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click **Create app** → **Deploy a public app from GitHub**.
3. Repository: `blagodaryamnogo/strat`. Branch: the branch with this code. Main file path: `learning_curve/app.py`.
   Community Cloud installs `learning_curve/requirements.txt` because it sits next to the entry file.
4. Optionally choose a custom subdomain (for example `byu-learning-curve`). The app URL is then
   `https://byu-learning-curve.streamlit.app`.
5. Under **Advanced settings → Secrets**, paste:
   ```toml
   SEC_USER_AGENT = "Your Name your.email@byu.edu"
   PUBLIC_APP_URL = "https://byu-learning-curve.streamlit.app"
   ```
   Use the exact URL Streamlit shows for your app. If you only learn it after deploying, add or edit the secret
   then (App settings → Secrets). The app reloads automatically.
6. Click **Deploy**. Public Community Cloud apps can be opened by anyone with the link, with no login.
7. Check it: open the URL in a private browser window, run a ticker, and confirm the PDF shows your URL.

If SEC returns HTTP 403 from the cloud host, confirm that `SEC_USER_AGENT` contains a real email address. SEC can
also block shared IP addresses for a while after heavy traffic, so wait a few minutes and retry.

## Using the app

1. Enter a ticker, choose Annual or Quarterly, then click **Retrieve SEC data**.
2. Check the auto-selected COGS concept and the analysis period. The default is the latest 10 fiscal years or
   20 quarters.
3. Provide unit volumes. SEC XBRL data rarely contain them. Most companies disclose units only in filing text
   (MD&A), earnings releases or investor decks. You can:
   - use a unit series the company tags in XBRL, if one is detected (you must confirm what it measures);
   - type or upload actual units for each period, with a source for every value; or
   - supply an average selling price for each period, with sources, so units = SEC revenue ÷ price. These are
     labeled as estimates.
4. Tick the scope box only if the volumes cover everything in consolidated COGS. Otherwise the result is flagged
   as not company-wide.
5. Click **Calculate Experience Curve**, review the results, then click **Export Report to PDF**
   (`Learning_Curve_[TICKER]_[DATE].pdf`). A CSV of the calculations is also available.

CSV upload format (one row per period; `period_end` must match an SEC period end within ±10 days):

```csv
period_end,units,source
<period end date>,<units for that period>,"<document, page and URL>"
```

Use `asp` instead of `units` for the revenue ÷ price method.
