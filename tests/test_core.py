import json

import pytest

import core


# --- dataset ---

def test_dataset_has_20_instruments_with_ids_in_row_order():
    equipment = core.load_equipment()
    assert [e["id"] for e in equipment] == [f"EQ{i:02d}" for i in range(1, 21)]
    assert all(e["instrument"] and e["location"] and e["contact"] for e in equipment)


def test_known_instruments_are_where_the_test_set_expects_them():
    known = core.equipment_by_id()
    assert known["EQ15"]["model"].endswith("5967")
    assert "rheometer" in known["EQ19"]["instrument"].lower()
    assert "(DSC)" in known["EQ18"]["instrument"]


def test_contacts_only_in_naive_prompt():
    contact = core.equipment_by_id()["EQ15"]["contact"]
    assert contact not in core.build_user_prompt("q", "structured")
    assert contact in core.build_user_prompt("q", "naive")
    assert "Recommended:" in core.build_user_prompt("q", "naive")


# --- parse_json ---

def test_parse_json_plain_fenced_and_with_text():
    assert core.parse_json('{"a": 1}') == {"a": 1}
    assert core.parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert core.parse_json('Here you go: {"a": {"b": 2}} done') == {"a": {"b": 2}}


@pytest.mark.parametrize("text", ["no json here", "[1, 2]"])
def test_parse_json_rejects_non_objects(text):
    with pytest.raises(ValueError):
        core.parse_json(text)


# --- check_recommendations ---

def test_check_recommendations_drops_unknown_ids_and_normalizes():
    recs = [{"instrument_id": " eq15 ", "technique": "compression"},
            {"instrument_id": "EQ99"}, {"technique": "no id"}, "not a dict"]
    checked, removed = core.check_recommendations(recs)
    assert [r["id"] for r in checked] == ["EQ15"]
    assert removed == ["EQ99", "(missing ID)"]


def test_check_recommendations_takes_contact_and_location_from_dataset():
    known = core.equipment_by_id()["EQ15"]
    recs = [{"instrument_id": "EQ15", "contact": "Made Up", "location": "Nowhere",
             "accessories_to_confirm": ["load cell"]}]
    checked, _ = core.check_recommendations(recs)
    assert checked[0]["contact"] == known["contact"]
    assert checked[0]["location"] == known["location"]
    assert checked[0]["accessories_to_confirm"] == ["load cell"]


# --- naive answers ---

def test_instrument_ids_in_text_by_id_model_name_and_abbreviation():
    text = "Try EQ01, the Instron 5967, a hybrid rheometer and the DSC."
    assert core.instrument_ids_in_text(text) == ["EQ01", "EQ15", "EQ18", "EQ19"]


@pytest.mark.parametrize("text, expected", [
    ("Use the DSC.\n\nRecommended: EQ18, eq19", ["EQ18", "EQ19"]),
    ("**Recommended:** EQ15", ["EQ15"]),
    ("Recommended: none", []),
    ("Recommended: EQ01\n...\nRecommended: EQ02", ["EQ02"]),  # the last line wins
    ("Recommended equipment: see below", None),  # a heading, not the line
    ("No line at all", None),
])
def test_recommended_line_ids(text, expected):
    assert core.recommended_line_ids(text) == expected


def test_read_naive_counts_only_the_recommended_line():
    raw = "The CM12 TEM needs thin sections, so not suitable. Use the Instron 5967.\nRecommended: EQ15, EQ77"
    result = core.read_answer("naive", raw)
    assert result["instrument_ids"] == ["EQ15"]
    assert result["mentioned_ids"] == ["EQ11", "EQ15"]
    assert result["removed"] == ["EQ77"]
    assert result["ids_source"] == "recommended_line"


def test_read_naive_falls_back_to_mentions():
    result = core.read_answer("naive", "Use the TGA and the DSC.")
    assert result["instrument_ids"] == ["EQ17", "EQ18"]
    assert result["ids_source"] == "mentions"


# --- structured answers ---

def test_read_structured_valid_and_invalid_json():
    raw = json.dumps({"recommendations": [{"instrument_id": "EQ17", "technique": "TGA"}],
                      "not_available": [{"technique": "GPC"}, "junk"], "clarifying_question": None})
    result = core.read_answer("structured", raw)
    assert result["json_ok"] and result["instrument_ids"] == ["EQ17"]
    assert result["not_available"] == [{"technique": "GPC"}]

    bad = core.read_answer("structured", "not json")
    assert bad["json_ok"] is False and bad["error"]


# --- whole runs with the mock model ---

def test_run_structured_with_mock_removes_invented_id():
    result = core.run_structured("I want to determine the compressive stiffness of a scaffold.")
    assert result["error"] is None and result["json_ok"]
    assert result["instrument_ids"] == ["EQ15"]
    assert result["removed"] == ["EQ99"]


def test_run_naive_with_mock_reads_recommended_line():
    result = core.run_naive("My polymer remains unexpectedly viscous.")
    assert result["error"] is None
    assert result["ids_source"] == "recommended_line"
    assert result["instrument_ids"] == ["EQ17", "EQ18", "EQ19"]


def test_api_errors_are_returned_not_raised(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nonsense")
    for run in (core.run_structured, core.run_naive):
        result = run("anything")
        assert "Unknown LLM_PROVIDER" in result["error"]
        assert result["instrument_ids"] == []
