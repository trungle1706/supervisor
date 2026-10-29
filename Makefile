# Linux/macOS convenience only. Bank users: see docs/RUNBOOK.md (Windows cmd).
.PHONY: sync test test-fast test-full lint fmt ddl reqs reqs-nexus preflight serve bench bench-quick

sync:
	uv sync --python 3.11

test:
	uv run python -m pytest

# WP-T1 (docs/testing.md): daily run without the slow tests, 6 workers (shared host)
test-fast:
	PYTHONPATH=src SUPERVISOR_ENV_FILE=/dev/null uv run python -m pytest tests -q -p no:cacheprovider -m "not slow" -n 6

test-full:
	PYTHONPATH=src SUPERVISOR_ENV_FILE=/dev/null uv run python -m pytest tests -q -p no:cacheprovider -n 6

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

# WP23: latency benchmark (docs/latency.md). Full run takes about 40 minutes.
bench:
	uv run python -m tools.bench_latency

bench-quick:
	uv run python -m tools.bench_latency --quick
