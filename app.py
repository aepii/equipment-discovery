"""Streamlit interface. Run with: streamlit run app.py"""

import hmac
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import streamlit as st


def load_secrets() -> None:
    """Copy Streamlit secrets (used when deployed) into the environment; locally .env is used instead."""
    try:
        secrets = dict(st.secrets)
    except Exception:  # no secrets.toml: running locally with .env
        return
    for key, value in secrets.items():
        if isinstance(value, (str, int, float)):
            os.environ[key] = str(value)


load_secrets()

import core  # noqa: E402  (imported after secrets so llm sees the deployed settings)
import knowledge  # noqa: E402
import llm  # noqa: E402
import runtime  # noqa: E402
import store  # noqa: E402

EXAMPLES = {
    "Viscous polymer": "My polymer remains unexpectedly viscous during extrusion at elevated temperatures. "
                       "What measurements could help me understand why?",
    "Scaffold stiffness": "I want to determine the compressive stiffness of a porous polymer scaffold. "
                          "What equipment could I use?",
    "Internal structure": "I need to examine the internal structure of a porous specimen without destroying it. "
                          "What characterization methods are available?",
}
# Sidebar choice -> modes to run (several are shown side by side).
MODES = {
    "Structured": ["structured"],
    "Structured + annotations": ["annotated"],
    "Naive": ["naive"],
    "Compare structured and naive": ["structured", "naive"],
    "Compare all three": ["structured", "annotated", "naive"],
}
MODE_LABELS = {"structured": "Structured", "annotated": "Structured + annotations", "naive": "Naive"}
RUNNERS = {"structured": core.run_structured, "annotated": core.run_annotated, "naive": core.run_naive}
RATINGS = ["Good", "Partly", "Wrong"]


def set_question(text: str) -> None:
    st.session_state["question"] = text


def password_ok() -> bool:
    """Shared-password gate so the public link does not spend API credits. Off when APP_PASSWORD is unset."""
    expected = os.getenv("APP_PASSWORD", "")
    if not expected or st.session_state.get("authenticated"):
        return True
    entered = st.text_input("Password", type="password")
    if entered and hmac.compare_digest(entered, expected):
        st.session_state["authenticated"] = True
        st.rerun()
    if entered:
        st.error("Wrong password.")
    return False


@st.cache_resource
def answer_cache() -> runtime.AnswerCache:
    """One cache for all sessions, in the server's memory (emptied when the app restarts)."""
    return runtime.AnswerCache()


@st.cache_resource
def daily_budget() -> runtime.DailyBudget:
    return runtime.DailyBudget()


def render_sidebar() -> str:
    with st.sidebar:
        mode = st.radio("Mode", list(MODES))
        st.text_input("Your name (optional, shown with your feedback)", key="rater")
        st.checkbox("Skip cache (ask the model again)", key="skip_cache")
        fallback = llm.fallback_model_name()
        st.caption(f"Provider: `{llm.provider()}`  \nModel: `{llm.model_name()}`"
                   + (f"  \nFallback model: `{fallback}`" if fallback else "")
                   + f"  \nLogging to: {store.destination()}")
        if runtime.flag("DEMO_OFFLINE"):
            st.warning("Offline demo mode: answers come from saved answers only.")
        max_calls = runtime.max_calls_per_session()
        st.caption(f"This session: {st.session_state['calls']} model calls"
                   + (f" of {max_calls}" if max_calls else "")
                   + f", ${st.session_state['cost']:.4f}  \n"
                   + f"Today, all users: ${daily_budget().spent():.4f}"
                   + (f" of ${runtime.daily_budget_usd():.2f}" if runtime.daily_budget_usd() else ""))
        with st.expander(f"Equipment in the dataset ({len(core.load_equipment())})"):
            st.dataframe(
                [{"ID": e["id"], "Instrument": e["instrument"], "Location": e["location"],
                  "Typical techniques (draft)": "; ".join(knowledge.technique_name(t)
                                                          for t in knowledge.techniques_of(e["id"]))}
                 for e in core.load_equipment()],
                hide_index=True,
            )
    return mode


def render_recommendation(rec: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{rec['instrument']}** · {rec['manufacturer']} {rec['model']} · `{rec['id']}`")
        st.markdown(f"**Technique:** {rec['technique']}")
        st.markdown(rec["why"])
        if rec.get("destructive"):
            st.markdown(f"**Destructive:** {rec['destructive']}")
        st.markdown(f"**Location:** {rec['location']}  \n**Contact (fictional):** {rec['contact']}")
        if rec["accessories_to_confirm"]:
            st.warning("**Confirm with the contact:** " + "; ".join(rec["accessories_to_confirm"]))
        for caution in rec.get("cautions", []):
            st.error(caution)
        if rec.get("notes_status") == "draft":
            st.caption("Instrument notes are a draft and not yet reviewed by the faculty mentor.")


def render_source(result: dict) -> None:
    """Where the answer came from, and what it took, when that is not just one live call."""
    usage = result.get("usage") or {}
    if result.get("source") == "demo_backup":
        demo = result["demo"]
        reason = f" The live model could not be used: {result['notice']}" if result.get("notice") else ""
        st.info(f"Showing a saved answer recorded {demo['recorded_at'][:10]} with `{demo['model']}`.{reason}")
        if demo["stale"]:
            st.warning("The prompt or dataset has changed since this answer was saved.")
        return
    if result.get("source") == "cache":
        st.caption("Shown again from the cache: this question was answered earlier with the same model.")
    if usage.get("fallback_used"):
        st.caption(f"The main model was unavailable; answered by the fallback model `{usage['model_used']}`.")
    if result.get("repaired"):
        st.caption("The model's first answer was not usable JSON; it was asked once to fix the format.")
    parts = [f"{usage['seconds']:.1f} s" if usage.get("seconds") is not None else "",
             f"{usage['output_tokens']:,} output tokens" if usage.get("output_tokens") is not None else "",
             f"${usage['cost_usd']:.4f}" if usage.get("cost_usd") else ""]
    if any(parts) and result.get("source") == "live":
        st.caption(" · ".join(p for p in parts if p))


def render_structured(result: dict) -> None:
    if result["error"]:
        st.error(f"Could not get an answer: {result['error']}")
    else:
        if result.get("clarifying_question"):
            st.info(f"**Please clarify:** {result['clarifying_question']}")
        if result.get("summary"):
            st.markdown(result["summary"])
        if result.get("measurement_needs"):
            st.markdown("**What needs to be measured**")
            st.markdown("\n".join(f"- {need}" for need in result["measurement_needs"]))
        if result["removed"]:
            st.error("Removed recommendation(s) naming an instrument not in the dataset: "
                     + ", ".join(result["removed"]))
        if result["recommendations"]:
            st.markdown("**Recommended equipment**")
            for rec in result["recommendations"]:
                render_recommendation(rec)
        elif not result.get("clarifying_question"):
            st.warning("No suitable equipment was found in the dataset.")
        if result.get("not_available"):
            st.markdown("**Suitable techniques not available in the dataset**")
            st.markdown("\n".join(f"- **{n.get('technique', '')}**: {n.get('why_useful', '')}"
                                  for n in result["not_available"]))
            for n in result["not_available"]:
                if n.get("available_on"):
                    st.error(f"{n.get('technique', '')} is listed as not available, but the instrument notes "
                             f"list it for {', '.join(n['available_on'])}.")
    with st.expander("Raw model output"):
        st.code(result["raw"] or "(empty)", language="json")


def render_naive(result: dict) -> None:
    if result["error"]:
        st.error(f"Could not get an answer: {result['error']}")
    else:
        st.markdown(result["raw"])


def render_feedback(answer: dict) -> None:
    """Feedback on one answer: overall rating, per-instrument ratings, missed instruments, gaps."""
    row, result = answer["row"], answer["result"]
    answer_id = row["answer_id"]
    if answer_id in st.session_state.setdefault("feedback_sent", set()):
        st.success("Thanks, your feedback was saved.")
        return
    known = core.equipment_by_id()

    def label(eq_id: str) -> str:
        return f"{eq_id} · {known[eq_id]['instrument']}"

    with st.form(f"feedback_{answer_id}"):
        st.markdown("**Rate this answer** (all fields optional)")
        overall = st.radio("Overall", ["Good", "Bad"], index=None, horizontal=True, key=f"{answer_id}_overall")
        comment = st.text_area("Why?", height=68, key=f"{answer_id}_comment")
        ratings = {}
        if result["instrument_ids"]:
            st.markdown("Each instrument in the answer:")
            for eq_id in result["instrument_ids"]:
                ratings[eq_id] = st.radio(label(eq_id), RATINGS, index=None, horizontal=True,
                                          key=f"{answer_id}_{eq_id}")
        missing = st.multiselect("Instruments that should have been recommended",
                                 [eq_id for eq_id in known if eq_id not in result["instrument_ids"]],
                                 format_func=label, key=f"{answer_id}_missing")
        gaps_ok = st.radio("Were the techniques it called not available in the dataset right?",
                           ["Yes", "Partly", "No", "Not applicable"], index=None, horizontal=True,
                           key=f"{answer_id}_gaps")
        gaps_comment = st.text_input("What was missing or wrong there?", key=f"{answer_id}_gaps_comment")
        if st.form_submit_button("Submit feedback"):
            rated = {eq_id: rating for eq_id, rating in ratings.items() if rating}
            store.save("feedback", store.feedback_row(
                row, st.session_state.get("rater", "").strip(), overall or "", comment.strip(), rated,
                missing, gaps_ok or "", gaps_comment.strip()))
            st.session_state["feedback_sent"].add(answer_id)
            st.rerun()


def cache_key(mode: str, question: str) -> tuple:
    """A new model, prompt or dataset never reuses an old answer."""
    return (mode, core.normalize_question(question), llm.provider(), llm.model_name(),
            core.prompt_version(mode), core.dataset_version())


def saved_or_error(mode: str, question: str, reason: str) -> dict:
    """The saved demo answer for this question, labelled with why it is shown; else the reason as an error."""
    saved = core.demo_answer(mode, question)
    if saved:
        saved["notice"] = reason
        return saved
    result = core.new_result(mode)
    result["error"] = reason
    return result


def run_live(question: str, modes: list[str], stream_box) -> dict[str, dict]:
    """Call the model for each mode at the same time. With a stream_box, naive streams its text into it
    from this thread (Streamlit can only draw from here) while the other mode runs in a worker thread."""
    stream = "naive" in modes and stream_box is not None
    threaded = [mode for mode in modes if not (stream and mode == "naive")]
    results = {}
    with ThreadPoolExecutor(max_workers=max(len(threaded), 1)) as pool:
        futures = {mode: pool.submit(RUNNERS[mode], question) for mode in threaded}
        if stream:
            results["naive"] = {}
            with stream_box:
                st.write_stream(core.stream_naive(question, results["naive"]))
        for mode, future in futures.items():
            results[mode] = future.result()
    return results


def get_answers(question: str, modes: list[str], stream_box=None) -> dict[str, dict]:
    """Answers from, in order: the cache, the model (with retries and fallback model), the saved demo
    answers. Spending limits apply only to model calls."""
    if runtime.flag("DEMO_OFFLINE"):
        return {mode: saved_or_error(mode, question, "Offline demo mode answers only the saved questions; "
                                                     "try one of the example buttons.") for mode in modes}
    results = {}
    if not st.session_state.get("skip_cache"):
        for mode in modes:
            hit = answer_cache().get(cache_key(mode, question))
            if hit:
                results[mode] = {**hit, "source": "cache"}
    live = [mode for mode in modes if mode not in results]
    if not live:
        return results
    blocked = runtime.limit_reason(st.session_state["calls"], len(live), daily_budget().spent())
    if blocked:
        return {**results, **{mode: saved_or_error(mode, question, blocked) for mode in live}}

    st.session_state["calls"] += len(live)
    for mode, result in run_live(question, live, stream_box).items():
        cost = result["usage"].get("cost_usd") or 0.0
        st.session_state["cost"] += cost
        daily_budget().add(cost)
        if not result["error"]:
            answer_cache().put(cache_key(mode, question), result)
        elif runtime.flag("DEMO_BACKUP", default=True) and core.demo_answer(mode, question):
            result = saved_or_error(mode, question, result["error"])
        results[mode] = result
    return results


def ask(question: str, modes: list[str], stream_box=None) -> list[dict]:
    """Answer the question in each mode and log every answer (cached and saved ones too, by source)."""
    results = get_answers(question, modes, stream_box)
    answers = []
    for mode in modes:
        result = results[mode]
        row = store.answer_row(question, result, session_id=st.session_state["session_id"],
                               rater=st.session_state.get("rater", "").strip(),
                               from_example=question in EXAMPLES.values())
        store.save("answers", row)
        answers.append({"result": result, "row": row})
    return answers


def stream_box_for(modes: list[str]):
    """Where the naive answer streams while it is generated, laid out like the final answers; None
    if streaming is off or naive is not asked."""
    if "naive" not in modes or not runtime.flag("STREAM_NAIVE", default=True):
        return None
    if len(modes) == 1:
        return st.container()
    box = None
    for column, mode in zip(st.columns(len(modes)), modes):
        column.subheader(MODE_LABELS[mode])
        if mode == "naive":
            box = column.container()
        else:
            column.caption(f"Waiting for the {MODE_LABELS[mode].lower()} answer...")
    return box


def render_answer(answer: dict) -> None:
    result = answer["result"]
    render_source(result)
    if result["mode"] in core.JSON_MODES:
        render_structured(result)
    else:
        render_naive(result)
    if not result["error"]:
        render_feedback(answer)


def main() -> None:
    st.set_page_config(page_title="Equipment Discovery", layout="wide")
    if not password_ok():
        return
    st.session_state.setdefault("session_id", uuid.uuid4().hex[:8])
    st.session_state.setdefault("calls", 0)
    st.session_state.setdefault("cost", 0.0)
    mode = render_sidebar()

    st.title("UMKC Research Equipment Discovery")
    st.write("Describe your research or measurement problem in plain language. "
             "You do not need to know which technique or instrument you need.")
    st.caption("Questions, answers and feedback are logged to help evaluate this prototype. "
               "Please do not enter confidential information.")

    cols = st.columns(len(EXAMPLES))
    for col, (label, text) in zip(cols, EXAMPLES.items()):
        col.button(label, on_click=set_question, args=(text,), use_container_width=True)

    question = st.text_area("Your question", key="question", height=100)
    if st.button("Find equipment", type="primary"):
        if not question.strip():
            st.warning("Please enter a question.")
            return
        modes = MODES[mode]
        stream_box = stream_box_for(modes)
        with st.spinner("Asking the model..."):
            st.session_state["answers"] = ask(question.strip(), modes, stream_box)
        st.rerun()  # redraw from the session so the streamed text is replaced by the full answer

    # Answers are kept in the session so they stay on screen while feedback is given.
    answers = st.session_state.get("answers", [])
    if len(answers) > 1:
        for column, answer in zip(st.columns(len(answers)), answers):
            with column:
                st.subheader(MODE_LABELS[answer["result"]["mode"]])
                render_answer(answer)
    elif answers:
        render_answer(answers[0])

main()
