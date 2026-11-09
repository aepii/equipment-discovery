"""Graph matching (GRAPH_MATCH=1): instruments the knowledge graph says can also measure what the answer asks
about are added as supplementary recommendations, never as primary ones."""

import json

import pytest

import answer_graph
import core
import run_eval
from api import presentation


def annotated(recs, **extra) -> dict:
    return core.read_answer("annotated", json.dumps({"recommendations": recs, "summary": "s", **extra}))


def rec(eq_id, technique_id, property_id, role="primary") -> dict:
    return {"instrument_id": eq_id, "technique_id": technique_id, "property_id": property_id, "role": role,
            "technique": "t", "why": "w", "accessories_to_confirm": []}


RHEOMETER = rec("EQ19", "rotational_rheometry", "viscosity_vs_temperature")
MICROSCOPE = rec("EQ12", "widefield_fluorescence_microscopy", "cell_morphology")


@pytest.fixture
def graph_on(monkeypatch):
    monkeypatch.setenv("GRAPH_MATCH", "1")


def test_nothing_is_added_when_the_flag_is_off(monkeypatch):
    monkeypatch.delenv("GRAPH_MATCH", raising=False)
    result = annotated([RHEOMETER])
    assert result["instrument_ids"] == ["EQ19"] and result["graph_added"] == []
    assert result["recommendations"][0]["source"] == "model"


def test_an_instrument_the_model_missed_is_added_as_supplementary(graph_on):
    result = annotated([RHEOMETER])
    assert result["graph_added"] == ["EQ21"]  # the second HR20
    added = result["recommendations"][1]
    assert added["source"] == "graph" and added["role"] == "supplementary"
    assert added["why"] == core.GRAPH_REASON and added["technique_id"] == "rotational_rheometry"
    assert added["fit"] in ("high", "medium")  # rated as a main pick: it can perform the measurement
    assert any("geometr" in a.lower() for a in added["accessories_to_confirm"])  # from its annotation
    assert result["primary_ids"] == ["EQ19"] and result["supplementary_ids"] == ["EQ21"]
    assert result["instrument_ids"] == ["EQ19", "EQ21"] and result["objective_met"] is True


def test_cap_and_notice(graph_on):
    result = annotated([MICROSCOPE])
    assert result["graph_added"] == ["EQ07", "EQ08"]
    assert result["graph_more"] == {"cell_morphology": ["EQ09", "EQ13", "EQ22", "EQ23"]}
    assert result["graph_notices"] == ["4 more instruments can also measure cell morphology: EQ09, EQ13, EQ22, EQ23."]


def test_conditions_exclude_an_instrument(graph_on):
    # Cells on a titanium disc: transmitted light is ruled out, the inverted stands are only partial.
    result = annotated([MICROSCOPE], sample_conditions=["opaque_sample"])
    assert result["graph_added"] == ["EQ08"] and result["graph_notices"] == []


def test_low_confidence_and_preparation_steps_are_never_added(graph_on):
    pairs = core.graph_candidates("solid_viscoelastic_properties")  # DMA on the rheometers is low confidence
    assert pairs == []
    assert all(eq not in ("EQ01", "EQ05", "EQ16") for eq, _ in core.graph_candidates("compressive_modulus"))


def test_no_property_means_nothing_added(graph_on):
    result = annotated([rec("EQ15", "compression_testing", None)], measurement_needs=["how stiff it is"])
    assert result["graph_added"] == []


def test_measurement_needs_that_name_a_property_count(graph_on):
    result = annotated([rec("EQ15", "compression_testing", None)], measurement_needs=["Viscosity vs. temperature"])
    assert result["graph_added"] == ["EQ19", "EQ21"]


def test_a_partial_answer_gets_no_full_alternative_that_does_not_exist(graph_on):
    # Q3: internal structure; only micro-CT (not in the dataset) measures it fully.
    result = annotated([rec("EQ08", "confocal_microscopy", "internal_3d_structure", role="supplementary")])
    assert result["graph_added"] == [] and result["objective_met"] is False


def test_source_reaches_the_payload_and_the_graph(graph_on):
    result = annotated([RHEOMETER])
    payload = presentation.sanitize(result)
    assert [c["source"] for c in payload["primary"]] == ["model"]
    assert [(c["id"], c["source"]) for c in payload["complementary"]] == [("EQ21", "graph")]
    assert presentation.sanitize(annotated([MICROSCOPE]))["graph_notices"][0].startswith("4 more")
    graph = answer_graph.build_graph(result)
    labels = {e["target"]: e["label"] for e in graph["edges"] if e["target"].startswith("i:")}
    assert labels == {"i:EQ19": "performed on", "i:EQ21": "added by graph"}
    node = next(n for n in graph["nodes"] if n["id"] == "i:EQ21")
    assert "added by graph" in node["label"] and node["border"] == answer_graph.GRAPH_ADDED[1]


def test_eval_counts_added_and_shown_instruments(graph_on):
    question = {"id": "QX", "category": "problem-only", "expected_ids": ["EQ19"], "expected_not_available": []}
    scores = run_eval.score(question, annotated([RHEOMETER]))
    assert scores["graph_added"] == 1 and scores["n_instruments"] == 2 and scores["graph_added_ids"] == "EQ21"
    assert scores["recall"] == 1.0  # recall counts primary picks only
    summary = run_eval.summarize_group([{**scores, "error": "", "json_ok": True, "repaired": False, "mode": "annotated",
                                         "seconds": 1, "output_tokens": 1, "recall": 1.0}])
    assert summary["mean_instruments"] == 2 and summary["mean_graph_added"] == 1
