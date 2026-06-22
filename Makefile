.PHONY: install test lint format smoke quality

SMOKE_DIR ?= outputs/smoke
PYTHON ?= python

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m mypy src

format:
	$(PYTHON) -m black .
	$(PYTHON) -m ruff check --fix .

smoke:
	$(PYTHON) -m hope_job_agent.pipeline.run_mvp --source approved_json --input data/sample_jobs.json --profiles data/sample_profiles.json --output $(SMOKE_DIR)/mvp_results.csv --limit 2 --database-url sqlite:///$(SMOKE_DIR)/mvp.sqlite3

quality:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m black --check .
	$(PYTHON) -m mypy src
	$(PYTHON) -m pytest
	$(MAKE) smoke

