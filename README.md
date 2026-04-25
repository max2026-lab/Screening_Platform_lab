# lawful_anomaly_screening

Phase 0 scaffold for v1.5.1.

This repository is intentionally synchronous, SQLite-only, and structured around a legal gate before analysis.

## Quick start

For development:
```powershell
uv sync
uv run python -m lawful_anomaly_screening.cli --help
```

For operators:
```powershell
# Install the package globally (e.g. via pipx or uv tool)
uv tool install .
lawful-anomaly --help

# Or install it into an active virtual environment
pip install .
lawful-anomaly --help
```

Operator runbook: `docs/operator_runbook.md`

## Core commands

- `version`
- `show-config`
- `show-baseline`
- `init-db`
- `validate-aoi`
- `legal-check`
- `create-run`

## Guardrails

- No Redis, RQ, Celery, or worker queue scaffold.
- No Postgres or PostGIS scaffold.
- Public and shared exports must not expose exact coordinates.
