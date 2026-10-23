"""Streamlit interface. Run with: streamlit run app.py"""

import streamlit as st

import core
import llm

EXAMPLES = {
    "Viscous polymer": "My polymer remains unexpectedly viscous during extrusion at elevated temperatures. "
                       "What measurements could help me understand why?",
    "Scaffold stiffness": "I want to determine the compressive stiffness of a porous polymer scaffold. "
                          "What equipment could I use?",
    "Internal structure": "I need to examine the internal structure of a porous specimen without destroying it. "
                          "What characterization methods are available?",
}
MODES = ["Structured", "Naive", "Compare both"]


def set_question(text: str) -> None:
    st.session_state["question"] = text


def render_sidebar() -> str:
    with st.sidebar:
        mode = st.radio("Mode", MODES)
        st.caption(f"Provider: `{llm.provider()}`  \nModel: `{llm.model_name()}`")
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


def main() -> None:
    st.set_page_config(page_title="Equipment Discovery", layout="wide")
    mode = render_sidebar()

    st.title("UMKC Research Equipment Discovery")
    st.write("Describe your research or measurement problem in plain language. "
             "You do not need to know which technique or instrument you need.")

    cols = st.columns(len(EXAMPLES))
    for col, (label, text) in zip(cols, EXAMPLES.items()):
        col.button(label, on_click=set_question, args=(text,), use_container_width=True)

    question = st.text_area("Your question", key="question", height=100)
    if not st.button("Find equipment", type="primary"):
        return
    if not question.strip():
        st.warning("Please enter a question.")
        return

    if mode == "Compare both":
        left, right = st.columns(2)
        with left:
            st.subheader("Structured")
            with st.spinner("Asking the model..."):
                render_structured(core.run_structured(question))
        with right:
            st.subheader("Naive")
            with st.spinner("Asking the model..."):
                render_naive(core.run_naive(question))
    elif mode == "Structured":
        with st.spinner("Asking the model..."):
            render_structured(core.run_structured(question))
    else:
        with st.spinner("Asking the model..."):
            render_naive(core.run_naive(question))


main()
