from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect


def _row_to_record(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    record = dict(row)
    record["include_pending"] = bool(record["include_pending"])
    record["label_count"] = int(record["label_count"])
    record["files"] = json.loads(record.pop("files_json"))
    record["file_hashes"] = json.loads(record.pop("file_hashes_json"))
    record["verification"] = json.loads(record.pop("verification_json"))
    return record


class CalibrationArtifactRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def fetch_artifact(self, artifact_hash: str) -> dict | None:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    artifact_hash,
                    run_id,
                    artifact_status,
                    label_pack_hash,
                    label_manifest_hash,
                    label_count,
                    include_pending,
                    files_json,
                    file_hashes_json,
                    verification_json
                FROM calibration_label_artifacts
                WHERE artifact_hash = ?
                """,
                (artifact_hash,),
            ).fetchone()
        return _row_to_record(row)

    def save_artifact(self, artifact_record: dict) -> dict:
        existing = self.fetch_artifact(artifact_record["artifact_hash"])
        if existing is not None:
            return existing

        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO calibration_label_artifacts (
                    artifact_hash,
                    run_id,
                    artifact_status,
                    label_pack_hash,
                    label_manifest_hash,
                    label_count,
                    include_pending,
                    files_json,
                    file_hashes_json,
                    verification_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_record["artifact_hash"],
                    artifact_record["run_id"],
                    artifact_record["artifact_status"],
                    artifact_record["label_pack_hash"],
                    artifact_record["label_manifest_hash"],
                    int(artifact_record["label_count"]),
                    int(bool(artifact_record["include_pending"])),
                    json.dumps(artifact_record["files"], sort_keys=True, separators=(",", ":")),
                    json.dumps(artifact_record["file_hashes"], sort_keys=True, separators=(",", ":")),
                    json.dumps(artifact_record["verification"], sort_keys=True, separators=(",", ":")),
                ),
            )
            conn.commit()
        return self.fetch_artifact(artifact_record["artifact_hash"])

    def list_artifacts(self) -> list[dict]:
        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    artifact_hash,
                    run_id,
                    artifact_status,
                    label_pack_hash,
                    label_manifest_hash,
                    label_count,
                    include_pending,
                    files_json,
                    file_hashes_json,
                    verification_json
                FROM calibration_label_artifacts
                ORDER BY run_id ASC, artifact_hash ASC
                """
            ).fetchall()
        return [_row_to_record(row) for row in rows]
