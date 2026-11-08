"""
Action checklist: flags -> concrete next steps for the clinician.

Pure deterministic code, no LLM. Every action is a fixed template filled from
the flag's own evidence, so a judge can trace any checklist line back to the
exact rule and value that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rules import AuditResult, Flag

_PRIORITY = {"high": 1, "medium": 2, "low": 3}


@dataclass
class Action:
    priority: int        # 1 = do before the order is signed/dispensed
    action: str
    because: str         # the flag message this action answers
    rule: str


def _evidence(flag: Flag) -> dict:
    out = {}
    for part in flag.evidence.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _action_for(flag: Flag) -> str:
    ev = _evidence(flag)
    if flag.rule == "drug_allergy_conflict" and flag.severity != "high":
        return (f"Review {ev.get('medication', 'the medication')} with the patient: ask what the "
                f"{ev.get('allergy', 'documented')} reaction actually was (intolerance vs allergy) "
                f"before dispensing.")
    if flag.rule == "drug_allergy_conflict":
        return (f"HOLD {ev.get('medication', 'the medication')}. Confirm the "
                f"{ev.get('allergy', 'documented')} allergy and its reaction with the patient; "
                f"if confirmed, choose an alternative outside that class.")
    if flag.rule == "dosage_out_of_range":
        return (f"Verify the {ev.get('medication', 'medication')} dose "
                f"({ev.get('dose', '?')}) with the prescriber before dispensing — "
                f"check for a transcription or unit error (mg vs g).")
    if flag.rule == "unrecognized_allergy":
        return (f"Manually check the '{ev.get('allergy', 'documented')}' allergy against the "
                f"ordered medications ({ev.get('medications', '?')}) — the auditor has no data for it.")
    if flag.rule == "missing_allergy_section":
        return "Ask and document allergy status (including 'NKDA' if none) before any new medication."
    if flag.rule == "missing_vitals":
        field = ev.get("field", "vital").replace("_", " ")
        return f"Record {field}."
    return f"Review: {flag.message}"


def build_checklist(result: AuditResult) -> list[Action]:
    actions: list[Action] = []
    missing_vitals = [f for f in result.flags if f.rule == "missing_vitals"]
    for f in result.flags:
        if f.rule == "missing_vitals":
            continue
        actions.append(Action(_PRIORITY.get(f.severity, 3), _action_for(f), f.message, f.rule))
    if missing_vitals:  # one line, not four
        names = ", ".join(_evidence(f).get("field", "?").replace("_", " ") for f in missing_vitals)
        actions.append(Action(_PRIORITY["medium"], f"Record missing vitals: {names}.",
                              f"{len(missing_vitals)} required vital(s) not in the note.", "missing_vitals"))
    actions.sort(key=lambda a: a.priority)
    return actions
