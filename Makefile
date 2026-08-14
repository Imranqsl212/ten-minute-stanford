PYTHON ?= .venv/bin/python

.PHONY: install test collect collect-year analyze visuals social audit audit-ci all year-analysis site submission preview

TERMS ?= Winter

install:
	python3.12 -m venv .venv
	.venv/bin/python -m pip install -e '.[dev]'

test:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m pytest

collect:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford collect --terms $(TERMS)

collect-year:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford collect --terms Autumn Winter Spring

analyze:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford analyze

visuals:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford visuals

social:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) scripts/generate_social_preview.py

audit:
	$(PYTHON) scripts/audit_publication.py --require-raw --write

audit-ci:
	$(PYTHON) scripts/audit_publication.py

all:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford all --terms $(TERMS)

year-analysis:
	MPLCONFIGDIR=.cache/matplotlib $(PYTHON) -m ten_minute_stanford all --terms Autumn Winter Spring

site:
	$(PYTHON) scripts/build_site.py --output _site

submission:
	$(PYTHON) scripts/build_submission_docx.py

preview: site
	python3 -m http.server 8000 --directory _site
