# UMKC Research Equipment Discovery Tool (Hack-A-Roo 2026, P21)

Type a research or measurement question in plain language; the app suggests techniques, matches them
to instruments in the built-in dataset (`data/dataset.xlsx`), and shows location and contact for each.
Contact names in the dataset are fictional.

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
- **Compare both**: the two side by side.

If `APP_PASSWORD` is set, the app asks for that password before showing anything.

## Speed, cost and resilience

- **Compare both** asks the two modes at the same time, so it takes about as long as one mode. The
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

A warning appears if the prompt or dataset changed since the answer was recorded.

For UI work with `LLM_PROVIDER=mock`: `MOCK_DELAY_S=3` makes each answer take 3 s, and `MOCK_FAIL=429:2`
makes the next 2 calls fail with error 429 (try `503:99` to see the saved-answer backup).

## Deploy (Streamlit Community Cloud)

1. Push the repo to GitHub (private is fine; Streamlit Cloud can deploy private repos).
2. On https://share.streamlit.io choose **Create app**, pick the repo and branch, main file `app.py`.
3. Under **Advanced settings > Secrets**, paste the contents of `.streamlit/secrets.toml.example`
   with the real API key and a shared `APP_PASSWORD`. Secrets are copied into the environment at
   startup, so they override `.env` (which is never committed).
4. Share the link and the password.

## Logging and feedback

Every answer is logged with what is needed to compare versions later: mode, provider, model,
prompt version (hash of the system prompt), dataset version, git commit, response time, input /
output / thinking tokens, cost, the model that answered (main or fallback), retries, whether the answer
came from the model, the cache or the saved answers (`answer_source`), whether the JSON parsed or was
repaired, instruments recommended (or, in naive mode,
detected in the text), removed IDs, "not available" techniques, errors, the question and the raw
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
python run_eval.py --runs 3                       # all questions, both modes
python run_eval.py --runs 1 --modes structured
python run_eval.py --questions Q1 Q4 --runs 1     # a few questions
python run_eval.py --category vague               # one category
python run_eval.py --runs 3 --log                 # also log answers to the sheet (source "eval")
python run_eval.py --rescore results/run_<time>.csv   # re-score saved answers, no model calls
python run_eval.py --review-sheet                 # results/expected_answers_review.md for Stefan
```

Use `LLM_PROVIDER=mock` to try it without spending API credits. Rate-limit and server errors are
retried inside each call (see "Speed, cost and resilience"), then the whole answer is retried twice more
after 10 and 20 s; other errors are kept and counted separately (they are left out of the averages).
The summary also has `repaired_rate` (structured answers that needed the repair call) and
`total_cost_usd` (when prices are set).

`results/run_<time>.csv` has one row per question x mode x run, with the same answer columns as the
app's log plus these scores:

| Column | Meaning |
|---|---|
| `expected_hits` / `expected_total`, `recall` | expected instruments that were recommended |
| `unacceptable_hits`, `unacceptable_ids` | recommended instruments that should not be |
| `unclassified_ids` | recommended, but in no list of the question: review and add them to the test file |
| `expected_only_mentioned` | naive only: expected instruments named in the answer but left off its `Recommended:` line; check by hand |
| `na_hits` / `na_total` | expected "not available" techniques named anywhere in the answer (both modes) |
| `accessory_hits` / `accessory_total` | expected accessories named for the recommended instruments (structured: in that instrument's `accessories_to_confirm`; naive: anywhere in the answer) |
| `asked_clarifying`, `clarifying_ok` | asked a clarifying question, and whether that was expected (naive is a heuristic: no instruments, and a `?` or a phrase like "more information is needed"; check by hand) |
| `contacts_ok` / `contacts_total` | naive only: the correct contact name appears for each recommended instrument |

`results/run_<time>_summary.csv` has one row per question x mode with consistency across runs
(`stable_runs` = runs that gave the most common instrument set, e.g. `3/3`; `mean_jaccard` = average
overlap of the instrument sets; `id_frequency` = how often each ID was recommended), then one row per
mode for reviewed, draft and all questions. The per-mode table is also printed.

**Naive mode** ends its answer with a line `Recommended: <IDs>`, and only those count as
recommendations (an instrument mentioned as unsuitable doesn't count). The IDs it mentions anywhere are
kept in `mentioned_ids`; `ids_source` says which was used. Naive runs from before this change
(different `prompt_version`) are not comparable with newer ones.

### Test questions

`test_questions.json` holds the questions and expected answers. Each question has an `id`, `category`
(named-instrument, problem-only, no-suitable-equipment, accessory-trap, misleading-keyword,
multi-step, vague), `status` (`draft` until Stefan has reviewed it, then `reviewed`), `expected_ids`,
`acceptable_ids` (reasonable partial answers, not scored either way), `unacceptable_ids`,
`expected_not_available` and `expected_accessories` (regex patterns, case-insensitive),
`expect_clarifying` and `notes`. After changing expected answers, re-score earlier runs with
`--rescore` instead of running the model again.

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
| `core.py` | Load dataset (IDs EQ01-EQ20 in row order), prompts, JSON parsing, answer checks |
| `llm.py` | `complete(system, user, json_mode)` for gemini / openai / ollama / mock, with timeouts, retries and fallback model; `complete_with_meta` adds tokens, time and cost; `stream_with_meta` streams text |
| `runtime.py` | Answer cache and daily spending shared by all app sessions; call and budget limits |
| `data/demo_answers.json` | Saved answers shown when the live model can't be used (`run_eval.py --record-demo`) |
| `store.py` | Answer and feedback rows; saves them to the Google Sheet or `results/log.jsonl` |
| `run_eval.py` | Batch evaluation: scores, consistency summary, re-scoring, review sheet, recording saved demo answers |
| `test_questions.json` | Test questions with expected, acceptable and unacceptable instruments |
| `tests/` | Unit tests (pytest, mock model) |
