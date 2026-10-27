"""Run the test questions in each mode N times, score the answers and summarize them.

Usage:
  python run_eval.py [--runs 3] [--modes structured naive] [--questions Q1 Q4] [--category vague] [--log]
  python run_eval.py --rescore results/run_<time>.csv     re-score saved answers, no model calls
  python run_eval.py --review-sheet                        expected answers as Markdown, for review

Writes results/run_<time>.csv (one row per answer: scores + the app's log columns, store.ANSWER_COLUMNS)
and results/run_<time>_summary.csv (consistency per question x mode, averages per mode).
--log also appends each answer to the Google Sheet (or results/log.jsonl), with source "eval".
"""

import argparse
import csv
import json
import re
import time
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path
from statistics import mean

import core
import store

ROOT = Path(__file__).parent
QUESTIONS_PATH = ROOT / "test_questions.json"
RESULTS_DIR = ROOT / "results"
RUNNERS = {"structured": core.run_structured, "naive": core.run_naive}
CATEGORIES = ["named-instrument", "problem-only", "no-suitable-equipment", "accessory-trap",
              "misleading-keyword", "multi-step", "vague"]
SCORE_COLUMNS = ["expected_hits", "expected_total", "recall", "unacceptable_hits", "unacceptable_ids",
                 "unclassified_ids", "expected_only_mentioned", "na_hits", "na_total", "accessory_hits", "accessory_total",
                 "asked_clarifying", "clarifying_ok", "contacts_ok", "contacts_total"]
COLUMNS = ["question_id", "category", "status", "run"] + SCORE_COLUMNS + store.ANSWER_COLUMNS
TRANSIENT = re.compile(r"\b(429|500|502|503|504)\b|rate.?limit|quota|unavailable|overloaded|timed? ?out",
                       re.IGNORECASE)


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- scoring: pure functions of (question, result), so saved answers can be re-scored ---

def count_matches(text: str, patterns: list[str]) -> int:
    return sum(bool(re.search(p, text, re.IGNORECASE)) for p in patterns)


def accessory_text(result: dict, eq_id: str) -> str:
    """Where accessories for one instrument should be named: its accessories_to_confirm list in
    structured mode; the whole answer in naive mode (free text can't be split per instrument)."""
    if result["mode"] == "structured":
        return " ".join(acc for rec in result["recommendations"] if rec["id"] == eq_id
                        for acc in rec["accessories_to_confirm"])
    return result["raw"]


ASKS_FOR_MORE = re.compile(r"\?|more (information|details?) (is|are) needed|please (specify|clarify|provide)"
                           r"|could you (tell|clarify|specify|provide)", re.IGNORECASE)


def asked_clarifying(result: dict) -> bool:
    """Structured: the clarifying_question field. Naive: a heuristic (asks for more, recommends nothing),
    so check naive clarifying scores by hand."""
    if result["mode"] == "structured":
        return bool(result.get("clarifying_question"))
    return bool(ASKS_FOR_MORE.search(result["raw"])) and not result["instrument_ids"]


def contact_name(eq_id: str) -> str:
    """The contact's name without the affiliation: "Avery Bennett (SOD)" -> "Avery Bennett"."""
    return re.sub(r"\s*\(.*\)\s*$", "", core.equipment_by_id()[eq_id]["contact"])


def score(question: dict, result: dict) -> dict:
    """Scores for one answer. Answers with an error get no scores (they are counted separately)."""
    if result["error"]:
        return {column: None for column in SCORE_COLUMNS}
    found = set(result["instrument_ids"])
    expected, acceptable = set(question["expected_ids"]), set(question.get("acceptable_ids", []))
    unacceptable = set(question.get("unacceptable_ids", []))
    accessories = {eq_id: patterns for eq_id, patterns in question.get("expected_accessories", {}).items()
                   if eq_id in found}
    asked = asked_clarifying(result)
    naive = result["mode"] == "naive"
    hits = len(found & expected)
    return {
        "expected_hits": hits,
        "expected_total": len(expected),
        "recall": round(hits / len(expected), 3) if expected else None,
        "unacceptable_hits": len(found & unacceptable),
        "unacceptable_ids": " ".join(sorted(found & unacceptable)),
        "unclassified_ids": " ".join(sorted(found - expected - acceptable - unacceptable)),
        # Naive only: expected instruments named in the text but left off the "Recommended:" line. Check by hand.
        "expected_only_mentioned": " ".join(sorted(expected & set(result["mentioned_ids"]) - found)),
        # Both modes are searched in the full answer, so a technique named in the summary counts too.
        "na_hits": count_matches(result["raw"], question["expected_not_available"]),
        "na_total": len(question["expected_not_available"]),
        "accessory_hits": sum(count_matches(accessory_text(result, eq_id), patterns)
                              for eq_id, patterns in accessories.items()),
        "accessory_total": sum(len(patterns) for patterns in accessories.values()),
        "asked_clarifying": asked,
        "clarifying_ok": asked == question.get("expect_clarifying", False),
        # Only naive answers write contacts themselves; structured contacts come from the dataset.
        "contacts_ok": sum(contact_name(eq_id) in result["raw"] for eq_id in found) if naive else None,
        "contacts_total": len(found) if naive else None,
    }


# --- consistency across repeated runs ---

def jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def consistency(id_sets: list[frozenset]) -> dict:
    """How alike the instrument sets of repeated runs are."""
    if not id_sets:
        return {"stable_runs": "", "mean_jaccard": None, "id_frequency": ""}
    modal_count = Counter(id_sets).most_common(1)[0][1]
    pairs = list(combinations(id_sets, 2))
    frequency = Counter(eq_id for ids in id_sets for eq_id in ids)
    return {
        "stable_runs": f"{modal_count}/{len(id_sets)}",
        "mean_jaccard": round(mean(jaccard(a, b) for a, b in pairs), 3) if pairs else 1.0,
        "id_frequency": " ".join(f"{eq_id}:{n}" for eq_id, n in sorted(frequency.items())),
    }


# --- summary ---

SUMMARY_COLUMNS = ["scope", "question_id", "mode", "answers", "errors", "json_ok_rate", "mean_recall",
                   "unacceptable_rate", "na_rate", "accessory_rate", "clarifying_ok_rate", "contacts_rate",
                   "mean_seconds", "mean_output_tokens", "stable_runs", "mean_jaccard", "id_frequency"]


def _num(value):
    """CSV cells are strings; turn numbers and booleans back into values (empty -> None)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, bool)):
        return value
    if value in ("True", "False"):
        return value == "True"
    return float(value)


def _mean(values) -> float | None:
    values = [v for v in (_num(v) for v in values) if v is not None]
    return round(mean(values), 3) if values else None


def _ratio(rows: list[dict], hits: str, total: str) -> float | None:
    totals = sum(_num(r[total]) or 0 for r in rows)
    return round(sum(_num(r[hits]) or 0 for r in rows) / totals, 3) if totals else None


def summarize_group(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    return {
        "answers": len(rows),
        "errors": len(rows) - len(scored),
        "json_ok_rate": _mean(r["json_ok"] for r in scored),
        "mean_recall": _mean(r["recall"] for r in scored),
        "unacceptable_rate": _mean(int((_num(r["unacceptable_hits"]) or 0) > 0) for r in scored),
        "na_rate": _ratio(scored, "na_hits", "na_total"),
        "accessory_rate": _ratio(scored, "accessory_hits", "accessory_total"),
        "clarifying_ok_rate": _mean(r["clarifying_ok"] for r in scored),
        "contacts_rate": _ratio(scored, "contacts_ok", "contacts_total"),
        "mean_seconds": _mean(r["seconds"] for r in scored),
        "mean_output_tokens": _mean(r["output_tokens"] for r in scored),
    }


def summarize(rows: list[dict]) -> list[dict]:
    """Per question x mode (with consistency), then per mode over reviewed, draft and all questions."""
    summary = []
    keys = list(dict.fromkeys((r["question_id"], r["mode"]) for r in rows))
    for question_id, mode in keys:
        group = [r for r in rows if r["question_id"] == question_id and r["mode"] == mode]
        id_sets = [frozenset(r["instrument_ids"].split()) for r in group if not r["error"]]
        summary.append({"scope": "question", "question_id": question_id, "mode": mode,
                        **summarize_group(group), **consistency(id_sets)})
    for mode in dict.fromkeys(r["mode"] for r in rows):
        for scope in ("reviewed", "draft", "all"):
            group = [r for r in rows if r["mode"] == mode and scope in ("all", r["status"])]
            if group:
                summary.append({"scope": scope, "question_id": "", "mode": mode, **summarize_group(group)})
    return summary


PRINTED = [("mean_recall", "recall"), ("unacceptable_rate", "unacc"), ("na_rate", "n/a"),
           ("accessory_rate", "acc"), ("clarifying_ok_rate", "clar"), ("contacts_rate", "contact"),
           ("mean_seconds", "sec")]


def print_summary(summary: list[dict]) -> None:
    """Per-mode averages as a table (the per-question rows are in the summary CSV)."""
    print("\n" + f"{'scope':<9}{'mode':<11}{'n':>4}{'err':>5}" + "".join(f"{label:>9}" for _, label in PRINTED))
    for s in summary:
        if s["scope"] == "question":
            continue
        cells = ["-" if s[key] is None else f"{s[key]:.2f}" for key, _ in PRINTED]
        print(f"{s['scope']:<9}{s['mode']:<11}{s['answers']:>4}{s['errors']:>5}" + "".join(f"{c:>9}" for c in cells))


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # -sig so Excel reads UTF-8
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(rows: list[dict], out_path: Path) -> None:
    write_csv(out_path, COLUMNS, rows)
    summary = summarize(rows)
    summary_path = out_path.with_name(out_path.stem + "_summary.csv")
    write_csv(summary_path, SUMMARY_COLUMNS, summary)
    print_summary(summary)
    print(f"\nSaved {out_path}\nSaved {summary_path}")


# --- running ---

def run_with_retry(mode: str, question: str, retries: int = 2, wait: float = 10) -> dict:
    """Retry rate limits and server errors (after 10 s, then 20 s); other errors are kept as answers."""
    for attempt in range(retries + 1):
        result = RUNNERS[mode](question)
        if not (result["error"] and TRANSIENT.search(result["error"])) or attempt == retries:
            return result
        time.sleep(wait * (attempt + 1))


def eval_row(question: dict, run: int, answer: dict, result: dict) -> dict:
    return {"question_id": question["id"], "category": question.get("category", ""),
            "status": question.get("status", "draft"), "run": run, **score(question, result), **answer}


def select_questions(questions: list[dict], ids: list[str] | None, category: str | None) -> list[dict]:
    return [q for q in questions if (not ids or q["id"] in ids) and (not category or q.get("category") == category)]


def run(questions: list[dict], modes: list[str], runs: int, log: bool = False) -> list[dict]:
    rows = []
    for q in questions:
        for mode in modes:
            for n in range(1, runs + 1):
                result = run_with_retry(mode, q["question"])
                answer = store.answer_row(q["question"], result, source="eval")
                if log:
                    store.save("answers", answer, background=False)
                row = eval_row(q, n, answer, result)
                rows.append(row)
                print(f"{q['id']:<4} {mode:<10} run {n}: [{row['instrument_ids']}] "
                      f"expected {row['expected_hits']}/{row['expected_total']}, "
                      f"unacceptable {row['unacceptable_hits']}, not-available {row['na_hits']}/{row['na_total']}"
                      + (f"  ERROR {row['error']}" if row["error"] else ""))
    return rows


def rescore(path: Path, questions: list[dict]) -> list[dict]:
    """Re-score saved answers against the current test_questions.json, without calling the model."""
    by_id = {q["id"]: q for q in questions}
    with path.open(encoding="utf-8-sig", newline="") as f:
        saved = list(csv.DictReader(f))
    if saved and "raw_output" not in saved[0]:
        raise SystemExit(f"{path} has no raw_output column; it was written by an older run_eval.py.")
    rows = []
    for old in saved:
        q = by_id.get(old["question_id"])
        if q is None:
            print(f"Skipping {old['question_id']}: no longer in {QUESTIONS_PATH.name}")
            continue
        if old["error"] and not old["raw_output"]:  # the model never answered; keep the error
            result = {**core.new_result(old["mode"], old["raw_output"]), "error": old["error"]}
        else:
            result = core.read_answer(old["mode"], old["raw_output"])
        # Keep the saved run's metadata (time, model, versions, tokens); refresh what reading the answer derives.
        fresh = store.answer_row(old["question"], result)
        answer = {column: old.get(column, "") for column in store.ANSWER_COLUMNS}
        answer.update({key: fresh[key] for key in ("json_ok", "clarifying_question", "instrument_ids", "ids_source",
                                                   "mentioned_ids", "removed_ids", "not_available", "error")})
        rows.append(eval_row(q, int(old["run"]), answer, result))
    return rows


def readable(pattern: str) -> str:
    r"""A scoring regex in plain words: "\bGPC\b|size.exclusion" -> "GPC / size exclusion"."""
    text = re.sub(r"\\b|[()]", "", pattern).replace(".?", " ")
    return re.sub(r"(?<=\w)\.(?=\w)", " ", text).replace("|", " / ")


def review_sheet(questions: list[dict]) -> str:
    """The expected answers in plain words (instrument names, not IDs), for the domain expert."""
    known = core.equipment_by_id()

    def names(ids: list[str]) -> str:
        return "; ".join(f"{known[i]['instrument']} ({known[i]['manufacturer']} {known[i]['model']})"
                         for i in ids) or "none"

    def terms(patterns: list[str]) -> str:
        return "; ".join(readable(p) for p in patterns) or "none"

    lines = ["# Test questions: expected answers for review", "",
             "Please correct anything that is wrong or missing. Acceptable = a reasonable partial answer;",
             "unacceptable = should not be recommended. Terms separated by / are alternatives.", ""]
    for q in questions:
        accessories = "; ".join(f"{known[i]['instrument']}: {terms(p)}"
                                for i, p in q.get("expected_accessories", {}).items()) or "none"
        lines += [
            f"## {q['id']} ({q.get('category', '')}, {q.get('status', 'draft')})", "",
            f"**Question:** {q['question']}", "",
            f"- **Expected:** {names(q['expected_ids'])}",
            f"- **Acceptable:** {names(q.get('acceptable_ids', []))}",
            f"- **Unacceptable:** {names(q.get('unacceptable_ids', []))}",
            f"- **Should be flagged as not available:** {terms(q['expected_not_available'])}",
            f"- **Accessories to confirm:** {accessories}",
            f"- **Should ask a clarifying question:** {'yes' if q.get('expect_clarifying') else 'no'}",
            f"- **Notes:** {q.get('notes', '')}",
            "- **Reviewer comments:** ", "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--modes", nargs="+", choices=list(RUNNERS), default=list(RUNNERS))
    parser.add_argument("--questions", nargs="+", metavar="ID", help="only these question IDs")
    parser.add_argument("--category", choices=CATEGORIES, help="only questions in this category")
    parser.add_argument("--log", action="store_true", help="also log answers to the sheet / log file")
    parser.add_argument("--rescore", type=Path, metavar="CSV", help="re-score a saved run, no model calls")
    parser.add_argument("--review-sheet", action="store_true", help="write the expected answers as Markdown")
    args = parser.parse_args()

    questions = select_questions(load_questions(), args.questions, args.category)
    RESULTS_DIR.mkdir(exist_ok=True)
    if args.review_sheet:
        path = RESULTS_DIR / "expected_answers_review.md"
        path.write_text(review_sheet(questions), encoding="utf-8")
        print(f"Saved {path}")
    elif args.rescore:
        write_outputs(rescore(args.rescore, questions), args.rescore.with_name(args.rescore.stem + "_rescored.csv"))
    else:
        rows = run(questions, args.modes, args.runs, args.log)
        write_outputs(rows, RESULTS_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.csv")


if __name__ == "__main__":
    main()
