"""All model calls go through complete(). Provider is chosen by LLM_PROVIDER in .env.

Every call has a timeout, retries temporary errors (rate limits, server errors, timeouts) with
backoff, and then tries the fallback model once if one is configured.
"""

import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache
from typing import Iterator

from dotenv import load_dotenv

load_dotenv()

TEMPERATURE = 0.1
MAX_BACKOFF_S = 30


def _env_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "mock").strip().lower()


def model_name() -> str:
    p = provider()
    if p == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    if p == "openai":
        return os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if p == "ollama":
        return os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    return "mock (canned answers)"


def fallback_model_name() -> str:
    """Model tried once when the main model keeps failing with temporary errors; "" if none."""
    names = {"gemini": "GEMINI_FALLBACK_MODEL", "openai": "OPENAI_FALLBACK_MODEL", "mock": "MOCK_FALLBACK_MODEL"}
    name = names.get(provider())
    fallback = os.getenv(name, "").strip() if name else ""
    return "" if fallback == model_name() else fallback


def _models() -> list[str]:
    return [model_name()] + ([fallback_model_name()] if fallback_model_name() else [])


# --- errors and retries ---

class ProviderError(RuntimeError):
    """An error from a provider without its own exception classes (Ollama, mock)."""

    def __init__(self, message: str, code: int | None = None, transient: bool = False):
        super().__init__(message)
        self.code = code
        self.transient = transient


_TRANSIENT_TYPES = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
                    "TransportError", "TimeoutException", "TimeoutError", "ConnectionError"}


def is_transient(exc: Exception) -> bool:
    """True for errors worth retrying: rate limits (429), server errors (5xx), timeouts, dropped connections.
    Bad requests, wrong keys and unknown models (4xx) are not retried."""
    if getattr(exc, "transient", False):
        return True
    code = getattr(exc, "code", None)
    if not isinstance(code, int):
        code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code in (408, 429) or code >= 500
    return any(cls.__name__ in _TRANSIENT_TYPES for cls in type(exc).__mro__)


def max_retries() -> int:
    return int(os.getenv("LLM_MAX_RETRIES", "2"))


def backoff_seconds(attempt: int) -> float:
    """Wait before retry number attempt+1: base, 2x base, 4x base ... (capped), with jitter."""
    base = _env_float("LLM_RETRY_BASE_S", 2.0)
    return min(base * 2 ** attempt, MAX_BACKOFF_S) * random.uniform(0.5, 1.0)


def timeout_seconds() -> float:
    return _env_float("LLM_TIMEOUT_S", 60.0)


def _with_retries_and_fallback(call, counter: dict):
    """Run call(model) on the main model with retries, then once on the fallback model.

    counter gets "attempts", "model_used" and "fallback_used". The last error is raised if all fail.
    """
    models = _models()
    for i, model in enumerate(models):
        last_model = i == len(models) - 1
        retries = max_retries() if i == 0 else 0
        for attempt in range(retries + 1):
            counter["attempts"] = counter.get("attempts", 0) + 1
            counter["model_used"], counter["fallback_used"] = model, i > 0
            try:
                return call(model)
            except Exception as exc:
                if not is_transient(exc) or (last_model and attempt == retries):
                    raise
                if attempt < retries:
                    time.sleep(backoff_seconds(attempt))


# --- cost ---

def price_per_million(fallback: bool = False) -> tuple[float | None, float | None]:
    """(input, output) USD per million tokens from the env; the fallback model may have its own prices."""
    price_in, price_out = _env_float("PRICE_IN_PER_M"), _env_float("PRICE_OUT_PER_M")
    if fallback:
        price_in = _env_float("FALLBACK_PRICE_IN_PER_M", price_in)
        price_out = _env_float("FALLBACK_PRICE_OUT_PER_M", price_out)
    return price_in, price_out


def cost_usd(input_tokens, output_tokens, thinking_tokens=None, fallback: bool = False) -> float | None:
    """Cost of one call, or None when prices or token counts are unknown. Local models cost nothing."""
    if provider() in ("ollama", "mock"):
        return 0.0
    price_in, price_out = price_per_million(fallback)
    if price_in is None or price_out is None or input_tokens is None or output_tokens is None:
        return None
    # Gemini counts thinking tokens separately from output; OpenAI includes them in completion_tokens.
    billed_output = output_tokens + ((thinking_tokens or 0) if provider() == "gemini" else 0)
    return round((input_tokens * price_in + billed_output * price_out) / 1e6, 6)


# --- public API ---

def complete(system: str, user: str, json_mode: bool = False) -> str:
    """Send one system + user message to the configured model and return its text."""
    return complete_with_meta(system, user, json_mode)["text"]


def _check_provider() -> str:
    p = provider()
    if p not in _CALLS:
        raise ValueError(f"Unknown LLM_PROVIDER '{p}'. Use gemini, openai, ollama or mock.")
    return p


def _finish_meta(usage: dict, counter: dict, start: float) -> dict:
    return {**usage, "seconds": round(time.perf_counter() - start, 2),
            "model_used": counter.get("model_used", model_name()),
            "attempts": counter.get("attempts", 0),
            "fallback_used": counter.get("fallback_used", False),
            "cost_usd": cost_usd(usage.get("input_tokens"), usage.get("output_tokens"),
                                 usage.get("thinking_tokens"), counter.get("fallback_used", False))}


def complete_with_meta(system: str, user: str, json_mode: bool = False) -> dict:
    """Like complete(), but also return usage for evaluation: {"text", "input_tokens", "output_tokens",
    "thinking_tokens", "seconds", "model_used", "attempts", "fallback_used", "cost_usd"}.
    Unknown counts are None."""
    call = _CALLS[_check_provider()]
    counter, start = {}, time.perf_counter()
    text, usage = _with_retries_and_fallback(lambda model: call(system, user, json_mode, model), counter)
    return {"text": text, **_finish_meta(usage, counter, start)}


def stream_with_meta(system: str, user: str, meta: dict) -> Iterator[str]:
    """Yield the answer text in chunks as it is generated (plain text, no JSON mode).

    When the generator is exhausted, meta holds the same fields as complete_with_meta (without "text").
    Retries and the fallback model apply until the first chunk arrives; an error after that is raised.
    """
    stream = _STREAMS[_check_provider()]
    counter, usage, start = {}, {}, time.perf_counter()

    def first_chunk(model: str):
        usage.clear()
        chunks = stream(system, user, model, usage)
        return chunks, next(chunks, "")

    chunks, first = _with_retries_and_fallback(first_chunk, counter)
    if first:
        yield first
    yield from chunks
    meta.update(_finish_meta({**_usage(), **usage}, counter, start))


def _usage(input_tokens=None, output_tokens=None, thinking_tokens=None) -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "thinking_tokens": thinking_tokens}


# --- gemini ---

@lru_cache(maxsize=4)
def _gemini_client(api_key: str | None, timeout_s: float):
    from google import genai
    from google.genai import types

    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))


def _gemini_config(system: str, json_mode: bool):
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=system,
        temperature=TEMPERATURE,
        response_mime_type="application/json" if json_mode else "text/plain",
    )


def _gemini_usage(meta) -> dict:
    return _usage(meta.prompt_token_count, meta.candidates_token_count, meta.thoughts_token_count) if meta else _usage()


def _gemini(system: str, user: str, json_mode: bool, model: str) -> tuple[str, dict]:
    client = _gemini_client(os.getenv("GEMINI_API_KEY"), timeout_seconds())
    response = client.models.generate_content(model=model, contents=user, config=_gemini_config(system, json_mode))
    return response.text or "", _gemini_usage(response.usage_metadata)


def _gemini_stream(system: str, user: str, model: str, usage: dict) -> Iterator[str]:
    client = _gemini_client(os.getenv("GEMINI_API_KEY"), timeout_seconds())
    for chunk in client.models.generate_content_stream(model=model, contents=user,
                                                       config=_gemini_config(system, False)):
        if chunk.usage_metadata:  # running totals; the last chunk has the final counts
            usage.update(_gemini_usage(chunk.usage_metadata))
        if chunk.text:
            yield chunk.text


# --- openai ---

@lru_cache(maxsize=4)
def _openai_client(api_key: str | None, timeout_s: float):
    from openai import OpenAI

    # Retries are done here, not by the SDK, so they don't stack.
    return OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)


def _openai_messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _openai_usage(usage) -> dict:
    if not usage:
        return _usage()
    details = usage.completion_tokens_details
    return _usage(usage.prompt_tokens, usage.completion_tokens, details.reasoning_tokens if details else None)


def _openai(system: str, user: str, json_mode: bool, model: str) -> tuple[str, dict]:
    client = _openai_client(os.getenv("OPENAI_API_KEY"), timeout_seconds())
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = client.chat.completions.create(
        model=model, temperature=TEMPERATURE, messages=_openai_messages(system, user), **kwargs)
    return response.choices[0].message.content or "", _openai_usage(response.usage)


def _openai_stream(system: str, user: str, model: str, usage: dict) -> Iterator[str]:
    client = _openai_client(os.getenv("OPENAI_API_KEY"), timeout_seconds())
    stream = client.chat.completions.create(
        model=model, temperature=TEMPERATURE, messages=_openai_messages(system, user),
        stream=True, stream_options={"include_usage": True})
    for chunk in stream:
        if chunk.usage:  # only on the last chunk
            usage.update(_openai_usage(chunk.usage))
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# --- ollama ---

def _ollama_request(system: str, user: str, json_mode: bool, model: str, stream: bool):
    """Local model served by Ollama (https://ollama.com); works without internet."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    body = {
        "model": model,
        "messages": _openai_messages(system, user),
        "stream": stream,
        # Ollama's default context window is small; the equipment list and rules need more room.
        "options": {"temperature": TEMPERATURE, "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192"))},
    }
    if json_mode:
        body["format"] = "json"
    request = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        # Local models can be slow to load, so Ollama gets its own, longer timeout.
        return urllib.request.urlopen(request, timeout=_env_float("OLLAMA_TIMEOUT_S", 300.0))
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"Ollama error {exc.code}: {exc.read().decode(errors='replace')}", exc.code) from exc
    except urllib.error.URLError as exc:
        timed_out = isinstance(exc.reason, TimeoutError)
        raise ProviderError(f"Cannot reach Ollama at {host}. Is it running? ({exc.reason})",
                            transient=timed_out) from exc


def _ollama_usage(data: dict) -> dict:
    return _usage(data.get("prompt_eval_count"), data.get("eval_count"))


def _ollama(system: str, user: str, json_mode: bool, model: str) -> tuple[str, dict]:
    with _ollama_request(system, user, json_mode, model, stream=False) as response:
        data = json.loads(response.read())
    return data["message"]["content"] or "", _ollama_usage(data)


def _ollama_stream(system: str, user: str, model: str, usage: dict) -> Iterator[str]:
    with _ollama_request(system, user, False, model, stream=True) as response:
        for line in response:  # one JSON object per line; the last has done = true and the counts
            data = json.loads(line)
            if data.get("done"):
                usage.update(_ollama_usage(data))
            text = data.get("message", {}).get("content")
            if text:
                yield text


# --- mock provider: canned answers keyed on words in the question, for UI work ---
# MOCK_DELAY_S=3 makes each answer take 3 s (to see parallel Compare and streaming).
# MOCK_FAIL=429:2 makes the next 2 calls fail with error 429 (to try retries, fallback and the demo backup).

_MOCK_ANSWERS = {
    "viscous": {
        "measurement_needs": ["viscosity vs. temperature and shear rate", "thermal transitions", "thermal degradation / moisture"],
        "recommendations": [
            {"instrument_id": "EQ19", "technique_id": "rotational_rheometry", "technique": "Rotational rheology (temperature and shear-rate sweeps)",
             "why": "Shows how viscosity changes with temperature and shear rate.",
             "accessories_to_confirm": ["Temperature-control accessory (e.g. Peltier or environmental test chamber)", "Parallel-plate or cone-and-plate geometry"]},
            {"instrument_id": "EQ18", "technique_id": "differential_scanning_calorimetry", "technique": "Differential scanning calorimetry",
             "why": "Identifies melting, glass transition or crystallization that affects flow.",
             "accessories_to_confirm": ["Suitable pans and lids"]},
            {"instrument_id": "EQ17", "technique_id": "thermogravimetric_analysis", "technique": "Thermogravimetric analysis",
             "why": "Checks for degradation, moisture or filler content.", "accessories_to_confirm": []},
        ],
        "not_available": [
            {"technique_id": "capillary_rheometry", "technique": "Capillary rheometry / melt flow index", "why_useful": "Measures flow under extrusion-like conditions."},
            {"technique_id": "gel_permeation_chromatography", "technique": "Molecular-weight analysis (GPC/SEC)", "why_useful": "Molecular weight strongly controls melt viscosity."},
        ],
        "clarifying_question": None,
        "summary": "Rheology, DSC and TGA together can explain unexpected viscosity. (Mock answer.)",
    },
    "compress": {
        "measurement_needs": ["compressive modulus of a porous scaffold"],
        "recommendations": [
            {"instrument_id": "EQ15", "technique_id": "compression_testing", "technique": "Uniaxial compression testing",
             "why": "Measures the stress-strain response; stiffness is the slope of the linear region.",
             "accessories_to_confirm": ["Load cell with a suitable (low) capacity", "Compression platens"]},
            {"instrument_id": "EQ99", "technique": "Made-up instrument (tests the removal notice)",
             "why": "This ID is not in the dataset.", "accessories_to_confirm": []},
        ],
        "not_available": [{"technique_id": "micro_computed_tomography", "technique": "Micro-CT", "why_useful": "Quantifies porosity and pore structure."}],
        "clarifying_question": None,
        "summary": "Use the Instron 5967 in compression; confirm load cell and platens. (Mock answer.)",
    },
    "internal": {
        "measurement_needs": ["non-destructive 3D imaging of internal pore structure"],
        "recommendations": [
            {"instrument_id": "EQ08", "technique_id": "multiphoton_microscopy", "technique": "Multiphoton microscopy (partial option)",
             "why": "Can image some depth into transparent or fluorescent samples only.",
             "accessories_to_confirm": ["Suitable objectives and laser lines"]},
        ],
        "not_available": [{"technique_id": "micro_computed_tomography", "technique": "Micro-CT", "why_useful": "Standard non-destructive method for internal 3D structure."}],
        "clarifying_question": None,
        "summary": "No fully suitable instrument is available. Micro-CT is not in the dataset. (Mock answer.)",
    },
}

_MOCK_CLARIFY = {
    "measurement_needs": [],
    "recommendations": [],
    "not_available": [],
    "clarifying_question": "What material is the sample, and what property do you want to measure? (Mock answer.)",
    "summary": "The question needs more detail before equipment can be suggested.",
}

_mock_lock = threading.Lock()
_mock_failed = {"spec": "", "count": 0}


def _mock_maybe_fail() -> None:
    """Fail while fewer than N calls have failed for the current MOCK_FAIL=<code>:<N> setting."""
    spec = os.getenv("MOCK_FAIL", "").strip()
    if not spec:
        return
    code, _, times = spec.partition(":")
    with _mock_lock:
        if _mock_failed["spec"] != spec:  # a new setting starts a new count
            _mock_failed.update(spec=spec, count=0)
        if _mock_failed["count"] >= int(times or 1):
            return
        _mock_failed["count"] += 1
    raise ProviderError(f"Mock error {code} (MOCK_FAIL={spec})", int(code))


def _mock_text(user: str, json_mode: bool) -> str:
    # The question is the last part of the user message; search only that part.
    question = user.rsplit("Question:", 1)[-1].lower()
    answer = next((a for key, a in _MOCK_ANSWERS.items() if key in question), _MOCK_CLARIFY)
    if json_mode:
        return json.dumps(answer, indent=2)
    lines = [answer["summary"], ""]
    for rec in answer["recommendations"]:
        lines.append(f"- **{rec['instrument_id']}**: {rec['technique']}. {rec['why']}")
    ids = ", ".join(rec["instrument_id"] for rec in answer["recommendations"]) or "none"
    lines += ["", f"Recommended: {ids}"]
    return "\n".join(lines)


def _mock(system: str, user: str, json_mode: bool, model: str) -> tuple[str, dict]:
    _mock_maybe_fail()
    time.sleep(_env_float("MOCK_DELAY_S", 0.0))
    return _mock_text(user, json_mode), _usage()


def _mock_stream(system: str, user: str, model: str, usage: dict) -> Iterator[str]:
    _mock_maybe_fail()
    words = _mock_text(user, False).split(" ")
    pause = _env_float("MOCK_DELAY_S", 0.0) / max(len(words), 1)
    for i, word in enumerate(words):
        time.sleep(pause)
        yield word if i == 0 else " " + word


_CALLS = {"gemini": _gemini, "openai": _openai, "ollama": _ollama, "mock": _mock}
_STREAMS = {"gemini": _gemini_stream, "openai": _openai_stream, "ollama": _ollama_stream, "mock": _mock_stream}
