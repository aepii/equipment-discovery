"""Run every test question in each mode N times and save results/run_<time>.csv for manual scoring.

Usage: python run_eval.py [--runs 3] [--modes structured naive]
"""

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

import core
import llm

ROOT = Path(__file__).parent
RUNNERS = {"structured": core.run_structured, "naive": core.run_naive}
COLUMNS = ["question_id", "mode", "run", "provider", "model", "instruments_found",
           "expected_found", "not_available_flagged", "removed_ids", "error", "answer"]


def instrument_patterns() -> dict[str, re.Pattern]:
    """Ways an instrument can be named in free text: its ID, model, full name or abbreviation."""
    patterns = {}
    for e in core.load_equipment():
        names = [e["id"], e["model"], e["instrument"]]
        names += re.findall(r"\(([A-Z]{2,})\)", e["instrument"])  # e.g. TGA, DSC, ESEM
        alternatives = "|".join(re.escape(n) for n in names if n)
        patterns[e["id"]] = re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)
    return patterns


def instruments_found(result: dict, patterns: dict[str, re.Pattern]) -> list[str]:
    if result["mode"] == "structured":
        return [rec["id"] for rec in result.get("recommendations", [])]
    return [eq_id for eq_id, pattern in patterns.items() if pattern.search(result["raw"])]


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
    args = parser.parse_args()

    questions = json.loads((ROOT / "test_questions.json").read_text(encoding="utf-8"))
    patterns = instrument_patterns()
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
                    found = instruments_found(result, patterns)
                    row = {
                        "question_id": q["id"], "mode": mode, "run": run,
                        "provider": llm.provider(), "model": llm.model_name(),
                        "instruments_found": " ".join(found),
                        "expected_found": score(found, q["expected_ids"]),
                        "not_available_flagged": flagged(not_available_text(result), q["expected_not_available"]),
                        "removed_ids": " ".join(result.get("removed", [])),
                        "error": result["error"] or "",
                        "answer": result["raw"],
                    }
                    writer.writerow(row)
                    print(f"{q['id']} {mode:<10} run {run}: found [{row['instruments_found']}] "
                          f"expected {row['expected_found']}, not-available {row['not_available_flagged']}"
                          + (f"  ERROR {row['error']}" if row["error"] else ""))
    print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
