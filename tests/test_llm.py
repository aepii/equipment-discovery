import pytest

import llm


class StatusError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


# --- which errors are retried ---

@pytest.mark.parametrize("exc, transient", [
    (llm.ProviderError("rate limited", 429), True),
    (llm.ProviderError("server", 503), True),
    (llm.ProviderError("bad request", 400), False),
    (llm.ProviderError("no key", 401), False),
    (llm.ProviderError("ollama timed out", transient=True), True),
    (StatusError(500), True),
    (StatusError(404), False),
    (APITimeoutError(), True),
    (TimeoutError(), True),
    (ValueError("bad"), False),
])
def test_is_transient(exc, transient):
    assert llm.is_transient(exc) is transient


def test_backoff_grows_and_is_capped(monkeypatch):
    monkeypatch.setenv("LLM_RETRY_BASE_S", "2")
    assert 1 <= llm.backoff_seconds(0) <= 2
    assert 4 <= llm.backoff_seconds(2) <= 8
    assert llm.backoff_seconds(10) <= llm.MAX_BACKOFF_S


# --- retries and fallback, driven by the mock's MOCK_FAIL setting ---

def test_temporary_errors_are_retried(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "429:2")
    meta = llm.complete_with_meta("s", "Question: viscous", json_mode=True)
    assert meta["attempts"] == 3 and not meta["fallback_used"]
    assert "EQ19" in meta["text"]


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "503:5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    with pytest.raises(llm.ProviderError):
        llm.complete("s", "Question: viscous")
    assert llm._mock_failed["count"] == 2


def test_other_errors_are_not_retried(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "400:5")
    with pytest.raises(llm.ProviderError):
        llm.complete("s", "Question: viscous")
    assert llm._mock_failed["count"] == 1


def test_fallback_model_after_retries(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "429:3")
    monkeypatch.setenv("MOCK_FALLBACK_MODEL", "mock-lite")
    meta = llm.complete_with_meta("s", "Question: viscous")
    assert meta["attempts"] == 4
    assert meta["fallback_used"] and meta["model_used"] == "mock-lite"


def test_no_fallback_for_other_errors(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "401:1")
    monkeypatch.setenv("MOCK_FALLBACK_MODEL", "mock-lite")
    with pytest.raises(llm.ProviderError):
        llm.complete("s", "Question: viscous")


def test_fallback_same_as_main_model_is_ignored(monkeypatch):
    monkeypatch.setenv("MOCK_FALLBACK_MODEL", llm.model_name())
    assert llm.fallback_model_name() == ""


# --- cost ---

def test_cost_from_env_prices(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("PRICE_IN_PER_M", "0.5")
    monkeypatch.setenv("PRICE_OUT_PER_M", "3")
    # Gemini bills thinking tokens as output: 1000 * 0.5 + (200 + 300) * 3 = 2000 per million
    assert llm.cost_usd(1000, 200, 300) == pytest.approx(0.002)
    monkeypatch.setenv("FALLBACK_PRICE_OUT_PER_M", "1")
    assert llm.cost_usd(1000, 200, 300, fallback=True) == pytest.approx(0.001)


def test_openai_reasoning_tokens_are_already_in_output(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("PRICE_IN_PER_M", "1")
    monkeypatch.setenv("PRICE_OUT_PER_M", "1")
    assert llm.cost_usd(1000, 500, 400) == pytest.approx(0.0015)


def test_cost_unknown_without_prices_or_tokens(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert llm.cost_usd(1000, 200) is None
    monkeypatch.setenv("PRICE_IN_PER_M", "1")
    monkeypatch.setenv("PRICE_OUT_PER_M", "1")
    assert llm.cost_usd(None, 200) is None


def test_local_models_are_free():
    assert llm.complete_with_meta("s", "Question: viscous")["cost_usd"] == 0.0


# --- streaming ---

def test_stream_yields_the_whole_answer_and_fills_meta(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "429:1")
    meta = {}
    text = "".join(llm.stream_with_meta("s", "Question: viscous", meta))
    assert text == llm.complete("s", "Question: viscous")
    assert meta["attempts"] == 2 and "seconds" in meta
