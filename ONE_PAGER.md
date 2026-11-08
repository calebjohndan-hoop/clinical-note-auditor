# Clinical Note Auditor

**Paste a messy clinical note. Get a structured SOAP note, safety flags, and a checklist of what to fix before signing.**

## Problem
Clinical notes are written fast, in free text, full of abbreviations and brand names. A penicillin allergy on line 3 and an amoxicillin order on line 30 is exactly the kind of error a tired reader misses. WHO estimates medication errors cost about US$42 billion a year worldwide. Most documentation tools check billing completeness, not medication safety inside the note.

## What it does
- **Structured SOAP** version of the note.
- **Safety flags:** drug–allergy conflicts, out-of-range doses, missing vitals, missing or unclear allergy documentation. Each flag shows the evidence that triggered it.
- **Action checklist**, e.g. "HOLD amoxicillin — confirm penicillin allergy and reaction."

## How it works: the LLM reads, the rules decide
- An extractor turns free text into fields (allergies, medications + doses, vitals). It can run as **regex**, **LLM** (Groq `gpt-oss-120b` or Gemini), or **hybrid** (both).
- Every flag comes from **deterministic rules** over a small reference table. Each entry is sourced (FDA labels via DailyMed, AAAAI, ACR, AHA).
- **The LLM can only add findings, never remove them.** Hybrid mode takes the union of regex and LLM findings. A test runs the full safety suite against an LLM that returns nothing, and it still passes.
- **Failures are loud.** If the LLM fails, the result says so ("regex (LLM unavailable)"). It never comes back as a silent all-clear.
- Deliberate choices: penicillin allergy does *not* block cephalosporins, "iodine allergy" does *not* block contrast (both are clinical myths), and codeine→hydrocodone is "review", not "stop". Brand-name amoxicillin/ampicillin allergies are treated as penicillin (conservative).

## Evidence
I hand-labeled 25 real, de-identified notes from MTSamples (allergies, medications and doses, which vitals are present), then re-checked every label against the note text on a second pass.

**Held-out test (10 notes the system had never seen):**

| | Regex | Hybrid (LLM) |
|---|---|---|
| Allergies P/R | 88% / 100% | 88% / 100% |
| Medications P/R | 68% / 61% | 76% / **100%** |
| Safety flags P/R | 91% / 91% | 91% / 91% |

**The LLM raised medication recall from 61% to 100% on unseen notes.** For example, in one note the drug name and its dose were in different sentences. Regex can't connect them; the LLM did.

After fixing the regex bugs those notes exposed, regex scores 93% / 96% on medications across all 25 notes, with 100% / 100% on allergies and flags. Those 10 notes are now development data, so this is not a held-out number. 97 automated tests cover every bug found along the way.

**Honesty notes:** while re-checking, I found one of my own labels had copied a junk extraction ("on" as a drug name). I corrected it and re-scored. The 15-note development set was tuned on, so I don't claim hybrid beats regex there.

## Limitations
- Small sample: 25 notes, one labeler. Flag scores are derived from my labels, so they mostly measure extraction, not clinical judgment.
- Misses drugs with no mg dose (e.g. inhalers). Counts supplements as medications. Can attribute a family member's medication to the patient, and can't tell a planned or past dose from a current one.
- The dose table covers 7 drugs and the allergy table 7 classes, because every entry is sourced. Dose checks are per-dose sanity bounds, not personalized dosing.
- Research prototype on de-identified data. **Not a medical device. Not clinically validated.**

## Next
Larger, multi-labeler evaluation; more sourced drugs; kidney-function-based dosing; a pre-sign check inside the EHR note editor.
