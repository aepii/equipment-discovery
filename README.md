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
- **Naive**: equipment list + question, no rules; the answer is shown as text.
- **Compare both**: the two side by side.

If `APP_PASSWORD` is set, the app asks for that password before showing anything.

## Deploy (Streamlit Community Cloud)

1. Push the repo to GitHub (private is fine; Streamlit Cloud can deploy private repos).
2. On https://share.streamlit.io choose **Create app**, pick the repo and branch, main file `app.py`.
3. Under **Advanced settings > Secrets**, paste the contents of `.streamlit/secrets.toml.example`
   with the real API key and a shared `APP_PASSWORD`. Secrets are copied into the environment at
   startup, so they override `.env` (which is never committed).
4. Share the link and the password.

## Run the evaluation

```
python run_eval.py --runs 3                 # all questions, both modes
python run_eval.py --runs 1 --modes structured
```

Writes `results/run_<time>.csv` with, per question x mode x run: the instruments found, how many
expected instruments were found (e.g. `2/3`), how many expected "not available" techniques were
mentioned (e.g. micro-CT), removed IDs, errors and the full answer. Score manually from the CSV.
Test questions and draft expected answers are in `test_questions.json`.

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface |
| `core.py` | Load dataset (IDs EQ01-EQ20 in row order), prompts, JSON parsing, answer checks |
| `llm.py` | `complete(system, user, json_mode)` for gemini / openai / ollama / mock |
| `run_eval.py` | Batch evaluation to CSV |
| `test_questions.json` | Test questions with expected instrument IDs |
