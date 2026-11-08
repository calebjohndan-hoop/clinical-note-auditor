"""
Pull a sample of REAL de-identified notes from the MTSamples dataset and
create label files for you to hand-correct.

1. Download the dataset CSV (free): Kaggle -> "Medical Transcriptions"
   (tboyle10/medicaltranscriptions) -> mtsamples.csv. Put it in data/.
2. python3 tools/sample_real_notes.py data/mtsamples.csv --n 20
3. Open each data/real_notes/<id>.label.json, compare against <id>.txt and
   FIX the labels by hand, then set "verified": true. The prefill is the
   regex extractor's guess — it's there to save typing, NOT to be trusted.
   Read the note yourself; anchoring on the prefill defeats the purpose.
4. python3 tools/eval_real_notes.py        (regex)
   EXTRACTOR=hybrid python3 tools/eval_real_notes.py   (with Gemini)

Note texts are written to data/real_notes/ which is .gitignored: MTSamples
says its reports are "for reference purpose only", so don't publish them in
your repo — publish your labels + the script, and cite the dataset.
"""
import argparse
import csv
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.extractor import extract_regex  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "real_notes")


def interesting(text: str) -> bool:
    t = text.lower()
    return bool(re.search(r"allerg|nkda", t)) and bool(re.search(r"\d\s*mg\b", t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--prefix", default="mts", help="file prefix: mts_00.txt ... (use 'hold' for a held-out set)")
    ap.add_argument("--blank", action="store_true",
                    help="write EMPTY label stubs (no regex guess to anchor on) - use for the held-out set")
    args = ap.parse_args()

    with open(args.csv_path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("transcription") and interesting(r["transcription"])]
    # never re-sample a note that is already on disk (keeps a held-out set truly new)
    have = set()
    if os.path.isdir(OUT):
        for fn in os.listdir(OUT):
            if fn.endswith(".txt"):
                with open(os.path.join(OUT, fn), encoding="utf-8") as f:
                    have.add(re.sub(r"\W+", "", f.read().lower())[:400])
    rows = [r for r in rows
            if re.sub(r"\W+", "", r["transcription"].replace(",", ", ").lower())[:400] not in have]
    print(f"{len(rows)} NEW notes mention allergies AND a mg dose; sampling {args.n}")
    random.Random(args.seed).shuffle(rows)

    os.makedirs(OUT, exist_ok=True)
    for i, row in enumerate(rows[: args.n]):
        nid = f"{args.prefix}_{i:02d}"
        text = row["transcription"].replace(",", ", ").replace(".,", ". ")
        with open(os.path.join(OUT, f"{nid}.txt"), "w", encoding="utf-8") as f:
            f.write(text)
        guess = {"medications": []} if args.blank else extract_regex(text)
        label = {
            "id": nid,
            "source": f"MTSamples via Kaggle: {row.get('sample_name', '').strip()} "
                      f"({row.get('medical_specialty', '').strip()})",
            "verified": False,
            "allergy_documented": False if args.blank else "allergies" in guess,
            "allergies": guess.get("allergies", []),
            "medications": [{"name": m["name"], "dose_mg": m["dose"]} for m in guess["medications"]],
            "expected_flags": [],
            "notes": "",
        }
        with open(os.path.join(OUT, f"{nid}.label.json"), "w", encoding="utf-8") as f:
            json.dump(label, f, indent=2)
    print(f"Wrote {min(args.n, len(rows))} notes + label stubs to data/real_notes/. Now verify labels by hand.")


if __name__ == "__main__":
    main()
