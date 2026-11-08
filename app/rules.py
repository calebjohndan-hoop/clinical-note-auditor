"""
Deterministic rule engine.

This is the trust layer of the project: given a STRUCTURED note (a dict,
already extracted from free text by app/extractor.py), it runs explicit,
auditable checks and returns a list of flags. No LLM calls happen here —
that's the point. A judge or clinician can read every rule and know
exactly why something was flagged.

Input contract (structured_note dict):
{
    "allergies": ["penicillin", ...],           # list[str], lowercase
    "medications": [{"name": "amoxicillin", "dose": 500, "unit": "mg"}, ...],
    "vitals": {"blood_pressure": "120/80", "heart_rate": 72, ...},
    "history": ["hypertension", ...],           # free-form list[str]
    "raw_text": "..."                            # original note, for context
}
"""

from dataclasses import dataclass, field
from data.reference_tables import (
    ALLERGY_DRUG_CONFLICTS,
    CONFLICT_SEVERITY,
    DOSAGE_SAFE_RANGES,
    REQUIRED_VITALS,
)


@dataclass
class Flag:
    rule: str
    severity: str  # "high", "medium", "low"
    message: str
    evidence: str  # the specific field/value that triggered this


@dataclass
class AuditResult:
    flags: list = field(default_factory=list)

    def add(self, rule: str, severity: str, message: str, evidence: str):
        self.flags.append(Flag(rule, severity, message, evidence))

    @property
    def has_high_severity(self) -> bool:
        return any(f.severity == "high" for f in self.flags)


def check_drug_allergy_conflicts(note: dict, result: AuditResult) -> None:
    allergies = [a.lower().strip() for a in note.get("allergies", [])]
    medications = [m["name"].lower().strip() for m in note.get("medications", [])]

    for allergy in allergies:
        conflicting_drugs = ALLERGY_DRUG_CONFLICTS.get(allergy, [])
        for drug in medications:
            if drug in conflicting_drugs:
                severity = CONFLICT_SEVERITY.get(allergy, "high")
                result.add(
                    rule="drug_allergy_conflict",
                    severity=severity,
                    message=(f"Patient has documented {allergy} allergy but is prescribed {drug}."
                             if severity == "high" else
                             f"Documented {allergy} allergy and {drug} ordered — review (cross-reactivity uncommon)."),
                    evidence=f"allergy={allergy}, medication={drug}",
                )


def check_dosage_ranges(note: dict, result: AuditResult) -> None:
    for med in note.get("medications", []):
        name = med.get("name", "").lower().strip()
        dose = med.get("dose")
        unit = med.get("unit", "")
        if name not in DOSAGE_SAFE_RANGES or dose is None:
            continue
        low, high, expected_unit = DOSAGE_SAFE_RANGES[name]
        if unit != expected_unit:
            continue  # avoid false positives from unit mismatch until unit conversion is added
        if dose < low or dose > high:
            result.add(
                rule="dosage_out_of_range",
                severity="high",
                message=f"{name} dose of {dose:g}{unit} is outside the typical {low:g}-{high:g}{unit} range.",
                evidence=f"medication={name}, dose={dose:g}{unit}",
            )


def check_missing_vitals(note: dict, result: AuditResult) -> None:
    vitals = note.get("vitals", {})
    for field_name in REQUIRED_VITALS:
        if field_name not in vitals or vitals[field_name] in (None, "", "N/A"):
            result.add(
                rule="missing_vitals",
                severity="medium",
                message=f"Required vital '{field_name.replace('_', ' ')}' is missing from the note.",
                evidence=f"field={field_name}",
            )


def check_missing_allergy_section(note: dict, result: AuditResult) -> None:
    # A note with no allergy field at all (vs. an explicit "NKDA"/empty list) is a
    # documentation gap, not a clean bill of health — flag it distinctly.
    if "allergies" not in note:
        result.add(
            rule="missing_allergy_section",
            severity="medium",
            message="Note has no allergy section at all (not even 'no known allergies').",
            evidence="field=allergies",
        )


def check_unrecognized_allergies(note: dict, result: AuditResult) -> None:
    """An allergy that isn't in the reference table can't be checked against the
    orders. Say so, instead of letting 'no flag' read as 'no conflict'."""
    meds = [m["name"] for m in note.get("medications", [])]
    if not meds:
        return
    for allergy in note.get("allergies", []):
        if allergy.lower().strip() not in ALLERGY_DRUG_CONFLICTS:
            result.add(
                rule="unrecognized_allergy",
                severity="low",
                message=(f"Allergy '{allergy}' is not in the reference table, so it was NOT checked "
                         f"against the prescribed medications."),
                evidence=f"allergy={allergy}, medications={'/'.join(meds)}",
            )


RULES = [
    check_drug_allergy_conflicts,
    check_dosage_ranges,
    check_missing_vitals,
    check_missing_allergy_section,
    check_unrecognized_allergies,
]


def run_all_rules(structured_note: dict) -> AuditResult:
    result = AuditResult()
    for rule_fn in RULES:
        rule_fn(structured_note, result)
    return result
