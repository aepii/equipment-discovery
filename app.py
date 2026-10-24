"""Streamlit interface. Run with: streamlit run app.py"""

import hmac
import os
import uuid

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
import llm  # noqa: E402
import store  # noqa: E402

EXAMPLES = {
    "Viscous polymer": "My polymer remains unexpectedly viscous during extrusion at elevated temperatures. "
                       "What measurements could help me understand why?",
    "Scaffold stiffness": "I want to determine the compressive stiffness of a porous polymer scaffold. "
                          "What equipment could I use?",
    "Internal structure": "I need to examine the internal structure of a porous specimen without destroying it. "
                          "What characterization methods are available?",
}
MODES = ["Structured", "Naive", "Compare both"]
RUNNERS = {"structured": core.run_structured, "naive": core.run_naive}
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


def render_sidebar() -> str:
    with st.sidebar:
        mode = st.radio("Mode", MODES)
        st.text_input("Your name (optional, shown with your feedback)", key="rater")
        st.caption(f"Provider: `{llm.provider()}`  \nModel: `{llm.model_name()}`  \n"
                   f"Logging to: {store.destination()}")
        with st.expander(f"Equipment in the dataset ({len(core.load_equipment())})"):
            st.dataframe(
                [{"ID": e["id"], "Instrument": e["instrument"], "Location": e["location"]}
                 for e in core.load_equipment()],
                hide_index=True,
            )
    return mode


def render_recommendation(rec: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{rec['instrument']}** · {rec['manufacturer']} {rec['model']} · `{rec['id']}`")
        st.markdown(f"**Technique:** {rec['technique']}")
        st.markdown(rec["why"])
        st.markdown(f"**Location:** {rec['location']}  \n**Contact (fictional):** {rec['contact']}")
        if rec["accessories_to_confirm"]:
            st.warning("**Confirm with the contact:** " + "; ".join(rec["accessories_to_confirm"]))


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


def ask(question: str, modes: list[str]) -> list[dict]:
    """Run the question in each mode and log every answer."""
    answers = []
    for mode in modes:
        result = RUNNERS[mode](question)
        row = store.answer_row(question, result, session_id=st.session_state["session_id"],
                               rater=st.session_state.get("rater", "").strip(),
                               from_example=question in EXAMPLES.values())
        store.save("answers", row)
        answers.append({"result": result, "row": row})
    return answers


def render_answer(answer: dict) -> None:
    result = answer["result"]
    if result["mode"] == "structured":
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
        modes = {"Structured": ["structured"], "Naive": ["naive"]}.get(mode, ["structured", "naive"])
        with st.spinner("Asking the model..."):
            st.session_state["answers"] = ask(question.strip(), modes)

    # Answers are kept in the session so they stay on screen while feedback is given.
    answers = st.session_state.get("answers", [])
    if len(answers) == 2:
        for column, answer in zip(st.columns(2), answers):
            with column:
                st.subheader(answer["result"]["mode"].capitalize())
                render_answer(answer)
    elif answers:
        render_answer(answers[0])

main()
