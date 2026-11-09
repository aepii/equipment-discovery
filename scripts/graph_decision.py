"""The decision rule in PLAN.md for the knowledge fixes (Task 2) and graph matching (Task 1), on run CSVs.

Usage (from the project folder; each CSV a run or a rescore, annotated rows are used):
  python scripts/graph_decision.py --poster P.csv --task1 P_g1.csv --task2 N.csv --both N_g1.csv [--set curated]

Prints Markdown: a table of the metrics per version, the decision rule item by item for each change
(pass/fail), and the questions that gained or lost. No model calls.

Metrics, per mode "annotated":
  found (main + supporting)  expected instruments recommended in any role (recall_any)
  recall (main)              expected instruments recommended as primary
  wrong main picks           answers with a false primary or any unacceptable instrument (as on the poster)
  accessories / n/a / no-obj accessory_rate, na_rate, objective_met_ok_rate
  instruments per answer     n_instruments (any role)
"""

import argparse
import csv
from pathlib import Path
from statistics import mean

REVIEWED = ("Q20", "Q21")
ONE_QUESTION = 1.0  # item 3: a rule metric may drop by at most one question's worth


def num(value) -> float | None:
    return None if value in (None, "") else float(value)


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if r["mode"] == "annotated" and not r["error"]]


def wrong(r: dict) -> bool:
    return (num(r["false_primary_hits"]) or 0) + (num(r["unacceptable_hits"]) or 0) > 0


def ratio(rows: list[dict], hits: str, total: str) -> float | None:
    t = sum(num(r[total]) or 0 for r in rows)
    return sum(num(r[hits]) or 0 for r in rows) / t if t else None


def avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def metrics(rows: list[dict]) -> dict:
    return {
        "found (main + supporting)": avg(num(r["recall_any"]) for r in rows),
        "recall (main)": avg(num(r["recall"]) for r in rows),
        "wrong main picks": avg(float(wrong(r)) for r in rows),
        "accessories named": ratio(rows, "accessory_hits", "accessory_total"),
        "unavailable technique flagged": ratio(rows, "na_hits", "na_total"),
        "said so when nothing fits": avg(None if r["objective_met_ok"] == "" else float(r["objective_met_ok"] == "True")
                                         for r in rows),
        "instruments per answer": avg(num(r["n_instruments"]) for r in rows),
        "graph-added per answer": avg(num(r.get("graph_added")) for r in rows),
        "answers": len(rows),
        "cost (USD)": sum(num(r["cost_usd"]) or 0 for r in rows),
    }


# --- per question (mean over runs), for item 3 and the gains/losses list ---

def per_question(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for qid in dict.fromkeys(r["question_id"] for r in rows):
        group = [r for r in rows if r["question_id"] == qid]
        out[qid] = {"found": avg(num(r["recall_any"]) for r in group),
                    "wrong": avg(float(wrong(r)) for r in group),
                    "accessories": ratio(group, "accessory_hits", "accessory_total"),
                    "n/a": ratio(group, "na_hits", "na_total"),
                    "no-obj": avg(None if r["objective_met_ok"] == "" else float(r["objective_met_ok"] == "True")
                                  for r in group),
                    "instruments": avg(num(r["n_instruments"]) for r in group),
                    "ids": sorted({r["instrument_ids"] for r in group})}
    return out


def question_drop(old: dict, new: dict, key: str) -> float:
    """How many questions' worth a per-question score dropped in total (gains elsewhere do not offset)."""
    return sum(max(0.0, (old[q][key] or 0) - (new[q][key] or 0)) for q in old
               if q in new and old[q][key] is not None and new[q][key] is not None)


def reviewed_worse(old_rows: list[dict], new_rows: list[dict]) -> list[str]:
    """Item 4: Q20 and Q21 not worse in any run (runs paired by number)."""
    problems = []
    for qid in REVIEWED:
        for old in [r for r in old_rows if r["question_id"] == qid]:
            new = next((r for r in new_rows if r["question_id"] == qid and r["run"] == old["run"]), None)
            if new is None:
                problems.append(f"{qid} run {old['run']}: missing")
                continue
            checks = [("found", num(new["recall_any"] or 0) < num(old["recall_any"] or 0) if old["recall_any"] else False),
                      ("wrong pick", wrong(new) and not wrong(old)),
                      ("n/a", (ratio([new], "na_hits", "na_total") or 0) < (ratio([old], "na_hits", "na_total") or 0)),
                      ("accessories", (ratio([new], "accessory_hits", "accessory_total") or 0)
                       < (ratio([old], "accessory_hits", "accessory_total") or 0)),
                      ("no-obj", old["objective_met_ok"] == "True" and new["objective_met_ok"] != "True")]
            problems += [f"{qid} run {old['run']}: {name} worse" for name, worse in checks if worse]
    return problems


def decide(old_rows: list[dict], new_rows: list[dict], curated: bool) -> list[tuple[str, bool, str]]:
    old, new = metrics(old_rows), metrics(new_rows)
    po, pn = per_question(old_rows), per_question(new_rows)
    items = [
        ("1. found (main + supporting) does not go down",
         round(new["found (main + supporting)"], 3) >= round(old["found (main + supporting)"], 3),
         f"{old['found (main + supporting)']:.3f} -> {new['found (main + supporting)']:.3f}"),
        ("2. wrong main picks do not go up",
         round(new["wrong main picks"], 3) <= round(old["wrong main picks"], 3),
         f"{old['wrong main picks']:.3f} -> {new['wrong main picks']:.3f}"),
    ]
    for label, key in (("accessories named", "accessories"), ("unavailable technique flagged", "n/a"),
                       ("said so when nothing fits", "no-obj")):
        drop = question_drop(po, pn, key)
        items.append((f"3. {label}: drop <= one question", drop <= ONE_QUESTION + 1e-9,
                      f"{drop:.2f} questions' worth lost"))
    if curated:
        worse = reviewed_worse(old_rows, new_rows)
        items.append(("4. Q20 and Q21 not worse in any run", not worse, "; ".join(worse) or "no run worse"))
    rise = new["instruments per answer"] - old["instruments per answer"]
    items.append(("5. instruments per answer rises by at most 1", rise <= 1 + 1e-9,
                  f"{old['instruments per answer']:.2f} -> {new['instruments per answer']:.2f} ({rise:+.2f})"))
    return items


def fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def report(versions: dict[str, list[dict]], curated: bool) -> str:
    table = {name: metrics(rows) for name, rows in versions.items()}
    names = list(versions)
    lines = ["| Metric (annotated mode) | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key in next(iter(table.values())):
        lines.append(f"| {key} | " + " | ".join(fmt(table[n][key]) for n in names) + " |")
    poster = versions[names[0]]
    for change, name in (("Task 2 (knowledge fixes)", names[2]), ("Task 1 (graph matching)", names[1]),
                         ("Both", names[3])):
        lines += ["", f"**{change}: {names[0]} vs. {name}**", "", "| Item | Result | Detail |", "|---|---|---|"]
        items = decide(poster, versions[name], curated)
        lines += [f"| {label} | {'pass' if ok else '**fail**'} | {detail} |" for label, ok, detail in items]
        lines.append(f"| **Overall** | {'**pass**' if all(ok for _, ok, _ in items) else '**fail**'} | |")
    lines += ["", "**Per-question changes** (mean over runs; only questions that changed)", "",
              "| Question | Version | found | wrong | accessories | n/a | no-obj | instruments |", "|---|---|---|---|---|---|---|---|"]
    base = per_question(poster)
    for name in names[1:]:
        other = per_question(versions[name])
        for qid, b in base.items():
            o = other.get(qid)
            if not o:
                continue
            keys = ("found", "wrong", "accessories", "n/a", "no-obj")
            if any(b[k] != o[k] for k in keys) or abs((o["instruments"] or 0) - (b["instruments"] or 0)) >= 1:
                cells = [f"{fmt(b[k])} -> {fmt(o[k])}" if b[k] != o[k] else fmt(b[k]) for k in keys + ("instruments",)]
                lines.append(f"| {qid} | {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("poster", "task1", "task2", "both"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--set", choices=["curated", "generated"], default="curated")
    args = parser.parse_args()
    versions = {"poster": load(args.poster), "Task 1 only": load(args.task1), "Task 2 only": load(args.task2),
                "both": load(args.both)}
    print(report(versions, curated=args.set == "curated"))


if __name__ == "__main__":
    main()
