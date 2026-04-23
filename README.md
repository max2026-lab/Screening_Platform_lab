# lawful_anomaly_screening

Phase 0 scaffold for v1.5.1.

This repository is intentionally synchronous, SQLite-only, and structured around a legal gate before analysis.

## Quick start

```powershell
uv sync
uv run python -m lawful_anomaly_screening.cli --help
```

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
