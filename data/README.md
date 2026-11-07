# Data

| File | What it is | Edit by hand? |
|---|---|---|
| `dataset.xlsx` | Stefan's equipment list (20 instruments, IDs EQ01-EQ20 in row order) | No, it is the source data |
| `test_instruments.json` | Fictional test instruments for model-specific testing, appended as EQ21, EQ22, EQ23 (see below) | Yes, but only append: IDs follow the file order |
| `vocabulary.json` | Controlled vocabulary: property ids, technique kinds, sources, confidence, statuses | Yes: add a term here before using it |
| `techniques.json` | Technique knowledge base, including techniques not in the dataset | Yes |
| `annotations.json` | Instrument annotations (source of truth for capabilities) | Yes |
| `instrument_capabilities.xlsx` | Review copy of the annotations for Stefan | No: regenerate with `python scripts/draft_annotations.py export` |
| `demo_answers.json` | Saved answers for the live demo | No: `python run_eval.py --record-demo` |

After any edit run `python scripts/draft_annotations.py check` (also run by `pytest`).

## Fictional test instruments (EQ21-EQ23)

Stefan (Oct 30) wants to test whether the AI understands specific instrument **models and their installed
configurations**, not just instrument categories. Long-term, equipment owners would enter only
manufacturer, model, installed accessories, location and contact, and the AI would work out the
capabilities. `test_instruments.json` has that shape: `instrument`, `manufacturer`, `model`, `notes`,
`location`, `contact`, `installed_accessories` (list) and `"fictional_test_instrument": true`.
`dataset.xlsx` is not edited; `core.load_equipment` appends these after EQ20.

| ID | Instrument | Model | Installed accessories | Tests |
|---|---|---|---|---|
| EQ21 | Hybrid rheometer | TA Instruments Discovery HR20 | Environmental Test Chamber (ETC), P/N 534040.901 | same model as EQ19, but its high-temperature configuration is known (Q18) |
| EQ22 | Upright optical microscope | Olympus BX53 | none listed | upright: not for cells in well plates (Q19) |
| EQ23 | Inverted optical microscope | Olympus IX83 | none listed | inverted: suits well plates (Q19) |

- Every instrument now has `installed_accessories`; the 20 dataset instruments have `[]` (the dataset
  doesn't record them). Every mode's prompt, naive included, prints `Installed accessories: ...` when
  there are some. Structured and annotated mode treat them as confirmed; everything else is still
  "confirm with the contact".
- The notes of a test instrument only say it is fictional, so they are left out of prompts
  (`core.prompt_notes`); the app labels these instruments "Fictional test instrument".
- Their annotations were drafted by the LLM from manufacturer, model and installed accessories only
  (`draft_annotations.py draft --ids EQ21 EQ22 EQ23`). Installed accessories have status
  `listed_in_dataset` (source `dataset`); everything else is `llm_draft` / `to_confirm`.
- Names shared with an earlier instrument (e.g. "Hybrid rheometer") stay with that instrument when
  naive answers are searched for mentions, so a test instrument is found by its ID or model.

## How the pieces connect

```
instrument (annotations.json) --performs--> technique (techniques.json) --measures--> property (vocabulary.json)
instrument --needs--> accessory (to_confirm | listed_in_dataset | confirmed)
technique --requires_before / leads_to--> technique
```

A technique that no instrument performs is "not available in the dataset". Properties a technique
gives only under a condition go in `partial` with the condition (e.g. confocal microscopy gives internal
3D structure only for transparent or fluorescent samples).

## Sources and confidence

Each technique an instrument performs, and each accessory, has a `source`:
`dataset` (stated in `dataset.xlsx`), `llm_draft` (drafted, unreviewed), later `expert_review` (Stefan)
or `contact_confirmed`. Confidence: `high` standard for the instrument type or stated in the dataset;
`medium` common but depends on configuration; `low` only with optional hardware the dataset does not
list (the app then warns). Each instrument's `review.status` stays `draft` until Stefan has reviewed it.

## History: from the first draft spreadsheet

The first draft was a team member's `Instrument_Capabilities_Filled.xlsx` (template filled with an LLM,
Oct 27). It was mapped to the controlled vocabulary and corrected as below; the corrected version is
`instrument_capabilities.xlsx` (generated from the JSON).

- **Free text to ids.** Techniques and "what it measures" became technique and property ids, so the
  same thing has one name everywhere (e.g. "TGA" and "thermogravimetric analysis (TGA)"). Commas used as
  separators (EQ19 samples) were split.
- **Fabrication and preparation instruments measure nothing** (EQ01-EQ05). The draft listed e.g.
  "scaffold geometry", "capsule size", "particle size reduction" as measurements. They now have no
  measured properties, and a limitation says so (the bioprinter is a known distractor for Q1).
- **EQ11 TEM/STEM: destructive.** The draft said "No"; samples must be sectioned or thinned
  (Stefan's expected answer for Q3 relies on this).
- **EQ15 Instron: load cell added** as the first accessory to confirm, plus bend fixture, bond-strength
  jig and fluid bath; compression platens kept. Bond strength testing added (common in dentistry).
  Limitation added: a porous scaffold gives an apparent modulus; porosity is not measured.
- **EQ01: print heads are in the dataset**, so they are `listed_in_dataset`, not "to confirm".
- **No assumed configurations.** EDS on the ESEM (EQ10), live-cell imaging (EQ07, EQ09, EQ13),
  fluorescence on the inverted microscope (EQ13), cryo-sectioning (EQ16) and DMA mode on the rheometer
  (EQ19) are `low` confidence with the needed hardware as an accessory to confirm. The draft's
  "EDS system if available" and "live-cell microscopy" assumed them.
- **Destructiveness moved to techniques**, with a note, because it depends on the technique, not the
  instrument (e.g. ESEM: depends; confocal imaging: depends on labeling; compression: depends on whether
  tested to failure). "Must come before" / "Leads to" also moved to techniques and point at technique
  ids (e.g. ultramicrotomy leads to TEM; TEM requires ultramicrotomy for bulk samples). The DSC/TGA
  loop in the draft ("leads to" each other) became "TGA recommended before DSC".
- **Limits made specific** where they matter for the test questions: confocal and multiphoton depth,
  rheometer shear rate below extrusion rates, Zetasizer size range.
- **Techniques not in the dataset** were added to `techniques.json` (micro-CT, GPC/SEC, capillary
  rheometry, melt flow index, FTIR, XRD, porosimetry, BET, AFM, contact angle, hardness, laser
  diffraction) so code can say what is missing.
