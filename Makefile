# Linux/macOS convenience only. Bank users: see docs/RUNBOOK.md (Windows cmd).
.PHONY: sync test lint fmt ddl reqs preflight serve

sync:
	uv sync --python 3.11

test:
	uv run python -m pytest

lint:
	uv run python -m ruff check .
	uv run python -m ruff format --check .

fmt:
	uv run python -m ruff format .
	uv run python -m ruff check --fix .

ddl:
	uv run python -m schema.generate

reqs:
	uv run python -m supervisor.cli export-reqs

preflight:
	uv run python -m supervisor.cli preflight

serve:
	uv run python -m supervisor.cli serve
