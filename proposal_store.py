"""Persistent review queue for high-risk memory changes."""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ProposalStore:
    """Store merge and Dream proposals until explicitly approved or rejected."""

    def __init__(self, buckets_dir: str):
        state_dir = Path(buckets_dir).resolve() / ".ombre"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "proposals.db"
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
                CREATE TABLE IF NOT EXISTS proposals (
                    proposal_id TEXT PRIMARY KEY,
                    proposal_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewer TEXT NOT NULL DEFAULT '',
                    review_note TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_proposals_status
                ON proposals(status, created_at DESC)
                """
            )

    def create(
        self,
        proposal_type: str,
        summary: str,
        payload: dict,
        scope: str = "global",
    ) -> str:
        proposal_id = uuid.uuid4().hex[:12]
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proposals
                    (proposal_id, proposal_type, status, scope, summary,
                     payload_json, created_at)
                VALUES (?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    proposal_type,
                    scope or "global",
                    summary,
                    json.dumps(payload, ensure_ascii=False),
                    _now_iso(),
                ),
            )
        return proposal_id

    def get(self, proposal_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return self._decode(row) if row else None

    def list(self, status: str = "pending", scope: str = "", limit: int = 50) -> list[dict]:
        clauses = []
        params = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(limit, 500)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM proposals {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode(row) for row in rows]

    def resolve(self, proposal_id: str, status: str, reviewer: str, note: str = "") -> bool:
        if status not in ("approved", "rejected", "cancelled"):
            return False
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE proposals
                SET status = ?, reviewed_at = ?, reviewer = ?, review_note = ?
                WHERE proposal_id = ? AND status = 'pending'
                """,
                (status, _now_iso(), reviewer, note, proposal_id),
            )
        return cursor.rowcount == 1

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result
