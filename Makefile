.PHONY: install lock test lint format smoke quality

SMOKE_DIR ?= outputs/smoke

# Every target runs through `uv run`, which syncs the environment from uv.lock
# first. That makes a local `make quality` resolve exactly what CI resolves.
UV ?= uv
RUN ?= $(UV) run

install:
	$(UV) sync

lock:
	$(UV) lock

test:
	$(RUN) python -m pytest

lint:
	$(RUN) ruff check .
	$(RUN) mypy src

format:
	$(RUN) black .
	$(RUN) ruff check --fix .

smoke:
	$(RUN) python -m hope_job_agent.pipeline.run_mvp --source approved_json --input data/sample_jobs.json --profiles data/sample_profiles.json --output $(SMOKE_DIR)/mvp_results.csv --limit 2 --database-url sqlite:///$(SMOKE_DIR)/mvp.sqlite3

quality:
	$(UV) lock --check
	$(RUN) ruff check .
	$(RUN) black --check .
	$(RUN) mypy src
	$(RUN) python -m pytest
	$(MAKE) smoke
