# Final numbers for the poster

System with the knowledge fixes, without graph matching (`results/FINDINGS_graph_matching.md`). Produced by `python scripts/final_numbers.py` from saved answers (no model calls), model `gemini-3.8-flash`. Naive and structured answers come from the poster runs (their prompts do not include the knowledge files); full-system answers come from the runs with the knowledge fixes. Every answer is scored with the final code and keys.

## Curated set (23 questions, 3 runs)

Answers: `run_20261107_144209.csv` (naive, structured) and `run_20261109_090405.csv` (full system); rows in `results/final/curated.csv`.

| Metric | Naive (baseline) | Structured | Structured + annotations (full system) |
|---|---|---|---|
| Expected instruments found, main picks | 87.5% | 81.2% | 85.1% |
| Expected instruments found, main + supporting | 87.5% | 96.9% | 94.1% |
| Wrong main picks (false primary or any unacceptable; lower is better) | 4.3% | 5.8% | 0% |
| Answers with an unacceptable pick (lower is better) | 0% | 1.4% | 0% |
| Accessories to confirm named | 35.7% | 94.0% | 100% |
| Unavailable technique flagged | 59.3% | 88.9% | 88.9% |
| Said so when nothing fits | 53.3% | 100% | 100% |
| Vague questions: asked to clarify in every run | 1 of 2 (3 of 6 answers) | 2 of 2 (6 of 6 answers) | 2 of 2 (6 of 6 answers) |
| Wrong or complementary picks rated low fit (full system only) | - | - | 10 of 10 |
| Answers | 69 | 69 | 69 |
| Errors | 0 | 0 | 0 |
| Cost (USD) | $0.58 | $0.42 | $0.91 |

## Generated set (98 questions, 1 run)

Answers: `run_generated_20261108_100132.csv` (naive, structured) and `run_generated_20261109_092656.csv` (full system); rows in `results/final/generated.csv`.

| Metric | Naive (baseline) | Structured | Structured + annotations (full system) |
|---|---|---|---|
| Expected instruments found, main picks | 90.3% | 84.8% | 89.8% |
| Expected instruments found, main + supporting | 90.3% | 93.1% | 93.4% |
| Wrong main picks (false primary or any unacceptable; lower is better) | 4.1% | 2.0% | 1.0% |
| Answers with an unacceptable pick (lower is better) | 0% | 2.0% | 1.0% |
| Accessories to confirm named | 42.9% | 100% | 100% |
| Unavailable technique flagged | 92.0% | 100% | 100% |
| Said so when nothing fits | 88.0% | 100% | 100% |
| Vague questions: asked to clarify in every run | 0 of 4 (0 of 4 answers) | 4 of 4 (4 of 4 answers) | 4 of 4 (4 of 4 answers) |
| Wrong or complementary picks rated low fit (full system only) | - | - | 9 of 9 |
| Answers | 98 | 98 | 98 |
| Errors | 0 | 0 | 0 |
| Cost (USD) | $0.70 | $0.57 | $1.32 |

Wrong or complementary picks rated low fit: of the instruments the key calls unacceptable or supplementary only that the full system showed, how many it rated low. Vague questions: asked to clarify in every run of the question (in brackets: per answer).

## Remaining faulty generated keys

The 15 keys flagged in `results/FINDINGS.md`, against the final keys:

| Question | Status |
|---|---|
| G002 | remains: key lists every capable microscope |
| G012 | remains: key lists every capable microscope |
| G030 | remains: key lists every capable microscope |
| G083 | remains: key lists every capable microscope |
| G003 | fixed: opaque titanium disc, inverted stands now only acceptable |
| G019 | fixed: stereomicroscope expected for 50 um - 1 mm beads, ESEM acceptable |
| G084 | fixed: stereomicroscope expected for capsules, ESEM acceptable |
| G077 | remains: 5-200 um powder, ESEM expected and stereomicroscope only acceptable (unchanged) |
| G021 | remains: ESEM expected next to TEM for nanoparticles (left for Stefan) |
| G078 | remains: ESEM expected next to TEM for nanoparticles (left for Stefan) |
| G059 | fixed: DSC on a small piece now acceptable |
| G060 | fixed: DSC on a small piece now acceptable |
| G062 | fixed: TEM on a drop of suspension now acceptable |
| G063 | fixed by removal: no listed technique measures heat of cure non-destructively once FTIR is corrected (not in the set any more) |
| G076 | remains: TGA as a supplementary check counts as an unacceptable pick |

Fixed: 7 (G003, G019, G084, G059, G060, G062, G063). Remaining: 8 (G002, G012, G030, G083, G077, G021, G078, G076).

| Expected instruments found, main picks | Naive (baseline) | Structured | Structured + annotations (full system) |
|---|---|---|---|
| all generated questions | 90.3% | 84.8% | 89.8% |
| without the 8 remaining faulty keys | 94.7% | 90.2% | 95.5% |

## Knowledge fixes, before / after (full system, curated)

Poster version: the full-system answers of `run_20261107_144209` (`results/graph_matching/curated_poster_g0.csv`, the poster column of `results/graph_matching/decision_curated.md`). Final: `run_20261109_090405`. Both scored with the final code and keys.

| Metric (full system, curated) | Poster version | Final |
|---|---|---|
| Expected instruments found, main picks | 83.3% | 85.1% |
| Expected instruments found, main + supporting | 93.8% | 94.1% |
| Wrong main picks (false primary or any unacceptable; lower is better) | 0% | 0% |
| Answers with an unacceptable pick (lower is better) | 0% | 0% |
| Accessories to confirm named | 100% | 100% |
| Unavailable technique flagged | 88.9% | 88.9% |
| Said so when nothing fits | 100% | 100% |
| Vague questions: asked to clarify in every run | 2 of 2 (6 of 6 answers) | 2 of 2 (6 of 6 answers) |
| Wrong or complementary picks rated low fit (full system only) | 9 of 9 | 10 of 10 |
| Answers | 69 | 69 |
| Errors | 0 | 0 |
| Cost (USD) | $0.88 | $0.91 |
| Instruments per answer | 1.61 | 1.54 |

## Graph matching (tested, not kept)

- Expected instruments found, main + supporting: 0.94 -> 0.99 (poster answers, curated).
- Wrong main picks: 0% -> 3%. Cause: graph matching adds upright microscopes for living cells in well plates (Q19), which cannot image a well plate. See `results/FINDINGS_graph_matching.md`.

## Q20 roughness example (final full-system answers)

| Run | Says nothing fits | AFM not available | ESEM | Fit |
|---|---|---|---|---|
| 1 | yes | yes | complementary | low |
| 2 | yes | yes | complementary | low |
| 3 | yes | yes | complementary | low |

Run 1, summary: "No listed instrument can perform quantitative nanoscale surface roughness measurements or calculate RMS roughness."

## Model comparison (23 curated + 98 generated questions, structured + annotated, 1 run)

Matches the app today. Annotated answers were re-run with the final version for every model (`results/final_runs/`); structured answers come from the Nov 8 comparison (`results/models*/`), whose structured prompt is unchanged (`ca824b2c`). All are scored with the final code and keys. Main score as in `make_charts.py`. Chart: `results/final/charts/models_cost_vs_score.png`.

| model | answers | errors | main score | wrong main picks | cost per answer (USD) | total cost (USD) |
|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 242 | 0 | 81.5% | 2.9% | 0.00201 | 0.4853 |
| gemini-3.5-flash-lite | 242 | 0 | 82.9% | 4.1% | 0.00276 | 0.6688 |
| gemini-3-flash-preview | 242 | 0 | 90.1% | 3.3% | 0.00868 | 2.1001 |
| gemini-3.8-flash | 242 | 0 | 90.0% | 2.1% | 0.00972 | 2.3517 |
| gemini-4-argon | 242 | 0 | 97.0% | 5.0% | 0.01955 | 4.7314 |
| gemini-3.1-pro-preview | 242 | 0 | 93.9% | 2.9% | 0.0272 | 6.5814 |
