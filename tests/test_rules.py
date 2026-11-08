import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.extractor import extract_fields
from app.rules import run_all_rules
from data.synthetic_notes import NOTES


def audit(note_key: str):
    structured = extract_fields(NOTES[note_key])
    return run_all_rules(structured), structured


def test_drug_allergy_conflict_is_caught():
    result, structured = audit("drug_allergy_conflict")
    rules_triggered = {f.rule for f in result.flags}
    assert "drug_allergy_conflict" in rules_triggered, (
        f"Expected drug_allergy_conflict flag. Got: {rules_triggered}. Structured note: {structured}"
    )


def test_dosage_out_of_range_is_caught():
    result, structured = audit("dosage_out_of_range")
    rules_triggered = {f.rule for f in result.flags}
    assert "dosage_out_of_range" in rules_triggered, (
        f"Expected dosage_out_of_range flag. Got: {rules_triggered}. Structured note: {structured}"
    )


def test_missing_vitals_is_caught():
    result, _ = audit("missing_vitals")
    rules_triggered = {f.rule for f in result.flags}
    assert "missing_vitals" in rules_triggered


def test_missing_allergy_section_is_caught():
    result, _ = audit("missing_allergy_section")
    rules_triggered = {f.rule for f in result.flags}
    assert "missing_allergy_section" in rules_triggered


def test_clean_note_has_no_high_severity_flags():
    result, structured = audit("clean_note")
    assert not result.has_high_severity, (
        f"Clean note should have no high-severity flags. Got: {result.flags}. Structured: {structured}"
    )


def test_clean_note_2_has_no_high_severity_flags():
    result, structured = audit("clean_note_2")
    assert not result.has_high_severity, (
        f"Clean note should have no high-severity flags. Got: {result.flags}. Structured: {structured}"
    )


def test_messy_phrasing_conflict_is_caught():
    # Regression test for the 2026-09-10 extractor bug: "an allergy to X"
    # phrasing (no colon) previously extracted the whole trailing clause
    # instead of the drug name, so the conflict silently went unflagged.
    result, structured = audit("messy_phrasing_conflict")
    rules_triggered = {f.rule for f in result.flags}
    assert "drug_allergy_conflict" in rules_triggered, (
        f"Expected drug_allergy_conflict flag. Got: {rules_triggered}. Structured note: {structured}"
    )


def test_prose_allergy_conflict_is_caught():
    # Same regression, "<drug> allergy" phrasing order.
    result, structured = audit("prose_allergy_conflict")
    rules_triggered = {f.rule for f in result.flags}
    assert "drug_allergy_conflict" in rules_triggered, (
        f"Expected drug_allergy_conflict flag. Got: {rules_triggered}. Structured note: {structured}"
    )


if __name__ == "__main__":
    for name in [
        "test_drug_allergy_conflict_is_caught",
        "test_dosage_out_of_range_is_caught",
        "test_missing_vitals_is_caught",
        "test_missing_allergy_section_is_caught",
        "test_clean_note_has_no_high_severity_flags",
        "test_clean_note_2_has_no_high_severity_flags",
        "test_messy_phrasing_conflict_is_caught",
        "test_prose_allergy_conflict_is_caught",
    ]:
        globals()[name]()
        print(f"PASS: {name}")
    print("\nAll tests passed.")
