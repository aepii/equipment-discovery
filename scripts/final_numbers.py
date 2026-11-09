"""Final poster numbers: rescore the saved answers with the final code and keys, no model calls.

Usage (from the project folder):
  python scripts/final_numbers.py

Writes results/final/:
  curated.csv, generated.csv (+ _summary.csv)   naive and structured answers from the poster runs, full-system
                                                (annotated) answers from the runs with the knowledge fixes
  models/, models_generated/                    the saved model-comparison runs, rescored
  charts/                                       modes.png (curated), the per-set charts, models_cost_vs_score.png
  FINAL_NUMBERS.md                              the tables for the poster
Definitions as in make_charts.py and graph_decision.py.
"""

import csv
import json
import shutil
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import compare_models as cm  # noqa: E402
import make_charts as mc  # noqa: E402
import run_eval  # noqa: E402

RESULTS = run_eval.RESULTS_DIR
FINAL = RESULTS / "final"
CHARTS = FINAL / "charts"
# set -> (question file, run with the naive + structured answers, run with the full-system answers)
RUNS = {
    "curated": (run_eval.QUESTIONS_PATH, "run_20261107_144209.csv", "run_20261109_090405.csv"),
    "generated": (run_eval.GENERATED_PATH, "run_generated_20261108_100132.csv", "run_generated_20261109_092656.csv"),
}
MODES = {"naive": "Naive (baseline)", "structured": "Structured", "annotated": "Structured + annotations (full system)"}
# Generated keys flagged in results/FINDINGS.md (Nov 8) and what the knowledge fixes did to them.
FLAGGED = {
    "G002": "remains: key lists every capable microscope",
    "G012": "remains: key lists every capable microscope",
    "G030": "remains: key lists every capable microscope",
    "G083": "remains: key lists every capable microscope",
    "G003": "fixed: opaque titanium disc, inverted stands now only acceptable",
    "G019": "fixed: stereomicroscope expected for 50 um - 1 mm beads, ESEM acceptable",
    "G084": "fixed: stereomicroscope expected for capsules, ESEM acceptable",
    "G077": "remains: 5-200 um powder, ESEM expected and stereomicroscope only acceptable (unchanged)",
    "G021": "remains: ESEM expected next to TEM for nanoparticles (left for Stefan)",
    "G078": "remains: ESEM expected next to TEM for nanoparticles (left for Stefan)",
    "G059": "fixed: DSC on a small piece now acceptable",
    "G060": "fixed: DSC on a small piece now acceptable",
    "G062": "fixed: TEM on a drop of suspension now acceptable",
    "G063": "fixed by removal: no listed technique measures heat of cure non-destructively once FTIR is corrected",
    "G076": "remains: TGA as a supplementary check counts as an unacceptable pick",
}
MODEL_RERUNS = RESULTS / "final_runs"  # annotated mode per model with the final version (compare_models --results-dir)
POSTER_CURATED =RESULTS / "graph_matching" / "curated_poster_g0.csv"  # poster full-system answers, final scoring


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(value) -> float | None:
    return None if value in (None, "") else float(value)


def as_rows(rows: list[dict]) -> list[dict]:
    """Rows as they read back from a CSV (strings), so in-memory and saved rows score the same."""
    return [{k: "" if v is None else str(v) for k, v in r.items()} for r in rows]


# --- step 2: rescore ---

def rescore_set(name: str) -> list[dict]:
    question_file, poster_run, full_run = RUNS[name]
    questions = run_eval.load_questions(question_file)
    rows = [r for r in run_eval.rescore(RESULTS / poster_run, questions) if r["mode"] in ("naive", "structured")]
    rows += [r for r in run_eval.rescore(RESULTS / full_run, questions) if r["mode"] == "annotated"]
    order = list(MODES)
    rows.sort(key=lambda r: (order.index(r["mode"]), int(r["run"])))
    run_eval.write_outputs(rows, FINAL / f"{name}.csv")
    return as_rows(rows)


def rescore_models() -> None:
    """Per model: structured answers from the Nov 8 comparison (that prompt is unchanged), annotated answers
    from the re-run with the final version (MODEL_RERUNS); both rescored."""
    for name, question_file in (("curated", run_eval.QUESTIONS_PATH), ("generated", run_eval.GENERATED_PATH)):
        questions = run_eval.load_questions(question_file)
        source, rerun, target = cm.out_dir(name), cm.out_dir(name, MODEL_RERUNS), cm.out_dir(name, FINAL)
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted(source.glob("*.csv")):
            if path.stem.endswith(("_summary", "_errors")):
                continue
            if not (rerun / path.name).exists():
                raise SystemExit(f"No annotated re-run for {path.stem} in {rerun}")
            rows = [r for r in run_eval.rescore(path, questions) if r["mode"] == "structured"]
            rows += [r for r in run_eval.rescore(rerun / path.name, questions) if r["mode"] == "annotated"]
            run_eval.write_outputs(rows, target / path.name)


# --- step 3: numbers ---

def wrong(r: dict) -> bool:
    return (num(r["false_primary_hits"]) or 0) + (num(r["unacceptable_hits"]) or 0) > 0


def ratio(rows: list[dict], hits: str, total: str) -> float | None:
    t = sum(num(r[total]) or 0 for r in rows)
    return sum(num(r[hits]) or 0 for r in rows) / t if t else None


def avg(values) -> float | None:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def mode_numbers(rows: list[dict], questions: list[dict]) -> dict:
    scored = [r for r in rows if not r["error"]]
    vague = [q["id"] for q in questions if q.get("expect_clarifying")]
    asked = [qid for qid in vague
             if (group := [r for r in scored if r["question_id"] == qid])
             and all(r["asked_clarifying"] == "True" for r in group)]
    vague_answers = [r for r in scored if r["question_id"] in vague]
    low, bad = (sum(num(r[c]) or 0 for r in scored) for c in ("fit_bad_low", "fit_bad_total"))
    return {
        "found_main": avg(num(r["recall"]) for r in scored),
        "found_any": avg(num(r["recall_any"]) for r in scored),
        "wrong": avg(float(wrong(r)) for r in scored),
        "unacceptable": avg(float((num(r["unacceptable_hits"]) or 0) > 0) for r in scored),
        "accessories": ratio(scored, "accessory_hits", "accessory_total"),
        "na": ratio(scored, "na_hits", "na_total"),
        "no_fit": avg(None if r["objective_met_ok"] == "" else float(r["objective_met_ok"] == "True") for r in scored),
        "clarifying": (f"{len(asked)} of {len(vague)} "
                       f"({sum(r['asked_clarifying'] == 'True' for r in vague_answers)} of {len(vague_answers)} answers)"),
        "fit_low": f"{low:.0f} of {bad:.0f}" if bad else "-",
        "answers": len(rows), "errors": len(rows) - len(scored),
        "cost": sum(num(r["cost_usd"]) or 0 for r in rows),
    }


LINES = [("Expected instruments found, main picks", "found_main", "pct"),
         ("Expected instruments found, main + supporting", "found_any", "pct"),
         ("Wrong main picks (false primary or any unacceptable; lower is better)", "wrong", "pct"),
         ("Answers with an unacceptable pick (lower is better)", "unacceptable", "pct"),
         ("Accessories to confirm named", "accessories", "pct"),
         ("Unavailable technique flagged", "na", "pct"),
         ("Said so when nothing fits", "no_fit", "pct"),
         ("Vague questions: asked to clarify in every run", "clarifying", "text"),
         ("Wrong or complementary picks rated low fit (full system only)", "fit_low", "text"),
         ("Answers", "answers", "text"), ("Errors", "errors", "text"), ("Cost (USD)", "cost", "usd")]


def cell(value, kind: str) -> str:
    if value is None:
        return "-"
    if kind == "pct":
        return f"{value:.0%}" if value in (0, 1) else f"{value:.1%}"
    return f"${value:.2f}" if kind == "usd" else str(value)


def table(by_mode: dict[str, dict], modes: list[str], labels: list[str]) -> list[str]:
    lines = ["| Metric | " + " | ".join(labels) + " |", "|---|" + "---|" * len(modes)]
    for label, key, kind in LINES:
        values = [by_mode[m][key] if (key != "fit_low" or m == "annotated") else "-" for m in modes]
        lines.append(f"| {label} | " + " | ".join(cell(v, kind) for v in values) + " |")
    return lines


def set_numbers(rows: list[dict], questions: list[dict]) -> dict[str, dict]:
    return {m: mode_numbers([r for r in rows if r["mode"] == m], questions) for m in MODES}


def faulty_keys(rows: list[dict]) -> list[str]:
    in_set = {r["question_id"] for r in rows}
    lines = ["| Question | Status |", "|---|---|"]
    lines += [f"| {qid} | {status}{'' if qid in in_set else ' (not in the set any more)'} |"
              for qid, status in FLAGGED.items()]
    remaining = {qid for qid, s in FLAGGED.items() if s.startswith("remains")}
    fixed = [qid for qid in FLAGGED if qid not in remaining]
    lines += ["", f"Fixed: {len(fixed)} ({', '.join(fixed)}). Remaining: {len(remaining)} "
                  f"({', '.join(q for q in FLAGGED if q in remaining)}).", "",
              "| Expected instruments found, main picks | " + " | ".join(MODES.values()) + " |",
              "|---|---|---|---|"]
    for label, keep in (("all generated questions", lambda q: True),
                        (f"without the {len(remaining)} remaining faulty keys", lambda q: q not in remaining)):
        values = [avg(num(r["recall"]) for r in rows if r["mode"] == m and not r["error"] and keep(r["question_id"]))
                  for m in MODES]
        lines.append(f"| {label} | " + " | ".join(cell(v, "pct") for v in values) + " |")
    return lines


def before_after(final_rows: list[dict], questions: list[dict]) -> list[str]:
    poster = [r for r in read(POSTER_CURATED) if r["mode"] == "annotated"]
    new = [r for r in final_rows if r["mode"] == "annotated"]
    by = {"poster": mode_numbers(poster, questions), "final": mode_numbers(new, questions)}
    lines = ["| Metric (full system, curated) | Poster version | Final |", "|---|---|---|"]
    for label, key, kind in LINES:
        lines.append(f"| {label} | {cell(by['poster'][key], kind)} | {cell(by['final'][key], kind)} |")
    lines.append(f"| Instruments per answer | {avg(num(r['n_instruments']) for r in poster):.2f} "
                 f"| {avg(num(r['n_instruments']) for r in new):.2f} |")
    return lines


def q20(rows: list[dict]) -> list[str]:
    answers = [r for r in rows if r["question_id"] == "Q20" and r["mode"] == "annotated" and not r["error"]]
    lines = ["| Run | Says nothing fits | AFM not available | ESEM | Fit |", "|---|---|---|---|---|"]
    for r in answers:
        fits = dict(item.split(":") for item in r["fit_levels"].split())
        esem = ("complementary" if "EQ10" in r["supplementary_ids"].split()
                else "main pick" if "EQ10" in r["primary_ids"].split() else "not shown")
        lines.append(f"| {r['run']} | {'yes' if r['objective_met'] == 'False' else 'no'} "
                     f"| {'yes' if 'AFM' in r['not_available'] or 'atomic force' in r['not_available'].lower() else 'no'} "
                     f"| {esem} | {fits.get('EQ10', '-')} |")
    summary = json.loads(answers[0]["raw_output"])["summary"].split(". ")[0].rstrip(".") + "."
    return lines + ["", f"Run {answers[0]['run']}, summary: \"{summary}\""]


def model_table() -> list[str]:
    note = "Final version: annotated answers re-run with the knowledge fixes. "
    table = cm.write_charts("all", FINAL, CHARTS, prefix="models", note=note)
    header, rows = table[0], table[1:]
    keep = [0, 1, 2, 3, 4, 5, 6]
    lines = ["| " + " | ".join(header[i] for i in keep) + " |", "|" + "---|" * len(keep)]
    for row in rows:
        lines.append("| " + " | ".join(f"{row[i]:.1%}" if i in (3, 4) else str(row[i]) for i in keep) + " |")
    return lines


def main() -> None:
    FINAL.mkdir(parents=True, exist_ok=True)
    rows, questions = {}, {}
    for name, (question_file, _, _) in RUNS.items():
        questions[name] = run_eval.load_questions(question_file)
        rows[name] = rescore_set(name)
    rescore_models()

    for name in RUNS:  # charts of each set, from the final CSVs
        mc.write_charts(mc.read_csv(FINAL / f"{name}_summary.csv"), rows[name], name, CHARTS)
    shutil.copyfile(CHARTS / "curated_modes.png", CHARTS / "modes.png")

    labels = list(MODES.values())
    md = ["# Final numbers for the poster", "",
          "System with the knowledge fixes, without graph matching (`results/FINDINGS_graph_matching.md`). "
          "Produced by `python scripts/final_numbers.py` from saved answers (no model calls), model "
          "`gemini-3.8-flash`. Naive and structured answers come from the poster runs (their prompts do not "
          "include the knowledge files); full-system answers come from the runs with the knowledge fixes. "
          "Every answer is scored with the final code and keys.", ""]
    for name, (_, poster_run, full_run) in RUNS.items():
        n_q = len({r["question_id"] for r in rows[name]})
        n_runs = len({r["run"] for r in rows[name]})
        md += [f"## {name.capitalize()} set ({n_q} questions, {n_runs} run{'s' if n_runs > 1 else ''})", "",
               f"Answers: `{poster_run}` (naive, structured) and `{full_run}` (full system); "
               f"rows in `results/final/{name}.csv`.", ""]
        md += table(set_numbers(rows[name], questions[name]), list(MODES), labels) + [""]
    md += ["Wrong or complementary picks rated low fit: of the instruments the key calls unacceptable or "
           "supplementary only that the full system showed, how many it rated low. Vague questions: asked to "
           "clarify in every run of the question (in brackets: per answer).", "",
           "## Remaining faulty generated keys", "",
           "The 15 keys flagged in `results/FINDINGS.md`, against the final keys:", ""]
    md += faulty_keys(rows["generated"]) + [""]
    md += ["## Knowledge fixes, before / after (full system, curated)", "",
           "Poster version: the full-system answers of `run_20261107_144209` "
           "(`results/graph_matching/curated_poster_g0.csv`, the poster column of "
           "`results/graph_matching/decision_curated.md`). Final: `run_20261109_090405`. Both scored with the "
           "final code and keys.", ""]
    md += before_after(rows["curated"], questions["curated"]) + [""]
    md += ["## Graph matching (tested, not kept)", "",
           "- Expected instruments found, main + supporting: 0.94 -> 0.99 (poster answers, curated).",
           "- Wrong main picks: 0% -> 3%. Cause: graph matching adds upright microscopes for living cells in "
           "well plates (Q19), which cannot image a well plate. See `results/FINDINGS_graph_matching.md`.", "",
           "## Q20 roughness example (final full-system answers)", ""]
    md += q20(rows["curated"]) + [""]
    md += ["## Model comparison (23 curated + 98 generated questions, structured + annotated, 1 run)", "",
           "Matches the app today. Annotated answers were re-run with the final version for every model "
           "(`results/final_runs/`); structured answers come from the Nov 8 comparison (`results/models*/`), "
           "whose structured prompt is unchanged (`ca824b2c`). All are scored with the final code and keys. "
           "Main score as in `make_charts.py`. Chart: `results/final/charts/models_cost_vs_score.png`.", ""]
    md += model_table() + [""]
    (FINAL / "FINAL_NUMBERS.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nSaved {FINAL / 'FINAL_NUMBERS.md'}")


if __name__ == "__main__":
    main()
