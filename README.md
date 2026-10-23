# UMKC Research Equipment Discovery Tool (Hack-A-Roo 2026, P21)

Type a research or measurement question in plain language; the app suggests techniques, matches them
to instruments in the built-in dataset (`data/dataset.xlsx`), and shows location and contact for each.
Contact names in the dataset are fictional.

## Setup

```
pip install -r requirements.txt
copy .env.example .env      # then edit .env
```

In `.env`, set `LLM_PROVIDER` to `gemini`, `openai` or `mock` (canned answers, no API key), and the
matching API key. Model names come from `GEMINI_MODEL` / `OPENAI_MODEL`.

## Run the app

```
streamlit run app.py
```

Sidebar modes:
- **Structured**: rules + JSON output. The model returns only instrument IDs; code fills in name,
  location and contact from the dataset and removes any ID that is not in the dataset (with a notice).
- **Naive**: equipment list + question, no rules; the answer is shown as text.
- **Compare both**: the two side by side.

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
| `llm.py` | `complete(system, user, json_mode)` for gemini / openai / mock |
| `run_eval.py` | Batch evaluation to CSV |
| `test_questions.json` | Test questions with expected instrument IDs |
