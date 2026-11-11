import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.fever_benchmark import (
    FEVER_EXPECTED_MINIMUM,
    get_fever_status,
    import_fever_jsonl,
    search_fever_claims,
)


class TestFeverBenchmark(unittest.TestCase):
    def test_import_indexes_records_and_keeps_evidence_links(self):
        records = [
            {
                "id": 1,
                "label": "SUPPORTS",
                "claim": "Earth orbits the Sun",
                "evidence": [[[11, 12, "Earth", 0]]],
            },
            {
                "id": 2,
                "label": "REFUTES",
                "claim": "Earth is the Sun",
                "evidence": [[[21, 22, "Earth", 1]]],
            },
            {
                "id": 3,
                "label": "NOT ENOUGH INFO",
                "claim": "Earth orbits an unknown planet",
                "evidence": [[[31, 32, None, None]]],
            },
        ]
        source = [json.dumps(record).encode("utf-8") + b"\n" for record in records]

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fever.sqlite3"
            with patch("app.core.fever_benchmark.FEVER_EXPECTED_MINIMUM", 3):
                count = import_fever_jsonl(source, database_path)

            self.assertEqual(count, 3)
            status = get_fever_status(database_path)
            self.assertTrue(status["available"])
            self.assertEqual(status["record_count"], 3)
            self.assertIn("not published fact-check reviews", status["note"])

            results = search_fever_claims("Earth orbits Sun", database_path=database_path)
            self.assertEqual(results[0]["label"], "SUPPORTS")
            self.assertEqual(
                results[0]["evidence_articles"][0]["url"],
                "https://en.wikipedia.org/wiki/Earth",
            )

    def test_too_small_or_invalid_import_does_not_replace_existing_database(self):
        records = [
            {
                "id": 1,
                "label": "UNKNOWN",
                "claim": "Invalid label",
                "evidence": [],
            }
        ]
        source = [json.dumps(records[0]).encode("utf-8") + b"\n"]

        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "fever.sqlite3"
            database_path.write_bytes(b"existing database")
            with patch(
                "app.core.fever_benchmark.FEVER_EXPECTED_MINIMUM",
                FEVER_EXPECTED_MINIMUM,
            ):
                with self.assertRaises(ValueError):
                    import_fever_jsonl(source, database_path)
            self.assertEqual(database_path.read_bytes(), b"existing database")

    def test_missing_database_reports_import_instructions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status = get_fever_status(Path(temp_dir) / "missing.sqlite3")

        self.assertFalse(status["available"])
        self.assertEqual(status["record_count"], 0)
        self.assertIn("import_fever_benchmark.py", status["note"])


if __name__ == "__main__":
    unittest.main()
