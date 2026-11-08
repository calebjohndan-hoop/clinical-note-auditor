"""
Stress tests: messier phrasing than data/synthetic_notes.py.

Every MUST_FLAG case was a silent miss in an earlier extractor version
(found 2026-09-10 and 2026-09-25). Every MUST_NOT_FLAG case guards against
the fixes over-correcting into false positives. When you swap in the LLM
extractor, this whole file must still pass unchanged.

Run: python3 -m pytest tests/ -v    (or: python3 tests/test_extractor_stress.py)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.extractor import extract_fields
from app.rules import run_all_rules

VITALS = " BP 120/80 HR 70 Temp 98.6 RR 16."

# (label, note text, rule that MUST fire)
MUST_FLAG = [
    ("prose 'allergy to'", "Pt has an allergy to Penicillin noted in chart. Rx: Amoxicillin 500 mg PO TID." + VITALS, "drug_allergy_conflict"),
    ("prose '<drug> allergy'", "Penicillin allergy noted on intake. Plan: amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
    ("'allergic to' only", "Patient is allergic to aspirin. Plan: aspirin 81mg." + VITALS, "drug_allergy_conflict"),
    ("negation with exception", "No known drug allergies except penicillin. Rx amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
    ("plural class", "Allergies: NSAIDs. Plan: ibuprofen 400mg." + VITALS, "drug_allergy_conflict"),
    ("'<class> drugs'", "Allergies: sulfa drugs. Plan: sulfamethoxazole 800mg." + VITALS, "drug_allergy_conflict"),
    ("caps + newlines + multi", "ALLERGIES: Penicillin, Codeine\nMeds: hydrocodone 5mg\n" + VITALS, "drug_allergy_conflict"),
    ("gram dose overdose", "Allergies: NKDA. Plan: acetaminophen 2 g now." + VITALS, "dosage_out_of_range"),
    # 2026-10-04 pass
    ("PCN abbreviation", "Allergies: PCN. Plan: amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
    ("brand Augmentin", "Allergies: penicillin. Start Augmentin 875mg." + VITALS, "drug_allergy_conflict"),
    ("brand Tylenol overdose", "Allergies: NKDA. Tylenol 2000mg now." + VITALS, "dosage_out_of_range"),
    ("dose-first phrasing", "Allergies: NKDA. Give 5000 mg metformin." + VITALS, "dosage_out_of_range"),
    ("comma thousands", "Allergies: NKDA. metformin 5,000 mg." + VITALS, "dosage_out_of_range"),
    ("reaction in parens", "Allergies: penicillin (rash). Plan: amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
]

# (label, note text, rule that must NOT fire)
MUST_NOT_FLAG = [
    ("denies allergies", "Patient denies any drug allergies. Plan: amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
    ("NKDA", "Allergies: NKDA. Plan: amoxicillin 500mg." + VITALS, "drug_allergy_conflict"),
    ("seasonal only", "Seasonal allergies, no drug allergies. Plan: ibuprofen 400mg." + VITALS, "drug_allergy_conflict"),
    ("decimal in range", "Allergies: NKDA. Plan: warfarin 2.5 mg daily." + VITALS, "dosage_out_of_range"),
    ("metformin ER 1500", "Allergies: NKDA. metformin ER 1,500 mg daily." + VITALS, "dosage_out_of_range"),
    ("amox 2 g prophylaxis", "Allergies: NKDA. amoxicillin 2 g once before dental procedure." + VITALS, "dosage_out_of_range"),
    ("iodine is not a contrast allergy", "Allergies: iodine. Plan: iodinated contrast CT, atorvastatin 20mg." + VITALS, "drug_allergy_conflict"),
    ("gram dose in range", "Allergies: NKDA. Plan: acetaminophen 0.5 g q6h." + VITALS, "dosage_out_of_range"),
    ("'allergic' is a section", "Patient is allergic to latex. Plan: atorvastatin 20mg." + VITALS, "missing_allergy_section"),
]


def _rules(text):
    return {f.rule for f in run_all_rules(extract_fields(text)).flags}


def test_must_flag():
    for label, text, rule in MUST_FLAG:
        got = _rules(text)
        assert rule in got, f"[{label}] expected {rule}, got {got}; extracted={extract_fields(text)}"


def test_must_not_flag():
    for label, text, rule in MUST_NOT_FLAG:
        got = _rules(text)
        assert rule not in got, f"[{label}] {rule} should NOT fire, got {got}; extracted={extract_fields(text)}"


def test_vitals_alt_wording():
    v = extract_fields("Allergies: NKDA. Pulse 88, resp rate 18, T 37.2, BP 130/85.")["vitals"]
    assert set(v) == {"heart_rate", "respiratory_rate", "temperature", "blood_pressure"}, v


def test_vitals_word_boundaries():
    # "three" contains "hr"; must not be read as a heart rate
    v = extract_fields("Allergies: NKDA. Take three 10 times. BP 120/80 Temp 98.6 RR 16.")["vitals"]
    assert "heart_rate" not in v, v


if __name__ == "__main__":
    for fn in (test_must_flag, test_must_not_flag, test_vitals_alt_wording, test_vitals_word_boundaries):
        fn()
        print(f"PASS: {fn.__name__}")
    print("\nAll stress tests passed.")


# --- regressions from the first real-note (MTSamples) run -----------------------------
import pytest as _pytest
from app.extractor import extract_regex as _xr


@_pytest.mark.parametrize("text,name,dose", [
    ("Patient takes Lexapro 20 mg daily.", "escitalopram", 20.0),
    ("Inderal LA 80 mg once daily.", "propranolol", 80.0),
    ("Magnesium oxide 400 mg twice daily.", "magnesium oxide", 400.0),
    ("Metoprolol tartrate 25 mg twice daily.", "metoprolol tartrate", 25.0),
    ("Colace 200 mg at bedtime.", "docusate", 200.0),
    ("Synthroid 0.075 mg daily.", "levothyroxine", 0.075),
])
def test_real_note_brand_and_salt_names(text, name, dose):
    meds = {(m["name"], m["dose"]) for m in _xr(text)["medications"]}
    assert (name, dose) in meds, meds


def test_allergy_sentence_after_colon_is_not_a_list_item():
    note = _xr("Allergies: he states that Imuran caused him to develop tachycardia.")
    assert note["allergies"] == ["azathioprine"], note["allergies"]


def test_unknown_drug_in_allergy_sentence_stays_loud_not_silent():
    # Unknown drug in a sentence after "Allergies:" must not vanish: it should still
    # reach the allergy list so the unrecognized_allergy flag fires.
    note = _xr("Allergies: she reports a bad rash after taking zyvoxamine. Metformin 500 mg daily.")
    assert note["allergies"], "allergy silently dropped"


@_pytest.mark.parametrize("text,allergy", [
    ("Allergies: Keflex causes hives. Lisinopril 10 mg.", "cephalexin"),
    ("Allergic to Augmentin. Ampicillin 500 mg.", "penicillin"),
])
def test_brand_allergy_with_reaction_is_normalized(text, allergy):
    assert allergy in _xr(text)["allergies"]


# --- vitals phrasings from real MTSamples notes (first real-note run) ----------------------
@_pytest.mark.parametrize("text,expected", [
    ("VITAL SIGNS: At the time of admission, pulse was 94, respirations 20, blood pressure 120/62, "
     "temperature 98.7, height 171.5 cm, weight 63.04 kg, and pulse oximetry on room air 95%.",
     {"heart_rate": 94, "respiratory_rate": 20, "blood_pressure": "120/62", "temperature": 98.7}),
    ("Temperature 97.8, blood pressure 122/74, heart rate 76, respirations 24, weight 250 lbs, O2 sat 95% on R.A.",
     {"temperature": 97.8, "blood_pressure": "122/74", "heart_rate": 76, "respiratory_rate": 24}),
    ("Vitals: T 100.9-102.7 BP 136/86 Pulse 117 RR 12 98% sat on room air",
     {"temperature": 100.9, "blood_pressure": "136/86", "heart_rate": 117, "respiratory_rate": 12}),
])
def test_real_note_vitals_phrasings(text, expected):
    got = _xr("Allergies: none. " + text)["vitals"]
    assert got == expected, got


def test_pulse_oximetry_is_not_a_pulse():
    assert "heart_rate" not in _xr("Pulse oximetry on room air 95%.")["vitals"]


@_pytest.mark.parametrize("text,name,dose", [
    ("Tylenol 1 gm q.i.d.", "acetaminophen", 1000.0),
    ("Amoxicillin 1 gram twice daily", "amoxicillin", 1000.0),
    ("Metformin 0.5 gm daily", "metformin", 500.0),
])
def test_gm_and_gram_units(text, name, dose):
    meds = {(m["name"], m["dose"]) for m in _xr(text)["medications"]}
    assert (name, dose) in meds, meds


# --- second look at real notes, after the first hybrid run ---------------------------------
@_pytest.mark.parametrize("text,expected", [
    ("Temperature 99.2, blood pressure ranges from 88/41 to 108/60, pulse 70, respiratory rate, 20, O2 saturation 98%.",
     {"temperature": 99.2, "blood_pressure": "88/41", "heart_rate": 70, "respiratory_rate": 20}),
    ("VS: T 100.2F BP 132/85 P 111 RR 20 O2 Sat 95% on room air",
     {"temperature": 100.2, "blood_pressure": "132/85", "heart_rate": 111, "respiratory_rate": 20}),
])
def test_vitals_ranges_commas_and_bare_P(text, expected):
    assert _xr("Allergies: none. " + text)["vitals"] == expected


def test_allergy_clause_is_trimmed_to_the_allergen():
    assert _xr("ALLERGIES: Hypaque dye when she had x-rays for her kidneys.")["allergies"] == ["hypaque dye"]


def test_opioid_brand_allergies_normalize():
    got = _xr("ALLERGIES: Percocet, Percodan, oxycodone, and Duragesic.")["allergies"]
    assert got == ["oxycodone", "fentanyl"], got


def test_folic_acid_keeps_its_name():
    meds = {(m["name"], m["dose"]) for m in _xr("MEDICATIONS: Folic acid 1 mg daily.")["medications"]}
    assert ("folic acid", 1.0) in meds, meds


# --- first HELD-OUT run (10 unseen MTSamples notes): exact sentences from the failures -----
_HOLD07 = ("MEDICATIONS: Fosamax - 70 mg weekly. Lisinopril - 20 mg daily. Metformin - 850 mg daily. "
           "Amlodipine - 5 mg daily. Metoprolol - 150 mg twice daily. Warfarin - 5 mg daily. "
           "Magnesium oxide - 200 mg daily. PLANS: I have restarted her Lasix at 80 mg daily. "
           "If she is truly on 150 mg of metoprolol twice a day, one could switch her amlodipine from 5 mg daily.")


def test_dash_separated_medication_list():
    meds = {(m["name"], m["dose"]) for m in _xr(_HOLD07)["medications"]}
    for want in [("fosamax", 70.0), ("lisinopril", 20.0), ("metformin", 850.0), ("amlodipine", 5.0),
                 ("metoprolol", 150.0), ("warfarin", 5.0), ("magnesium oxide", 200.0), ("furosemide", 80.0)]:
        assert want in meds, (want, meds)


@_pytest.mark.parametrize("text,junk", [
    ("He is given a prescription for 150 mg that he will start at bedtime.", "for"),
    ("She is taking 100 mg of something.", "taking"),
    ("Dose decreased from 25 mg to 22.5 mg.", "from"),
    ("She is truly on 150 mg of metoprolol.", "on"),
    ("Isosorbide mononitrate 120 mg daily.", "mononitrate"),
])
def test_everyday_words_are_not_drug_names(text, junk):
    names = {m["name"] for m in _xr(text)["medications"]}
    assert junk not in names, names


def test_denied_is_not_an_allergen():
    assert _xr("She denied any allergies. Metformin 500 mg daily.")["allergies"] == []


def test_empty_allergy_heading_counts_as_missing_section():
    assert "allergies" not in _xr("HPI: cough.\nALLERGIES:")
    assert "allergies" not in _xr("ALLERGIES:\nMEDICATIONS: lisinopril 10 mg")
    assert _xr("ALLERGIES: none. Lisinopril 10 mg")["allergies"] == []
    assert _xr("Allergies:\nPenicillin: rash\nMEDICATIONS: lisinopril 10 mg")["allergies"] == ["penicillin"]
