"""
Real-note regression gate. Skips until you've verified labels with
tools/sample_real_notes.py. Once labels exist, safety recall (allergies and
flags) must not regress below the floor — raise the floor as you improve.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.eval_real_notes import evaluate

# Start honest: set these to whatever the regex scores on day one, then only
# ever raise them. A drop means a change made the auditor miss real issues.
# Floors set from the regex run on 15 hand-labeled notes (Oct 2026: allergies 100%, meds 96%+,
# flags 100%), with a little slack. Raise them as the labeled set grows; never lower them to
# make a failing change pass.
ALLERGY_RECALL_FLOOR = 0.95
MED_RECALL_FLOOR = 0.90
FLAG_RECALL_FLOOR = 0.95


def test_real_note_recall_does_not_regress(monkeypatch):
    # Deterministic and free: never spend LLM quota inside the test suite.
    monkeypatch.setenv("EXTRACTOR", "regex")
    res = evaluate(verbose=False)
    if res["n"] == 0:
        pytest.skip("no verified real-note labels yet")
    assert res["allergies"]["recall"] >= ALLERGY_RECALL_FLOOR, res
    assert res["medications"]["recall"] >= MED_RECALL_FLOOR, res
    assert res["flags"]["recall"] >= FLAG_RECALL_FLOOR, res
