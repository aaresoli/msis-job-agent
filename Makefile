.PHONY: install test lint format

install:
	pip install -r requirements-dev.txt

test:
	pytest

lint:
	ruff check src tests
	mypy src

format:
	black src tests
	ruff check --fix src tests

