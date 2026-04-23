from dataclasses import dataclass


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    status: str
