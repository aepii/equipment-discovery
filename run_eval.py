"""Run every test question in each mode N times and save results/run_<time>.csv for manual scoring.

Usage: python run_eval.py [--runs 3] [--modes structured naive] [--log]

The CSV has the same answer columns as the app's log (store.ANSWER_COLUMNS), plus the scores.
--log also appends each answer to the Google Sheet (or results/log.jsonl), with source "eval".
"""

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

import core
import store

ROOT = Path(__file__).parent
RUNNERS = {"structured": core.run_structured, "naive": core.run_naive}
COLUMNS = ["question_id", "run", "expected_found", "not_available_flagged"] + store.ANSWER_COLUMNS


def not_available_text(result: dict) -> str:
    """Text in which a 'not available' technique should be mentioned."""
    if result["mode"] == "structured":
        return json.dumps(result.get("not_available", []))
    return result["raw"]


def score(found: list[str], expected: list[str]) -> str:
    return f"{len(set(found) & set(expected))}/{len(expected)}"


def flagged(text: str, expected_patterns: list[str]) -> str:
    hits = sum(bool(re.search(p, text, re.IGNORECASE)) for p in expected_patterns)
    return f"{hits}/{len(expected_patterns)}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--modes", nargs="+", choices=list(RUNNERS), default=list(RUNNERS))
    parser.add_argument("--log", action="store_true", help="also log answers to the sheet / log file")
    args = parser.parse_args()

    questions = json.loads((ROOT / "test_questions.json").read_text(encoding="utf-8"))
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"run_{datetime.now():%Y%m%d_%H%M%S}.csv"

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:  # -sig so Excel reads UTF-8
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for q in questions:
            for mode in args.modes:
                for run in range(1, args.runs + 1):
                    result = RUNNERS[mode](q["question"])
                    answer = store.answer_row(q["question"], result, source="eval")
                    if args.log:
                        store.save("answers", answer, background=False)
                    found = result["instrument_ids"]
                    row = {
                        "question_id": q["id"], "run": run,
                        "expected_found": score(found, q["expected_ids"]),
                        "not_available_flagged": flagged(not_available_text(result), q["expected_not_available"]),
                        **answer,
                    }
                    writer.writerow(row)
                    print(f"{q['id']} {mode:<10} run {run}: found [{row['instrument_ids']}] "
                          f"expected {row['expected_found']}, not-available {row['not_available_flagged']}"
                          + (f"  ERROR {row['error']}" if row["error"] else ""))
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
