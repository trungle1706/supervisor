# Linux/macOS convenience only. Bank users: see docs/RUNBOOK.md (Windows cmd).
.PHONY: sync test lint fmt ddl reqs reqs-nexus preflight serve

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

# Local hand-off copy only (never commit): make reqs-nexus NEXUS=<nexus host>
reqs-nexus:
	uv run python -m supervisor.cli export-reqs --nexus $(NEXUS)

preflight:
	uv run python -m supervisor.cli preflight

serve:
	uv run python -m supervisor.cli serve
