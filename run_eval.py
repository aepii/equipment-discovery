"""Run the test questions in each mode N times, score the answers and summarize them.

Usage:
  python run_eval.py [--runs 3] [--modes structured annotated naive] [--questions Q1 Q4] [--category vague] [--log]
  python run_eval.py --question-file test_questions_generated.json --sample 15 --runs 1 --yes
  python run_eval.py --rescore results/run_<time>.csv     re-score saved answers, no model calls
  python run_eval.py --review-sheet [--sample 20]          expected answers as Markdown, for review
  python run_eval.py --record-demo [--questions Q1 Q2]     save one answer per question x mode as the
                                                           app's backup for the live demo (data/demo_answers.json)

Writes results/run_<time>.csv (one row per answer: scores + the app's log columns, store.ANSWER_COLUMNS)
and results/run_<time>_summary.csv (consistency per question x mode, averages per mode and per source
group: reviewed, stefan (Q18-Q19), draft, generated; for generated questions also per rule).
With another --question-file the set's name goes into the file name: results/run_generated_<time>.csv.
Above MAX_CALLS_WITHOUT_YES model calls (questions x modes x runs) a run needs --yes.
--log also appends each answer to the Google Sheet (or results/log.jsonl), with source "eval".
--no-repair turns off the one repair call for structured and annotated answers that are not usable JSON
(the "repaired" column shows where it was used, so first-try JSON validity can be reported either way).
"""

import argparse
import csv
import json
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from functools import partial
from itertools import combinations
from pathlib import Path
from statistics import mean

import core
import knowledge
import llm
import store

ROOT = Path(__file__).parent
QUESTIONS_PATH = ROOT / "test_questions.json"
GENERATED_PATH = ROOT / "test_questions_generated.json"
STEFAN_SOURCED = {"Q18", "Q19"}  # Stefan's own test questions (Oct 30), still marked draft
SOURCE_GROUPS = ["reviewed", "stefan", "draft", "generated"]
MAX_CALLS_WITHOUT_YES = 200
RESULTS_DIR = ROOT / "results"
RUNNERS = {"structured": core.run_structured, "annotated": core.run_annotated, "naive": core.run_naive}
CATEGORIES = ["named-instrument", "problem-only", "no-suitable-equipment", "accessory-trap",
              "misleading-keyword", "multi-step", "vague", "model-specific"]
SCORE_COLUMNS = ["expected_hits", "expected_total", "recall", "unacceptable_hits", "unacceptable_ids",
                 "false_primary_hits", "false_primary_ids", "objective_met_ok",
                 "unclassified_ids", "expected_only_mentioned", "na_hits", "na_total", "accessory_hits", "accessory_total",
                 "asked_clarifying", "clarifying_ok", "contacts_ok", "contacts_total",
                 "fit_expected_good", "fit_expected_total", "fit_bad_low", "fit_bad_total",
                 "dead_end_flagged", "dead_end_ok", "workflow_hits", "workflow_total"]
COLUMNS = ["question_id", "category", "status", "source_group", "rule", "run"] + SCORE_COLUMNS + store.ANSWER_COLUMNS
TRANSIENT = re.compile(r"\b(429|500|502|503|504)\b|rate.?limit|quota|unavailable|overloaded|timed? ?out",
                       re.IGNORECASE)


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def question_set(path: Path) -> str:
    """The set's name for file names and charts: "curated" for test_questions.json, else e.g. "generated"."""
    if path.resolve() == QUESTIONS_PATH.resolve():
        return "curated"
    return path.stem.removeprefix("test_questions_") or path.stem


def source_group(question: dict) -> str:
    """reviewed (by Stefan), stefan (his own test questions), draft, or generated."""
    status = question.get("status", "draft")
    if status == "draft" and question["id"] in STEFAN_SOURCED:
        return "stefan"
    return status


# --- scoring: pure functions of (question, result), so saved answers can be re-scored ---

def count_matches(text: str, patterns: list[str]) -> int:
    return sum(bool(re.search(p, text, re.IGNORECASE)) for p in patterns)


def accessory_text(result: dict, eq_id: str) -> str:
    """Where accessories for one instrument should be named: its accessories_to_confirm list in
    structured and annotated mode; the whole answer in naive mode (free text can't be split per instrument)."""
    if result["mode"] in core.JSON_MODES:
        return " ".join(acc for rec in result["recommendations"] if rec["id"] == eq_id
                        for acc in rec["accessories_to_confirm"])
    return result["raw"]


ASKS_FOR_MORE = re.compile(r"\?|more (information|details?) (is|are) needed|please (specify|clarify|provide)"
                           r"|could you (tell|clarify|specify|provide)", re.IGNORECASE)


def asked_clarifying(result: dict) -> bool:
    """Structured: the clarifying_question field. Naive: a heuristic (asks for more, recommends nothing),
    so check naive clarifying scores by hand."""
    if result["mode"] in core.JSON_MODES:
        return bool(result.get("clarifying_question"))
    return bool(ASKS_FOR_MORE.search(result["raw"])) and not result["instrument_ids"]


def contact_name(eq_id: str) -> str:
    """The contact's name without the affiliation: "Avery Bennett (SOD)" -> "Avery Bennett"."""
    return re.sub(r"\s*\(.*\)\s*$", "", core.equipment_by_id()[eq_id]["contact"])


def fit_scores(question: dict, result: dict) -> dict:
    """Does the fit level separate good picks from bad ones? (annotated mode only; None otherwise)
    Good: expected instruments rated high or medium. Bad: unacceptable or supplementary-only
    instruments rated low."""
    fits = {r["id"]: r["fit"] for r in result["recommendations"] if r.get("fit")}
    if result["mode"] != "annotated":
        return {"fit_expected_good": None, "fit_expected_total": None, "fit_bad_low": None, "fit_bad_total": None}
    good = [fits[i] for i in question["expected_ids"] if i in fits]
    bad_ids = set(question.get("unacceptable_ids", [])) | set(question.get("supplementary_only_ids", []))
    bad = [fits[i] for i in bad_ids if i in fits]
    return {"fit_expected_good": sum(f in ("high", "medium") for f in good), "fit_expected_total": len(good),
            "fit_bad_low": sum(f == "low" for f in bad), "fit_bad_total": len(bad)}


def workflow_scores(question: dict, result: dict) -> dict:
    """Dead ends and prerequisite instruments (optional test fields expect_dead_end and workflow_ids).

    A dead end counts as flagged when code marked one (annotated mode) or, for a question that expects
    one, when the answer names the missing next step (an expected_not_available pattern), so all modes
    can be compared. Avoiding a false dead end (expect_dead_end false) can only be checked in annotated
    mode: no expected instrument may be marked a dead end. Prerequisite instruments count as named when
    recommended, mentioned in the text, or listed in an annotated card's workflow.
    """
    expect = question.get("expect_dead_end")
    annotated = result["mode"] == "annotated"
    marked = [r["id"] for r in result["recommendations"] if r.get("dead_end")]
    names_missing = count_matches(result["raw"], question["expected_not_available"]) > 0
    if expect:
        flagged = bool(marked) or names_missing
    else:
        flagged = bool(marked) if annotated else None
    if expect is None:
        ok = None
    elif expect:
        ok = flagged
    else:
        ok = not set(marked) & set(question["expected_ids"]) if annotated else None
    wanted = set(question.get("workflow_ids", []))
    workflow_text = " ".join(line for r in result["recommendations"] for line in r.get("workflow", []))
    named = (set(result["instrument_ids"]) | set(core.instrument_ids_in_text(result["raw"]))
             | set(re.findall(r"\bEQ\d+\b", workflow_text)))
    return {"dead_end_flagged": flagged, "dead_end_ok": ok,
            "workflow_hits": len(wanted & named) if wanted else None,
            "workflow_total": len(wanted) if wanted else None}


def score(question: dict, result: dict) -> dict:
    """Scores for one answer. Answers with an error get no scores (they are counted separately).

    Recall counts only primary recommendations (naive: every recommended instrument). An instrument
    that is only fine as a supplementary one, or not at all, counts as a false primary.
    """
    if result["error"]:
        return {column: None for column in SCORE_COLUMNS}
    found, primary = set(result["instrument_ids"]), set(result["primary_ids"])
    expected, acceptable = set(question["expected_ids"]), set(question.get("acceptable_ids", []))
    unacceptable = set(question.get("unacceptable_ids", []))
    supplementary_only = set(question.get("supplementary_only_ids", []))
    false_primary = primary & (supplementary_only | unacceptable)
    # Only for questions no listed instrument can answer: did the answer say so (objective_met false)?
    no_answer_expected = not question["expected_ids"] and not question.get("expect_clarifying", False)
    accessories = {eq_id: patterns for eq_id, patterns in question.get("expected_accessories", {}).items()
                   if eq_id in found}
    asked = asked_clarifying(result)
    naive = result["mode"] == "naive"
    hits = len(primary & expected)
    return {
        "expected_hits": hits,
        "expected_total": len(expected),
        "recall": round(hits / len(expected), 3) if expected else None,
        "unacceptable_hits": len(found & unacceptable),
        "unacceptable_ids": " ".join(sorted(found & unacceptable)),
        "false_primary_hits": len(false_primary),
        "false_primary_ids": " ".join(sorted(false_primary)),
        "objective_met_ok": (result["objective_met"] is False) if no_answer_expected else None,
        "unclassified_ids": " ".join(sorted(found - expected - acceptable - unacceptable - supplementary_only)),
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
        **fit_scores(question, result),
        **workflow_scores(question, result),
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

SUMMARY_COLUMNS = ["scope", "question_id", "mode", "answers", "errors", "json_ok_rate", "repaired_rate", "mean_recall",
                   "unacceptable_rate", "false_primary_rate", "objective_met_ok_rate", "fit_expected_good_rate",
                   "fit_bad_low_rate", "dead_end_ok_rate", "workflow_rate", "na_rate", "accessory_rate", "clarifying_ok_rate", "contacts_rate",
                   "mean_seconds", "mean_output_tokens", "total_cost_usd", "stable_runs", "mean_jaccard",
                   "id_frequency"]


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


def _total(values) -> float | None:
    values = [v for v in (_num(v) for v in values) if v is not None]
    return round(sum(values), 6) if values else None


def _ratio(rows: list[dict], hits: str, total: str) -> float | None:
    totals = sum(_num(r.get(total)) or 0 for r in rows)
    return round(sum(_num(r.get(hits)) or 0 for r in rows) / totals, 3) if totals else None


def summarize_group(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    return {
        "answers": len(rows),
        "errors": len(rows) - len(scored),
        "json_ok_rate": _mean(r["json_ok"] for r in scored),
        "repaired_rate": _mean(r["repaired"] for r in scored if r["mode"] in core.JSON_MODES),
        "mean_recall": _mean(r["recall"] for r in scored),
        "unacceptable_rate": _mean(int((_num(r["unacceptable_hits"]) or 0) > 0) for r in scored),
        "false_primary_rate": _mean(int((_num(r.get("false_primary_hits")) or 0) > 0) for r in scored),
        "objective_met_ok_rate": _mean(r.get("objective_met_ok") for r in scored),
        # Annotated only: share of expected instruments rated high/medium, of bad picks rated low.
        "fit_expected_good_rate": _ratio(scored, "fit_expected_good", "fit_expected_total"),
        "fit_bad_low_rate": _ratio(scored, "fit_bad_low", "fit_bad_total"),
        "dead_end_ok_rate": _mean(r.get("dead_end_ok") for r in scored),
        "workflow_rate": _ratio(scored, "workflow_hits", "workflow_total"),
        "na_rate": _ratio(scored, "na_hits", "na_total"),
        "accessory_rate": _ratio(scored, "accessory_hits", "accessory_total"),
        "clarifying_ok_rate": _mean(r["clarifying_ok"] for r in scored),
        "contacts_rate": _ratio(scored, "contacts_ok", "contacts_total"),
        "mean_seconds": _mean(r["seconds"] for r in scored),
        "mean_output_tokens": _mean(r["output_tokens"] for r in scored),
        # All answers, failed ones too: a failed call can still cost money. None if no prices are set.
        "total_cost_usd": _total(r.get("cost_usd") for r in rows),
    }


def summarize(rows: list[dict]) -> list[dict]:
    """Per question x mode (with consistency), then per mode over each source group, each generation rule
    (scope "rule:<rule>") and all questions."""
    summary = []
    keys = list(dict.fromkeys((r["question_id"], r["mode"]) for r in rows))
    for question_id, mode in keys:
        group = [r for r in rows if r["question_id"] == question_id and r["mode"] == mode]
        id_sets = [frozenset(r["instrument_ids"].split()) for r in group if not r["error"]]
        summary.append({"scope": "question", "question_id": question_id, "mode": mode,
                        **summarize_group(group), **consistency(id_sets)})
    for mode in dict.fromkeys(r["mode"] for r in rows):
        mode_rows = [r for r in rows if r["mode"] == mode]
        groups = [(g, [r for r in mode_rows if r.get("source_group", r["status"]) == g]) for g in SOURCE_GROUPS]
        rules = dict.fromkeys(r["rule"] for r in mode_rows if r.get("rule"))
        groups += [(f"rule:{rule}", [r for r in mode_rows if r.get("rule") == rule]) for rule in rules]
        for scope, group in groups + [("all", mode_rows)]:
            if group:
                summary.append({"scope": scope, "question_id": "", "mode": mode, **summarize_group(group)})
    return summary


PRINTED = [("mean_recall", "recall"), ("unacceptable_rate", "unacc"), ("false_primary_rate", "falseP"),
           ("objective_met_ok_rate", "no-obj"), ("fit_expected_good_rate", "fit+"),
           ("fit_bad_low_rate", "fit-"), ("na_rate", "n/a"),
           ("accessory_rate", "acc"), ("clarifying_ok_rate", "clar"), ("contacts_rate", "contact"),
           ("mean_seconds", "sec")]


def print_summary(summary: list[dict]) -> None:
    """Per-mode averages as a table (the per-question rows are in the summary CSV)."""
    width = max([10] + [len(s["scope"]) + 1 for s in summary if s["scope"] != "question"])
    print("\n" + f"{'scope':<{width}}{'mode':<11}{'n':>4}{'err':>5}" + "".join(f"{label:>9}" for _, label in PRINTED))
    for s in summary:
        if s["scope"] == "question":
            continue
        cells = ["-" if s[key] is None else f"{s[key]:.2f}" for key, _ in PRINTED]
        cost = "" if s["total_cost_usd"] is None else f"   ${s['total_cost_usd']:.4f}"
        print(f"{s['scope']:<{width}}{s['mode']:<11}{s['answers']:>4}{s['errors']:>5}"
              + "".join(f"{c:>9}" for c in cells) + cost)


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
            "status": question.get("status", "draft"), "source_group": source_group(question),
            "rule": question.get("derived_from", {}).get("rule", ""), "run": run,
            **score(question, result), **answer}


def select_questions(questions: list[dict], ids: list[str] | None, category: str | None) -> list[dict]:
    return [q for q in questions if (not ids or q["id"] in ids) and (not category or q.get("category") == category)]


def sample_questions(questions: list[dict], n: int | None, seed: int = 0) -> list[dict]:
    """A fixed random subset of n questions (same seed -> same subset), kept in file order."""
    if not n or n >= len(questions):
        return questions
    chosen = {q["id"] for q in random.Random(seed).sample(questions, n)}
    return [q for q in questions if q["id"] in chosen]


def check_budget(n_questions: int, modes: list[str], runs: int, yes: bool) -> None:
    """Print how many model calls a run makes; above MAX_CALLS_WITHOUT_YES, stop unless --yes."""
    calls = n_questions * len(modes) * runs
    print(f"{n_questions} questions x {len(modes)} modes x {runs} runs = {calls} model calls "
          "(plus a repair call for any unusable JSON answer)")
    if calls > MAX_CALLS_WITHOUT_YES and not yes:
        raise SystemExit(f"More than {MAX_CALLS_WITHOUT_YES} calls: add --yes to run, or use --sample / --runs.")


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
                supplementary = f" +supplementary [{row['supplementary_ids']}]" if row["supplementary_ids"] else ""
                print(f"{q['id']:<4} {mode:<10} run {n}: [{row['primary_ids']}]{supplementary} "
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
            print(f"Skipping {old['question_id']}: no longer in the question file")
            continue
        if old["error"] and not old["raw_output"]:  # the model never answered; keep the error
            result = {**core.new_result(old["mode"], old["raw_output"]), "error": old["error"]}
        else:
            result = core.read_answer(old["mode"], old["raw_output"])
        # Keep the saved run's metadata (time, model, versions, tokens); refresh what reading the answer derives.
        fresh = store.answer_row(old["question"], result)
        answer = {column: old.get(column, "") for column in store.ANSWER_COLUMNS}
        answer.update({key: fresh[key] for key in ("json_ok", "schema_problems", "clarifying_question",
                                                   "instrument_ids", "ids_source", "mentioned_ids", "removed_ids",
                                                   "not_available", "error", "primary_ids", "supplementary_ids",
                                                   "objective_met", "fit_levels")})
        rows.append(eval_row(q, int(old["run"]), answer, result))
    return rows


def record_demo(questions: list[dict], modes: list[str], path: Path = core.DEMO_ANSWERS_PATH) -> None:
    """Save one live answer per question x mode as the app's backup. Answers already saved for other
    questions, or for questions that fail now, are kept."""
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"answers": []}
    by_key = {(a["mode"], core.normalize_question(a["question"])): a for a in saved["answers"]}
    for q in questions:
        for mode in modes:
            result = run_with_retry(mode, q["question"])
            if result["error"]:
                print(f"{q['id']:<4} {mode:<10} not saved: {result['error']}")
                continue
            by_key[(mode, core.normalize_question(q["question"]))] = {
                "question_id": q["id"], "mode": mode, "question": q["question"], "raw": result["raw"],
                "usage": result["usage"], "model": result["usage"].get("model_used", llm.model_name()),
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "prompt_version": core.prompt_version(mode), "dataset_version": core.dataset_version(),
            }
            print(f"{q['id']:<4} {mode:<10} saved [{' '.join(result['instrument_ids'])}]")
    path.write_text(json.dumps({"answers": list(by_key.values())}, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    core.load_demo_answers.cache_clear()
    print(f"\nSaved {len(by_key)} answers to {path}")


def readable(pattern: str) -> str:
    r"""A scoring regex in plain words: "\bGPC\b|size.exclusion" -> "GPC / size exclusion"."""
    text = re.sub(r"\\b|[()]", "", pattern).replace(".?", " ")
    return re.sub(r"(?<=\w)\.(?=\w)", " ", text).replace("|", " / ")


def derivation(derived: dict) -> str:
    """How a generated answer key was built, in plain words."""
    known = core.equipment_by_id()
    parts = [f"rule {derived['rule']}"]
    if derived.get("property"):
        parts.append(f"property: {knowledge.property_label(derived['property'])}")
    if derived.get("prep"):
        parts.append(f"first {knowledge.technique_name(derived['prep'])}, "
                     f"then {knowledge.technique_name(derived['goal_technique'])}")
    if derived.get("techniques"):
        parts.append("techniques: " + ", ".join(knowledge.technique_name(t) for t in derived["techniques"]))
    for key in ("instrument", "distractor"):
        if derived.get(key):
            parts.append(f"{key}: {known[derived[key]]['instrument']}")
    for key in ("condition", "reason"):
        if derived.get(key):
            parts.append(f"{key}: {derived[key]}")
    return "; ".join(parts)


def review_sheet(questions: list[dict]) -> str:
    """The expected answers in plain words (instrument names, not IDs), for the domain expert. Generated
    questions also show how their answer key was derived, and a line for the spot-check verdict."""
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
            f"- **Complementary only (wrong as the main answer):** {names(q.get('supplementary_only_ids', []))}",
            f"- **Unacceptable:** {names(q.get('unacceptable_ids', []))}",
            f"- **Should be flagged as not available:** {terms(q['expected_not_available'])}",
            f"- **Accessories to confirm:** {accessories}",
            f"- **Should ask a clarifying question:** {'yes' if q.get('expect_clarifying') else 'no'}",
            *([f"- **Dead end expected:** {'yes' if q['expect_dead_end'] else 'no'}"] if "expect_dead_end" in q else []),
            *([f"- **Prerequisite instruments to name:** {names(q['workflow_ids'])}"] if q.get("workflow_ids") else []),
            *([f"- **Derived from:** {derivation(q['derived_from'])}",
               "- **Answer key:** correct / wrong / unsure, because "] if q.get("derived_from") else []),
            f"- **Notes:** {q.get('notes', '')}",
            "- **Reviewer comments:** ", "",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-file", type=Path, default=QUESTIONS_PATH,
                        help="questions to use (default test_questions.json; e.g. test_questions_generated.json)")
    parser.add_argument("--sample", type=int, metavar="N", help="only a fixed random subset of N questions")
    parser.add_argument("--seed", type=int, default=0, help="seed for --sample (default 0)")
    parser.add_argument("--yes", action="store_true", help=f"allow more than {MAX_CALLS_WITHOUT_YES} model calls")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--modes", nargs="+", choices=list(RUNNERS), default=list(RUNNERS))
    parser.add_argument("--questions", nargs="+", metavar="ID", help="only these question IDs")
    parser.add_argument("--category", choices=CATEGORIES, help="only questions in this category")
    parser.add_argument("--log", action="store_true", help="also log answers to the sheet / log file")
    parser.add_argument("--rescore", type=Path, metavar="CSV", help="re-score a saved run, no model calls")
    parser.add_argument("--review-sheet", action="store_true", help="write the expected answers as Markdown")
    parser.add_argument("--record-demo", action="store_true", help="save answers as the app's demo backup")
    parser.add_argument("--no-repair", action="store_true", help="no repair call for unusable structured JSON")
    args = parser.parse_args()
    if args.no_repair:
        RUNNERS["structured"] = partial(core.run_structured, repair=False)
        RUNNERS["annotated"] = partial(core.run_annotated, repair=False)

    questions = select_questions(load_questions(args.question_file), args.questions, args.category)
    questions = sample_questions(questions, args.sample, args.seed)
    name = question_set(args.question_file)
    prefix = "run_" if name == "curated" else f"run_{name}_"
    RESULTS_DIR.mkdir(exist_ok=True)
    if args.review_sheet:
        path = RESULTS_DIR / ("expected_answers_review.md" if name == "curated" else f"{name}_review_sheet.md")
        path.write_text(review_sheet(questions), encoding="utf-8")
        print(f"Saved {path} ({len(questions)} questions)")
    elif args.record_demo:
        check_budget(len(questions), args.modes, 1, args.yes)
        record_demo(questions, args.modes)
    elif args.rescore:
        write_outputs(rescore(args.rescore, questions), args.rescore.with_name(args.rescore.stem + "_rescored.csv"))
    else:
        check_budget(len(questions), args.modes, args.runs, args.yes)
        rows = run(questions, args.modes, args.runs, args.log)
        write_outputs(rows, RESULTS_DIR / f"{prefix}{datetime.now():%Y%m%d_%H%M%S}.csv")


if __name__ == "__main__":
    main()
