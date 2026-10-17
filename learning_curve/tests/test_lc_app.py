"""Test 6 (app side): drive the Streamlit page end-to-end on the SYNTHETIC company.

SEC responses are served from the client's on-disk cache, pre-filled with synthetic JSON,
so the test runs offline and never presents synthetic numbers as a real company.
"""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import synthetic as syn
from analysis import equation_text, fmt_b, fmt_pct, fmt_r2
from helpers import synthetic_analysis
from sec_client import FACTS_URL, SUBMISSIONS_URL, TICKERS_URL, SECClient

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def offline_sec(tmp_path, monkeypatch):
    client = SECClient("Test Runner test@example.edu", cache_dir=str(tmp_path))
    for url, body in ((TICKERS_URL, syn.tickers_json()),
                      (FACTS_URL.format(cik=syn.CIK), syn.make_facts(n_years=8)),
                      (SUBMISSIONS_URL.format(cik=syn.CIK), syn.submissions_json())):
        client._cache_path(url).write_text(json.dumps(body))
    monkeypatch.setenv("LC_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("SEC_USER_AGENT", "Test Runner test@example.edu")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://example-learning-curve.streamlit.app")
    return tmp_path


@pytest.mark.parametrize("freq", ["annual", "quarterly"])
def test_app_end_to_end_matches_analysis(offline_sec, freq):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].input(syn.TICKER)
    at.radio[0].set_value(freq.capitalize())
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert any(syn.NAME in s.value for s in at.subheader)

    # Method radio defaults to the SEC-tagged unit series; fill definition, confirm scope + series
    at.text_input[1].input("vehicles delivered")
    for cb in at.checkbox:
        cb.check()
    at.run()
    calc = next(b for b in at.button if b.label == "Calculate Experience Curve")
    calc.click().run()
    assert not at.exception, at.exception
    assert not at.error, [e.value for e in at.error]

    metrics = {m.label: m.value for m in at.metric}
    window = (lambda obs: obs[-10:]) if freq == "annual" else (lambda obs: obs[-20:])
    an = synthetic_analysis(freq, n_years=8, window=window)
    assert metrics["Learning rate"] == fmt_pct(an.regression.learning_rate)
    assert metrics["Coefficient b"] == fmt_b(an.regression.b)
    assert metrics["R²"] == fmt_r2(an.regression.r2)
    assert int(metrics["Observations"]) == an.regression.n
    assert any(equation_text(an.regression) in m.value for m in at.markdown)
    labels = [b.label for b in at.get("download_button")]
    assert "Export Report to PDF" in labels and "Download calculations (CSV)" in labels


def test_app_refuses_without_units(offline_sec):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].input(syn.TICKER)
    at.button[0].click().run()
    at.radio[1].set_value(at.radio[1].options[1]).run()   # "Enter or upload actual unit volumes"
    at.text_input[1].input("vehicles delivered")
    next(b for b in at.button if b.label == "Calculate Experience Curve").click().run()
    assert not at.exception
    assert at.error and "cannot be reported" in at.error[0].value
    assert not at.metric

