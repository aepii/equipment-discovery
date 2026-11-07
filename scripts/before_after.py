"""Save a before/after pair for one question, for the poster.

Usage (from the project folder):
  python scripts/before_after.py --before LOGGED_ROWS.json --question-id Q20 [--modes structured annotated]

LOGGED_ROWS.json holds answer rows exported from the log (Google Sheet "answers" tab or
results/log.jsonl) for the old version; they are saved unchanged in results/before_<name>.json. The
question is then asked again with the current code and model, and the answers (checked like in the app:
roles, objective_met and, in annotated mode, fit levels) are saved in results/after_<name>.json.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import llm  # noqa: E402
import run_eval  # noqa: E402

RESULTS = ROOT / "results"
KEEP = ("mode", "summary", "objective_met", "primary_ids", "supplementary_ids", "not_available", "error", "raw")


def card(rec: dict) -> dict:
    """What a recommendation card shows."""
    return {key: rec.get(key) for key in ("id", "instrument", "role", "technique", "fit", "fit_reason",
                                           "accessories_to_confirm", "dead_end") if key in rec}


def after(question: dict, modes: list[str]) -> dict:
    answers = []
    for mode in modes:
        result = run_eval.run_with_retry(mode, question["question"])
        answers.append({**{k: result.get(k) for k in KEEP}, "cards": [card(r) for r in result["recommendations"]],
                        "usage": result["usage"], "score": run_eval.score(question, result)})
        print(f"{mode}: primary {result['primary_ids']}, supplementary {result['supplementary_ids']}, "
              f"objective_met {result['objective_met']}" + (f", ERROR {result['error']}" if result["error"] else ""))
    return {"question_id": question["id"], "question": question["question"],
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": llm.model_name(), "git_commit": core.git_commit(),
            "prompt_versions": {mode: core.prompt_version(mode) for mode in modes}, "answers": answers}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", type=Path, required=True, help="logged answer rows (JSON list)")
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--name", default="afm")
    parser.add_argument("--modes", nargs="+", default=["structured", "annotated"])
    args = parser.parse_args()
    question = run_eval.select_questions(run_eval.load_questions(), [args.question_id], None)[0]
    RESULTS.mkdir(exist_ok=True)
    before = json.loads(args.before.read_text(encoding="utf-8"))
    (RESULTS / f"before_{args.name}.json").write_text(
        json.dumps({"question_id": question["id"], "note": "Answers logged by the app before the change.",
                    "answers": before}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (RESULTS / f"after_{args.name}.json").write_text(
        json.dumps(after(question, args.modes), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved results/before_{args.name}.json and results/after_{args.name}.json")


if __name__ == "__main__":
    main()
