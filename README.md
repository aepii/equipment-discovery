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
output / thinking tokens, whether the JSON parsed, instruments recommended (or, in naive mode,
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
python run_eval.py --runs 3                 # all questions, both modes
python run_eval.py --runs 1 --modes structured
python run_eval.py --runs 3 --log            # also log answers to the sheet (source "eval")
```

Writes `results/run_<time>.csv` with, per question x mode x run: how many expected instruments were
found (e.g. `2/3`), how many expected "not available" techniques were mentioned (e.g. micro-CT), and
the same answer columns as the app's log (instruments, tokens, time, versions, full answer).
Score manually from the CSV.
Test questions and draft expected answers are in `test_questions.json`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface |
| `core.py` | Load dataset (IDs EQ01-EQ20 in row order), prompts, JSON parsing, answer checks |
| `llm.py` | `complete(system, user, json_mode)` for gemini / openai / ollama / mock; `complete_with_meta` adds tokens and time |
| `store.py` | Answer and feedback rows; saves them to the Google Sheet or `results/log.jsonl` |
| `run_eval.py` | Batch evaluation to CSV |
| `test_questions.json` | Test questions with expected instrument IDs |
