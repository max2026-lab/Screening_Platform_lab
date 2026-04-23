from __future__ import annotations


class RunRepository:
    def create_run(self, run_id: str, status: str) -> None:
        self._last = (run_id, status)
