"""The knowledge layer: the data files, their checks, annotated mode and the drafting script."""

import copy
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

import core
import knowledge
import llm
import run_eval

EQUIPMENT = list(core.load_equipment())


def load_script():
    path = Path(__file__).parent.parent / "scripts" / "draft_annotations.py"
    spec = importlib.util.spec_from_file_location("draft_annotations", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the data files ---

def test_knowledge_files_pass_the_checks():
    assert knowledge.validate(EQUIPMENT) == []


def test_every_instrument_is_annotated_and_still_a_draft():
    assert list(knowledge.annotations()) == [e["id"] for e in EQUIPMENT]
    assert {knowledge.review_status(e["id"]) for e in EQUIPMENT} == {"draft"}


def test_micro_ct_and_gpc_are_not_available():
    unavailable = knowledge.unavailable_techniques()
    for tid in ("micro_computed_tomography", "gel_permeation_chromatography", "capillary_rheometry"):
        assert tid in unavailable
    assert "rotational_rheometry" not in unavailable


@pytest.mark.parametrize("eq_id", ["EQ01", "EQ02", "EQ03", "EQ04", "EQ05", "EQ16"])
def test_instruments_that_make_or_prepare_samples_measure_nothing(eq_id):
    assert all(not knowledge.techniques()[t]["measures"] for t in knowledge.techniques_of(eq_id))


def test_electron_microscopy_and_ultramicrotomy_are_destructive():
    techs = knowledge.techniques()
    assert techs["transmission_electron_microscopy"]["destructive"] == "yes"
    assert techs["ultramicrotomy"]["destructive"] == "yes"
    assert techs["micro_computed_tomography"]["destructive"] == "no"


def test_instron_compression_needs_load_cell_and_platens_to_confirm():
    accessories = " ".join(knowledge.accessories_for("EQ15", "compression_testing")).lower()
    assert "load cell" in accessories and "platens" in accessories


def test_only_dataset_facts_are_listed_as_installed():
    listed = [(a["id"], x["item"]) for a in knowledge.annotations().values()
              for x in a["accessories"] if x["status"] != "to_confirm"]
    assert listed == [("EQ01", "two low-temperature heads, one high-temperature head, one UV-light head"),
                      ("EQ21", "Environmental Test Chamber (ETC), P/N 534040.901")]
    for e in EQUIPMENT:  # every installed accessory of the test instruments is in its annotation
        items = [x["item"] for x in knowledge.annotations()[e["id"]]["accessories"]]
        assert set(e["installed_accessories"]) <= set(items)


def test_installed_accessories_are_printed_once_in_the_annotated_prompt():
    prompt = core.build_user_prompt("q", "annotated")
    assert prompt.count("Environmental Test Chamber (ETC), P/N 534040.901") == 1


def test_ultramicrotomy_leads_to_tem_which_requires_it():
    techs = knowledge.techniques()
    assert "transmission_electron_microscopy" in techs["ultramicrotomy"]["leads_to"]
    assert "ultramicrotomy" in [s["technique"] for s in techs["transmission_electron_microscopy"]["requires_before"]]


# --- the checks catch mistakes ---

def annotations_with(change) -> list[dict]:
    annots = copy.deepcopy(list(knowledge.annotations().values()))
    change({a["id"]: a for a in annots})
    return annots


@pytest.mark.parametrize("change, problem", [
    (lambda a: a["EQ19"]["techniques"].append({"technique": "magic", "source": "llm_draft", "confidence": "high"}),
     "'magic' is not in techniques.json"),
    (lambda a: a["EQ19"].update(instrument="Rheometer"), "does not match the dataset"),
    (lambda a: a["EQ15"]["accessories"][0].update(status="listed_in_dataset"), "its source is not the dataset"),
    (lambda a: a["EQ15"]["accessories"][0].update(status="installed"), "accessory status 'installed'"),
    (lambda a: a["EQ15"]["accessories"][0].update({"for": ["rotational_rheometry"]}), "does not perform"),
    (lambda a: a["EQ15"]["techniques"][0].update(confidence="certain"), "confidence 'certain'"),
])
def test_validate_finds_problems_in_annotations(change, problem):
    problems = knowledge.validate(EQUIPMENT, annots=annotations_with(change))
    assert any(problem in p for p in problems), problems


def test_validate_finds_missing_annotations_and_unknown_properties():
    annots = [a for a in knowledge.annotations().values() if a["id"] != "EQ20"]
    assert "EQ20 has no annotation" in knowledge.validate(EQUIPMENT, annots=annots)
    techs = copy.deepcopy(knowledge.techniques())
    techs["dynamic_light_scattering"]["measures"].append("colour")
    assert any("'colour' is not in the vocabulary" in p for p in knowledge.validate(EQUIPMENT, techs=techs))


# --- annotated mode ---

def test_annotated_prompt_has_notes_and_unavailable_techniques_but_no_contacts():
    prompt = core.build_user_prompt("q", "annotated")
    assert "compression_testing" in prompt and "load cell" in prompt
    assert "micro_computed_tomography" in prompt.split("Techniques not available")[1]
    assert core.equipment_by_id()["EQ15"]["contact"] not in prompt
    assert "technique_id" in core.ANNOTATED_SYSTEM
    assert core.prompt_version("annotated") != core.prompt_version("structured")


def annotated(recs, **extra) -> dict:
    return core.read_answer("annotated", json.dumps({"recommendations": recs, "summary": "s", **extra}))


def test_annotated_answer_is_checked_against_the_notes():
    result = annotated([
        {"instrument_id": "EQ15", "technique_id": "compression_testing", "technique": "Compression",
         "why": "", "accessories_to_confirm": []},
        {"instrument_id": "EQ01", "technique_id": "compression_testing", "technique": "Compression",
         "why": "", "accessories_to_confirm": []},
        {"instrument_id": "EQ10", "technique_id": "energy_dispersive_xray_spectroscopy", "technique": "EDS",
         "why": "", "accessories_to_confirm": ["EDS detector"]},
        {"instrument_id": "EQ12", "technique": "Brightfield", "why": "", "accessories_to_confirm": []},
        {"instrument_id": "EQ99", "technique_id": "x", "technique": "?", "why": ""},
    ])
    instron, printer, esem, microscope = result["recommendations"]
    assert result["removed"] == ["EQ99"]
    assert instron["cautions"] == [] and instron["destructive"].startswith("depends")
    assert any("load cell" in a for a in instron["accessories_to_confirm"])  # filled in from the notes
    assert "not among this instrument's typical techniques" in printer["cautions"][0]
    assert "optional hardware" in esem["cautions"][0]
    assert esem["accessories_to_confirm"] == ["EDS detector"]  # the model's list is kept
    assert "No technique ID" in microscope["cautions"][0]
    assert instron["notes_status"] == "draft"


def test_not_available_that_is_available_is_flagged():
    result = annotated([], not_available=[
        {"technique_id": "micro_computed_tomography", "technique": "Micro-CT"},
        {"technique_id": "rotational_rheometry", "technique": "Rheology"},
        {"technique_id": None, "technique": "Something else"}])
    assert [n["available_on"] for n in result["not_available"]] == [[], ["EQ19", "EQ21"], []]


def test_structured_mode_is_not_checked_against_the_notes():
    rec = {"instrument_id": "EQ01", "technique_id": "compression_testing", "technique": "x", "why": ""}
    result = core.read_answer("structured", json.dumps({"recommendations": [rec], "summary": "s"}))
    assert "cautions" not in result["recommendations"][0]


def test_run_annotated_with_mock_model(monkeypatch):
    prompts = []
    real = llm.complete_with_meta
    monkeypatch.setattr(core, "complete_with_meta", lambda s, u, **kw: prompts.append(s) or real(s, u, **kw))
    result = core.run_annotated("I want to determine the compressive stiffness of a porous polymer scaffold.")
    assert result["mode"] == "annotated" and not result["error"]
    assert result["instrument_ids"] == ["EQ15"] and result["removed"] == ["EQ99"]
    assert prompts == [core.ANNOTATED_SYSTEM]


def test_eval_scores_annotated_accessories_per_instrument():
    question = {"expected_ids": ["EQ15"], "expected_not_available": ["micro.?CT"],
                "expected_accessories": {"EQ15": ["load cell", "platen"]}}
    result = annotated([{"instrument_id": "EQ15", "technique_id": "compression_testing", "technique": "c",
                         "why": "", "accessories_to_confirm": []}],
                       not_available=[{"technique_id": "micro_computed_tomography", "technique": "Micro-CT"}])
    s = run_eval.score(question, result)
    assert (s["expected_hits"], s["accessory_hits"], s["na_hits"], s["contacts_total"]) == (1, 2, 1, None)


# --- drafting script ---

def test_draft_writes_a_checked_draft_and_reports_proposals(monkeypatch, tmp_path):
    script = load_script()
    answer = {"id": "EQ19", "instrument": "wrong name", "techniques": [
        {"technique": "rotational_rheometry", "source": "dataset", "confidence": "high"},
        {"technique": "made_up", "source": "llm_draft", "confidence": "low"}],
        "typical_samples": ["gels"], "limitations": [], "accessories": [],
        "proposed_techniques": [{"name": "Extensional rheometry", "measures": "extensional viscosity"}]}
    monkeypatch.setattr(script.llm, "complete", lambda system, user, json_mode=False: json.dumps(answer))
    before = knowledge.ANNOTATIONS_PATH.read_bytes()
    out = tmp_path / "draft.json"
    problems = script.draft(["EQ19"], out)
    saved = json.loads(out.read_text(encoding="utf-8"))["instruments"]
    assert saved[0]["instrument"] == "Hybrid rheometer" and saved[0]["review"]["status"] == "draft"
    assert any("'made_up' is not in techniques.json" in p for p in problems)
    assert any("Extensional rheometry" in p for p in problems)
    assert not any("has no annotation" in p for p in problems)
    assert knowledge.ANNOTATIONS_PATH.read_bytes() == before


def test_draft_prompt_lists_techniques_and_the_dataset_row():
    script = load_script()
    prompt = script.draft_prompt(core.equipment_by_id()["EQ01"])
    assert "micro_computed_tomography" in prompt and "Two low-temperature heads" in prompt
    test_instrument = script.draft_prompt(core.equipment_by_id()["EQ21"])
    assert "installed accessories: Environmental Test Chamber (ETC)" in test_instrument
    assert "Discovery HR20" in test_instrument and "model-specific testing" not in test_instrument


def test_export_writes_one_row_per_instrument(tmp_path):
    script = load_script()
    out = tmp_path / "review.xlsx"
    script.export(out)
    wb = openpyxl.load_workbook(out)
    rows = list(wb["Instruments"].iter_rows(min_row=2, values_only=True))
    assert [r[0] for r in rows] == [e["id"] for e in EQUIPMENT]
    printer = dict(zip([c.value for c in wb["Instruments"][1]], rows[0]))
    assert printer["What it measures"] == "nothing (makes or prepares samples)"
    techniques = {r[0]: r for r in wb["Techniques"].iter_rows(min_row=2, values_only=True)}
    assert techniques["micro_computed_tomography"][8] == "NOT AVAILABLE in the dataset"


# --- fit level (annotated mode; computed by code) ---

def fitted(eq_id, technique_id, role="primary", property_id=None, accessories=None) -> dict:
    rec = {"instrument_id": eq_id, "role": role, "technique_id": technique_id, "property_id": property_id,
           "technique": "t", "why": "w", "accessories_to_confirm": accessories or []}
    return annotated([rec])["recommendations"][0]


@pytest.mark.parametrize("rec, level, reason", [
    # Q20: the ESEM is only complementary for quantitative RMS roughness
    (lambda: fitted("EQ10", "environmental_sem", role="supplementary"), "low", "Complementary only"),
    (lambda: fitted("EQ15", None), "low", "No technique given"),
    (lambda: fitted("EQ15", "made_up"), "low", "Unknown technique"),
    (lambda: fitted("EQ01", "compression_testing"), "low", "not among this instrument's typical techniques"),
    # Q10: EDS on the ESEM needs a detector the dataset does not list
    (lambda: fitted("EQ10", "energy_dispersive_xray_spectroscopy"), "low", "Needs optional hardware (EDS detector"),
    (lambda: fitted("EQ07", "confocal_microscopy", property_id="internal_3d_structure"), "low",
     "Partial: only for transparent or fluorescent samples"),
    # Q2: the Instron's load cell and platens are to confirm
    (lambda: fitted("EQ15", "compression_testing", property_id="compressive_modulus"), "medium",
     "Confirm with the contact: load cell"),
    # Q18: the second HR20 has the Environmental Test Chamber installed
    (lambda: fitted("EQ21", "rotational_rheometry", property_id="viscosity_vs_temperature",
                    accessories=["parallel-plate geometry"]), "high", "Environmental Test Chamber (ETC)"),
])
def test_fit_rules(rec, level, reason):
    rec = rec()
    assert rec["fit"] == level and reason in rec["fit_reason"], rec["fit_reason"]


def test_fit_high_when_nothing_needs_confirming_and_low_for_dead_ends():
    rec = {**core.equipment_by_id()["EQ17"], "role": "primary", "technique_id": "thermogravimetric_analysis",
           "accessories_to_confirm": []}
    assert core.assign_fit(dict(rec))["fit_reason"] == "Standard technique; no accessories to confirm."
    dead = core.assign_fit({**rec, "dead_end": "Dead end: X-ray diffraction is not available."})
    assert dead["fit"] == "low" and dead["fit_reason"].startswith("Dead end")


def test_a_measured_property_is_not_partial():
    assert fitted("EQ07", "confocal_microscopy", property_id="cell_morphology")["fit"] != "low"


def test_fit_only_in_annotated_mode_and_logged():
    recs = [{"instrument_id": "EQ15", "role": "primary", "technique_id": "compression_testing", "technique": "t",
             "why": "w"},
            {"instrument_id": "EQ18", "role": "supplementary", "technique_id": "differential_scanning_calorimetry",
             "technique": "t", "why": "w"}]
    result = annotated(recs)
    assert core.fit_levels(result) == "EQ15:medium;EQ18:low"
    import store
    assert store.answer_row("q", result)["fit_levels"] == "EQ15:medium;EQ18:low"
    plain = core.read_answer("structured", json.dumps({"recommendations": recs, "summary": "s"}))
    assert "fit" not in plain["recommendations"][0] and core.fit_levels(plain) == ""


def test_property_id_must_be_a_string_or_null():
    problems = core.validate_structured({"summary": "s", "recommendations": [
        {"instrument_id": "EQ15", "role": "primary", "technique": "t", "why": "w", "property_id": 3}]})
    assert any('"property_id"' in p for p in problems)


def test_eval_fit_scores_separate_good_and_bad_picks():
    question = {"expected_ids": ["EQ15"], "unacceptable_ids": ["EQ01"], "supplementary_only_ids": ["EQ18"],
                "expected_not_available": [], "expected_accessories": {}}
    result = annotated([
        {"instrument_id": "EQ15", "role": "primary", "technique_id": "compression_testing", "technique": "t", "why": "w"},
        {"instrument_id": "EQ01", "role": "primary", "technique_id": "compression_testing", "technique": "t", "why": "w"},
        {"instrument_id": "EQ18", "role": "primary", "technique_id": "differential_scanning_calorimetry",
         "technique": "t", "why": "w", "accessories_to_confirm": ["pans"]}])
    s = run_eval.score(question, result)
    assert (s["fit_expected_good"], s["fit_expected_total"]) == (1, 1)
    assert (s["fit_bad_low"], s["fit_bad_total"]) == (1, 2)  # EQ01 is low; EQ18 as primary is medium
    assert run_eval.score(question, core.read_answer("naive", "Recommended: EQ15"))["fit_expected_total"] is None


# --- workflow check and dead ends (annotated mode) ---

def test_workflow_for_labels_steps():
    tem = knowledge.workflow_for("transmission_electron_microscopy")["requires"]
    by_step = {s["technique"]: s for s in tem}
    assert by_step["ultramicrotomy"]["status"] == "available" and by_step["ultramicrotomy"]["instruments"] == ["EQ16"]
    assert by_step["negative_staining"]["status"] == "bench_step"
    assert all(s["conditional"] for s in tem)  # "for tissue, ..." is a condition, never a blocker
    assert knowledge.workflow_for("dynamic_light_scattering")["requires"][0]["conditional"] is False  # "always"
    milling = {s["technique"]: s["status"] for s in knowledge.workflow_for("milling")["leads_to"]}
    assert milling["x_ray_diffraction"] == "missing" and milling["thermogravimetric_analysis"] == "available"


def rec_for(eq_id, technique_id) -> dict:
    return {"instrument_id": eq_id, "role": "primary", "technique_id": technique_id, "technique": "t", "why": "w"}


def test_tem_workflow_names_the_ultramicrotome_and_its_contact():
    tem = annotated([rec_for("EQ11", "transmission_electron_microscopy")])["recommendations"][0]
    contact = core.equipment_by_id()["EQ16"]["contact"]
    assert any("May need Ultramicrotomy" in line and f"(EQ16), {contact}" in line for line in tem["workflow"])
    assert tem["dead_end"] == "" and tem["role"] == "primary"


def test_milling_alone_is_a_dead_end_and_not_primary():
    result = annotated([rec_for("EQ05", "milling")], objective_met=True)
    mill = result["recommendations"][0]
    assert mill["dead_end"].startswith("Dead end: this step is only useful if")
    assert "X-ray diffraction" in mill["dead_end"]
    assert mill["role"] == "supplementary" and mill["fit"] == "low" and mill["fit_reason"] == mill["dead_end"]
    assert result["primary_ids"] == [] and result["objective_met"] is False


def test_milling_followed_by_a_recommended_measurement_is_not_a_dead_end():
    result = annotated([rec_for("EQ05", "milling"), rec_for("EQ17", "thermogravimetric_analysis")])
    assert result["recommendations"][0]["dead_end"] == "" and result["primary_ids"] == ["EQ05", "EQ17"]


def test_bioprinter_alone_is_a_dead_end_here():
    printer = annotated([rec_for("EQ01", "extrusion_bioprinting")])["recommendations"][0]
    assert printer["dead_end"].startswith("Dead end here") and "(EQ15)" in printer["dead_end"]


def test_conditional_missing_prerequisite_is_not_a_dead_end():
    esem = annotated([rec_for("EQ10", "environmental_sem")])["recommendations"][0]  # sputter coating is optional
    assert esem["dead_end"] == "" and "not available in the dataset" in esem["workflow"][0]


def test_unconditional_missing_prerequisite_is_a_dead_end(monkeypatch):
    techs = copy.deepcopy(knowledge.techniques())
    techs["thermogravimetric_analysis"]["requires_before"] = [{"technique": "x_ray_diffraction", "when": "always"}]
    monkeypatch.setattr(knowledge, "techniques", lambda: techs)
    tga = annotated([rec_for("EQ17", "thermogravimetric_analysis")])["recommendations"][0]
    assert tga["dead_end"].startswith("Dead end: X-ray diffraction") and tga["role"] == "supplementary"


def test_eval_dead_end_and_workflow_scores():
    q23 = run_eval.select_questions(run_eval.load_questions(), ["Q23"], None)[0]
    s = run_eval.score(q23, annotated([rec_for("EQ05", "milling")]))
    assert s["dead_end_flagged"] is True and s["dead_end_ok"] is True and s["false_primary_hits"] == 0
    naive = core.read_answer("naive", "Grind it in the IKA A11. Identifying phases needs XRD, not listed.\nRecommended: EQ05")
    assert run_eval.score(q23, naive)["dead_end_ok"] is True  # names the missing next step
    assert run_eval.score(q23, core.read_answer("naive", "Use the mill.\nRecommended: EQ05"))["dead_end_ok"] is False

    q24 = run_eval.select_questions(run_eval.load_questions(), ["Q24"], None)[0]
    assert run_eval.score(q24, annotated([rec_for("EQ10", "environmental_sem")]))["dead_end_ok"] is True
    assert run_eval.score(q24, core.read_answer("naive", "Recommended: EQ10"))["dead_end_ok"] is None

    q14 = run_eval.select_questions(run_eval.load_questions(), ["Q14"], None)[0]
    s = run_eval.score(q14, annotated([rec_for("EQ11", "transmission_electron_microscopy")]))
    assert (s["workflow_hits"], s["workflow_total"]) == (1, 1)  # EQ16 is named in the TEM workflow


def test_versions_ignore_line_endings(tmp_path, monkeypatch):
    """A Windows checkout (CRLF) and a Linux checkout (LF) of the same files give the same versions."""
    import core

    versions = {}
    for name, newline in (("lf", b"\n"), ("crlf", b"\r\n")):
        folder = tmp_path / name
        folder.mkdir()
        for attr in ("VOCABULARY_PATH", "TECHNIQUES_PATH", "ANNOTATIONS_PATH"):
            source = getattr(knowledge, attr)
            target = folder / source.name
            target.write_bytes(source.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline))
            monkeypatch.setattr(knowledge, attr, target)
        instruments = folder / "test_instruments.json"
        instruments.write_bytes(core.TEST_INSTRUMENTS_PATH.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline))
        monkeypatch.setattr(core, "TEST_INSTRUMENTS_PATH", instruments)
        core.dataset_version.cache_clear()
        versions[name] = (knowledge.knowledge_version(), core.dataset_version())
    core.dataset_version.cache_clear()
    assert versions["lf"] == versions["crlf"]
