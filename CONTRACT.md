# Extraction contract

Every extractor (regex, Gemini, or hybrid) MUST return a dict of exactly this
shape. `app/rules.py` and `app/checklist.py` only ever read this shape, so any
extractor that honours it can be swapped in without touching the rule engine.
`tests/` is the enforcement: if `pytest tests/` passes, the contract holds.

```python
{
    # Present ONLY if the note says anything about allergy status
    # (a list, "NKDA", "denies allergies", "allergic to X" ...).
    # Missing key  -> rules fire `missing_allergy_section`.
    # Empty list   -> documented as no allergies. Not a flag.
    "allergies": ["penicillin", "sulfa"],      # lowercase, normalized to
                                               # ALLERGY_DRUG_CONFLICTS keys
                                               # where one matches

    "medications": [                           # one entry per order/mention
        {"name": "amoxicillin",                # lowercase GENERIC name
         "dose": 500.0,                        # float, ALWAYS converted to mg
         "unit": "mg"},                        # always "mg"
    ],

    "vitals": {                                # omit a key if not in the note
        "blood_pressure": "120/80",            # str "sys/dia"
        "heart_rate": 72,                      # int
        "temperature": 98.6,                   # float, unit as written (F or C)
        "respiratory_rate": 16,                # int
    },

    "soap": {                                  # best-effort note restructuring
        "subjective": "...",                   # "" if nothing found
        "objective": "...",
        "assessment": "...",
        "plan": "...",
    },

    "raw_text": "<original note, unmodified>",
    "extractor": "regex" | "gemini" | "hybrid", # which path produced this
}
```

## Rules for any new extractor

1. **Normalize through `app/extractor.normalize_note()`.** It lowercases,
   maps brands to generics (`DRUG_ALIASES`), abbreviations to allergy keys
   (`ALLERGY_ALIASES`), plurals/class words to keys, and converts g/mcg to mg.
   An LLM saying "Penicillin" or "Augmentin" is useless to the rule engine
   until it's normalized.
2. **Fail loudly.** If the LLM returns unparseable or off-schema JSON, raise
   `ExtractionError`. Never return `{}` — an empty note produces no conflict
   flags, which reads as "safe".
3. **Never drop what the regex found** (hybrid mode). The LLM may add
   findings; it may not remove a regex finding. Safety rules run on the union.
4. **Don't invent.** The LLM prompt says: only extract what is literally in
   the note; no inferred doses, no guessed allergies.
