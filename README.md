# Clinical Note Auditor

> **Live demo:** [PASTE RENDER LINK HERE] (free hosting: the first visit can take up to a minute to wake the server) · **Demo video:** [PASTE YOUTUBE LINK HERE] · **One-pager:** [ONE_PAGER.pdf](ONE_PAGER.pdf) · Built solo by Caleb John Daniel Balakumar for DSH Hacks V2 (AI x Healthcare).

Paste a messy clinical note. Get back:

1. **A structured SOAP note** (Subjective / Objective / Assessment / Plan)
2. **Safety flags**: drug–allergy conflicts, out-of-range doses, missing vitals, missing or unrecognized allergy documentation
3. **An action checklist** in priority order, e.g. *"HOLD amoxicillin. Confirm the penicillin allergy and its reaction with the patient."*

**Result in one line:** on 10 real notes the system had never seen, adding an LLM to the rules raised medication recall from **61% to 100%**, while every safety decision still comes from deterministic, sourced rules. Small sample, one labeler, not clinically validated.

| Held-out (10 unseen real notes) | Regex only | Hybrid (regex + LLM) |
|---|---|---|
| Allergies precision / recall | 88% / 100% | 88% / 100% |
| Medications precision / recall | 68% / 61% | 76% / **100%** |
| Safety flags precision / recall | 91% / 91% | 91% / 91% |

## Architecture: the LLM reads, the rules decide

```
note text ──► extractor (regex | llm | hybrid) ──► structured note (CONTRACT.md)
                                                          │
                                   rules.py (deterministic) ◄┘
                                          │
                                   flags ──► checklist.py (deterministic)
```

- **The AI never makes the safety call.** The LLM (Groq `openai/gpt-oss-120b`, or Google Gemini) only turns free text into fields. Every flag and checklist line comes from plain Python rules over a reference table where every entry cites a source.
- **Hybrid mode makes the LLM additive only.** Regex and LLM both run, and the rules see the *union* of their findings. The LLM can add an allergy the regex missed; it can never remove one. Enforced by `test_full_suite_passes_in_hybrid_mode_even_with_a_useless_llm`.
- **Failures are loud.** If the LLM fails, LLM-only mode returns HTTP 502 ("note NOT audited") and hybrid mode falls back to regex with a visible warning. No mode ever returns a silent "all clear".

## Run it

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # optional: paste a free Groq key into LLM_API_KEY for hybrid mode
uvicorn app.main:app
```

**macOS / Linux**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optional: add a free Groq key for hybrid mode
uvicorn app.main:app
```

Open http://127.0.0.1:8000/ and click a sample (Allergy conflict, Dose error, Messy prose, Hidden allergy, Clean), or `POST /audit {"text": "..."}`.
Without a key it runs in `regex` mode, fully offline. The line under each result shows which extractor ran.

**Deploy your own:** `render.yaml` is a one-click Render Blueprint (free plan). On the public demo, `LLM_MAX_WAIT=5` and `LLM_TIMEOUT=30` make a rate-limited or slow LLM fall back to regex with a visible warning instead of hanging.

## Tests

```bash
python -m pytest tests -q        # 97 tests, offline, ~10 s (forces regex mode; never spends LLM quota)
```

| File | What it proves |
|---|---|
| `tests/test_rules.py` | Planted-error and clean synthetic notes |
| `tests/test_extractor_stress.py` | Messy phrasings that MUST flag and that must NOT flag. Every case started as a real miss: brand names, abbreviations (PCN, ASA), "NKDA except X", dose-first wording, gm/mcg units, ER/XR suffixes, salt names, vitals phrasings from real notes |
| `tests/test_llm_and_api.py` | LLM output parsing, bad JSON → loud error, retries and rate limits (local fake servers), the hybrid union property, checklist, SOAP, API |
| `tests/test_real_notes.py` | Recall floor on the hand-labeled real notes (skips on a fresh clone; see below) |

## Real-note evaluation (MTSamples)

25 de-identified notes from MTSamples (Kaggle "Medical Transcriptions"), hand-labeled: allergies, medications with doses, and which vitals are present. 15 were used for development, 10 held out until the end. Labels are in `data/real_notes/*.label.json`; each label's `source` field names the MTSamples sample it came from. Note texts are **not** in this repo (MTSamples is "for reference purpose only"). To sample and score your own:

```bash
# put mtsamples.csv in data/, then:
python tools/sample_real_notes.py data/mtsamples.csv --help   # sampling options (--n, --seed, --prefix)
python tools/eval_real_notes.py                               # regex scores on labeled notes
python tools/eval_real_notes.py hold                          # held-out set only
```

Set `EXTRACTOR=hybrid` (and an LLM key) to score hybrid mode.

**What the real notes taught me:** the first run scored medication recall 65% on the dev set. Real notes use brand names (Lasix, Norvasc), salts ("metoprolol tartrate"), "1 gm", "pulse was 94", dash-separated lists, and allergy lists on the line below the heading. Each became a fix plus a regression test. The held-out set then showed what regex alone still misses (a dose in a different sentence than its drug), which is exactly where the LLM helps. While re-checking labels I also found and corrected one of my own label errors.

## Reference data

`data/reference_tables.py`: every entry has a source comment (DailyMed labels, ACR contrast manual, AHA 2021, AAAAI 2022). Deliberate choices:

- **Iodine → contrast is NOT flagged.** That conflict is a myth (ACR).
- **Penicillin → cephalosporins is NOT flagged.** Cross-reactivity is low and current guidance doesn't treat it as a contraindication (AAAAI).
- **Codeine → hydrocodone is a medium "review", not a HOLD.** A "codeine allergy" is usually an intolerance.
- **Amoxicillin / ampicillin / Augmentin allergies count as penicillin** (conservative).

## Known limitations

- Small evaluation: 25 notes, one labeler. Flag scores are derived from my labels, so they mostly measure extraction.
- Dose table covers 7 drugs and allergy table 7 classes, because every entry must be sourced. Dose checks are per-dose sanity bounds, not personalized dosing.
- Misses drugs with no mg dose (inhalers), counts supplements as medications, can attribute a family member's medication or allergy to the patient (regex), and can't tell a planned or past dose from a current one.
- A *resolved* allergy still flags (by design: over-flag rather than miss).

**Synthetic or de-identified notes only. Research prototype. Not a medical device. Not clinically validated.**

Built with AI coding assistance; the problem choice, labeling and evaluation are my own.
