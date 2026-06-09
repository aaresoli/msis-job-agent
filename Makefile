.PHONY: install test lint format

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m mypy src

format:
	python -m black .
	python -m ruff check --fix .

