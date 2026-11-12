import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional


VERIFIED_VERDICTS = {"Likely True", "Likely False"}


def normalize_claim(claim: str) -> str:
    normalized = unicodedata.normalize("NFKC", claim).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


class VerificationStore:
    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim TEXT NOT NULL,
                normalized_claim TEXT NOT NULL UNIQUE,
                verdict TEXT NOT NULL CHECK (verdict IN ('Likely True', 'Likely False')),
                confidence_score INTEGER NOT NULL CHECK (confidence_score BETWEEN 0 AND 100),
                explanation TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                verification_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )

    @staticmethod
    def _serialize_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["sources"] = json.loads(record.pop("sources_json"))
        record["signals"] = json.loads(record.pop("signals_json"))
        record.pop("normalized_claim")
        return record

    def save_if_conclusive(self, result: dict[str, Any]) -> Optional[dict[str, Any]]:
        verdict = result.get("verdict")
        if verdict not in VERIFIED_VERDICTS:
            return None

        claim = result.get("primary_claim") or result.get("input_text")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("A conclusive verification must include claim text.")

        normalized = normalize_claim(claim)
        if not normalized:
            raise ValueError("A conclusive verification must include a searchable claim.")

        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        confidence = max(0, min(100, int(result.get("confidence_score", 0))))
        sources = json.dumps(result.get("sources") or [], ensure_ascii=False)
        signals = json.dumps(result.get("signals") or {}, ensure_ascii=False)
        explanation = str(result.get("explanation") or "")

        with self._connection() as connection:
            self._initialize(connection)
            connection.execute(
                """
                INSERT INTO verification_records (
                    claim, normalized_claim, verdict, confidence_score,
                    explanation, sources_json, signals_json, created_at,
                    updated_at, verification_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(normalized_claim) DO UPDATE SET
                    claim = excluded.claim,
                    verdict = excluded.verdict,
                    confidence_score = excluded.confidence_score,
                    explanation = excluded.explanation,
                    sources_json = excluded.sources_json,
                    signals_json = excluded.signals_json,
                    updated_at = excluded.updated_at,
                    verification_count = verification_records.verification_count + 1
                """,
                (
                    claim.strip(),
                    normalized,
                    verdict,
                    confidence,
                    explanation,
                    sources,
                    signals,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM verification_records WHERE normalized_claim = ?",
                (normalized,),
            ).fetchone()
        if row is None:
            raise sqlite3.DatabaseError("Saved verification could not be read.")
        return self._serialize_row(row)

    def list_records(
        self, search: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        with self._connection() as connection:
            self._initialize(connection)
            if search:
                pattern = f"%{search.strip()}%"
                total = connection.execute(
                    "SELECT COUNT(*) FROM verification_records WHERE claim LIKE ?",
                    (pattern,),
                ).fetchone()[0]
                rows = connection.execute(
                    """
                    SELECT * FROM verification_records
                    WHERE claim LIKE ?
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (pattern, limit, offset),
                ).fetchall()
            else:
                total = connection.execute(
                    "SELECT COUNT(*) FROM verification_records"
                ).fetchone()[0]
                rows = connection.execute(
                    """
                    SELECT * FROM verification_records
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
        return [self._serialize_row(row) for row in rows], total

    def get_record(self, record_id: int) -> Optional[dict[str, Any]]:
        with self._connection() as connection:
            self._initialize(connection)
            row = connection.execute(
                "SELECT * FROM verification_records WHERE id = ?", (record_id,)
            ).fetchone()
        return self._serialize_row(row) if row else None

    def update_record(self, record_id: int, changes: dict[str, Any]) -> bool:
        claim = changes["claim"].strip()
        normalized = normalize_claim(claim)
        if not normalized:
            raise ValueError("Claim text must contain letters or numbers.")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connection() as connection:
            self._initialize(connection)
            cursor = connection.execute(
                """
                UPDATE verification_records
                SET claim = ?, normalized_claim = ?, verdict = ?,
                    confidence_score = ?, explanation = ?, sources_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    claim,
                    normalized,
                    changes["verdict"],
                    changes["confidence_score"],
                    changes["explanation"],
                    json.dumps(changes["sources"], ensure_ascii=False),
                    timestamp,
                    record_id,
                ),
            )
            updated = cursor.rowcount > 0
        return updated

    def delete_record(self, record_id: int) -> bool:
        with self._connection() as connection:
            self._initialize(connection)
            cursor = connection.execute(
                "DELETE FROM verification_records WHERE id = ?", (record_id,)
            )
            deleted = cursor.rowcount > 0
        return deleted

    def summary(self) -> dict[str, Any]:
        with self._connection() as connection:
            self._initialize(connection)
            total = connection.execute(
                "SELECT COUNT(*) FROM verification_records"
            ).fetchone()[0]
            verdict_rows = connection.execute(
                """
                SELECT verdict, COUNT(*) AS count
                FROM verification_records
                GROUP BY verdict
                """
            ).fetchall()
        return {
            "total": total,
            "verdicts": {row["verdict"]: row["count"] for row in verdict_rows},
        }


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_configured_database_path = Path(
    os.getenv("FACTSHIELD_DATABASE_PATH", "data/factshield_verifications.sqlite3")
)
if not _configured_database_path.is_absolute():
    _configured_database_path = _PROJECT_ROOT / _configured_database_path

verification_store = VerificationStore(_configured_database_path)
