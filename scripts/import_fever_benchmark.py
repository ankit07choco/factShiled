#!/usr/bin/env python3
"""Download and import the official FEVER training split into its separate benchmark DB."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

from app.core.fever_benchmark import (
    FEVER_DATABASE_PATH,
    FEVER_DATASET_URL,
    import_fever_jsonl,
)


def main() -> None:
    argparse.ArgumentParser(
        description="Download and index the official FEVER training split."
    ).parse_args()
    with requests.get(
        FEVER_DATASET_URL,
        headers={"User-Agent": "FactShield-FEVER-importer/1.0"},
        timeout=(10, 60),
        stream=True,
    ) as response:
        response.raise_for_status()
        count = import_fever_jsonl(response.iter_lines(), FEVER_DATABASE_PATH)
    print(f"Imported {count:,} FEVER benchmark claims into {FEVER_DATABASE_PATH}")
    print("This benchmark is separate from the published fact-check database.")


if __name__ == "__main__":
    main()
