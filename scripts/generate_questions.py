"""Generated test questions: the answer key comes from code, the wording from Claude Code.

Usage (from the project folder):
  python scripts/generate_questions.py plan    writes data/generated/question_plan.json

The plan holds one item per question to write: the full answer key (same fields as test_questions.json),
`derived_from` (the rule and inputs that produced it), a `brief` for the question writer and
`forbidden_terms` (words the question must not use, so it does not give the answer away).

The answer key is built only from data/techniques.json, data/annotations.json, data/vocabulary.json and
the dataset. No model is called here. The briefs and samples below only steer the wording; they never
change an answer key.
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import knowledge as k  # noqa: E402

PLAN_PATH = ROOT / "data" / "generated" / "question_plan.json"
ANSWER_KEY_FIELDS = ["category", "expected_ids", "acceptable_ids", "unacceptable_ids", "supplementary_only_ids",
                     "expected_not_available", "expected_accessories", "expect_clarifying", "expect_dead_end",
                     "workflow_ids"]
CONFIDENT = ("high", "medium")  # "low" = only with optional hardware the dataset does not list

# --- wording hints (never part of the answer key) ---

# Plain-language property names for briefs, where the vocabulary label would name a technique or is unclear.
BRIEF_LABEL = {
    "melt_flow_rate": "how easily a molten plastic flows through a standard die (a single flow number)",
    "wettability": "how well water spreads on (or beads up on) a surface",
    "particle_size_distribution": "size distribution of nanoparticles dispersed in a liquid",
    "microparticle_size_distribution": "size distribution of particles from micrometres to millimetres",
    "surface_roughness": "quantitative surface roughness (a roughness number, not just a picture)",
    "processing_shear_viscosity": "viscosity at the very high shear rates of an extruder or injection moulder",
    "ultrastructure": "nanometre-scale structure inside cells or tissue",
    "nanoparticle_morphology": "size and shape of individual nanoparticles, seen directly",
    "fluorescence_intensity": "how bright a fluorescent stain is in different cells or regions (from images)",
    "fluorescence_localization": "where a fluorescent label sits inside cells or tissue",
    "solid_viscoelastic_properties": "stiffness and damping of a solid polymer as temperature changes",
    "reaction_enthalpy": "how much heat a curing or reacting material releases",
    "chemical_functional_groups": "which chemical groups / bonds are present",
    "specific_surface_area": "total surface area per gram of a powder",
    "elemental_composition": "which chemical elements are present, and where",
    "tissue_morphology": "the structure of a tissue section (histology)",
    "macroscopic_morphology": "visible defects and overall shape at low magnification",
    "hardness": "hardness",
    "zeta_potential": "surface charge of particles in a liquid (and so how stable the dispersion is)",
}

# Two to four sample contexts per property, used in order by the rules (dentistry, pharmacy, engineering).
SAMPLES = {
    "bond_strength": ["a resin cement bonded to zirconia", "an adhesive between dentin and composite"],
    "cell_counts": ["fibroblasts seeded on a culture plate", "stem cells after a drug treatment",
                    "keratinocytes grown in a 24-well plate"],
    "cell_morphology": ["osteoblasts spreading on a titanium disc", "fibroblasts on a soft hydrogel",
                        "unstained living fibroblasts in a culture flask"],
    "chemical_functional_groups": ["a newly synthesized dental monomer", "a plasma-treated polymer film",
                                   "a polymer powder"],
    "compressive_modulus": ["bovine trabecular bone cubes",
                            "a hydrogel cylinder that should behave like cartilage", "a soft collagen sponge"],
    "compressive_strength": ["glass-ionomer cement cylinders", "a calcium phosphate bone cement",
                             "a bioprinted alginate scaffold"],
    "crystallization_temperature": ["a polypropylene used for medical tubing", "a PLA filament",
                                    "a polyethylene glycol (PEG) wax used in a drug formulation"],
    "degree_of_crystallinity": ["a PEEK implant material", "a PLLA suture", "an injection-moulded PLA part"],
    "elemental_composition": ["contaminants on an implant surface", "corrosion spots on a retrieved orthodontic wire"],
    "elongation_at_break": ["an elastic orthodontic chain", "an electrospun polyurethane membrane"],
    "filler_content": ["a dental composite paste", "a glass-filled nylon part", "a polymer composite"],
    "flexural_modulus": ["a 3D-printed denture base resin", "a fibre-reinforced post material",
                         "a printed occlusal splint resin"],
    "flexural_strength": ["CAD/CAM ceramic blocks", "a provisional crown resin"],
    "fluorescence_intensity": ["GFP-expressing cells after a drug treatment", "immunostained tissue sections",
                               "stained cell monolayers"],
    "fluorescence_localization": ["cells stained for a nuclear and a membrane protein",
                                  "labelled nanoparticles taken up by macrophages"],
    "gelation_and_curing_kinetics": ["a gelatin methacrylate hydrogel", "a photocurable dental resin"],
    "glass_transition_temperature": ["an amorphous drug dispersion", "a denture base acrylic",
                                     "a polycarbonate implant prototype"],
    "internal_3d_structure": ["a cast ceramic part", "a printed titanium lattice",
                              "a composite filling in an extracted tooth", "a freeze-dried scaffold"],
    "hardness": ["enamel after a bleaching treatment", "a thin ceramic coating on an implant"],
    "live_cell_behavior":["migrating cancer cells", "dividing stem cells"],
    "macroscopic_morphology": ["printed aligner trays", "a batch of extruded filaments", "resin-printed parts"],
    "mass_loss_vs_temperature": ["a biodegradable polymer blend", "a drug-loaded polymer film"],
    "melt_flow_rate": ["recycled polyethylene pellets", "a PLA filament batch from a new supplier"],
    "melting_temperature": ["a crystalline drug powder", "a wax-based drug carrier", "a PLA filament"],
    "moisture_and_volatile_content": ["a hygroscopic drug powder", "nylon pellets before moulding"],
    "microparticle_size_distribution": ["alginate microbeads", "a spray-dried drug powder",
                                        "cell-loaded alginate capsules", "a bone graft granulate"],
    "molecular_weight_distribution":["a PLGA polymer after degradation", "a batch of chitosan"],
    "nanoparticle_morphology": ["gold nanoparticles", "silica nanoparticles for drug delivery",
                                "lipid nanoparticles", "dried silver nanoparticles"],
    "nucleic_acid_concentration": ["DNA extracted from dental pulp cells", "RNA from cultured fibroblasts",
                                   "a DNA library before sequencing"],
    "particle_size_distribution": ["a liposome formulation", "a polymeric nanoparticle suspension"],
    "porosity_and_pore_size": ["a freeze-dried collagen scaffold", "a sintered ceramic bone graft",
                               "a printed polymer scaffold"],
    "processing_shear_viscosity": ["a polymer compound for injection moulding",
                                   "a filled thermoplastic for an extrusion line"],
    "protein_concentration": ["a cell lysate", "purified protein from saliva", "a cell lysate in tubes"],
    "reaction_enthalpy": ["a light-cured dental composite", "an epoxy resin system",
                          "a self-curing bone cement"],
    "crystalline_phase": ["a zirconia crown after sintering", "a calcium phosphate coating"],
    "solid_viscoelastic_properties": ["a denture liner material", "a shape-memory polymer strip"],
    "specific_surface_area": ["a mesoporous silica drug carrier", "a bone graft powder"],
    "surface_morphology": ["a sandblasted implant surface", "the fracture surface of a broken composite",
                           "an etched enamel surface"],
    "surface_roughness": ["a polished composite restoration", "a titanium implant after acid etching"],
    "tensile_modulus": ["an electrospun nanofibre mat", "a silicone impression material",
                        "resin-printed dog-bone specimens"],
    "tensile_strength": ["a suture material", "a thin polymer film", "dog-bone specimens printed in resin"],
    "thermal_stability": ["a flame-retardant polymer", "a drug-polymer blend", "a new polymer blend"],
    "tissue_morphology": ["periodontal tissue biopsies", "a resin-embedded bone biopsy",
                          "resin-embedded gingival tissue"],
    "ultrastructure": ["dental pulp cells", "a biofilm on a tooth surface"],
    "viscoelastic_moduli": ["a hyaluronic acid gel", "a bioink", "a polypropylene melt"],
    "viscosity_vs_shear_rate": ["a toothpaste formulation", "a bioink for printing"],
    "viscosity_vs_temperature": ["a thermosensitive hydrogel", "a wax-based drug carrier"],
    "wettability": ["a plasma-treated implant surface", "a coated contact lens material"],
    "yield_stress": ["a bioink", "a dental cement paste", "a hydrogel printing paste"],
    "zeta_potential": ["a nanoparticle suspension", "an emulsion formulation", "a liposome suspension"],
}

# --- overrides: what code cannot derive well (each entry explained) ---

OVERRIDES = {
    # Accessory regexes for a (instrument, technique) pair the dataset leaves open. Each regex must match a
    # "to_confirm" accessory of that instrument and technique in annotations.json (checked below).
    "accessory_patterns": {
        ("EQ10", "energy_dispersive_xray_spectroscopy"): [r"\bEDS\b|\bEDX\b|energy.dispersive"],
        ("EQ19", "dynamic_mechanical_analysis"): [r"\bDMA\b|clamp|torsion"],
        ("EQ21", "dynamic_mechanical_analysis"): [r"\bDMA\b|clamp|torsion"],
        ("EQ07", "live_cell_time_lapse_imaging"): [r"incubat|stage.top|CO2|environmental"],
        ("EQ09", "live_cell_time_lapse_imaging"): [r"incubat|stage.top|CO2|environmental"],
        ("EQ13", "live_cell_time_lapse_imaging"): [r"incubat|stage.top|CO2|environmental"],
        ("EQ23", "live_cell_time_lapse_imaging"): [r"incubat|stage.top|CO2|environmental"],
    },
    # Optional-hardware items where a key to_confirm accessory decides (confidence is high/medium, but the
    # question's condition needs one specific accessory). Instruments come from the property; the regex is
    # applied to each one that has a matching to_confirm accessory for the technique.
    "accessory_items": [
        {"property": "flexural_modulus", "technique": "flexural_testing",
         "pattern": r"bend|flexur|three.point|3.point|four.point", "condition": "rectangular bars loaded in bending"},
        {"property": "bond_strength", "technique": "bond_strength_testing",
         "pattern": r"shear.bond|micro.?tensile|jig", "condition": "shear test on bonded specimens"},
        {"property": "zeta_potential", "technique": "electrophoretic_light_scattering",
         "pattern": r"titrat", "condition": "how it changes over a pH range from 3 to 9"},
        {"property": "compressive_modulus", "technique": "compression_testing",
         "pattern": r"bath|environmental chamber|37", "condition": "tested soaked in liquid at body temperature"},
        {"property": "gelation_and_curing_kinetics", "technique": "oscillatory_rheometry",
         "pattern": r"\bUV\b|photo|light", "condition": "while it cures under UV / blue light"},
        {"property": "crystallization_temperature", "technique": "differential_scanning_calorimetry",
         "pattern": r"cool|sub.ambient|refrigerat", "condition": "on controlled cooling to below room temperature"},
    ],
    # Distractors: (property, instrument the brief mentions, how). The instrument performs none of the
    # expected techniques (checked below), so recommending it as the answer is wrong.
    "distractors": [
        ("yield_stress", "EQ01", "they print the paste on the bioprinter"),
        ("fluorescence_intensity", "EQ06", "they thought of the fluorometer because it measures fluorescence"),
        ("thermal_stability", "EQ18", "they already have time booked on the DSC"),
        ("melting_temperature", "EQ17", "they thought the TGA heats samples so it should work"),
        ("microparticle_size_distribution", "EQ20", "they heard the particle size analyzer measures particle size"),
        ("nanoparticle_morphology", "EQ14", "they tried the stereomicroscope first"),
        ("macroscopic_morphology", "EQ03", "the parts were printed on the resin printer"),
        ("protein_concentration", "EQ09", "they wonder if the high-content imaging system can do it"),
    ],
    # Workflow (prep step, goal property) pairs. Curated Q14 (ultramicrotomy -> TEM) and Q23 (milling -> XRD)
    # are not repeated. The goal technique must be in the prep step's leads_to (checked below). The last
    # field is the sample (wording only), chosen to fit the prep step.
    "workflows": [
        ("milling", "ftir_spectroscopy", "chemical_functional_groups", "cured dental composite chips"),  # dead end
        ("milling", "thermogravimetric_analysis", "filler_content", "a glass-filled nylon part"),
        ("ultramicrotomy", "brightfield_microscopy", "tissue_morphology", "a resin-embedded bone biopsy"),
        ("vibrating_nozzle_encapsulation", "laser_diffraction", "microparticle_size_distribution",
         "cell-loaded alginate capsules"),
        ("vat_photopolymerization_printing", "tensile_testing", "tensile_strength", "dog-bone specimens"),
        ("extrusion_bioprinting", "compression_testing", "compressive_strength", "a printed alginate scaffold"),
    ],
    # Named-instrument items: (instrument, property). Curated Q4 (Zetasizer) and Q5 (TGA) are not repeated.
    "named": [
        ("EQ18", "glass_transition_temperature", "the DSC"),
        ("EQ11", "nanoparticle_morphology", "the CM12 / the TEM"),
        ("EQ14", "macroscopic_morphology", "the stereomicroscope"),
        ("EQ06", "nucleic_acid_concentration", "the Qubit"),
        ("EQ10", "surface_morphology", "the ESEM"),
    ],
    # Model-specific pairs. Rheology: EQ21 has the Environmental Test Chamber installed (dataset), EQ19 is
    # the same model with its temperature accessory unknown, so EQ19 is complementary only (as in Q18).
    # Well plates need an inverted or plate-based microscope: the "suitable" set is hand-assigned from the
    # instrument types (inverted microscopes, inverted confocal, plate imager); upright ones are
    # unacceptable (as in Stefan's Q19).
    "model_specific": [
        {"property": "viscoelastic_moduli", "condition": "of a PEEK melt at about 380 °C",
         "expected": ["EQ21"], "supplementary_only": ["EQ19"],
         "accessories": {"EQ21": [r"parallel.plate|geometry|plate"]},
         "forbidden": ["Environmental Test Chamber", "ETC", "Peltier"]},
        {"property": "gelation_and_curing_kinetics", "condition": "of a high-temperature epoxy that cures at about 230 °C",
         "expected": ["EQ21"], "supplementary_only": ["EQ19"],
         "accessories": {"EQ21": [r"parallel.plate|geometry|plate"]},
         "forbidden": ["Environmental Test Chamber", "ETC", "Peltier"]},
        {"property": "cell_counts", "condition": "how confluent stem cells are in a 6-well plate before passaging",
         "suitable": ["EQ07", "EQ09", "EQ13", "EQ23"], "forbidden": ["inverted", "upright"]},
        {"property": "cell_morphology", "condition": "fibroblasts fixed and stained in the bottom of a 96-well plate",
         "suitable": ["EQ07", "EQ09", "EQ13", "EQ23"], "forbidden": ["inverted", "upright"]},
    ],
    # Vague briefs: no property or no sample, so the right answer is a clarifying question.
    "vague": [
        "wants to characterize a new material they made; says nothing about what they want to know",
        "asks which equipment could help with their dental research project; no sample, no goal",
        "has a powder and wants to 'learn more about it'",
        "wants to check whether their scaffolds are 'good enough'",
    ],
}


# --- knowledge lookups ---

def available_full(prop: str) -> dict[str, list[tuple[str, str]]]:
    """Instruments that fully measure a property: {eq_id: [(technique, confidence), ...]}."""
    found: dict[str, list] = {}
    for tid, t in k.techniques().items():
        if t["kind"] in k.MEASURING_KINDS and prop in t["measures"]:
            for eq in k.instruments_for(tid):
                found.setdefault(eq, []).append((tid, k.techniques_of(eq)[tid]["confidence"]))
    return found


def available_partial(prop: str) -> dict[str, list[str]]:
    """Instruments whose technique measures a property only partly: {eq_id: [technique, ...]}."""
    found: dict[str, list] = {}
    for tid, t in k.techniques().items():
        if t["kind"] in k.MEASURING_KINDS and prop in t.get("partial", {}) and prop not in t["measures"]:
            for eq in k.instruments_for(tid):
                found.setdefault(eq, []).append(tid)
    return found


def missing_full(prop: str) -> list[str]:
    """Unavailable techniques that fully measure a property."""
    return [tid for tid in k.unavailable_techniques() if prop in k.techniques()[tid]["measures"]]


def split_name(name: str) -> list[str]:
    """'Differential scanning calorimetry (DSC)' -> ['Differential scanning calorimetry', 'DSC']."""
    name = re.sub(r"(?<=\S)\((\w+)\)", r"\1", name)  # 'Widefield (epi)fluorescence' -> '(epi)' kept as text
    name = re.sub(r"\((\w+)\)(?=\S)", r"\1", name)
    terms = [re.sub(r"\s*\(.*?\)", "", name).strip()]
    for inner in re.findall(r"\((.*?)\)", name):
        terms += [p.strip() for p in inner.split("/")]
    return [t for t in terms if t]


def technique_terms(tid: str) -> list[str]:
    t = k.techniques()[tid]
    return split_name(t["name"]) + list(t.get("aliases", []))


def instrument_terms(eq: str) -> list[str]:
    e = core.equipment_by_id()[eq]
    return split_name(e["instrument"]) + [e["model"]]


def term_regex(terms: list[str]) -> str:
    """Terms -> one scoring regex: hyphens/spaces optional ('.?'), word boundaries around word-like ends."""
    parts = []
    for term in dict.fromkeys(terms):
        body = ".?".join(re.escape(w) for w in re.split(r"[\s-]+", term) if w)
        start = r"\b" if re.match(r"\w", term) else ""
        end = r"\b" if re.search(r"\w$", term) else ""
        parts.append(f"{start}{body}{end}")
    return "|".join(parts)


def contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) is not None


def label(prop: str) -> str:
    return BRIEF_LABEL.get(prop) or re.sub(r"\s*\(.*?\)", "", k.property_label(prop))


class Samples:
    """Hands out each property's sample contexts in order, so two items never share property and sample."""

    def __init__(self):
        self.used = Counter()

    def next(self, prop: str) -> str:
        options = SAMPLES[prop]
        if self.used[prop] >= len(options):
            raise SystemExit(f"SAMPLES['{prop}'] needs more entries (used {self.used[prop] + 1} times)")
        self.used[prop] += 1
        return options[self.used[prop] - 1]


# --- building items ---

def item(category: str, derived_from: dict, brief: str, forbidden: list[str], **key) -> dict:
    answer = {"category": category, "expected_ids": [], "acceptable_ids": [], "unacceptable_ids": [],
              "supplementary_only_ids": [], "expected_not_available": [], "expected_accessories": {},
              "expect_clarifying": False, "expect_dead_end": False, "workflow_ids": []}
    answer.update(key)
    for field in ("expected_ids", "acceptable_ids", "unacceptable_ids", "supplementary_only_ids", "workflow_ids"):
        answer[field] = sorted(set(answer[field]))
    return {**answer, "derived_from": derived_from, "brief": brief,
            "forbidden_terms": sorted(dict.fromkeys(forbidden), key=str.lower)}


def property_key(prop: str) -> dict:
    """The available-property answer key: confident full instruments expected; low-confidence or partial
    ones acceptable. Also returns the techniques behind the expected instruments."""
    full, partial = available_full(prop), available_partial(prop)
    expected = [eq for eq, ts in full.items() if any(c in CONFIDENT for _, c in ts)]
    acceptable = [eq for eq in list(full) + list(partial) if eq not in expected]
    techs = sorted({t for eq in expected for t, c in full[eq] if c in CONFIDENT})
    return {"expected_ids": expected, "acceptable_ids": acceptable, "techniques": techs}


def answer_forbidden(techs: list[str], eqs: list[str]) -> list[str]:
    return [term for t in techs for term in technique_terms(t)] + [term for eq in eqs for term in instrument_terms(eq)]


def available_property_items(samples: Samples, skipped: list) -> list[dict]:
    items = []
    for prop in sorted(k.vocabulary()["properties"]):
        full = available_full(prop)
        if not full:
            skipped.append((prop, "available-property", "no listed instrument measures it (no-match rule)"))
            continue
        key = property_key(prop)
        if not key["expected_ids"]:
            skipped.append((prop, "available-property", "only low-confidence instruments (optional-hardware rule)"))
            continue
        sample = samples.next(prop)
        items.append(item("problem-only",
                          {"rule": "available-property", "property": prop, "techniques": key["techniques"]},
                          f"{label(prop)}; sample: {sample}",
                          answer_forbidden(key["techniques"], key["expected_ids"]),
                          expected_ids=key["expected_ids"], acceptable_ids=key["acceptable_ids"]))
    return items


def no_match_items(samples: Samples) -> list[dict]:
    items = []
    for prop in sorted(k.vocabulary()["properties"]):
        if available_full(prop):
            continue
        missing = missing_full(prop)
        for _ in range(2):
            sample = samples.next(prop)
            items.append(item("no-suitable-equipment",
                              {"rule": "no-match-property", "property": prop, "techniques": missing},
                              f"{label(prop)}; sample: {sample}",
                              [term for t in missing for term in technique_terms(t)],
                              expected_not_available=[term_regex([x for t in missing for x in technique_terms(t)])],
                              supplementary_only_ids=list(available_partial(prop))))
    return items


def destructive(tid: str) -> str:
    return k.techniques()[tid]["destructive"]


def non_destructive_items(samples: Samples, skipped: list) -> list[dict]:
    """Only properties where 'without damaging the sample' changes the answer: some candidate instrument
    has only destructive techniques for it, and a non-destructive alternative exists (listed or not).
    'depends' counts as possible without damage (see destructive_note in techniques.json)."""
    items = []
    for prop in sorted(k.vocabulary()["properties"]):
        full, partial = available_full(prop), available_partial(prop)
        techs_of = {eq: [t for t, _ in ts] for eq, ts in full.items()}
        for eq, ts in partial.items():
            techs_of.setdefault(eq, []).extend(ts)
        damaging = [eq for eq, ts in techs_of.items() if all(destructive(t) == "yes" for t in ts)]
        gentle_missing = [t for t in missing_full(prop) if destructive(t) != "yes"]
        gentle_full = {eq: [(t, c) for t, c in ts if destructive(t) != "yes"] for eq, ts in full.items()}
        gentle_full = {eq: ts for eq, ts in gentle_full.items() if ts}
        if not damaging:
            continue
        if not gentle_full and not gentle_missing:
            skipped.append((prop, "non-destructive", "every technique for it is destructive"))
            continue
        confident = [eq for eq, ts in gentle_full.items() if any(c in CONFIDENT for _, c in ts)]
        expected = confident or list(gentle_full)  # low-confidence only: still the right answer (optional hardware)
        gentle_partial = [eq for eq, ts in partial.items() if eq not in damaging and eq not in gentle_full]
        acceptable = [eq for eq in gentle_full if eq not in expected] + (gentle_partial if expected else [])
        techs = sorted({t for eq in expected for t, _ in gentle_full[eq]})
        accessories = {eq: pats for eq in expected for t in techs
                       for pats in [OVERRIDES["accessory_patterns"].get((eq, t))] if pats}
        sample = samples.next(prop)
        items.append(item("problem-only" if expected else "no-suitable-equipment",
                          {"rule": "non-destructive", "property": prop, "techniques": techs or gentle_missing},
                          f"{label(prop)}, without damaging or using up the sample; sample: {sample}",
                          answer_forbidden(techs, expected) + [term for t in gentle_missing for term in technique_terms(t)],
                          expected_ids=expected, acceptable_ids=acceptable, unacceptable_ids=damaging,
                          supplementary_only_ids=[] if expected else gentle_partial,
                          expected_not_available=[] if expected else
                          [term_regex([x for t in gentle_missing for x in technique_terms(t)])],
                          expected_accessories=accessories))
    return items


def accessory_regex_ok(eq: str, tech: str, pattern: str) -> bool:
    return any(re.search(pattern, acc, re.IGNORECASE) for acc in k.accessories_for(eq, tech))


def optional_hardware_items(samples: Samples) -> list[dict]:
    items = []
    # Properties whose only full instruments need optional hardware (e.g. elemental composition -> EDS on EQ10).
    for prop in sorted(k.vocabulary()["properties"]):
        full = available_full(prop)
        if not full or property_key(prop)["expected_ids"]:
            continue
        expected = list(full)
        techs = sorted({t for ts in full.values() for t, _ in ts})
        accessories = {}
        for eq in expected:
            for t, _ in full[eq]:
                pats = OVERRIDES["accessory_patterns"].get((eq, t))
                if not pats:
                    raise SystemExit(f"OVERRIDES['accessory_patterns'] has no entry for ({eq}, {t})")
                accessories[eq] = pats
        sample = samples.next(prop)
        items.append(item("accessory-trap",
                          {"rule": "optional-hardware", "property": prop, "techniques": techs,
                           "reason": "only low-confidence instruments"},
                          f"{label(prop)}; sample: {sample}", answer_forbidden(techs, expected),
                          expected_ids=expected, acceptable_ids=list(available_partial(prop)),
                          expected_accessories=accessories))
    # Key to_confirm accessory decides (hand-picked condition, see OVERRIDES).
    for o in OVERRIDES["accessory_items"]:
        prop, tech, pattern = o["property"], o["technique"], o["pattern"]
        key = property_key(prop)
        with_acc = [eq for eq in k.instruments_for(tech) if accessory_regex_ok(eq, tech, pattern)]
        if not with_acc:
            raise SystemExit(f"accessory pattern {pattern!r} matches no to_confirm accessory for {tech}")
        expected = [eq for eq in key["expected_ids"] if eq in with_acc]
        sample = samples.next(prop)
        items.append(item("accessory-trap",
                          {"rule": "optional-hardware", "property": prop, "techniques": [tech],
                           "reason": "key accessory to confirm", "condition": o["condition"]},
                          f"{label(prop)}, {o['condition']}; sample: {sample}",
                          answer_forbidden([tech], expected),
                          expected_ids=expected,
                          acceptable_ids=[eq for eq in key["expected_ids"] + key["acceptable_ids"] if eq not in expected],
                          expected_accessories={eq: [pattern] for eq in expected}))
    return items


def distractor_items(samples: Samples) -> list[dict]:
    items = []
    for prop, eq, how in OVERRIDES["distractors"]:
        key = property_key(prop)
        if set(k.techniques_of(eq)) & set(key["techniques"]) or eq in key["expected_ids"] + key["acceptable_ids"]:
            raise SystemExit(f"distractor {eq} performs an expected technique for {prop}")
        name = core.equipment_by_id()[eq]["instrument"]
        sample = samples.next(prop)
        items.append(item("misleading-keyword",
                          {"rule": "distractor", "property": prop, "techniques": key["techniques"], "distractor": eq},
                          f"{label(prop)}; sample: {sample}; mention the {name} ({how}) as a misleading lead",
                          answer_forbidden(key["techniques"], key["expected_ids"]),
                          expected_ids=key["expected_ids"], acceptable_ids=key["acceptable_ids"],
                          unacceptable_ids=[eq]))
    return items


def workflow_items() -> list[dict]:
    items = []
    for prep, goal, prop, sample in OVERRIDES["workflows"]:
        if goal not in k.techniques()[prep]["leads_to"] or prop not in k.techniques()[goal]["measures"]:
            raise SystemExit(f"workflow ({prep}, {goal}, {prop}) does not follow techniques.json")
        prep_eqs = k.instruments_for(prep)
        derived = {"rule": "workflow", "prep": prep, "goal_technique": goal, "property": prop}
        prep_name = split_name(k.technique_name(prep))[0].lower()
        brief = f"first {prep_name} (they plan to do this step), then {label(prop)}; sample: {sample}"
        goal_eqs = [eq for eq in k.instruments_for(goal) if k.techniques_of(eq)[goal]["confidence"] in CONFIDENT]
        if available_full(prop):
            # The goal technique's instruments are expected; if it is missing (encapsulation -> laser
            # diffraction), the property's other instruments are, and it is not a dead end.
            key = property_key(prop)
            expected, techs = (goal_eqs, [goal]) if goal_eqs else (key["expected_ids"], key["techniques"])
            derived["goal_available"] = bool(goal_eqs)
            items.append(item("multi-step", derived, brief, answer_forbidden(techs, expected),
                              expected_ids=expected,
                              acceptable_ids=[eq for eq in key["expected_ids"] + key["acceptable_ids"]
                                              if eq not in expected],
                              workflow_ids=prep_eqs))
        else:  # the goal cannot be measured with listed equipment: preparing the sample leads nowhere
            items.append(item("multi-step", derived, brief, technique_terms(goal),
                              supplementary_only_ids=prep_eqs, expect_dead_end=True,
                              expected_not_available=[term_regex(technique_terms(goal))]))
    return items


def named_items(samples: Samples) -> list[dict]:
    items = []
    for eq, prop, called in OVERRIDES["named"]:
        full = available_full(prop)
        if eq not in full:
            raise SystemExit(f"named item: {eq} does not measure {prop}")
        sample = samples.next(prop)
        others = [x for x in list(full) + list(available_partial(prop)) if x != eq]
        items.append(item("named-instrument",
                          {"rule": "named", "property": prop, "instrument": eq,
                           "techniques": sorted(t for t, _ in full[eq])},
                          f"ask whether {called} can measure {label(prop)}; sample: {sample}", [],
                          expected_ids=[eq], acceptable_ids=others))
    return items


def model_specific_items() -> list[dict]:
    items = []
    for o in OVERRIDES["model_specific"]:
        prop = o["property"]
        full = available_full(prop)
        derived = {"rule": "model-specific", "property": prop, "condition": o["condition"]}
        brief = f"{label(prop)}, {o['condition']}"  # the condition names the sample
        if "expected" in o:  # an installed accessory decides
            expected = o["expected"]
            techs = sorted({t for eq in expected for t, _ in full[eq]})
            items.append(item("model-specific", {**derived, "techniques": techs}, brief,
                              answer_forbidden(techs, expected) + o["forbidden"],
                              expected_ids=expected, supplementary_only_ids=o["supplementary_only"],
                              expected_accessories=o["accessories"]))
        else:  # the instrument type decides (well plates need an inverted or plate-based microscope)
            suitable = [eq for eq in full if eq in o["suitable"]]
            expected = [eq for eq in suitable if any(c in CONFIDENT for _, c in full[eq])]
            techs = sorted({t for eq in expected for t, c in full[eq] if c in CONFIDENT})
            items.append(item("model-specific", {**derived, "techniques": techs}, brief,
                              answer_forbidden(techs, expected) + o["forbidden"],
                              expected_ids=expected, acceptable_ids=[eq for eq in suitable if eq not in expected],
                              unacceptable_ids=[eq for eq in full if eq not in suitable]))
    return items


def vague_items() -> list[dict]:
    return [item("vague", {"rule": "vague"}, brief, [], expect_clarifying=True) for brief in OVERRIDES["vague"]]


# --- checks (same rules as tests/test_questions_file.py, plus brief vs. forbidden terms) ---

def key_problems(q: dict) -> list[str]:
    known = set(core.equipment_by_id())
    problems = []
    expected, acceptable, unacceptable, supp = (set(q.get(f, [])) for f in
                                                ("expected_ids", "acceptable_ids", "unacceptable_ids",
                                                 "supplementary_only_ids"))
    if not (expected | acceptable | unacceptable | supp | set(q.get("workflow_ids", []))) <= known:
        problems.append("unknown instrument ID")
    if expected & acceptable or expected & unacceptable or acceptable & unacceptable:
        problems.append("expected / acceptable / unacceptable overlap")
    if supp & (expected | acceptable | unacceptable):
        problems.append("supplementary_only overlaps another set")
    if not set(q["expected_accessories"]) <= expected | acceptable:
        problems.append("accessories for an instrument that is not expected or acceptable")
    for pattern in q["expected_not_available"] + [p for ps in q["expected_accessories"].values() for p in ps]:
        try:
            re.compile(pattern)
        except re.error as e:
            problems.append(f"bad regex {pattern!r}: {e}")
    if q["expect_clarifying"] and expected:
        problems.append("vague question with expected instruments")
    if q["category"] != "vague" and not (expected or q["expected_not_available"]):
        problems.append("nothing expected and nothing flagged")
    return problems


def plan_problems(items: list[dict]) -> list[str]:
    problems = []
    for q in items:
        problems += [f"{q['id']}: {p}" for p in key_problems(q)]
        problems += [f"{q['id']}: brief uses forbidden term '{t}'" for t in q["forbidden_terms"]
                     if contains_term(q["brief"], t)]
    return problems


# --- commands ---

def build_plan() -> tuple[list[dict], list]:
    samples, skipped = Samples(), []
    items = (available_property_items(samples, skipped) + no_match_items(samples)
             + non_destructive_items(samples, skipped) + optional_hardware_items(samples)
             + distractor_items(samples) + workflow_items() + named_items(samples)
             + model_specific_items() + vague_items())
    return [{"id": f"G{i:03d}", **q} for i, q in enumerate(items, start=1)], skipped


def print_table(items: list[dict], skipped: list) -> None:
    counts = Counter((q["derived_from"]["rule"], q["category"]) for q in items)
    print(f"{'rule':<20} {'category':<24} {'items':>5}")
    for (rule, category), n in counts.items():
        print(f"{rule:<20} {category:<24} {n:>5}")
    print(f"{'total':<45} {len(items):>5}")
    if skipped:
        print("\nSkipped:")
        for prop, rule, why in skipped:
            print(f"  {prop:<32} {rule:<20} {why}")


def cmd_plan(_args) -> None:
    items, skipped = build_plan()
    problems = plan_problems(items)
    print_table(items, skipped)
    if problems:
        raise SystemExit("\nProblems:\n  " + "\n  ".join(problems))
    plan = {"knowledge_version": k.knowledge_version(),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items}
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nWrote {PLAN_PATH.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="write the question plan (answer keys from the knowledge layer)")
    args = parser.parse_args()
    {"plan": cmd_plan}[args.command](args)


if __name__ == "__main__":
    main()
