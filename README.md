# UMKC Research Equipment Discovery Tool (Hack-A-Roo 2026, P21)

Type a research or measurement question in plain language; the app suggests techniques, matches them
to instruments in the built-in dataset (`data/dataset.xlsx`), and shows location and contact for each.
Contact names in the dataset are fictional.

The dataset has Stefan's 20 instruments (EQ01-EQ20) plus 3 fictional test instruments (EQ21-EQ23,
`data/test_instruments.json`) for testing whether the AI understands specific models and their installed
accessories, e.g. a second Discovery HR20 rheometer with the Environmental Test Chamber installed.
Instruments can list `installed_accessories`; those count as confirmed in every prompt, and anything else
is still "confirm with the contact". The app labels test instruments "Fictional test instrument". See
[`data/README.md`](data/README.md).

## Setup

```
pip install -r requirements.txt
copy .env.example .env      # then edit .env
```

In `.env`, set `LLM_PROVIDER` to `gemini`, `openai`, `ollama` (local model, offline) or `mock`
(canned answers, no API key), and the matching API key. Model names come from `GEMINI_MODEL` /
`OPENAI_MODEL` / `OLLAMA_MODEL`.

### Offline mode (Ollama)

1. Install Ollama from https://ollama.com and start it (it runs in the background on port 11434).
2. Download a model once, while online: `ollama pull qwen2.5:7b`
3. In `.env`: `LLM_PROVIDER=ollama` and `OLLAMA_MODEL=qwen2.5:7b`.

After that the app needs no internet. A 7-8B model needs about 6 GB of free RAM/VRAM; on weaker
machines try `qwen2.5:3b` or `llama3.2:3b`. Small local models are noticeably less accurate than
the cloud models, so use them as a fallback and note the model name when comparing results.

## Run the app

```
streamlit run app.py
```

Sidebar modes:
- **Structured**: rules + JSON output. The model returns only instrument IDs; code fills in name,
  location and contact from the dataset and removes any ID that is not in the dataset (with a notice).
- **Naive**: equipment list (including contacts) + question, no rules, plus a plain request to give
  the location and contact for each suggested instrument; the answer is shown as text. The model
  copies contacts itself here, so naive answers can be checked for wrong or invented contacts.
- **Structured + annotations** (`annotated`): structured mode, plus each instrument's draft notes from
  the knowledge layer (typical techniques, what they measure, destructive or not, limitations,
  accessories to confirm) and a list of techniques no listed instrument performs (e.g. micro-CT). The
  model also returns a technique ID per recommendation, and code checks it against the notes: it warns
  when the instrument's notes don't list that technique or it needs optional hardware, shows whether
  it is destructive, fills in accessories to confirm if the model named none, and warns when a "not
  available" technique is in fact listed for an instrument. See "Knowledge layer" below.
- **Compare structured and naive** / **Compare all three**: side by side.

**Primary vs. supplementary** (structured and annotated, from Stefan's feedback of Oct 31): each
recommendation has a `role`. `primary` = the instrument can itself perform the measurement that answers
the question; `supplementary` = useful context, preparation or a partial/qualitative view, but it cannot
meet the objective on its own. The answer also has `objective_met` (false when nothing is primary). The
page shows two sections, "Can perform this measurement" and "Complementary only: cannot perform the main
measurement", and when the objective is not met a notice "No instrument in the dataset can perform this
measurement" with the techniques that are not available. A missing or invalid role is a schema problem
(so the repair call fixes it); if it is still missing it counts as primary. Naive mode gets no role
instructions (it is the baseline), and every instrument it recommends counts as primary.

**Fit level** (annotated mode only). Each recommendation gets `fit` (high / medium / low) and a
one-sentence `fit_reason`, assigned by **code** from the knowledge files and the dataset, never by the
model (a model's own confidence number is not calibrated). The first rule that matches wins:

| Fit | Rule |
|---|---|
| low | role is supplementary |
| low | no or unknown technique ID, a technique not in the instrument's notes, or one with `low` confidence (needs optional hardware) |
| low | the workflow check found a dead end |
| low | the property the model names (`property_id`) is only `partial` for that technique (e.g. confocal for internal structure) |
| high | standard technique and the dataset lists an installed accessory for it (e.g. EQ21's Environmental Test Chamber); smaller items such as geometries are still listed to confirm under Details |
| medium | standard technique with accessories to confirm (e.g. load cell and platens for the Instron) |
| high | standard technique and nothing to confirm |

Each card has at most three badges, always with a text label: role (**Can perform this** /
**Complementary only**), fit level (green high, amber medium, grey low, red only for dead ends) with its
reason below, and destructive (**Destroys sample** / **Non-destructive** / **Depends**). Everything else
(installed accessories, accessories to confirm, workflow, cautions, draft-notes status, fictional test
instrument) is in a collapsed **Details** section. Structured mode has no technique IDs, so it shows
no fit level, only the role and a highlighted "Confirm with the contact" line; naive mode shows text only.

**Workflow check and dead ends** (annotated mode only). `techniques.json` links techniques with
`requires_before` (with a `when` condition) and `leads_to`. `knowledge.workflow_for()` labels each step
`available` (with instruments), `bench_step` (a lab procedure, no instrument needed) or `missing`. For each
recommendation, code adds a **Workflow** list to the card's Details, e.g. "May need Ultramicrotomy first
(for tissue, cells or bulk polymer samples): Ultramicrotome (EQ16), Jamie Collins (SOP)". Steps with a
condition are "may need", never blockers. It is a **dead end** (red badge, fit low, role forced to
supplementary) when:
- a preparation or fabrication step (mill, printer, sectioning) has no available follow-up among the
  answer's recommendations, e.g. milling bone when phase identification needs XRD, which is not listed; or
- an unconditional prerequisite is missing from the dataset (and is not a bench step).

The dead-end rule is checked before the "supplementary" fit rule, so the card shows the specific reason.

**How this answer was reached** (annotated mode only). An expander under each annotated answer draws the
part of the knowledge graph behind it (`answer_graph.py`, rendered with `st.graphviz_chart`, no extra
dependency): question -> property asked about -> technique (measured by / partly measured by / uses) ->
instrument with contact, role and fit level, plus accessories to confirm, steps that must or may come
first, and suitable techniques marked NOT IN DATASET. Nothing in it is new: it is drawn from the
knowledge files and the checked answer.

If `APP_PASSWORD` is set, the app asks for that password before showing anything.

## Speed, cost and resilience

- **Compare** modes ask all their modes at the same time, so it takes about as long as one mode. The
  naive answer streams in as it is written (`STREAM_NAIVE=0` turns this off).
- **Cache**: answers are kept in the app's memory, shared by everyone using the app, keyed on mode,
  question (ignoring case and spacing), model, prompt version and dataset version. Asking the same
  question again is instant and free. The cache is emptied when the app restarts or is redeployed.
  Tick **Skip cache** in the sidebar to ask the model again. Errors are never cached.
- **Retries and fallback model**: each call has a timeout (`LLM_TIMEOUT_S`). Rate limits (429), server
  errors (5xx) and timeouts are retried `LLM_MAX_RETRIES` times with growing waits. If they still fail
  and `GEMINI_FALLBACK_MODEL` / `OPENAI_FALLBACK_MODEL` is set, that model is tried once. Wrong keys and
  bad requests are not retried.
- **JSON repair**: if a structured answer is not JSON of the expected shape, the model is asked once to
  fix the format. The answer is marked (`repaired` in the log) so first-try JSON validity can still be
  reported; `run_eval.py --no-repair` turns this off.
- **Cost**: set `PRICE_IN_PER_M` / `PRICE_OUT_PER_M` (USD per million tokens, from the provider's
  pricing page) to log `cost_usd` per answer and show the session's and today's spending in the
  sidebar. Limits: `MAX_CALLS_PER_SESSION` and `DAILY_BUDGET_USD` (all users of one running app; resets
  daily and on restart). When a limit is reached the app says so and shows a saved answer if it has one.

### Saved answers for the live demo

`data/demo_answers.json` holds one recorded answer per test question and mode (the three example
buttons are Q1-Q3). Record or refresh it with the real model before a demo:

```
python run_eval.py --record-demo                    # all test questions, both modes
python run_eval.py --record-demo --questions Q1 Q2 Q3
```

Answers for questions that fail are kept from the previous recording. Saved answers are the raw model
output, so they are checked like live ones (unknown IDs removed, contact and location from the dataset).

- `DEMO_BACKUP=1` (default): if the live model fails after retries and the fallback model, the saved
  answer is shown, labelled with the recording date and model and the live error.
- `DEMO_OFFLINE=1`: never call the model; only saved answers (e.g. no internet at the venue).

A warning appears if the prompt or dataset changed since the answer was recorded. The prompts and the
dataset version changed with the primary/supplementary roles and the test instruments (Nov 7), so
re-record with the real model: `python run_eval.py --record-demo`.

For UI work with `LLM_PROVIDER=mock` (canned answers for questions mentioning viscous, compress,
internal or roughness; the roughness one shows the "Complementary only" section): `MOCK_DELAY_S=3` makes each answer take 3 s, and `MOCK_FAIL=429:2`
makes the next 2 calls fail with error 429 (try `503:99` to see the saved-answer backup).

## Deploy (Streamlit Community Cloud)

1. Push the repo to GitHub (private is fine; Streamlit Cloud can deploy private repos).
2. On https://share.streamlit.io choose **Create app**, pick the repo and branch, main file `app.py`.
3. Under **Advanced settings > Secrets**, paste the contents of `.streamlit/secrets.toml.example`
   with the real API key and a shared `APP_PASSWORD`. Secrets are copied into the environment at
   startup, so they override `.env` (which is never committed).
4. Share the link and the password.

## Web app (presentation interface)

A separate interface for presenting: FastAPI (`api/`) plus a React frontend (`web/`). It answers with
the same code as the Streamlit app (same prompts, cache, limits, saved answers and logging, with
`source = web`), so the Streamlit app and the evaluation are unaffected. It shows Equipment Finder
(annotated mode) by default, General AI (naive mode) in Compare, and the rules-only mode under Advanced.

Needs Node.js 20+ in addition to Python.

```
pip install -r requirements.txt -r requirements-web.txt
scripts/run_web.sh              # build the frontend, serve everything on http://localhost:8000
scripts/run_web.sh --offline    # saved answers only: the example questions work with Wi-Fi off
```

On Windows PowerShell: `scripts\run_web.ps1` (or `scripts\run_web.ps1 -Offline`).

For frontend work, run the API and the Vite dev server separately (the dev server forwards `/api`):

```
python -m uvicorn api.main:app --port 8000 --reload
cd web && npm install && npm run dev       # http://localhost:5173
```

The environment variables are the same as for the Streamlit app (`.env` locally). `DEMO_OFFLINE=1`
answers only from `data/demo_answers.json`; the start screen's examples (`api/presentation.py`) all
have saved answers. `MAX_CALLS_PER_SESSION` counts per browser (an anonymous ID kept in the
browser), and `DAILY_BUDGET_USD` caps total spending.

What the interface receives is built from an allowlist in `api/presentation.py`;
`tests/test_presentation.py` checks that saved answers, examples and the built frontend never show
internal project wording. Conversations are stored in the browser only (localStorage); there is no
server-side history or login. Follow-up questions are rewritten into standalone questions
(`core.rewrite_followup`) and shown as "Answering: ...".

The header shows the UMKC logo from `web/public/umkc-logo.png` (cropped to the wordmark, transparent
background, 144 px tall for sharp display); if the file is missing it shows "UMKC" as text. Check UMKC's
brand guidelines before showing the logo publicly.

**Deploy.** The `Dockerfile` builds the frontend and serves API and frontend on one port
(`$PORT`, default 8000). It works on Render, Railway, Fly.io or Hugging Face Spaces (Docker). Set the
API key and other settings as the host's environment variables; never bake `.env` into the image.
Free hosts sleep when idle, so open the site a few minutes before presenting. For the live demo, also
run it locally on the presenting laptop as a backup.

## Logging and feedback

Every answer is logged with what is needed to compare versions later: mode, provider, model,
prompt version (hash of the system prompt), dataset version, git commit, response time, input /
output / thinking tokens, cost, the model that answered (main or fallback), retries, whether the answer
came from the model, the cache or the saved answers (`answer_source`), whether the JSON parsed or was
repaired, instruments recommended (or, in naive mode,
detected in the text), which of them are primary and supplementary, `objective_met`, removed IDs, "not available" techniques, errors, the question and the raw
output. Under each answer, a feedback form collects: overall Good/Bad and why, Good/Partly/Wrong per
instrument, instruments that should have been recommended, and whether the "not available" part was
right. Raters can enter their name in the sidebar.

Rows go to two tabs, `answers` and `feedback` (joined on `answer_id`), of a Google Sheet. Without a
sheet configured they go to `results/log.jsonl`. The sidebar shows which one is in use. Saving
runs in the background; failures are printed in the server log and never break the app.

Google Sheet setup (once):
1. In Google Cloud Console, create a project, enable the **Google Sheets API** and the
   **Google Drive API**, and create a **service account**. Under Keys, add a JSON key and download it.
2. Create a Google Sheet and share it (Editor) with the service account's `client_email`.
3. Locally: save the key as `service_account.json` (git-ignored) and set `GOOGLE_SHEET_ID` (the
   long ID in the sheet URL) in `.env`. Deployed: add `GOOGLE_SHEET_ID` and paste the key file into
   `GOOGLE_SERVICE_ACCOUNT_JSON` in the secrets (see `.streamlit/secrets.toml.example`).

## Run the evaluation

```
python run_eval.py --runs 3 --yes                 # all questions, all three modes (207 calls: needs --yes)
python run_eval.py --runs 1 --modes structured annotated
python run_eval.py --questions Q1 Q4 --runs 1     # a few questions
python run_eval.py --category vague               # one category
python run_eval.py --runs 3 --log                 # also log answers to the sheet (source "eval")
python run_eval.py --rescore results/run_<time>.csv   # re-score saved answers, no model calls
python run_eval.py --review-sheet                 # results/expected_answers_review.md for Stefan
```

Every run first prints how many model calls it will make (questions x modes x runs, plus a repair call
for any unusable JSON answer) and stops above 200 unless `--yes` is given. The run CSV has a
`source_group` column (reviewed, stefan = Q18-Q19, draft, generated), and the summary averages each mode
per source group.

Poster results (`pip install -r requirements-dev.txt` for matplotlib):

```
python scripts/make_charts.py                     # newest curated run -> results/charts/curated_*.png (300 dpi)
python scripts/make_charts.py --set generated     # newest generated run -> results/charts/generated_*.png
python scripts/make_charts.py --summary results/run_<time>_rescored_summary.csv
python scripts/before_after.py --before rows.json --question-id Q20   # results/before_afm.json, after_afm.json
```

`make_charts.py` draws one grouped bar chart per mode (expected instruments found, wrong main picks,
unavailable techniques flagged, accessories named), a table of median response time and cost, and the
main score per question category, plus per source group (curated set) or per generation rule (generated
set). It writes the same numbers as CSV next to them. `before_after.py` saves logged answers of an older version
(rows exported from the answers tab) next to fresh answers from the current code, for a before/after
example. A short write-up of the latest run is in `results/FINDINGS.md` (not committed, like all of `results/`).

Use `LLM_PROVIDER=mock` to try it without spending API credits. Rate-limit and server errors are
retried inside each call (see "Speed, cost and resilience"), then the whole answer is retried twice more
after 10 and 20 s; other errors are kept and counted separately (they are left out of the averages).
The summary also has `repaired_rate` (structured answers that needed the repair call),
`false_primary_rate` (answers with at least one false primary), `objective_met_ok_rate` and
`total_cost_usd` (when prices are set). In the printed table these are `falseP` and `no-obj`, and each
printed answer line shows the primary IDs, then `+supplementary [...]` if there are any.

Recall changed meaning with the roles (it now counts primary instruments only), so runs from before
Nov 7 are not directly comparable; `--rescore` re-reads old answers, but those have no roles, so every
recommendation counts as primary there.

`results/run_<time>.csv` has one row per question x mode x run, with the same answer columns as the
app's log (including `primary_ids`, `supplementary_ids` and `objective_met`) plus these scores:

| Column | Meaning |
|---|---|
| `expected_hits` / `expected_total`, `recall` | expected instruments recommended as **primary** (naive: every recommended instrument) |
| `unacceptable_hits`, `unacceptable_ids` | recommended instruments (any role) that should not be |
| `false_primary_hits`, `false_primary_ids` | primary instruments that are in `supplementary_only_ids` or `unacceptable_ids` |
| `objective_met_ok` | only for questions with no expected instrument (and no clarifying question expected): the answer said `objective_met: false` (naive: `Recommended: none`) |
| `unclassified_ids` | recommended, but in no list of the question: review and add them to the test file |
| `expected_only_mentioned` | naive only: expected instruments named in the answer but left off its `Recommended:` line; check by hand |
| `na_hits` / `na_total` | expected "not available" techniques named anywhere in the answer (both modes) |
| `accessory_hits` / `accessory_total` | expected accessories named for the recommended instruments (structured and annotated: in that instrument's `accessories_to_confirm`; naive: anywhere in the answer) |
| `asked_clarifying`, `clarifying_ok` | asked a clarifying question, and whether that was expected (naive is a heuristic: no instruments, and a `?` or a phrase like "more information is needed"; check by hand) |
| `contacts_ok` / `contacts_total` | naive only: the correct contact name appears for each recommended instrument |
| `fit_expected_good` / `fit_expected_total` | annotated only: expected instruments rated high or medium fit |
| `fit_bad_low` / `fit_bad_total` | annotated only: recommended instruments in `unacceptable_ids` or `supplementary_only_ids` rated low fit |

The answer columns include `fit_levels` (e.g. `EQ15:medium;EQ18:low`). The summary has
`fit_expected_good_rate` and `fit_bad_low_rate` (printed as `fit+` and `fit-`): together they show
whether the fit level separates good picks from bad ones.

| Column | Meaning |
|---|---|
| `dead_end_flagged` | code marked a dead end (annotated), or, for a question with `expect_dead_end: true`, the answer names the missing next step (any mode, so modes can be compared) |
| `dead_end_ok` | matches `expect_dead_end`; for `false` only checked in annotated mode (no expected instrument marked a dead end) |
| `workflow_hits` / `workflow_total` | `workflow_ids` (prerequisite instruments, e.g. EQ16 for TEM) recommended, mentioned or listed in a workflow |

The summary adds `dead_end_ok_rate` and `workflow_rate`. Test questions can set the optional fields
`expect_dead_end` (bool) and `workflow_ids`.

`results/run_<time>_summary.csv` has one row per question x mode with consistency across runs
(`stable_runs` = runs that gave the most common instrument set, e.g. `3/3`; `mean_jaccard` = average
overlap of the instrument sets; `id_frequency` = how often each ID was recommended), then one row per
mode for each source group (reviewed, stefan, draft, generated), each generation rule (`rule:<rule>`,
generated questions only) and all questions. The per-mode table is also printed.

**Naive mode** ends its answer with a line `Recommended: <IDs>`, and only those count as
recommendations (an instrument mentioned as unsuitable doesn't count). The IDs it mentions anywhere are
kept in `mentioned_ids`; `ids_source` says which was used. Naive runs from before this change
(different `prompt_version`) are not comparable with newer ones.

### Test questions

`test_questions.json` holds the questions and expected answers. Each question has an `id`, `category`
(named-instrument, problem-only, no-suitable-equipment, accessory-trap, misleading-keyword,
multi-step, vague, model-specific), `status` (`draft` until Stefan has reviewed it, then `reviewed`), `expected_ids`,
`acceptable_ids` (reasonable partial answers, not scored either way), optional `supplementary_only_ids`
(fine as supplementary, wrong as primary), `unacceptable_ids`,
`expected_not_available` and `expected_accessories` (regex patterns, case-insensitive),
`expect_clarifying` and `notes`. After changing expected answers, re-score earlier runs with
`--rescore` instead of running the model again.

## Generated questions

Besides the 23 curated questions in `test_questions.json` (which carry the accuracy claim), there are 99
generated questions in `test_questions_generated.json` for coverage: every property in the knowledge
layer, plus no-match, non-destructive, optional-hardware, distractor, workflow, named, model-specific and
vague questions.

- **The answer key comes from code, never from a model.** `scripts/generate_questions.py plan` derives
  each expected answer from `data/techniques.json`, `data/annotations.json`, `data/vocabulary.json` and
  the dataset, and writes `data/generated/question_plan.json` (answer key, `derived_from`, a brief and
  forbidden terms per item). Hand-picked inputs are in a short, commented `OVERRIDES` dict.
- **Only the wording is written by Claude Code**, from each brief, without the technique or instrument
  names that would give the answer away. Gemini, the model being tested, never sees the plan.
- `scripts/generate_questions.py check` verifies the questions against the plan: same answer keys, no
  forbidden terms, no near-duplicates, no close paraphrase of a curated question (stricter when the
  generated question has the same rule inputs), and a plan built from the current knowledge files (if
  they changed: rerun `plan`, update the questions, re-check).
- **Cross-checks without an expert.** `compare` maps each curated question to a rule and its inputs
  (`CURATED_INPUTS`), builds the generated key for it and writes `results/key_comparison.md`: agreement
  for Stefan-sourced (Q18-Q21) and other questions, and each difference per instrument as a conflict
  (good pick in one key, wrong in the other), a level difference or one-sided. `facts` writes
  `results/knowledge_facts.md`, the technique and instrument facts the generated keys rest on, with the
  most-used rows marked to check first (against manufacturer pages or with Stefan).
- **Bias:** annotated mode reads the same annotations that produced these answer keys, so it has a
  built-in advantage on this set; and the annotations are still drafts. Report generated results next to,
  not instead of, the curated ones.

```
python scripts/generate_questions.py plan
python scripts/generate_questions.py check
python scripts/generate_questions.py compare       # results/key_comparison.md
python scripts/generate_questions.py facts         # results/knowledge_facts.md
python run_eval.py --question-file test_questions_generated.json --review-sheet --sample 20   # spot-check sheet
python run_eval.py --question-file test_questions_generated.json --sample 15 --runs 1 --yes   # a fixed subset first
python run_eval.py --question-file test_questions_generated.json --runs 1 --yes               # all 99 (~300 calls)
python scripts/make_charts.py --set generated
```

Runs on the generated set are saved as `results/run_generated_<time>.csv`; their summary is also broken
down by generation rule (`rule:<rule>` scopes). `--sample N --seed S` always picks the same subset.

## Knowledge layer

A lightweight knowledge graph, stored as JSON: typed entities (instruments, techniques, properties, accessories) and typed relations (performs, measures / partly measures, must come first, leads to, accessory to confirm or installed), each with a source and confidence. Annotated mode reasons over it in code (fit levels, workflow, dead ends), and "How this answer was reached" draws the part used for one answer. Details and the list
of corrections to the first draft are in [`data/README.md`](data/README.md).

| File | Holds |
|---|---|
| `data/vocabulary.json` | Controlled vocabulary: property ids (e.g. `compressive_modulus`), technique kinds, sources, confidence levels, accessory and review statuses |
| `data/techniques.json` | Technique knowledge base: what each technique measures (fully or `partial`ly), destructive or not, `requires_before` / `leads_to` workflow steps. Includes techniques not in the dataset (micro-CT, GPC, capillary rheometry, ...) |
| `data/annotations.json` | Per instrument (EQ01-EQ23): techniques it typically performs (each with `source` and `confidence`), typical samples, limitations, accessories (`to_confirm` unless the dataset lists them), review status |
| `data/instrument_capabilities.xlsx` | Review copy for Stefan, generated from the JSON files |

Annotations describe what this **type** of instrument typically does, never what is installed. Every
fact has a source (`dataset` or `llm_draft`; later `expert_review` or `contact_confirmed`) and a
confidence (`high` standard, `medium` depends on configuration, `low` needs optional hardware).

```
python scripts/draft_annotations.py check     # validate the files against each other and the dataset
python scripts/draft_annotations.py export    # regenerate data/instrument_capabilities.xlsx for review
python scripts/draft_annotations.py draft --ids EQ05   # LLM draft -> data/annotations_draft.json
```

`draft` never overwrites `annotations.json`; copy reviewed entries over by hand. Stefan's corrections
are made in the JSON files and committed as data changes; then run `check` and `export`. Changing a
knowledge file changes annotated mode's `prompt_version`, so cached and saved demo answers for that
mode are not reused.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest
```

The tests always use the mock model, so they need no API key and cost nothing. They also check
`test_questions.json` (IDs exist, regexes compile, at least two questions per category).

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface |
| `core.py` | Load dataset (IDs EQ01-EQ20 in row order) and test instruments (EQ21-EQ23), prompts, JSON parsing, answer checks |
| `knowledge.py` | Load and check the knowledge files; lookups; instrument notes for the annotated prompt |
| `answer_graph.py` | The knowledge-graph view of one annotated answer (Graphviz DOT) |
| `scripts/draft_annotations.py` | Draft annotations with the LLM, check the knowledge files, export the review spreadsheet |
| `data/vocabulary.json`, `data/techniques.json`, `data/annotations.json` | Knowledge layer (see above) |
| `llm.py` | `complete(system, user, json_mode)` for gemini / openai / ollama / mock, with timeouts, retries and fallback model; `complete_with_meta` adds tokens, time and cost; `stream_with_meta` streams text |
| `runtime.py` | Answer cache and daily spending shared by all app sessions; call and budget limits |
| `data/demo_answers.json` | Saved answers shown when the live model can't be used (`run_eval.py --record-demo`) |
| `store.py` | Answer and feedback rows; saves them to the Google Sheet or `results/log.jsonl` |
| `run_eval.py` | Batch evaluation: scores, consistency summary, re-scoring, review sheet, recording saved demo answers; `--question-file`, `--sample`, call budget |
| `scripts/generate_questions.py` | Generated questions: `plan` (answer keys from the knowledge layer), `check` (questions vs. plan) |
| `data/generated/question_plan.json`, `test_questions_generated.json` | The generated-question plan and the 99 worded questions |
| `scripts/make_charts.py`, `scripts/before_after.py` | Poster charts and the before/after example from evaluation results |
| `test_questions.json` | Test questions with expected, acceptable and unacceptable instruments |
| `tests/` | Unit tests (pytest, mock model) |
| `api/main.py`, `api/service.py` | Web API: ask (also streamed with progress stages), feedback, examples, equipment |
| `api/presentation.py` | The allowlisted answer payload, audience labels and example questions for the web app |
| `web/` | React frontend (Vite + TypeScript); `npm run build` writes `web/dist` |
| `Dockerfile`, `scripts/run_web.sh`, `scripts/run_web.ps1` | Deploy and run the web app |
