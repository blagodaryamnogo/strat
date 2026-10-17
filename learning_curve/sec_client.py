"""Minimal client for the SEC EDGAR APIs (ticker lookup, company facts, submissions).

SEC fair-access rules: identify yourself with a User-Agent that contains contact
information, and stay under 10 requests per second. Responses are cached on disk
so repeated analyses do not re-download the same JSON.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data"


class SECError(Exception):
    """A retrieval problem the user should see in plain language."""


def filing_index_url(cik: int, accession: str) -> str:
    """Deterministic URL of a filing's index page on EDGAR."""
    return f"{ARCHIVE_ROOT}/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"


def filing_document_url(cik: int, accession: str, primary_document: str | None) -> str:
    if not primary_document:
        return filing_index_url(cik, accession)
    return f"{ARCHIVE_ROOT}/{int(cik)}/{accession.replace('-', '')}/{primary_document}"


class SECClient:
    def __init__(self, user_agent: str, cache_dir: str | None = None,
                 ttl_seconds: int = 24 * 3600, min_interval: float = 0.2, timeout: float = 30):
        user_agent = (user_agent or "").strip()
        if "@" not in user_agent:
            raise SECError(
                "An SEC User-Agent with a contact email is required (for example "
                "'Jane Doe jane@example.edu'). Set SEC_USER_AGENT as described in the README.")
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir or os.environ.get("LC_CACHE_DIR")
                              or Path(tempfile.gettempdir()) / "lc_sec_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_seconds
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_request = 0.0

    # ---- HTTP -----------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def get_json(self, url: str) -> dict:
        path = self._cache_path(url)
        if path.exists() and time.time() - path.stat().st_mtime < self.ttl:
            with path.open() as f:
                return json.load(f)
        data = self._fetch(url)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as f:
            json.dump(data, f)
        tmp.replace(path)
        return data

    def _fetch(self, url: str) -> dict:
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        last_error = ""
        for attempt in range(3):
            wait = self.min_interval - (time.time() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.time()
            try:
                r = requests.get(url, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                last_error = f"network error: {e}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    raise SECError(f"SEC returned a non-JSON response for {url}.")
            if r.status_code == 404:
                raise SECError(f"SEC has no data at {url} (HTTP 404).")
            if r.status_code == 403:
                raise SECError(
                    "SEC refused the request (HTTP 403). The SEC requires a User-Agent with "
                    "contact information and may temporarily block high-volume or shared IP "
                    "addresses. Check SEC_USER_AGENT and try again later.")
            last_error = f"HTTP {r.status_code}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            break
        raise SECError(f"Could not retrieve {url} from SEC EDGAR ({last_error}).")

    # ---- Endpoints ------------------------------------------------------
    def lookup(self, ticker_or_cik: str) -> dict:
        """Return {'cik', 'ticker', 'title'} for a ticker symbol or numeric CIK."""
        q = (ticker_or_cik or "").strip().upper()
        if not q:
            raise SECError("Enter a ticker symbol.")
        table = self.get_json(TICKERS_URL)
        rows = table.values() if isinstance(table, dict) else table
        if q.isdigit():
            for row in rows:
                if int(row["cik_str"]) == int(q):
                    return {"cik": int(row["cik_str"]), "ticker": row["ticker"], "title": row["title"]}
            return {"cik": int(q), "ticker": q, "title": ""}
        q = q.replace(".", "-")  # SEC lists class shares as e.g. BRK-B
        for row in rows:
            if row["ticker"].upper() == q:
                return {"cik": int(row["cik_str"]), "ticker": row["ticker"], "title": row["title"]}
        raise SECError(f"Ticker '{ticker_or_cik}' was not found in the SEC ticker list.")

    def company_facts(self, cik: int) -> dict:
        return self.get_json(FACTS_URL.format(cik=int(cik)))

    def submissions(self, cik: int) -> dict:
        return self.get_json(SUBMISSIONS_URL.format(cik=int(cik)))


def primary_documents(submissions: dict) -> dict[str, str]:
    """Map accession number -> primary document file name (recent filings only)."""
    recent = (submissions or {}).get("filings", {}).get("recent", {})
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    return {a: d for a, d in zip(accns, docs) if d}
