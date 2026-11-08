"""
Score the current extractor against your hand-verified real-note labels.
Prints per-note misses and overall precision/recall — the numbers for your
one-pager ("on 20 real de-identified notes, regex allergy recall was X%,
hybrid Y%").

    python3 tools/eval_real_notes.py
    EXTRACTOR=hybrid python3 tools/eval_real_notes.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.extractor import extract_fields, normalize_note  # noqa: E402
from app.rules import run_all_rules  # noqa: E402

DIR = os.path.join(os.path.dirname(__file__), "..", "data", "real_notes")


def _mode() -> str:
    # Same default as app.extractor.extract_fields: hybrid when an LLM key is set.
    from app.llm_extractor import llm_configured
    return os.environ.get("EXTRACTOR") or ("hybrid" if llm_configured() else "regex")


def _pr(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r


def evaluate(verbose=True, prefix="") -> dict:
    os.environ.setdefault("LLM_SKIP_SOAP", "1")   # eval scores allergies/meds/vitals only: ask for nothing else
    labels = []
    for path in sorted(glob.glob(os.path.join(DIR, f"{prefix}*.label.json"))):
        with open(path, encoding="utf-8") as f:
            lab = json.load(f)
        # Note texts are .gitignored (MTSamples licence), so a fresh clone has labels but no
        # text: skip those instead of crashing. Regenerate texts with tools/sample_real_notes.py.
        if lab.get("verified") and os.path.exists(os.path.join(DIR, lab["id"] + ".txt")):
            labels.append(lab)
    if not labels:
        if verbose:
            print("No verified labels yet (set \"verified\": true after checking each label).")
        return {"n": 0}

    fallbacks, first_error = [], None
    tot = {"a": [0, 0, 0], "m": [0, 0, 0], "f": [0, 0, 0]}
    for lab in labels:
        with open(os.path.join(DIR, lab["id"] + ".txt"), encoding="utf-8") as f:
            text = f.read()
        got = extract_fields(text)
        if got.get("extractor_warning"):
            fallbacks.append(lab["id"])
            first_error = first_error or got["extractor_warning"]
        # normalize the LABELS the same way so "PCN" vs "penicillin" isn't a false miss
        exp = normalize_note({"allergies": lab["allergies"],
                              "medications": [{"name": m["name"], "dose": m["dose_mg"], "unit": "mg"}
                                              for m in lab["medications"]]})
        pairs = {
            "a": (set(exp["allergies"]), set(got.get("allergies", []))),
            "m": ({(m["name"], m["dose"]) for m in exp["medications"]},
                  {(m["name"], m["dose"]) for m in got["medications"]}),
            "f": (set(lab.get("expected_flags", [])), {f.rule for f in run_all_rules(got).flags}),
        }
        for k, (e, g) in pairs.items():
            tot[k][0] += len(e & g)
            tot[k][1] += len(g - e)
            tot[k][2] += len(e - g)
            if verbose and (e - g or g - e):
                print(f"{lab['id']} [{ {'a':'allergies','m':'meds','f':'flags'}[k] }] "
                      f"MISSED={sorted(e - g)} EXTRA={sorted(g - e)}")

    if fallbacks and verbose:
        print(f"\nWARNING: LLM fell back to regex on {len(fallbacks)} note(s): {fallbacks}. "
              "Those are NOT hybrid results; wait a minute and rerun.")
        print(f"First error: {str(first_error)[:300]}")
    out = {"fell_back": fallbacks, "n": len(labels), "extractor": _mode()}
    for k, name in (("a", "allergies"), ("m", "medications"), ("f", "flags")):
        p, r = _pr(*tot[k])
        out[name] = {"precision": round(p, 3), "recall": round(r, 3)}
    if verbose:
        print(f"\n{out['n']} verified notes, extractor={out['extractor']}")
        for name in ("allergies", "medications", "flags"):
            print(f"  {name:12} precision {out[name]['precision']:.0%}   recall {out[name]['recall']:.0%}")
    return out


if __name__ == "__main__":
    # python tools/eval_real_notes.py            -> every verified note
    # python tools/eval_real_notes.py hold       -> only the held-out set (hold_*.label.json)
    evaluate(prefix=sys.argv[1] if len(sys.argv) > 1 else "")
