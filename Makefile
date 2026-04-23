.PHONY: sync test help init-db

sync:
\tuv sync

test:
\tuv run pytest

init-db:
\tuv run python -m lawful_anomaly_screening.cli init-db

help:
\tuv run python -m lawful_anomaly_screening.cli --help
