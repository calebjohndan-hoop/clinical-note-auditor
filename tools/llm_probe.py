"""
Check that your LLM provider works on a REAL (long) note, using the actual extractor code.
It tries the extractor in two configurations and prints what came back:

    python tools/llm_probe.py data/real_notes/mts_02.txt

1 = full extraction (what the demo UI asks for, includes the SOAP rewrite)
2 = lean extraction (what the evaluation asks for: allergies/meds/vitals only)
Free tiers allow only ~8k tokens/minute, so 429 waits are handled inside the extractor
(it can pause up to ~75 s per retry). Be patient: the whole probe can take 2-3 minutes.
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app  # noqa: E402,F401  (loads .env)
from app.extractor import ExtractionError  # noqa: E402
from app.llm_extractor import extract_gemini  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python tools/llm_probe.py data/real_notes/mts_02.txt")
    text = open(sys.argv[1], encoding="utf-8").read()
    print(f"model={os.environ.get('LLM_MODEL')}  base={os.environ.get('LLM_BASE_URL')}  "
          f"note_chars={len(text)}\n")
    for name, skip in (("1 full extraction (with SOAP)", None), ("2 lean extraction (no SOAP)", "1")):
        if skip:
            os.environ["LLM_SKIP_SOAP"] = skip
        else:
            os.environ.pop("LLM_SKIP_SOAP", None)
        t0 = time.time()
        try:
            n = extract_gemini(text)
            print(f"{name}: OK in {time.time() - t0:.0f}s")
            print(f"   allergies = {n.get('allergies')}")
            print(f"   meds      = {[(m['name'], m['dose']) for m in n['medications']]}")
            print(f"   vitals    = {n['vitals']}")
            print(f"   soap sections filled = {[k for k, v in n['soap'].items() if v.strip()]}\n")
        except ExtractionError as e:
            print(f"{name}: FAILED in {time.time() - t0:.0f}s\n   {str(e)[:400]}\n")


if __name__ == "__main__":
    main()
