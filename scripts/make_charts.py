"""Charts for the poster from an evaluation run.

Usage (from the project folder):
  python scripts/make_charts.py [--summary results/run_<time>_summary.csv]

Without --summary the newest results/run_*_summary.csv is used. The run CSV next to it
(results/run_<time>.csv) gives the per-answer numbers. Writes to results/charts/ at 300 dpi:
  modes.png         grouped bars per mode: expected instruments found, wrong main picks,
                    unavailable techniques flagged, accessories named
  time_cost.png     table: answers, errors, median response time, output tokens, cost
  modes.csv, time_cost.csv   the same numbers as tables (the charts' table view)
"""

import argparse
import csv
import sys
from pathlib import Path
from statistics import mean, median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MODES = {"structured": "Structured", "annotated": "Structured + annotations", "naive": "Naive (baseline)"}

# Reference palette (dataviz skill): categorical slots 1-3, validated for all pairs; light surface for print.
SERIES = {"structured": "#2a78d6", "annotated": "#eb6834", "naive": "#1baf7a"}
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.family": ["Segoe UI", "Arial", "DejaVu Sans"], "font.size": 11})


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(value) -> float | None:
    return None if value in (None, "") else float(value)


def is_true(value) -> bool:
    return str(value) == "True"


def mode_metrics(summary: list[dict], answers: list[dict]) -> dict[str, dict]:
    """Per mode, over all questions: the four bar heights (0-1) and the time/cost numbers."""
    metrics = {}
    for mode in MODES:
        s = next((r for r in summary if r["scope"] == "all" and r["mode"] == mode), None)
        rows = [r for r in answers if r["mode"] == mode]
        scored = [r for r in rows if not r["error"]]
        if s is None or not scored:
            continue
        wrong = [(num(r["false_primary_hits"]) or 0) + (num(r["unacceptable_hits"]) or 0) > 0 for r in scored]
        seconds = [num(r["seconds"]) for r in scored if num(r["seconds"]) is not None]
        tokens = [num(r["output_tokens"]) for r in scored if num(r["output_tokens"]) is not None]
        costs = [num(r["cost_usd"]) for r in rows if num(r["cost_usd"]) is not None]
        metrics[mode] = {
            "Expected instruments found": num(s["mean_recall"]),
            "Wrong main picks": mean(wrong),
            "Unavailable techniques flagged": num(s["na_rate"]),
            "Accessories to confirm named": num(s["accessory_rate"]),
            "answers": len(rows), "errors": len(rows) - len(scored),
            "median_seconds": median(seconds) if seconds else None,
            "median_output_tokens": median(tokens) if tokens else None,
            "total_cost_usd": sum(costs) if costs else None,
            "cost_per_answer_usd": sum(costs) / len(rows) if costs else None,
        }
    return metrics


BARS = [("Expected instruments found", "higher is better"), ("Wrong main picks", "lower is better"),
        ("Unavailable techniques flagged", "higher is better"), ("Accessories to confirm named", "higher is better")]


def bar_chart(metrics: dict[str, dict], n_questions: int, out: Path) -> None:
    modes = list(metrics)
    fig, ax = plt.subplots(figsize=(10, 5.2), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    group, gap = 0.78, 0.03  # each metric's band; the leftover is air between groups
    width = group / len(modes) - gap
    for i, mode in enumerate(modes):
        xs = [k - group / 2 + i * (width + gap) + width / 2 for k in range(len(BARS))]
        values = [metrics[mode][name] or 0 for name, _ in BARS]
        ax.bar(xs, values, width=width, color=SERIES[mode], label=MODES[mode], zorder=3)
        for x, v in zip(xs, values):
            ax.text(x, v + 0.015, f"{v:.0%}", ha="center", va="bottom", fontsize=9, color=INK_2)
    ax.set_xticks(range(len(BARS)), [f"{name}\n({hint})" for name, hint in BARS], color=INK_2)
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1], ["0%", "25%", "50%", "75%", "100%"], color=MUTED)
    ax.tick_params(length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.set_title(f"How each mode answers {n_questions} test questions", loc="left", color=INK,
                 fontsize=14, fontweight="bold", pad=34)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(modes), frameon=False,
              labelcolor=INK_2, handlelength=1.2, borderaxespad=0.2)
    fig.text(0.01, 0.01, "Averages over all runs. Expected answers are drafts except Q20-Q21 (reviewed by Stefan).",
             color=MUTED, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=300, facecolor=SURFACE)
    plt.close(fig)


def money(value) -> str:
    return "-" if value is None else f"${value:.4f}"


def table_chart(metrics: dict[str, dict], out: Path) -> list[list[str]]:
    header = ["Mode", "Answers", "Errors", "Median time", "Median tokens out", "Cost / answer", "Total cost"]
    rows = [[MODES[m], str(v["answers"]), str(v["errors"]),
             "-" if v["median_seconds"] is None else f"{v['median_seconds']:.1f} s",
             "-" if v["median_output_tokens"] is None else f"{v['median_output_tokens']:,.0f}",
             money(v["cost_per_answer_usd"]), money(v["total_cost_usd"])] for m, v in metrics.items()]
    fig, ax = plt.subplots(figsize=(10, 0.42 * (len(rows) + 1)), facecolor=SURFACE)
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=header, loc="center", cellLoc="right", colLoc="right",
                     colWidths=[0.25, 0.09, 0.07, 0.15, 0.19, 0.13, 0.12])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)
    for (r, c), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(SURFACE)
        cell.get_text().set_color(INK if r == 0 else INK_2)
        if r == 0:
            cell.get_text().set_fontweight("bold")
        if c == 0:
            cell.get_text().set_horizontalalignment("left")
            cell._loc = "left"
    fig.savefig(out, dpi=300, facecolor=SURFACE, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return [header] + rows


def write_rows(path: Path, rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)


def newest_summary() -> Path:
    found = sorted(RESULTS.glob("run_*_summary.csv"))
    if not found:
        sys.exit("No results/run_*_summary.csv yet: run python run_eval.py first.")
    return found[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--summary", type=Path, help="a run's _summary.csv (default: the newest)")
    parser.add_argument("--out", type=Path, default=RESULTS / "charts")
    args = parser.parse_args()
    summary_path = args.summary or newest_summary()
    run_path = summary_path.with_name(summary_path.name.replace("_summary", ""))
    summary, answers = read_csv(summary_path), read_csv(run_path)
    metrics = mode_metrics(summary, answers)
    args.out.mkdir(parents=True, exist_ok=True)
    n_questions = len({r["question_id"] for r in answers})
    bar_chart(metrics, n_questions, args.out / "modes.png")
    write_rows(args.out / "modes.csv", [["metric"] + [MODES[m] for m in metrics]]
               + [[name] + [f"{metrics[m][name]:.3f}" for m in metrics] for name, _ in BARS])
    write_rows(args.out / "time_cost.csv", table_chart(metrics, args.out / "time_cost.png"))
    print(f"From {summary_path.name}: saved modes.png, time_cost.png, modes.csv, time_cost.csv in {args.out}")


if __name__ == "__main__":
    main()
