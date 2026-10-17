# Data-selection and calculation rules

## 1. Source data

* **Ticker → CIK:** `https://www.sec.gov/files/company_tickers.json`. A numeric CIK is also accepted.
* **Financial facts:** SEC Company Facts API, `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`.
  These are the XBRL facts as filed. Values are in whole currency units, not thousands.
* **Filing links:** each fact carries its accession number (`accn`), form and filing date. The link is the primary
  document named in the Submissions API (`data.sec.gov/submissions/…`). When that is not listed, the link is the
  filing index `https://www.sec.gov/Archives/edgar/data/<CIK>/<accession without dashes>/<accession>-index.htm`.
* Requests send `SEC_USER_AGENT`, wait at least 0.2 s apart (SEC allows 10 per second), retry 429/5xx responses
  twice with back-off, and are cached on disk for 24 hours.

## 2. Choosing the COGS concept

Candidates: `CostOfGoodsAndServicesSold`, `CostOfRevenue`, `CostOfGoodsSold` (pre-2018 tag),
`CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization`,
`CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization` and IFRS `CostOfSales`.

* Concepts still used in the company's latest filings come first: a concept qualifies if its latest period is
  within 400 days of the latest period of any candidate. Among those, the concept with the most usable periods
  wins, with ties broken in the order above. Without this rule, a deprecated tag with a longer history (for
  example Coca-Cola's `CostOfGoodsSold`, which ends in 2017) would be chosen over the current one. The user can
  switch concepts, and the choice is shown in the app and the report.
* **Verified fill, never a blind splice.** Companies sometimes switch tags; for example, NVIDIA tagged fiscal 2019
  cost of revenue only as `CostOfGoodsAndServicesSold` and every other year as `CostOfRevenue`. A period missing
  under the selected concept is taken from an alternative concept only if that concept reports **identical values
  (within 0.5%) in at least two overlapping periods**. Each filled row keeps its own tag, and a data note lists
  the filled periods. The user can turn this off. Alternative concepts that differ by more than 0.5% are never
  used, and the difference is disclosed for the periods in the window.
* If the selected concept stops well before the company's latest 10-K/10-Q (for example, GM and Deere after
  their last standard-tagged year), the app warns that recent filings probably use a company-specific tag, which
  the Company Facts API does not publish.
* Only facts without XBRL dimensions are used (the Company Facts API publishes consolidated, entity-wide facts),
  so COGS is always company-wide.
* If the concept appears in more than one currency, only the most frequent currency is used and the others are
  disclosed.

## 3. Periods

* A period is identified by its exact XBRL `start` and `end` dates. The filing's `fy`/`fp` labels are not used to
  identify periods, because comparative periods inside a filing carry the filing's own labels.
* **Duplicates and restatements:** when the same start/end pair appears in several filings (comparatives,
  amendments), the most recently filed value is used. Earlier values that differ by more than 0.1% are listed
  as revisions; smaller differences are rounding (for example $9,536,264 thousand vs $9,536 million).
* **Same period, shifted dates:** filings occasionally tag the same fiscal year with start or end dates a day or
  two apart. Periods whose start and end both match within 3 days are treated as one period, and the latest
  filed value is used.
* **Annual:** durations of 350–380 days (52/53-week years included) from 10-K, 10-KT, 20-F or 40-F filings and
  their amendments.
* **Quarterly:** durations of 75–120 days. This includes 16- and 17-week fourth quarters, such as Costco's
  12/12/12/16-week fiscal year, whose 53-week years have a 119-day Q4. Quarters are not normalized to equal
  length; unit cost is COGS ÷ units for the same period, so unequal lengths do not bias it.
  * A reported three-month value is used when one exists.
  * Otherwise the quarter is the difference between two consecutive cumulative values with the same fiscal-year
    start date: Q2 = 6M − 3M, Q3 = 9M − 6M, Q4 = FY − 9M. Both source filings are recorded.
  * Year-to-date values are never treated as quarters. If both a reported and a derived value exist and differ
    by more than 0.5%, the reported value is kept and the difference is disclosed.
  * Where all four quarters of a fiscal year are available, they are checked against the 10-K annual total.
* **Overlaps:** if two periods overlap (for example after a change of fiscal year-end), the more recent one is kept
  and the skipped period is disclosed.
* **Labels:** `FY<year>` uses the calendar year in which the fiscal year ends. A 52/53-week year ending in the
  first seven days of January belongs to the prior year. Quarter labels (`FY2024-Q3`) are positions within the
  containing fiscal year; the current, unfinished fiscal year is assumed to run 52 weeks after the last reported
  one. The dates themselves are authoritative.
* **Data notes** (revisions, reported/derived disagreements, quarter-sum mismatches) appear only for periods
  inside the selected window.
* **Gaps:** a hole of more than 7 days between consecutive periods inside the chosen window blocks the
  calculation, because cumulative units would be understated. Missing periods are never interpolated.

## 4. Unit volumes (in order of preference)

1. **Direct volumes tagged in SEC XBRL.** The app lists duration facts reported in a non-monetary,
   non-share unit (for example `Vehicle`) as candidates. Few companies have them. The user must confirm the series
   measures units produced or sold.
2. **Direct volumes entered or uploaded by the user.** Every value needs a source (document, page, URL, or
   "Assumption: …").
3. **Revenue ÷ average selling price.** Revenue comes from SEC XBRL (`RevenueFromContractWithCustomerExcludingAssessedTax`,
   `Revenues`, `SalesRevenueNet`, …) and is matched to each COGS period by dates. Prices are entered by the user
   for each period, with a source. Results are labeled as estimates. If the same price is used in every period,
   a warning explains that unit cost then reduces to a scaled COGS/revenue ratio.

Consolidated COGS covers every product and service. Unless the user confirms that the volumes cover the same
scope, every output carries a scope-mismatch qualification. If any period in the window lacks units, the
calculation is refused.

## 5. Calculation

For periods t = 1…T in the window:

* `N(t) = Σ units(1..t)`: cumulative units counted from the first period in the window
* `C(t) = COGS(t) / units(t)`: unit cost
* OLS: `ln C = ln A − b · ln N`; `b = −slope`; `R²` from the log-space regression; standard error of `b` reported
* Learning rate `= 1 − 2^(−b)`. A negative value means unit cost rose with volume and is reported as such.

Only positive observations enter the regression. A period with non-positive COGS still adds its units to `N`,
because those units were produced, but it is excluded from the fit and disclosed. At least 5 observations are
required. Fewer than 8 triggers a sensitivity warning.

**Cumulative production is measured from the beginning of the selected data window, not from the company's
founding. True lifetime cumulative production is generally unavailable.** Changing the window start therefore
changes `b`.

## 6. Interpretation rules

* Fit: R² ≥ 0.80 strong; 0.50–0.80 moderate or inconclusive; < 0.50 weak, so no meaningful experience curve is
  shown.
* A positive rate with a strong fit is called a visible experience curve, described as an association rather
  than proof of causation. The commonly cited 10–30% range is used only as a general reference. Industry-relative
  strength is never asserted, because no verified benchmark is built in.
* Limitations are always stated: nominal costs, cumulative units counted from the window start, plus estimated
  units or scope mismatch where they apply.

## 7. Reproducibility

The app, chart, CSV and PDF are all generated from one `Analysis` object, using shared formatting functions.
The PDF is built from that object without re-fetching. A short fingerprint of the inputs (periods, values,
accessions, unit sources, method) is printed in the app and the PDF. Identical inputs give an identical
fingerprint and identical results.
