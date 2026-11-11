import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import quote

FEVER_DATABASE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "fever_benchmark.sqlite3"
)
FEVER_DATASET_URL = "https://fever.ai/download/fever/train.jsonl"
FEVER_LICENSE_URL = "https://fever.ai/download/fever/license.html"
FEVER_ATTRIBUTION = (
    "Thorne et al. (2018), FEVER: a Large-scale Dataset for Fact Extraction "
    "and VERification, NAACL-HLT; claims derived from Wikipedia."
)
FEVER_EXPECTED_MINIMUM = 100_000
FEVER_LABELS = {"SUPPORTS", "REFUTES", "NOT ENOUGH INFO"}


def import_fever_jsonl(
    source: Iterable[bytes],
    database_path: Path = FEVER_DATABASE_PATH,
) -> int:
    """Builds a separate searchable benchmark DB, replacing it only after validation."""
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    count = 0

    try:
        with tempfile.NamedTemporaryFile(
            dir=database_path.parent,
            prefix=f".{database_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        connection = sqlite3.connect(temporary_path)
        try:
            connection.execute(
                """
                CREATE TABLE fever_claims (
                    id INTEGER PRIMARY KEY,
                    claim TEXT NOT NULL,
                    label TEXT NOT NULL
                        CHECK (label IN ('SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO')),
                    evidence_json TEXT NOT NULL
                )
                """
            )
            for line_number, raw_line in enumerate(source, start=1):
                if not raw_line.strip():
                    continue
                record = json.loads(raw_line)
                if not isinstance(record, dict):
                    raise ValueError(f"FEVER record on line {line_number} is not an object.")
                claim_id = record.get("id")
                claim = record.get("claim")
                label = record.get("label")
                if (
                    not isinstance(claim_id, int)
                    or not isinstance(claim, str)
                    or not claim.strip()
                    or label not in FEVER_LABELS
                ):
                    raise ValueError(f"FEVER record on line {line_number} has invalid fields.")
                connection.execute(
                    "INSERT INTO fever_claims (id, claim, label, evidence_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        claim_id,
                        claim.strip(),
                        label,
                        json.dumps(record.get("evidence", []), ensure_ascii=False),
                    ),
                )
                count += 1

            if count < FEVER_EXPECTED_MINIMUM:
                raise ValueError(
                    f"FEVER import contained {count} records; "
                    f"at least {FEVER_EXPECTED_MINIMUM} are required."
                )

            connection.execute(
                "CREATE VIRTUAL TABLE fever_claims_fts USING fts5("
                "claim, content='fever_claims', content_rowid='id')"
            )
            connection.execute(
                "INSERT INTO fever_claims_fts (rowid, claim) "
                "SELECT id, claim FROM fever_claims"
            )
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                [
                    ("dataset", "FEVER v1.0 training split"),
                    ("source_url", FEVER_DATASET_URL),
                    ("license_url", FEVER_LICENSE_URL),
                    ("license", "CC BY-SA 3.0 or applicable Wikipedia article license"),
                    ("attribution", FEVER_ATTRIBUTION),
                    ("record_count", str(count)),
                    ("use", "Research benchmark only; not published fact-check reviews"),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        os.replace(temporary_path, database_path)
        temporary_path = None
        return count
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _database_connection(database_path: Path) -> sqlite3.Connection:
    path = quote(str(Path(database_path).resolve()), safe="/")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def get_fever_status(
    database_path: Path = FEVER_DATABASE_PATH,
) -> Dict[str, Any]:
    if not Path(database_path).is_file():
        return {
            "available": False,
            "record_count": 0,
            "dataset": "FEVER v1.0 training split",
            "source_url": FEVER_DATASET_URL,
            "license": "CC BY-SA 3.0 or applicable Wikipedia article license",
            "license_url": FEVER_LICENSE_URL,
            "attribution": FEVER_ATTRIBUTION,
            "note": "Import the dataset with python scripts/import_fever_benchmark.py.",
        }

    connection = _database_connection(database_path)
    try:
        count = connection.execute("SELECT COUNT(*) FROM fever_claims").fetchone()[0]
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    finally:
        connection.close()
    return {
        "available": True,
        "record_count": count,
        "dataset": metadata["dataset"],
        "source_url": metadata["source_url"],
        "license": metadata["license"],
        "license_url": metadata["license_url"],
        "attribution": metadata.get("attribution", FEVER_ATTRIBUTION),
        "note": metadata["use"],
    }


def _evidence_articles(evidence_json: str) -> List[Dict[str, str]]:
    try:
        evidence_sets = json.loads(evidence_json)
    except (TypeError, json.JSONDecodeError):
        return []

    articles = []
    seen = set()
    if not isinstance(evidence_sets, list):
        return articles
    for evidence_set in evidence_sets:
        if not isinstance(evidence_set, list):
            continue
        for item in evidence_set:
            if not isinstance(item, list) or len(item) < 3:
                continue
            title = item[2]
            if not isinstance(title, str) or not title or title in seen:
                continue
            seen.add(title)
            articles.append({
                "title": title.replace("_", " "),
                "url": "https://en.wikipedia.org/wiki/"
                + quote(title, safe="()_,-"),
            })
    return articles


def search_fever_claims(
    query: str,
    limit: int = 10,
    database_path: Path = FEVER_DATABASE_PATH,
) -> List[Dict[str, Any]]:
    if not Path(database_path).is_file():
        return []
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not tokens:
        return []
    match_query = " AND ".join(f'"{token}"' for token in tokens)

    connection = _database_connection(database_path)
    try:
        rows = connection.execute(
            """
            SELECT c.id, c.claim, c.label, c.evidence_json
            FROM fever_claims_fts AS f
            JOIN fever_claims AS c ON c.id = f.rowid
            WHERE fever_claims_fts MATCH ?
            ORDER BY bm25(fever_claims_fts)
            LIMIT ?
            """,
            (match_query, min(max(limit, 1), 20)),
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "id": row[0],
            "claim": row[1],
            "label": row[2],
            "dataset": "FEVER v1.0 research benchmark",
            "evidence_articles": _evidence_articles(row[3]),
        }
        for row in rows
    ]
