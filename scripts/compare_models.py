"""Compare Gemini models on cost effectiveness: run the eval once per model, then chart score vs. cost.

Usage (from the project folder, LLM_PROVIDER=gemini in .env):
  python scripts/compare_models.py                       all models in MODELS, curated questions, 1 run
  python scripts/compare_models.py --models gemini-3.8-flash gemini-3.1-flash-lite --questions Q1 Q2
  python scripts/compare_models.py --question-file test_questions_generated.json     the 98 generated questions
  python scripts/compare_models.py --charts-only [--question-file ...]   only redraw the charts from saved runs
  python scripts/compare_models.py --all                 charts over curated + generated together (models_all_*)

Each model's answers go to results/models/<model>.csv (+ _summary.csv), scored like run_eval.py; for another
question file to results/models_<set>/ (e.g. models_generated), with charts prefixed models_<set>_.
A model that already has a CSV there is skipped (delete the file to re-run it), so an interrupted
comparison can be resumed. Prices are USD per million tokens (standard tier, prompts <= 200k,
output includes thinking), from the Gemini pricing page on 2026-11-08.
Charts go to results/charts/models_*.png and models_table.csv.
"""

import argparse
import os
import sys
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FixedLocator, FuncFormatter  # noqa: E402

import make_charts as mc  # noqa: E402
import run_eval  # noqa: E402

# model -> (input, output) USD per million tokens
MODELS = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-4-argon": (2.00, 10.00),
}
PRICE_NOTE = "Gemini API list prices of 2026-11-08; structured + annotated mode, 1 run."
MAX_ERROR_SHARE = 0.1  # a model run with more failed answers than this is not charted
LABEL_BELOW = {"gemini-3-flash-preview", "gemini-3.5-flash-lite"}
CHART_DIR = run_eval.RESULTS_DIR / "charts"


def use_model(model: str) -> None:
    """Point llm.py at this model and its prices; no fallback, so every answer comes from this model."""
    price_in, price_out = MODELS[model]
    os.environ.update({"LLM_PROVIDER": "gemini", "GEMINI_MODEL": model, "GEMINI_FALLBACK_MODEL": "",
                       "PRICE_IN_PER_M": str(price_in), "PRICE_OUT_PER_M": str(price_out)})


def out_dir(question_set: str, results_dir: Path = run_eval.RESULTS_DIR) -> Path:
    return results_dir / ("models" if question_set == "curated" else f"models_{question_set}")


def run_models(models: list[str], questions: list[dict], modes: list[str], runs: int, max_usd: float,
               out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for model in models:
        path = out / f"{model}.csv"
        if path.exists():
            print(f"\n== {model}: already done ({path.name}), skipped")
            continue
        if spent >= max_usd:
            print(f"\n== Stopping: ${spent:.2f} spent, limit --max-usd {max_usd}")
            break
        print(f"\n== {model}")
        use_model(model)
        rows = run_eval.run(questions, modes, runs)
        spent += sum(run_eval._num(r.get("cost_usd")) or 0 for r in rows)
        errors = [r["error"] for r in rows if r["error"]]
        if len(errors) > MAX_ERROR_SHARE * len(rows):
            # e.g. "403 Spend cap breached": keep the answers for a look, but out of the charts and resumable
            run_eval.write_outputs(rows, path.with_name(f"{model}_errors.csv"))
            raise SystemExit(f"{len(errors)}/{len(rows)} answers failed for {model}, stopping. "
                             f"First error: {errors[0][:200]}")
        run_eval.write_outputs(rows, path)
        print(f"Spent so far: ${spent:.3f}")


# --- charts ---

def model_metrics(paths: list[Path]) -> dict:
    rows = [r for path in paths for r in mc.read_csv(path)]
    scored = [r for r in rows if not r["error"]]
    scores = [s for s in (mc.row_score(r) for r in scored) if s is not None]
    wrong = [(mc.num(r["false_primary_hits"]) or 0) + (mc.num(r["unacceptable_hits"]) or 0) > 0 for r in scored]
    costs = [mc.num(r.get("cost_usd")) or 0 for r in rows]
    return {
        "model": paths[0].stem,
        "answers": len(rows),
        "errors": len(rows) - len(scored),
        "score": mean(scores) if scores else None,
        "wrong_rate": mean(wrong) if wrong else None,
        "cost_per_answer": sum(costs) / len(rows) if rows else None,
        "total_cost": sum(costs),
        "median_seconds": median(mc.num(r["seconds"]) or 0 for r in scored) if scored else None,
    }


def label(model: str) -> str:
    return model.removeprefix("gemini-")


def scatter(metrics: list[dict], x_key: str, x_label: str, title: str, out: Path, note: str, log_x: bool) -> None:
    fig, ax = plt.subplots(figsize=(8, 5.5), facecolor=mc.SURFACE)
    ax.set_facecolor(mc.SURFACE)
    for m in metrics:
        ax.scatter(m[x_key], m["score"] * 100, s=70, color=mc.SERIES["structured"], zorder=3)
        below = m["model"] in LABEL_BELOW  # keeps close points' labels apart
        ax.annotate(label(m["model"]), (m[x_key], m["score"] * 100), xytext=(7, -14 if below else 4),
                    textcoords="offset points", fontsize=10, color=mc.INK_2)
    if log_x:
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(FixedLocator([0.001, 0.002, 0.005, 0.01, 0.02, 0.05]))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
        ax.xaxis.set_minor_locator(FixedLocator([]))
    ax.set_xlabel(x_label, color=mc.INK_2)
    ax.set_ylabel("Main score (%), higher is better", color=mc.INK_2)
    ax.set_ylim(0, 105)
    ax.set_title(title, loc="left", color=mc.INK, fontsize=13, fontweight="bold")
    ax.grid(color=mc.GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(mc.AXIS)
    fig.text(0.01, 0.01, mc.SCORE_NOTE + " " + note + PRICE_NOTE, fontsize=8, color=mc.MUTED, wrap=True)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out, dpi=300)
    plt.close(fig)


def write_charts(question_set: str = "curated", results_dir: Path = run_eval.RESULTS_DIR,
                 chart_dir: Path = CHART_DIR, prefix: str | None = None, note: str = "") -> list[list]:
    """Charts for one question set, or for "all": curated + generated, only models run on both.
    results_dir holds the models*/ folders; prefix names the files (default models_all / models_<set>)."""
    dirs = ([out_dir("curated", results_dir), out_dir("generated", results_dir)] if question_set == "all"
            else [out_dir(question_set, results_dir)])
    prefix = prefix or ("models_all" if question_set == "all" else dirs[0].name)
    per_dir = [{p.stem: p for p in d.glob("*.csv") if not p.stem.endswith(("_summary", "_errors"))} for d in dirs]
    models = sorted(set.intersection(*(set(found) for found in per_dir)))
    metrics = [m for m in (model_metrics([found[mo] for found in per_dir]) for mo in models) if m["score"] is not None]
    if not metrics:
        raise SystemExit(f"No model runs in {', '.join(map(str, dirs))}")
    metrics.sort(key=lambda m: m["cost_per_answer"])
    n = sum(len({r["question_id"] for r in mc.read_csv(found[models[0]])}) for found in per_dir)
    note = f"{n} questions ({'curated + generated' if question_set == 'all' else question_set}). " + note
    chart_dir.mkdir(parents=True, exist_ok=True)
    scatter(metrics, "cost_per_answer", "Cost per answer (USD, log scale)",
            "Gemini models: answer quality vs. cost", chart_dir / f"{prefix}_cost_vs_score.png", note, log_x=True)
    scatter(metrics, "median_seconds", "Median response time (s)",
            "Gemini models: answer quality vs. speed", chart_dir / f"{prefix}_speed_vs_score.png", note, log_x=False)
    table = [["model", "answers", "errors", "main score", "wrong main picks", "cost per answer (USD)",
              "total cost (USD)", "median seconds", "score per cent"]]
    for m in metrics:
        per_cent = m["score"] / (m["cost_per_answer"] * 100) if m["cost_per_answer"] else ""
        table.append([m["model"], m["answers"], m["errors"], round(m["score"], 3), round(m["wrong_rate"], 3),
                      round(m["cost_per_answer"], 5), round(m["total_cost"], 4), m["median_seconds"],
                      round(per_cent, 2) if per_cent != "" else ""])
    mc.write_rows(chart_dir / f"{prefix}_table.csv", table)
    for row in table:
        print("  ".join(str(c).ljust(14) for c in row))
    print(f"\nSaved charts and table in {chart_dir}")
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", choices=list(MODELS), default=list(MODELS))
    parser.add_argument("--modes", nargs="+", choices=list(run_eval.RUNNERS), default=["structured", "annotated"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--question-file", type=Path, default=run_eval.QUESTIONS_PATH)
    parser.add_argument("--questions", nargs="+", metavar="ID", help="only these question IDs")
    parser.add_argument("--max-usd", type=float, default=8.0, help="start no new model after this spend")
    parser.add_argument("--charts-only", action="store_true")
    parser.add_argument("--all", action="store_true", help="charts over curated + generated runs together")
    args = parser.parse_args()
    if args.all:
        return write_charts("all")
    question_set = run_eval.question_set(args.question_file)
    if not args.charts_only:
        questions = run_eval.select_questions(run_eval.load_questions(args.question_file), args.questions, None)
        print(f"{len(args.models)} models x {len(questions)} questions x {len(args.modes)} modes x {args.runs} runs")
        run_models(args.models, questions, args.modes, args.runs, args.max_usd, out_dir(question_set))
    write_charts(question_set)


if __name__ == "__main__":
    main()
