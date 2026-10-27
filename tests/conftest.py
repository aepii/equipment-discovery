import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every test uses the mock model and never writes to the Google Sheet, whatever .env says."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
