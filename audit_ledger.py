"""Append-only audit ledger for memory bucket mutations."""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class AuditLedger:
    """Store immutable before/after snapshots alongside the bucket vault."""

    def __init__(self, buckets_dir: str):
        self.base_dir = Path(buckets_dir).resolve()
        self.state_dir = self.base_dir / ".ombre"
        self.trash_dir = self.state_dir / "trash"
        self.db_path = self.state_dir / "audit.db"
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bucket_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_bucket
                ON audit_events(bucket_id, event_id DESC)
                """
            )

    def snapshot_file(self, file_path: str) -> Optional[dict]:
        if not file_path or not os.path.exists(file_path):
            return None
        path = Path(file_path).resolve()
        try:
            relative_path = str(path.relative_to(self.base_dir))
        except ValueError:
            relative_path = path.name
        return {
            "relative_path": relative_path,
            "raw_text": path.read_text(encoding="utf-8"),
        }

    def record(
        self,
        bucket_id: str,
        action: str,
        before: Optional[dict] = None,
        after: Optional[dict] = None,
        actor: str = "system",
        reason: str = "",
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audit_events
                    (bucket_id, action, actor, reason, before_json, after_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bucket_id,
                    action,
                    actor,
                    reason,
                    json.dumps(before, ensure_ascii=False) if before is not None else None,
                    json.dumps(after, ensure_ascii=False) if after is not None else None,
                    _now_iso(),
                ),
            )
            return int(cursor.lastrowid)

    def history(self, bucket_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, bucket_id, action, actor, reason,
                       before_json, after_json, created_at
                FROM audit_events
                WHERE bucket_id = ?
                ORDER BY event_id DESC
                LIMIT ?
                """,
                (bucket_id, max(1, min(limit, 500))),
            ).fetchall()
        return [
            {
                **dict(row),
                "before": json.loads(row["before_json"]) if row["before_json"] else None,
                "after": json.loads(row["after_json"]) if row["after_json"] else None,
            }
            for row in rows
        ]

    def latest_delete(self, bucket_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event_id, before_json
                FROM audit_events
                WHERE bucket_id = ? AND action = 'delete'
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (bucket_id,),
            ).fetchone()
        if not row or not row["before_json"]:
            return None
        return {"event_id": row["event_id"], "before": json.loads(row["before_json"])}

    def event(self, bucket_id: str, event_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT event_id, bucket_id, action, actor, reason,
                       before_json, after_json, created_at
                FROM audit_events
                WHERE bucket_id = ? AND event_id = ?
                """,
                (bucket_id, event_id),
            ).fetchone()
        if not row:
            return None
        return {
            **dict(row),
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]) if row["after_json"] else None,
        }

    def trash_path(self, bucket_id: str) -> Path:
        return self.trash_dir / f"{bucket_id}.md"
