PY ?= python3
.PHONY: collect analyze site test all serve
collect:   ## live retrieval (needs network access to www.woot.com)
	$(PY) pipeline/collect.py
analyze:   ## raw -> normalized -> analysis.json
	$(PY) pipeline/normalize.py && $(PY) pipeline/analyze.py
site:      ## charts, startup text, report.html, report.pdf into site/
	$(PY) pipeline/report.py
test:
	$(PY) -m pytest -q tests
all: analyze site test
serve:
	$(PY) -m http.server -d site 8000
