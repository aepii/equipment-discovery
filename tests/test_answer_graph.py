"""The knowledge-graph view of one annotated answer."""

import json
import re

import answer_graph
import core


def annotated(recs, **extra) -> dict:
    return core.read_answer("annotated", json.dumps({"recommendations": recs, "summary": "s", **extra}))


def rec(eq_id, technique_id, property_id="", role="primary", **extra) -> dict:
    return {"instrument_id": eq_id, "technique_id": technique_id, "property_id": property_id, "role": role,
            "technique": "t", "why": "w", **extra}


def edges(dot: str) -> list[tuple[str, str, str]]:
    return re.findall(r'^"([^"]+)" -> "([^"]+)" \[label="([^"]*)"', dot, flags=re.M)


def well_formed(dot: str) -> None:
    """Every edge joins declared nodes, and the braces balance."""
    nodes = set(re.findall(r'^"([^"]+)" \[label=', dot, flags=re.M))
    assert dot.startswith("digraph") and dot.count("{") == dot.count("}")
    for a, b, _ in edges(dot):
        assert a in nodes and b in nodes, (a, b)


def test_only_annotated_answers_with_content_get_a_graph():
    assert answer_graph.build_dot(core.read_answer("structured", json.dumps({"recommendations": []}))) == ""
    assert answer_graph.build_dot(annotated([])) == ""
    assert answer_graph.build_dot({**annotated([rec("EQ15", "compression_testing")]), "error": "x"}) == ""


def test_question_property_technique_instrument_and_accessories():
    result = annotated([rec("EQ15", "compression_testing", "compressive_modulus")])
    dot = answer_graph.build_dot(result)
    well_formed(dot)
    assert ("q", "p:compressive_modulus", "asks about") in edges(dot)
    assert ("p:compressive_modulus", "t:compression_testing", "measured by") in edges(dot)
    assert ("t:compression_testing", "i:EQ15", "performed on") in edges(dot)
    contact = core.equipment_by_id()["EQ15"]["contact"]
    assert contact in dot and "medium fit" in dot and "Confirm with contact" in dot


def test_unavailable_technique_hangs_off_the_property_it_would_measure():
    """Q20: the ESEM is only complementary; AFM would measure the roughness and is not in the dataset."""
    result = annotated(
        [rec("EQ10", "scanning_electron_microscopy", "surface_roughness", role="supplementary")],
        not_available=[{"technique_id": "atomic_force_microscopy", "technique": "AFM", "why_useful": "u"}])
    dot = answer_graph.build_dot(result)
    well_formed(dot)
    assert ("p:surface_roughness", "t:atomic_force_microscopy", "would be measured by") in edges(dot)
    assert "AFM\\nNOT IN DATASET" in dot
    assert "Complementary only" in dot and "low fit" in dot


def test_dead_end_and_its_missing_follow_up():
    """Q23: milling alone, with XRD (what the powder is for) not in the dataset."""
    dot = answer_graph.build_dot(annotated([rec("EQ05", "milling")]))
    well_formed(dot)
    assert "DEAD END" in dot
    assert ("t:milling", "t:x_ray_diffraction", "leads to") in edges(dot)
    assert ("q", "t:milling", "uses") in edges(dot)  # preparation measures nothing


def test_prerequisite_steps_name_where_they_are_done():
    dot = answer_graph.build_dot(annotated([rec("EQ11", "transmission_electron_microscopy")]))
    well_formed(dot)
    assert ("t:ultramicrotomy", "t:transmission_electron_microscopy", "may come first") in edges(dot)
    assert "EQ16" in dot


def test_labels_are_escaped_and_wrapped():
    assert answer_graph._quote('a "b" \\ c\nd') == '"a \\"b\\" \\\\ c\\nd"'
    assert all(len(line) <= answer_graph.WRAP for line in answer_graph._wrap("word " * 30).split("\n"))


def test_every_recorded_annotated_answer_draws():
    for answer in core.load_demo_answers()["answers"]:
        if answer["mode"] == "annotated":
            dot = answer_graph.build_dot(core.read_answer("annotated", answer["raw"]))
            if dot:
                well_formed(dot)
