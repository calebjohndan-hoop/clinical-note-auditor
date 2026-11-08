"""
Fill in `expected_flags` for your hand-verified labels, without editing JSON.

Why this exists: expected flags are fully determined by facts YOU already labeled
(allergies, medications) plus one fact you check in the note (which vitals are written
down). So: for each note this tool shows you the lines that mention vitals, asks which
of the four are present, and derives the flags from your labels with the rule engine.
It never looks at what the extractor found - the ground truth stays yours.

    python tools/derive_flags.py            # asks about each note that has no answer yet
    python tools/derive_flags.py --redo     # ask again for every note
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.extractor import normalize_note  # noqa: E402
from app.rules import run_all_rules  # noqa: E402

DEFAULT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "real_notes")
VITAL_KEYS = {"b": "blood_pressure", "h": "heart_rate", "t": "temperature", "r": "respiratory_rate"}
VITAL_WORDS = re.compile(r"\b(bp|blood pressure|pulse|heart rate|hr|temp|temperature|resp|respiratory|rr|vitals?)\b", re.I)
DUMMY = {"blood_pressure": "120/80", "heart_rate": 70, "temperature": 98.6, "respiratory_rate": 16}


def derive(label: dict, vitals_letters: str) -> list:
    note = {
        "medications": [{"name": m["name"], "dose": m.get("dose_mg"), "unit": "mg"}
                        for m in label.get("medications", [])],
        "vitals": {VITAL_KEYS[c]: DUMMY[VITAL_KEYS[c]] for c in vitals_letters if c in VITAL_KEYS},
    }
    if label.get("allergy_documented", False):
        note["allergies"] = label.get("allergies", [])
    note = normalize_note(note)
    return sorted({f.rule for f in run_all_rules(note).flags})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--only", help="ask only about this note id, e.g. mts_11")
    args = ap.parse_args()

    for path in sorted(glob.glob(os.path.join(args.dir, "*.label.json"))):
        with open(path, encoding="utf-8") as f:
            label = json.load(f)
        if not label.get("verified"):
            continue
        if args.only and label["id"] != args.only:
            continue
        if "vitals_present" in label and not (args.redo or args.only):
            continue
        with open(os.path.join(args.dir, label["id"] + ".txt"), encoding="utf-8") as f:
            text = f.read()

        print("\n" + "=" * 70)
        print(f"{label['id']}  -  lines in the note that mention vitals:")
        hits = [s.strip() for s in re.split(r"(?<=[.;])\s+|\n+", text) if VITAL_WORDS.search(s)]
        for s in hits[:8] or ["(none found - but search the note yourself to be sure)"]:
            print("   >", s[:160])
        ans = input("Which are written in the note with a value?  b=BP  h=heart rate  "
                    "t=temperature  r=resp rate   (e.g. 'bh', or just Enter for none): ").strip().lower()
        letters = "".join(c for c in ans if c in VITAL_KEYS)

        flags = derive(label, letters)
        label["vitals_present"] = letters
        label["expected_flags"] = flags
        note_line = "expected_flags derived by tools/derive_flags.py from labeled allergies/meds + vitals answer"
        if note_line not in (label.get("notes") or ""):
            label["notes"] = ((label.get("notes") or "") + " | " + note_line).strip(" |")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(label, f, indent=2)
        print(f"   saved: vitals_present='{letters}'  expected_flags={flags}")
    print("\nDone. Now run: python tools/eval_real_notes.py")


if __name__ == "__main__":
    main()
