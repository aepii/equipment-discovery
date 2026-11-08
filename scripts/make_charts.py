"""Charts for the poster from an evaluation run.

Usage (from the project folder):
  python scripts/make_charts.py [--set curated|generated] [--summary results/run_<time>_summary.csv]

Without --summary the newest summary of the set is used (curated: results/run_<time>_summary.csv,
generated: results/run_generated_<time>_summary.csv). The run CSV next to it gives the per-answer
numbers. Writes to results/charts/ at 300 dpi, each file prefixed with the set (curated_, generated_):
  modes.png         grouped bars per mode: expected instruments found, wrong main picks,
                    unavailable techniques flagged, accessories named
  time_cost.png     table: answers, errors, median response time, output tokens, cost
  categories.png    main score per question category and mode
  groups.png        main score per source group (reviewed, stefan, draft) - curated set
  rules.png         main score per generation rule - generated set
  *.csv             the same numbers as tables (the charts' table view)
The main score of an answer is its recall (expected instruments found); where nothing is expected it is
whether the answer said nothing fits, and for vague questions whether it asked to clarify.
"""

import argparse
import csv
import sys
import textwrap
from pathlib import Path
from statistics import mean, median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
MODES = {"structured": "Structured", "annotated": "Structured + annotations", "naive": "Naive (baseline)"}
SETS = {"curated": "run_[0-9]*_summary.csv", "generated": "run_generated_*_summary.csv"}
FOOTNOTES = {
    "curated": "Expected answers are drafts except Q20-Q21 (reviewed by Stefan).",
    "generated": "Expected answers come from the draft knowledge layer, which annotated mode also reads "
                 "(a built-in advantage).",
}

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


def bar_chart(metrics: dict[str, dict], n_questions: int, out: Path, question_set: str = "curated") -> None:
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
    ax.set_title(f"How each mode answers {n_questions} {question_set} test questions", loc="left", color=INK,
                 fontsize=14, fontweight="bold", pad=34)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(modes), frameon=False,
              labelcolor=INK_2, handlelength=1.2, borderaxespad=0.2)
    fig.text(0.01, 0.01, "Averages over all runs. " + FOOTNOTES[question_set], color=MUTED, fontsize=8.5)
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


def row_score(r: dict) -> float | None:
    """One answer's main score: recall; else (nothing expected) said nothing fits; else asked to clarify."""
    if r["error"]:
        return None
    if r.get("recall") not in (None, ""):
        return float(r["recall"])
    if r.get("objective_met_ok") not in (None, ""):
        return float(is_true(r["objective_met_ok"]))
    return float(is_true(r["clarifying_ok"])) if r.get("category") == "vague" else None


def breakdown(answers: list[dict], key: str) -> dict[str, dict[str, tuple[float, int]]]:
    """{group: {mode: (mean main score, answers scored)}} for a column such as category or rule."""
    table: dict[str, dict] = {}
    for group in sorted({r.get(key) for r in answers if r.get(key)}):
        for mode in MODES:
            scores = [s for r in answers if r.get(key) == group and r["mode"] == mode
                      for s in [row_score(r)] if s is not None]
            if scores:
                table.setdefault(group, {})[mode] = (mean(scores), len(scores))
    return table


SCORE_NOTE = ("Main score: expected instruments found; where nothing fits, said so; "
              "for vague questions, asked to clarify. ")


def breakdown_chart(table: dict, title: str, footnote: str, out: Path) -> list[list[str]]:
    """Horizontal grouped bars: one group per table row, one bar per mode. Returns the table as rows."""
    groups = list(table)
    modes = [m for m in MODES if any(m in v for v in table.values())]
    fig, ax = plt.subplots(figsize=(10, 1.4 + 0.22 * len(groups) * len(modes)), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    group, gap = 0.8, 0.02
    height = group / len(modes) - gap
    for i, mode in enumerate(modes):
        ys = [k - group / 2 + i * (height + gap) + height / 2 for k in range(len(groups))]
        values = [table[g].get(mode, (0, 0))[0] for g in groups]
        ax.barh(ys, values, height=height, color=SERIES[mode], label=MODES[mode], zorder=3)
        for y, v in zip(ys, values):
            ax.text(v + 0.01, y, f"{v:.0%}", va="center", fontsize=8, color=INK_2)
    ax.set_yticks(range(len(groups)), groups, color=INK_2)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.12)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1], ["0%", "25%", "50%", "75%", "100%"], color=MUTED)
    ax.tick_params(length=0)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(AXIS)
    ax.set_title(title, loc="left", color=INK, fontsize=13, fontweight="bold", pad=30)
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=len(modes), frameon=False,
              labelcolor=INK_2, handlelength=1.2, borderaxespad=0.2)
    fig.text(0.01, 0.005, textwrap.fill(footnote, 150), color=MUTED, fontsize=7.5)
    fig.tight_layout(rect=(0, 0.45 / fig.get_figheight(), 1, 1))  # room for a two-line footnote
    fig.savefig(out, dpi=300, facecolor=SURFACE)
    plt.close(fig)
    header = ["group"] + [f"{MODES[m]} {x}" for m in modes for x in ("score", "answers")]
    return [header] + [[g] + [x for m in modes
                              for x in ((f"{table[g][m][0]:.3f}", str(table[g][m][1])) if m in table[g] else ("", ""))]
                       for g in groups]


def write_charts(summary: list[dict], answers: list[dict], question_set: str, out: Path) -> list[str]:
    """All charts and tables of one run, prefixed with the question set. Returns the names saved."""
    metrics = mode_metrics(summary, answers)
    out.mkdir(parents=True, exist_ok=True)

    def path(stem: str) -> Path:
        return out / f"{question_set}_{stem}"

    n_questions = len({r["question_id"] for r in answers})
    bar_chart(metrics, n_questions, path("modes.png"), question_set)
    write_rows(path("modes.csv"), [["metric"] + [MODES[m] for m in metrics]]
               + [[metric] + ["" if metrics[m][metric] is None else f"{metrics[m][metric]:.3f}" for m in metrics]
                  for metric, _ in BARS])
    write_rows(path("time_cost.csv"), table_chart(metrics, path("time_cost.png")))
    saved = ["modes", "time_cost"]
    extra = [("categories", "category", "question category")]
    if question_set == "curated":
        extra.append(("groups", "source_group", "source group"))
    else:
        extra.append(("rules", "rule", "generation rule"))
    for stem, column, label in extra:
        table = breakdown(answers, column)
        if table:
            rows = breakdown_chart(table, f"Main score per {label} ({question_set} questions)",
                                   SCORE_NOTE + FOOTNOTES[question_set], path(f"{stem}.png"))
            write_rows(path(f"{stem}.csv"), rows)
            saved.append(stem)
    return [f"{question_set}_{stem}" for stem in saved]


def newest_summary(question_set: str = "curated") -> Path:
    found = sorted(RESULTS.glob(SETS[question_set]))
    if not found:
        sys.exit(f"No results/{SETS[question_set]} yet: run python run_eval.py first.")
    return found[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=list(SETS), default="curated", dest="question_set",
                        help="which question set's run to chart; also the file prefix (default curated)")
    parser.add_argument("--summary", type=Path, help="a run's _summary.csv (default: the newest of the set)")
    parser.add_argument("--out", type=Path, default=RESULTS / "charts")
    args = parser.parse_args()
    summary_path = args.summary or newest_summary(args.question_set)
    run_path = summary_path.with_name(summary_path.name.replace("_summary", ""))
    saved = write_charts(read_csv(summary_path), read_csv(run_path), args.question_set, args.out)
    print(f"From {summary_path.name}: saved {', '.join(saved)} (.png and .csv) in {args.out}")


if __name__ == "__main__":
    main()
