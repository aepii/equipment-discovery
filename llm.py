"""All model calls go through complete(). Provider is chosen by LLM_PROVIDER in .env."""

import json
import os
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

TEMPERATURE = 0.1


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


def complete(system: str, user: str, json_mode: bool = False) -> str:
    """Send one system + user message to the configured model and return its text."""
    return complete_with_meta(system, user, json_mode)["text"]


def complete_with_meta(system: str, user: str, json_mode: bool = False) -> dict:
    """Like complete(), but also return usage for evaluation:
    {"text", "input_tokens", "output_tokens", "thinking_tokens", "seconds"}. Unknown counts are None."""
    calls = {"gemini": _gemini, "openai": _openai, "ollama": _ollama, "mock": _mock}
    p = provider()
    if p not in calls:
        raise ValueError(f"Unknown LLM_PROVIDER '{p}'. Use gemini, openai, ollama or mock.")
    start = time.perf_counter()
    text, usage = calls[p](system, user, json_mode)
    return {"text": text, **usage, "seconds": round(time.perf_counter() - start, 2)}


def _usage(input_tokens=None, output_tokens=None, thinking_tokens=None) -> dict:
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "thinking_tokens": thinking_tokens}


def _gemini(system: str, user: str, json_mode: bool) -> tuple[str, dict]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=TEMPERATURE,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    response = client.models.generate_content(model=model_name(), contents=user, config=config)
    meta = response.usage_metadata
    usage = _usage(meta.prompt_token_count, meta.candidates_token_count, meta.thoughts_token_count) if meta else _usage()
    return response.text or "", usage


def _openai(system: str, user: str, json_mode: bool) -> tuple[str, dict]:
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = client.chat.completions.create(
        model=model_name(),
        temperature=TEMPERATURE,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        **kwargs,
    )
    usage = _usage()
    if response.usage:
        details = response.usage.completion_tokens_details
        usage = _usage(response.usage.prompt_tokens, response.usage.completion_tokens,
                       details.reasoning_tokens if details else None)
    return response.choices[0].message.content or "", usage


def _ollama(system: str, user: str, json_mode: bool) -> tuple[str, dict]:
    """Local model served by Ollama (https://ollama.com); works without internet."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    body = {
        "model": model_name(),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        # Ollama's default context window is small; the equipment list and rules need more room.
        "options": {"temperature": TEMPERATURE, "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192"))},
    }
    if json_mode:
        body["format"] = "json"
    request = urllib.request.Request(
        f"{host}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Ollama error {exc.code}: {exc.read().decode(errors='replace')}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach Ollama at {host}. Is it running? ({exc.reason})") from exc
    usage = _usage(data.get("prompt_eval_count"), data.get("eval_count"))
    return data["message"]["content"] or "", usage


# --- mock provider: canned answers keyed on words in the question, for UI work ---

_MOCK_ANSWERS = {
    "viscous": {
        "measurement_needs": ["viscosity vs. temperature and shear rate", "thermal transitions", "thermal degradation / moisture"],
        "recommendations": [
            {"instrument_id": "EQ19", "technique": "Rotational rheology (temperature and shear-rate sweeps)",
             "why": "Shows how viscosity changes with temperature and shear rate.",
             "accessories_to_confirm": ["Temperature-control accessory (e.g. Peltier or environmental test chamber)", "Parallel-plate or cone-and-plate geometry"]},
            {"instrument_id": "EQ18", "technique": "Differential scanning calorimetry",
             "why": "Identifies melting, glass transition or crystallization that affects flow.",
             "accessories_to_confirm": ["Suitable pans and lids"]},
            {"instrument_id": "EQ17", "technique": "Thermogravimetric analysis",
             "why": "Checks for degradation, moisture or filler content.", "accessories_to_confirm": []},
        ],
        "not_available": [
            {"technique": "Capillary rheometry / melt flow index", "why_useful": "Measures flow under extrusion-like conditions."},
            {"technique": "Molecular-weight analysis (GPC/SEC)", "why_useful": "Molecular weight strongly controls melt viscosity."},
        ],
        "clarifying_question": None,
        "summary": "Rheology, DSC and TGA together can explain unexpected viscosity. (Mock answer.)",
    },
    "compress": {
        "measurement_needs": ["compressive modulus of a porous scaffold"],
        "recommendations": [
            {"instrument_id": "EQ15", "technique": "Uniaxial compression testing",
             "why": "Measures the stress-strain response; stiffness is the slope of the linear region.",
             "accessories_to_confirm": ["Load cell with a suitable (low) capacity", "Compression platens"]},
            {"instrument_id": "EQ99", "technique": "Made-up instrument (tests the removal notice)",
             "why": "This ID is not in the dataset.", "accessories_to_confirm": []},
        ],
        "not_available": [{"technique": "Micro-CT", "why_useful": "Quantifies porosity and pore structure."}],
        "clarifying_question": None,
        "summary": "Use the Instron 5967 in compression; confirm load cell and platens. (Mock answer.)",
    },
    "internal": {
        "measurement_needs": ["non-destructive 3D imaging of internal pore structure"],
        "recommendations": [
            {"instrument_id": "EQ08", "technique": "Multiphoton microscopy (partial option)",
             "why": "Can image some depth into transparent or fluorescent samples only.",
             "accessories_to_confirm": ["Suitable objectives and laser lines"]},
        ],
        "not_available": [{"technique": "Micro-CT", "why_useful": "Standard non-destructive method for internal 3D structure."}],
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


def _mock(system: str, user: str, json_mode: bool) -> tuple[str, dict]:
    # The question is the last part of the user message; search only that part.
    question = user.rsplit("Question:", 1)[-1].lower()
    answer = next((a for key, a in _MOCK_ANSWERS.items() if key in question), _MOCK_CLARIFY)
    if json_mode:
        return json.dumps(answer, indent=2), _usage()
    lines = [answer["summary"], ""]
    for rec in answer["recommendations"]:
        lines.append(f"- **{rec['instrument_id']}**: {rec['technique']}. {rec['why']}")
    ids = ", ".join(rec["instrument_id"] for rec in answer["recommendations"]) or "none"
    lines += ["", f"Recommended: {ids}"]
    return "\n".join(lines), _usage()
