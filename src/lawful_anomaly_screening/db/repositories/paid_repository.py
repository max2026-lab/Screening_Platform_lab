from __future__ import annotations

from pathlib import Path
import sqlite3

from lawful_anomaly_screening.db.sqlite import connect, upsert_paid_order, upsert_paid_quote


BOOLEAN_FIELDS = {
    "tasking_requested",
    "autonomous_purchase_enabled",
}


def _row_to_record(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    record = dict(row)
    for key in BOOLEAN_FIELDS:
        if key in record:
            record[key] = bool(record[key])
    return record


class PaidRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def save_quote(self, quote_record: dict) -> dict:
        with connect(self.db_path) as conn:
            upsert_paid_quote(conn, **quote_record)
            conn.commit()
        return self.fetch_quote(provider_quote_id=quote_record["provider_quote_id"])

    def fetch_quote(
        self,
        *,
        candidate_id: str | None = None,
        provider_quote_id: str | None = None,
    ) -> dict | None:
        if candidate_id is None and provider_quote_id is None:
            raise ValueError("candidate_id or provider_quote_id is required")

        where_clause = "provider_quote_id = ?"
        params: tuple[object, ...] = (provider_quote_id,)
        if provider_quote_id is None:
            where_clause = "candidate_id = ?"
            params = (candidate_id,)

        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT
                    provider_quote_id,
                    candidate_id,
                    run_id,
                    project_id,
                    provider,
                    amount,
                    credits,
                    currency,
                    eula_reference,
                    paid_status,
                    archive_mode,
                    tasking_requested,
                    autonomous_purchase_enabled,
                    created_at,
                    updated_at
                FROM paid_quotes
                WHERE {where_clause}
                ORDER BY created_at DESC, provider_quote_id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _row_to_record(row)

    def update_quote_status(self, *, provider_quote_id: str, paid_status: str) -> dict | None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE paid_quotes
                SET paid_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE provider_quote_id = ?
                """,
                (paid_status, provider_quote_id),
            )
            conn.commit()
        return self.fetch_quote(provider_quote_id=provider_quote_id)

    def save_order(self, order_record: dict) -> dict:
        with connect(self.db_path) as conn:
            upsert_paid_order(conn, **order_record)
            conn.commit()
        return self.fetch_order(provider_order_id=order_record["provider_order_id"])

    def fetch_order(
        self,
        *,
        candidate_id: str | None = None,
        provider_order_id: str | None = None,
    ) -> dict | None:
        if candidate_id is None and provider_order_id is None:
            raise ValueError("candidate_id or provider_order_id is required")

        where_clause = "provider_order_id = ?"
        params: tuple[object, ...] = (provider_order_id,)
        if provider_order_id is None:
            where_clause = "candidate_id = ?"
            params = (candidate_id,)

        with connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT
                    provider_order_id,
                    provider_quote_id,
                    candidate_id,
                    run_id,
                    project_id,
                    provider,
                    amount,
                    credits,
                    currency,
                    eula_reference,
                    paid_status,
                    archive_mode,
                    tasking_requested,
                    autonomous_purchase_enabled,
                    human_triggered_by,
                    created_at,
                    updated_at
                FROM paid_orders
                WHERE {where_clause}
                ORDER BY created_at DESC, provider_order_id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _row_to_record(row)

    def update_order_status(self, *, provider_order_id: str, paid_status: str) -> dict | None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE paid_orders
                SET paid_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE provider_order_id = ?
                """,
                (paid_status, provider_order_id),
            )
            conn.commit()
        return self.fetch_order(provider_order_id=provider_order_id)
