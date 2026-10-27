import pytest

import llm

# Settings from .env that would change what the tests see.
CLEARED = ["GOOGLE_SHEET_ID", "MOCK_FAIL", "MOCK_DELAY_S", "MOCK_FALLBACK_MODEL", "LLM_MAX_RETRIES",
           "PRICE_IN_PER_M", "PRICE_OUT_PER_M", "FALLBACK_PRICE_IN_PER_M", "FALLBACK_PRICE_OUT_PER_M",
           "MAX_CALLS_PER_SESSION", "DAILY_BUDGET_USD", "DEMO_OFFLINE", "DEMO_BACKUP", "STREAM_NAIVE"]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every test uses the mock model, never waits between retries and never writes to the Google Sheet,
    whatever .env says."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_RETRY_BASE_S", "0")
    for name in CLEARED:
        monkeypatch.delenv(name, raising=False)
    llm._mock_failed.update(spec="", count=0)
