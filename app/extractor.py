"""
Extraction layer: free-text clinical note -> structured dict.

This module is the deterministic (regex) extractor plus the shared
normalization every extractor goes through. extract_fields() dispatches to
regex / gemini / hybrid via the EXTRACTOR env var — see CONTRACT.md and
app/llm_extractor.py.

KNOWN LIMITATIONS (fixed 2026-09-10, hardened 2026-09-25): the original allergy extractor only
handled "Allergies: <list>" colon-style phrasing. Prose phrasing like
"Pt has an allergy to Penicillin" or "Penicillin allergy noted" captured
the whole trailing clause (e.g. "to penicillin noted in chart") instead of
the drug name, so it never matched app/rules.py's exact-key lookup into
ALLERGY_DRUG_CONFLICTS — a real drug-allergy conflict went unflagged with
no signal to the user. _extract_allergies now also parses common prose
patterns and cross-checks against known allergen terms as a safety net.
This is still a regex stub, not NLP — see tests/test_rules.py's
"messy_phrasing_conflict" and "prose_allergy_conflict" cases for the
patterns it's been verified against, and the LLM swap above remains the
real fix for phrasing this doesn't anticipate.

2026-09-25 stress pass found five more silent misses, all now fixed and
covered in tests/test_extractor_stress.py:
  - "allergic to X" alone was treated as NO allergy section at all
    (gate regex only matched allergy/allergies, not allergic)
  - "No known drug allergies except penicillin" -> whole sentence dropped
  - plurals / class words ("NSAIDs", "sulfa drugs") never matched table keys
  - gram / mcg doses ("acetaminophen 2 g") were never extracted, so the
    dosage rule silently skipped them
  - vitals regexes had no word boundaries ("hr" could match inside words)
"""

import re
import unicodedata

from data.reference_tables import (
    ALLERGY_ALIASES,
    ALLERGY_DRUG_CONFLICTS,
    DOSAGE_SAFE_RANGES,
    DRUG_ALIASES,
)

# Longest-first so multi-word keys (if any are added later) match first.
_KNOWN_ALLERGENS = sorted(ALLERGY_DRUG_CONFLICTS.keys(), key=len, reverse=True)

# Phrases meaning "no allergies". A sentence containing one contributes no
# allergens UNLESS it also has an exception clause ("...except penicillin").
_NEGATION_RE = re.compile(r"\b(no known|nkda|nka|none|denies|denied|denying|not allergic|no allerg)")
_EXCEPTION_RE = re.compile(r"\b(?:except|other than|apart from|but)\b\s*(?:to\s+|for\s+)?(.+)")

# Words that can precede "allergy" without being the allergen itself.
_NON_ALLERGEN_WORDS = {
    "a", "an", "the", "any", "no", "known", "drug", "drugs", "has", "have",
    "documented", "reports", "reported", "with", "of", "food", "seasonal",
    "environmental", "severe", "mild", "chart",
}

_ALLERGY_WORD = r"allerg(?:y|ies|ic)"


class ExtractionError(RuntimeError):
    """Raised when an extractor can't produce a trustworthy structured note.
    Never swallow this into an empty dict — empty reads as 'no conflicts'."""


def extract_fields(raw_text: str) -> dict:
    """Public entrypoint. Picks the extractor from the EXTRACTOR env var:
        regex  (default when no API key) - deterministic, offline
        gemini - LLM only
        hybrid (default when an LLM key is set: GEMINI_API_KEY or LLM_API_KEY) - union of regex + LLM
    Tests call this, so `EXTRACTOR=hybrid pytest tests/` runs the whole suite
    against the LLM path without editing a single test."""
    import os

    from app.llm_extractor import extract_gemini, extract_hybrid, llm_configured

    mode = os.environ.get("EXTRACTOR") or ("hybrid" if llm_configured() else "regex")
    if mode == "regex":
        return extract_regex(raw_text)

    if mode == "gemini":
        return extract_gemini(raw_text)
    if mode == "hybrid":
        return extract_hybrid(raw_text)
    raise ValueError(f"Unknown EXTRACTOR={mode!r} (use regex | gemini | hybrid)")


# An "ALLERGIES:" heading with nothing under it (end of note, or straight into the next
# ALL-CAPS heading) is NOT documentation: treat it as not mentioned so the audit flags it.
_EMPTY_ALLERGY_HEADING = re.compile(r"(?i:allerg(?:y|ies))[ \t]*:[ \t]*(?:\n[ \t]*)*(?=\Z|[A-Z][A-Z /&]{2,40}:)")


def extract_regex(raw_text: str) -> dict:
    # Fold accents ("pénicilline" -> "penicilline") so a word is never split into fragments.
    plain = "".join(c for c in unicodedata.normalize("NFKD", raw_text) if not unicodedata.combining(c))
    text = _EMPTY_ALLERGY_HEADING.sub("", plain).lower()
    # "ALLERGIES:\nPenicillin" -> keep the heading and its list in one sentence
    text = re.sub(r"(allerg(?:y|ies))[ \t]*:[ \t]*\n[ \t]*", r"\1: ", text)

    note = {
        "allergies": _extract_allergies(text),
        "medications": _extract_medications(text),
        "vitals": _extract_vitals(text),
        "soap": split_soap(raw_text),
        "raw_text": raw_text,
        "extractor": "regex",
    }
    # Only include the allergies key if the note mentions allergy status at all,
    # so check_missing_allergy_section can tell "not documented" from "documented as none".
    if not _mentions_allergy_status(text):
        del note["allergies"]
    return note


def normalize_note(note: dict) -> dict:
    """Force any extractor's output into CONTRACT.md's normalized form:
    allergy keys, generic drug names, mg doses, typed vitals."""
    out = dict(note)
    if "allergies" in out:
        seen, allergies = set(), []
        for a in out.get("allergies") or []:
            a = _normalize_allergen(str(a).lower())
            if a and a not in seen and a not in _NON_ALLERGEN_WORDS:
                seen.add(a)
                allergies.append(a)
        out["allergies"] = allergies
    meds = []
    for m in out.get("medications") or []:
        name = str(m.get("name", "")).lower().strip()
        name = re.sub(r"\s+(er|xr|xl|sr|cr|dr|ds|ir|la)$", "", name)
        # "metformin er" / "lisinopril tablets" -> first word when it is a drug we know;
        # otherwise keep the full name ("folic acid", "evening primrose") rather than
        # cutting it down to a meaningless "folic" / "evening".
        first = name.split()[0] if name else name
        name = _canonical_drug(first if first in _KNOWN_DRUGS or first in DRUG_ALIASES else name)
        dose, unit = m.get("dose"), str(m.get("unit") or "mg").lower().strip()
        if dose is not None:
            if unit not in _UNIT_TO_MG:
                continue  # unknown unit (units/IU/mL): can't range-check, don't fake it
            dose = _to_mg(str(dose), unit)
        meds.append({"name": name, "dose": dose, "unit": "mg"})
    out["medications"] = meds
    v = dict(out.get("vitals") or {})
    casts = {"heart_rate": int, "respiratory_rate": int, "temperature": float, "blood_pressure": str}
    out["vitals"] = {}
    for k, cast in casts.items():
        if v.get(k) not in (None, "", "N/A"):
            try:
                out["vitals"][k] = cast(v[k])
            except (TypeError, ValueError):
                pass
    return out


_SOAP_HEADINGS = {
    "subjective": r"subjective|chief complaint|cc|hpi|history of present illness|history",
    "objective": r"objective|exam|physical exam|vitals|vital signs|labs",
    "assessment": r"assessment|impression|diagnosis|diagnoses",
    "plan": r"plan|recommendations|disposition",
}


def split_soap(raw_text: str) -> dict:
    """Best-effort deterministic SOAP restructuring. Uses explicit headings if
    the note has them; otherwise classifies sentence by sentence. The LLM path
    does this better — this exists so the regex demo still shows SOAP output."""
    soap = {k: [] for k in _SOAP_HEADINGS}
    heading_re = re.compile(
        r"(?im)^\s*(?:(?:a/p|assessment and plan)|"
        + "|".join(f"(?:{v})" for v in _SOAP_HEADINGS.values())
        + r")\s*:"
    )
    if len(heading_re.findall(raw_text)) >= 2:
        current = "subjective"
        for line in raw_text.splitlines():
            m = re.match(r"\s*([a-z /]+?)\s*:(.*)", line, re.I)
            if m:
                label = m.group(1).strip().lower()
                if label in ("a/p", "assessment and plan"):
                    current = "plan"
                else:
                    for sec, pat in _SOAP_HEADINGS.items():
                        if re.fullmatch(pat, label):
                            current = sec
                            break
            if line.strip():
                soap[current].append(line.strip())
    else:
        for sent in _split_sentences(raw_text):
            s = sent.strip()
            low = s.lower()
            if re.search(r"\b(bp|hr|rr|temp|pulse|spo2|exam|vitals?)\b|\d{2,3}/\d{2,3}", low):
                sec = "objective"
            elif re.match(r"(plan|rx|start|continue|increase|decrease|give|recommend|follow)", low):
                sec = "plan"
            elif re.search(r"\b(diagnos|impression|assessment|consistent with|likely)\b", low):
                sec = "assessment"
            else:
                sec = "subjective"
            soap[sec].append(s)
    return {k: " ".join(v) for k, v in soap.items()}


def _mentions_allergy_status(text: str) -> bool:
    return bool(re.search(rf"{_ALLERGY_WORD}|\bnkda\b|\bnka\b", text))


def _normalize_allergen(item: str) -> str:
    """Map free text like 'sulfa drugs' / 'NSAIDs' / 'penicillins' to a table key."""
    item = re.sub(r"\s*\(.*$", "", item.strip())  # drop reaction notes: "penicillin (rash)"
    if item in ALLERGY_ALIASES:                    # "pen-class", "pcn" ...
        return ALLERGY_ALIASES[item]
    item = re.sub(r"[\s-]+(drugs?|class|antibiotics?|medications?)$", "", item)
    if item in ALLERGY_ALIASES:
        return ALLERGY_ALIASES[item]
    if item in ALLERGY_DRUG_CONFLICTS:
        return item
    if item.endswith("s") and item[:-1] in ALLERGY_DRUG_CONFLICTS:
        return item[:-1]
    for term in _KNOWN_ALLERGENS:
        if re.search(rf"\b{re.escape(term)}s?\b", item):
            return term
    return DRUG_ALIASES.get(item, item)  # brand-name allergy: "imuran" -> azathioprine


def _allergens_in(fragment: str) -> list:
    found = []
    # List style: "allergies: penicillin, sulfa" (colon required)
    colon = re.search(r"allerg(?:y|ies)\s*:\s*([a-z0-9,\- ]+)", fragment)
    if colon:
        for item in re.split(r",|\band\b", colon.group(1)):
            if not item.strip():
                continue
            # Items can be a name ("penicillin"), a name plus reaction ("keflex causes hives")
            # or a whole sentence ("he states that imuran caused tachycardia"). Keep the drug
            # names in it. If none is recognizable, keep the raw text: it then surfaces as an
            # unrecognized allergy (loud) instead of vanishing (silent).
            drugs = [w for w in re.findall(r"[a-z\-]+", item) if w in _KNOWN_DRUGS or w in ALLERGY_ALIASES]
            # "hypaque dye when she had x-rays for her kidneys" -> "hypaque dye"
            head = re.split(r"\b(?:when|after|which|that|causing|caused|because|during|since|who|while|for)\b", item)[0].strip()
            found += drugs or ([head] if head else [item])
    # Prose: "allergic/allergy to X", "X allergy"
    found += re.findall(rf"{_ALLERGY_WORD}?\s*to\s+([a-z\-]+)", fragment) if re.search(_ALLERGY_WORD, fragment) else []
    # "<drug> allergy" — noun form only; "is allergic" would capture "is"
    for w in re.findall(r"\b([a-z\-]+)\s+allerg(?:y|ies)\b", fragment):
        if w not in _NON_ALLERGEN_WORDS:
            found.append(w)
    # Safety net: any known allergen (incl. plural) or abbreviation in the fragment
    for abbr in ALLERGY_ALIASES:
        if re.search(rf"\b{re.escape(abbr)}s?\b", fragment):
            found.append(abbr)
    for term in _KNOWN_ALLERGENS:
        if re.search(rf"\b{re.escape(term)}s?\b", fragment):
            found.append(term)
    return found


def _extract_allergies(text: str) -> list:
    if not _mentions_allergy_status(text):
        return []

    raw = []
    for sentence in _split_sentences(text):
        if not re.search(rf"{_ALLERGY_WORD}|\bnkda\b|\bnka\b", sentence):
            continue
        if _NEGATION_RE.search(sentence):
            exc = _EXCEPTION_RE.search(sentence)
            if not exc:
                continue
            # Only the exception tail counts: "no known allergies except penicillin"
            tail = exc.group(1)
            raw += [w for w in re.findall(r"[a-z\-]+", tail) if w not in _NON_ALLERGEN_WORDS]
            continue
        raw += _allergens_in(sentence)

    seen, result = set(), []
    for a in raw:
        a = _normalize_allergen(a)
        if a and a not in seen and a not in _NON_ALLERGEN_WORDS:
            seen.add(a)
            result.append(a)
    return result


def _split_sentences(text: str) -> list:
    # Split on ". " / "; " / newline — but NOT inside numbers like "98.7" or "2.5 mg".
    return [s for s in re.split(r"(?<=[.;])\s+|\n+", text) if s.strip()]


_UNIT_TO_MG = {"mg": 1.0, "g": 1000.0, "gm": 1000.0, "gms": 1000.0, "gram": 1000.0, "grams": 1000.0,
               "mcg": 0.001, "µg": 0.001}


_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"   # 500, 2.5, 1,500
_UNIT = r"(mg|mcg|\u00b5g|grams?|gms?|g)"   # "1 gm q.i.d." is how real notes write grams
_NOT_DRUG = {"give", "take", "start", "started", "continue", "increase", "decrease",
             "to", "of", "and", "or", "by", "at", "then", "now", "daily", "rx", "dose",
             # everyday words that sit right before a dose in real notes ("prescription for 150 mg",
             # "decreased from 25 mg", "she is on 150 mg", "taking 100 mg")
             "taking", "for", "from", "on", "with", "per", "about", "around", "up", "over", "than",
             "being", "was", "is", "are", "will", "would", "reduced", "increased", "decreased",
             "tablet", "tablets", "capsule", "capsules", "pill", "pills", "each", "every", "once",
             "twice", "plus", "total", "dosage", "doses", "prescription", "sig", "po", "iv", "im",
             "prn", "bid", "tid", "qid", "qd", "weekly", "approximately", "currently", "truly"}
_SALT_WORDS = {"mononitrate", "dinitrate", "maleate", "fumarate", "mesylate", "oxide", "sulfate", "chloride", "carbonate", "citrate", "hydroxide",
               "gluconate", "phosphate", "bicarbonate", "tartrate", "succinate", "acetate", "besylate"}
_KNOWN_DRUGS = (
    set(DOSAGE_SAFE_RANGES)
    | set(DRUG_ALIASES)
    | {d for drugs in ALLERGY_DRUG_CONFLICTS.values() for d in drugs}
)


def _canonical_drug(name: str) -> str:
    return DRUG_ALIASES.get(name, name)


def _to_mg(num: str, unit: str) -> float:
    return round(float(num.replace(",", "")) * _UNIT_TO_MG[unit], 4)


def _extract_medications(text: str) -> list:
    """'amoxicillin 500mg', 'lisinopril 40 mg', 'acetaminophen 1 g', 'metformin 1,500 mg',
    'Tylenol 2000mg' (brand -> generic), and 'give 5000 mg metformin' (dose-first).
    All doses are normalized to mg so rules.py only ever sees one unit."""
    meds, seen_spans = [], []
    # name-first
    # optional formulation suffix between name and dose: "metformin er 1500 mg", "bactrim ds 800 mg"
    # "Fosamax - 70 mg weekly" (med lists use dashes/colons), "lisinopril tablets 10 mg"
    for m in re.finditer(rf"\b([a-z][a-z\-]+)(?:\s*[-\u2013\u2014:]\s*|\s+)"
                         rf"(?:(?:er|xr|xl|sr|cr|dr|ds|ir|la|tablets?|tabs?|capsules?|caps?)\s+)?"
                         rf"{_NUM}\s*{_UNIT}\b", text):
        name = m.group(1)
        if name in _NOT_DRUG:
            continue
        if name == "acid":  # "folic acid 1 mg" -> "folic acid", not "acid"
            prev = re.search(r"([a-z][a-z\-]+)\s+$", text[: m.start(1)])
            if prev and prev.group(1) not in _NOT_DRUG:
                name = prev.group(1) + " acid"
        elif name in _SALT_WORDS:  # "magnesium oxide 400 mg" / "metoprolol tartrate 25 mg"
            prev = re.search(r"([a-z][a-z\-]+)\s+$", text[: m.start(1)])
            if prev and prev.group(1) not in _NOT_DRUG:
                first = prev.group(1)
                # a known drug keeps its plain name (metoprolol); otherwise keep both words
                name = first if first in _KNOWN_DRUGS else f"{first} {name}"
        meds.append({"name": _canonical_drug(name), "dose": _to_mg(m.group(2), m.group(3)), "unit": "mg"})
        seen_spans.append(m.span())
    # "restarted her Lasix at 80 mg": a filler word between drug and dose. Only for drugs we
    # know, because with an unknown word ("truly on 150 mg") this would invent medications.
    for m in re.finditer(rf"\b([a-z][a-z\-]+)\s+(?:at|on|of|to|is|was|now|currently)\s+{_NUM}\s*{_UNIT}\b", text):
        name = m.group(1)
        if name not in _KNOWN_DRUGS or name in _NOT_DRUG:
            continue
        if any(a <= m.start() < b for a, b in seen_spans):
            continue
        meds.append({"name": _canonical_drug(name), "dose": _to_mg(m.group(2), m.group(3)), "unit": "mg"})
        seen_spans.append(m.span())
    # dose-first, only for drugs we know (avoids "500 mg of something")
    for m in re.finditer(rf"\b{_NUM}\s*{_UNIT}\s+(?:of\s+)?([a-z][a-z\-]+)\b", text):
        name = m.group(3)
        if name not in _KNOWN_DRUGS:
            continue
        if any(a <= m.start() < b for a, b in seen_spans):
            continue
        meds.append({"name": _canonical_drug(name), "dose": _to_mg(m.group(1), m.group(2)), "unit": "mg"})
    return meds


_LINK = r"(?:\s+(?:was|is|of|at|were|about|approximately|ranges?(?: from)?|ranged(?: from)?))?\s*[:=,]?\s*"   # "pulse was 94", "BP: 120/80", "temperature of 101"


def _extract_vitals(text: str) -> dict:
    vitals = {}
    bp = re.search(rf"\b(?:bp|blood pressure)\b{_LINK}(\d{{2,3}}/\d{{2,3}})", text)
    if bp:
        vitals["blood_pressure"] = bp.group(1)
    hr = re.search(rf"\b(?:hr|heart rate|pulse(?: rate)?)\b{_LINK}(\d{{2,3}})\b", text)
    if hr:
        vitals["heart_rate"] = int(hr.group(1))
    if "heart_rate" not in vitals:
        # "VS: T 100.2F BP 132/85 P 111 RR 20": a bare "P" right after a blood pressure is the pulse
        p = re.search(r"\b\d{2,3}/\d{2,3}\s*(?:mmhg)?\s+p\s*[:=]?\s*(\d{2,3})\b", text)
        if p:
            vitals["heart_rate"] = int(p.group(1))
    temp = re.search(rf"\b(?:temp|temperature|t)\b{_LINK}(\d{{2,3}}(?:\.\d)?)", text)
    if temp:
        vitals["temperature"] = float(temp.group(1))
    # "RR 12", "respiratory rate 18", "respirations 20", "resp 16"
    rr = re.search(rf"\b(?:rr|resp(?:iratory)? rate|respirations?|resps?)\b{_LINK}(\d{{1,2}})\b", text)
    if rr:
        vitals["respiratory_rate"] = int(rr.group(1))
    return vitals
