"""
Tests for the Gemini path, the hybrid merge, the action checklist, SOAP output
and the HTTP API. No network or API key needed: the Gemini call is replaced
with canned JSON, so this checks OUR handling of whatever the model returns.

To test against the REAL model instead:
    export GEMINI_API_KEY=...
    EXTRACTOR=gemini pytest tests/test_rules.py tests/test_extractor_stress.py
    EXTRACTOR=hybrid pytest tests/test_rules.py tests/test_extractor_stress.py
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

import app.llm_extractor as llm
from app.checklist import build_checklist
from app.extractor import ExtractionError, extract_fields, extract_regex
from app.main import app
from app.rules import run_all_rules
from tests import test_extractor_stress, test_rules

V = " BP 120/80 HR 70 Temp 98.6 RR 16."


def _fake_llm(payload: dict):
    return lambda raw_text: json.dumps(payload)


# ---------- parsing + normalization of LLM output ----------

def test_llm_output_is_normalized_to_contract():
    out = llm.parse_llm_json(json.dumps({
        "allergy_status": "documented",
        "allergies": ["PCN", "Sulfa drugs"],
        "medications": [{"name": "Augmentin", "dose": 875, "unit": "mg"},
                        {"name": "Tylenol", "dose": 1, "unit": "g"}],
        "vitals": {"blood_pressure": "120/80", "heart_rate": 70},
        "soap": {"plan": "Augmentin 875 mg BID"},
    }), "raw")
    assert out["allergies"] == ["penicillin", "sulfa"]
    assert {"name": "amoxicillin", "dose": 875.0, "unit": "mg"} in out["medications"]
    assert {"name": "acetaminophen", "dose": 1000.0, "unit": "mg"} in out["medications"]
    assert out["vitals"] == {"blood_pressure": "120/80", "heart_rate": 70}
    assert out["extractor"] == "gemini"


def test_llm_not_mentioned_means_no_allergy_key():
    out = llm.parse_llm_json(json.dumps({"allergy_status": "not_mentioned"}), "raw")
    assert "allergies" not in out
    assert "missing_allergy_section" in {f.rule for f in run_all_rules(out).flags}


def test_llm_none_means_empty_list_not_missing():
    out = llm.parse_llm_json(json.dumps({"allergy_status": "none", "allergies": []}), "raw")
    assert out["allergies"] == []


def test_llm_unknown_units_are_dropped_not_faked():
    out = llm.parse_llm_json(json.dumps({"allergy_status": "none",
        "medications": [{"name": "insulin", "dose": 10, "unit": "units"}]}), "raw")
    assert out["medications"] == []


@pytest.mark.parametrize("bad", ["not json", "{}", '{"allergy_status": "maybe"}', "[]", ""])
def test_bad_llm_json_raises_never_returns_empty(bad):
    with pytest.raises(ExtractionError):
        llm.parse_llm_json(bad, "raw")


def test_gemini_network_failure_raises(monkeypatch):
    def boom(_):
        raise TimeoutError("network down")
    monkeypatch.setattr(llm, "_call_llm", boom)
    with pytest.raises(ExtractionError):
        llm.extract_gemini("Allergies: penicillin. amoxicillin 500mg.")


# ---------- hybrid: the LLM can add findings, never remove them ----------

def test_hybrid_llm_cannot_erase_regex_allergy(monkeypatch):
    # LLM wrongly says "no allergies": the regex-found penicillin must survive.
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({"allergy_status": "none", "allergies": []}))
    note = llm.extract_hybrid("Allergies: penicillin. Plan: amoxicillin 500mg." + V)
    assert "penicillin" in note["allergies"]
    assert "drug_allergy_conflict" in {f.rule for f in run_all_rules(note).flags}


def test_hybrid_llm_adds_what_regex_missed(monkeypatch):
    # Phrasing the regex can't parse; the LLM catches it -> conflict fires.
    text = "Hx: anaphylaxis after a pen-class antibiotic as a child. Plan: ampicillin 500mg." + V
    assert "drug_allergy_conflict" not in {f.rule for f in run_all_rules(extract_regex(text)).flags}
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({"allergy_status": "documented", "allergies": ["penicillin"]}))
    note = llm.extract_hybrid(text)
    assert "drug_allergy_conflict" in {f.rule for f in run_all_rules(note).flags}


def test_hybrid_degrades_to_regex_with_visible_warning(monkeypatch):
    monkeypatch.setattr(llm, "_call_llm", lambda _: "garbage")
    note = llm.extract_hybrid("Allergies: penicillin. amoxicillin 500mg." + V)
    assert note["extractor"].startswith("regex")
    assert note["extractor_warning"]
    assert "drug_allergy_conflict" in {f.rule for f in run_all_rules(note).flags}


def test_full_suite_passes_in_hybrid_mode_even_with_a_useless_llm(monkeypatch):
    """The core safety property: with an LLM that finds NOTHING, hybrid mode
    still passes every existing rule + stress test, because regex findings
    are never dropped."""
    monkeypatch.setenv("EXTRACTOR", "hybrid")
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({"allergy_status": "not_mentioned"}))
    assert extract_fields("Allergies: penicillin.")["extractor"] == "hybrid"
    for name in dir(test_rules):
        if name.startswith("test_"):
            getattr(test_rules, name)()
    test_extractor_stress.test_must_flag()
    test_extractor_stress.test_vitals_alt_wording()
    test_extractor_stress.test_vitals_word_boundaries()


# ---------- checklist + SOAP ----------

def test_checklist_puts_hold_first_and_collapses_vitals():
    note = extract_regex("Allergies: penicillin. Plan: amoxicillin 500mg.")
    actions = build_checklist(run_all_rules(note))
    assert actions[0].priority == 1 and actions[0].action.startswith("HOLD amoxicillin")
    vitals_lines = [a for a in actions if a.rule == "missing_vitals"]
    assert len(vitals_lines) == 1 and "blood pressure" in vitals_lines[0].action


def test_checklist_dose_action_mentions_dose():
    note = extract_regex("Allergies: NKDA. Give 5000 mg metformin." + V)
    actions = build_checklist(run_all_rules(note))
    assert len(actions) == 1 and "5000mg" in actions[0].action


def test_clean_note_has_empty_checklist():
    note = extract_regex("Allergies: NKDA. atorvastatin 20mg." + V)
    assert build_checklist(run_all_rules(note)) == []


def test_soap_sections_populated():
    soap = extract_regex("Cough x3 days. Allergies: NKDA. BP 120/80 HR 70. "
                         "Likely viral URI. Plan: fluids, rest.")["soap"]
    assert "Cough" in soap["subjective"]
    assert "120/80" in soap["objective"]
    assert "viral" in soap["assessment"]
    assert "fluids" in soap["plan"]


# ---------- HTTP API ----------

client = TestClient(app)


def test_api_audit_returns_flags_checklist_soap(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "regex")
    r = client.post("/audit", json={"text": "Allergies: PCN. Start Augmentin 875mg." + V})
    assert r.status_code == 200
    d = r.json()
    assert d["has_high_severity"] is True
    assert d["checklist"][0]["action"].startswith("HOLD amoxicillin")
    assert set(d["soap"]) == {"subjective", "objective", "assessment", "plan"}
    assert d["extractor"] == "regex"


def test_api_extraction_failure_is_502_not_clean(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "gemini")
    monkeypatch.setattr(llm, "_call_llm", lambda _: "garbage")
    r = client.post("/audit", json={"text": "Allergies: penicillin. amoxicillin 500mg."})
    assert r.status_code == 502 and "NOT audited" in r.json()["detail"]


def test_api_rejects_empty_note():
    assert client.post("/audit", json={"text": ""}).status_code == 422


def test_frontend_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "Clinical Note Auditor" in r.text


def test_codeine_hydrocodone_is_review_not_hard_stop():
    note = extract_regex("Allergies: codeine. Plan: hydrocodone 5mg." + V)
    res = run_all_rules(note)
    conflict = [f for f in res.flags if f.rule == "drug_allergy_conflict"]
    assert conflict and conflict[0].severity == "medium" and not res.has_high_severity
    assert build_checklist(res)[0].action.startswith("Review hydrocodone")


# ---------- OpenAI-compatible providers (Groq / OpenRouter / Cerebras ...) ----------

import http.server
import threading


def _serve(status, body):
    seen = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            seen["body"] = json.loads(self.rfile.read(n))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


def _provider_env(monkeypatch, srv):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    monkeypatch.setenv("LLM_MODEL", "some-model")


def test_openai_compat_end_to_end_against_local_server(monkeypatch):
    payload = {"allergy_status": "documented", "allergies": ["PCN"],
               "medications": [{"name": "Augmentin", "dose": 875, "unit": "mg"}]}
    # real providers often wrap JSON in ```json fences — must still parse
    content = "```json\n" + json.dumps(payload) + "\n```"
    srv, seen = _serve(200, {"choices": [{"message": {"content": content}}]})
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_gemini("Allergies: PCN. Augmentin 875mg.")
    finally:
        srv.shutdown()
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "some-model" and seen["body"]["temperature"] == 0
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert "CLINICAL NOTE" in seen["body"]["messages"][1]["content"]
    assert note["allergies"] == ["penicillin"]
    assert note["medications"] == [{"name": "amoxicillin", "dose": 875.0, "unit": "mg"}]


def test_openai_compat_http_error_raises(monkeypatch):
    srv, _ = _serve(429, {"error": "rate limited"})
    try:
        _provider_env(monkeypatch, srv)
        with pytest.raises(ExtractionError, match="429"):
            llm.extract_gemini("Allergies: penicillin.")
    finally:
        srv.shutdown()


def test_openai_compat_hybrid_degrades_visibly(monkeypatch):
    srv, _ = _serve(500, {"error": "boom"})
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_hybrid("Allergies: penicillin. amoxicillin 500mg." + V)
    finally:
        srv.shutdown()
    assert note["extractor"].startswith("regex") and "500" in note["extractor_warning"]
    assert "drug_allergy_conflict" in {f.rule for f in run_all_rules(note).flags}


def test_llm_configured_detects_either_provider(monkeypatch):
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert not llm.llm_configured()
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert llm.llm_configured()
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert not llm.llm_configured()          # provider set but no key
    monkeypatch.setenv("LLM_API_KEY", "x")
    assert llm.llm_configured()


def test_default_mode_switches_to_hybrid_when_key_present(monkeypatch):
    monkeypatch.delenv("EXTRACTOR", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "x")
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({"allergy_status": "not_mentioned"}))
    assert extract_fields("Allergies: penicillin.")["extractor"] == "hybrid"


def test_hybrid_ignores_llm_soap_that_dumps_whole_note_in_one_section(monkeypatch):
    text = "Cough x3 days. Allergies: NKDA. BP 120/80 HR 70. Likely viral URI. Plan: fluids, rest."
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({
        "allergy_status": "none",
        "soap": {"subjective": text, "objective": "", "assessment": "", "plan": ""}}))
    soap = llm.extract_hybrid(text)["soap"]
    assert "120/80" in soap["objective"] and "fluids" in soap["plan"]   # regex split used
    assert soap["subjective"] != text


def test_hybrid_keeps_a_genuine_llm_soap_split(monkeypatch):
    text = "Cough x3 days. BP 120/80. Likely viral URI. Plan: fluids."
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({
        "allergy_status": "not_mentioned",
        "soap": {"subjective": "Cough x3 days.", "objective": "BP 120/80.",
                 "assessment": "Likely viral URI.", "plan": "Plan: fluids."}}))
    soap = llm.extract_hybrid(text)["soap"]
    assert soap["assessment"] == "Likely viral URI." and soap["subjective"] == "Cough x3 days."


# ---------- regression: real Groq output "pen-class" slipped through (2026-10-18) ----------

@pytest.mark.parametrize("llm_allergy", ["pen-class", "Pen-class antibiotic", "penicillins",
                                         "penicillin-type", "PCN", "pen", "Penicillin class"])
def test_llm_allergy_wordings_normalize_to_penicillin(llm_allergy):
    out = llm.parse_llm_json(json.dumps({"allergy_status": "documented", "allergies": [llm_allergy]}), "raw")
    assert out["allergies"] == ["penicillin"], out


def test_real_world_pen_class_note_flags_conflict(monkeypatch):
    # exactly what the live LLM returned for the demo note
    monkeypatch.setattr(llm, "_call_llm", _fake_llm({
        "allergy_status": "documented", "allergies": ["pen-class"],
        "medications": [{"name": "ampicillin", "dose": 500, "unit": "mg"}]}))
    note = llm.extract_hybrid("Hx: anaphylaxis after a pen-class antibiotic as a child. "
                              "Plan: ampicillin 500mg." + V)
    res = run_all_rules(note)
    assert "drug_allergy_conflict" in {f.rule for f in res.flags} and res.has_high_severity


def test_unknown_allergen_is_reported_not_silently_ignored():
    note = extract_regex("Allergies: kiwi. Plan: amoxicillin 500mg." + V)
    flags = [f for f in run_all_rules(note).flags if f.rule == "unrecognized_allergy"]
    assert flags and flags[0].severity == "low" and "kiwi" in flags[0].message
    assert "Manually check" in build_checklist(run_all_rules(note))[0].action


def test_known_allergens_do_not_trigger_unrecognized():
    for text in ("Allergies: penicillin. cephalexin 500mg.", "Allergies: latex. ibuprofen 400mg.",
                 "Allergies: NKDA. ibuprofen 400mg."):
        assert "unrecognized_allergy" not in {f.rule for f in run_all_rules(extract_regex(text + V)).flags}


def _serve_seq(responses):
    """Local server that answers with responses[0], then responses[1], ... (status, body)."""
    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            calls.append(json.loads(self.rfile.read(n)))
            status, body = responses[min(len(calls) - 1, len(responses) - 1)]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


_GOOD = {"choices": [{"message": {"content":
         'Here is the JSON:\n{"allergy_status": "documented", "allergies": ["penicillin"], '
         '"medications": [{"name": "amoxicillin", "dose": 500, "unit": "mg"}]}\nDone.'}}]}
_JSON_FAIL = {"error": {"message": "Failed to validate JSON.", "code": "json_validate_failed",
                        "failed_generation": ""}}


def test_groq_json_validate_failed_retries_without_json_mode(monkeypatch):
    # Seen on Cal's real-note run: 14/15 notes failed with this 400 and silently fell back.
    srv, calls = _serve_seq([(400, _JSON_FAIL), (200, _GOOD)])
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_gemini("Allergies: penicillin. amoxicillin 500mg.")
    finally:
        srv.shutdown()
    assert len(calls) == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]
    assert note["allergies"] == ["penicillin"]          # chatter around the JSON is tolerated


def test_rate_limit_retries_once_then_succeeds(monkeypatch):
    srv, calls = _serve_seq([(429, {"error": "rate limited"}), (200, _GOOD)])
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_gemini("Allergies: penicillin. amoxicillin 500mg.")
    finally:
        srv.shutdown()
    assert len(calls) == 2 and note["medications"][0]["name"] == "amoxicillin"


def test_persistent_json_failure_still_loud(monkeypatch):
    srv, calls = _serve_seq([(400, _JSON_FAIL), (400, _JSON_FAIL)])
    try:
        _provider_env(monkeypatch, srv)
        with pytest.raises(ExtractionError, match="400"):
            llm.extract_gemini("Allergies: penicillin.")
    finally:
        srv.shutdown()
    assert len(calls) == 2                               # one retry, not a loop


# ---------- Real-note lessons: reasoning budget, TPM 429 pacing, SOAP-free eval prompt ----------

class _FakeResp:
    def __init__(self, text="", headers=None):
        self.text, self.headers = text, headers or {}


def test_retry_wait_reads_header_and_provider_message():
    assert llm._retry_wait(_FakeResp(headers={"retry-after": "12"})) == 12.0
    assert llm._retry_wait(_FakeResp('{"message":"Please try again in 25.4s. Need more"}')) == pytest.approx(26.4)
    assert llm._retry_wait(_FakeResp('Please try again in 1m5.5s')) == pytest.approx(66.5)
    assert llm._retry_wait(_FakeResp('Please try again in 10m1.3s')) == 75.0      # capped
    assert llm._retry_wait(_FakeResp("rate limited")) == 0.0


def test_429_waits_the_suggested_time_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    rate = (429, {"error": {"message": "Rate limit. Please try again in 20s."}})
    srv, calls = _serve_seq([rate, rate, (200, _GOOD)])
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_gemini("Allergies: penicillin. amoxicillin 500mg.")
    finally:
        srv.shutdown()
    assert len(calls) == 3 and sleeps == [pytest.approx(21.0)] * 2
    assert note["allergies"] == ["penicillin"]


def test_reasoning_effort_and_token_budget_are_sent_when_configured(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setenv("LLM_MAX_TOKENS", "4096")
    srv, calls = _serve_seq([(200, _GOOD)])
    try:
        _provider_env(monkeypatch, srv)
        llm.extract_gemini("Allergies: penicillin.")
    finally:
        srv.shutdown()
    assert calls[0]["reasoning_effort"] == "low" and calls[0]["max_completion_tokens"] == 4096


def test_groq_gpt_oss_gets_reasoning_cap_by_default_other_providers_do_not(monkeypatch):
    for k in ("LLM_REASONING_EFFORT", "LLM_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    assert llm._provider_params("https://api.groq.com/openai/v1", "openai/gpt-oss-120b") == {
        "reasoning_effort": "low", "max_completion_tokens": 4096}
    assert llm._provider_params("https://openrouter.ai/api/v1", "openai/gpt-oss-120b") == {}
    assert llm._provider_params("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile") == {}


def test_empty_answer_from_token_exhaustion_is_loud(monkeypatch):
    srv, _ = _serve_seq([(200, {"choices": [{"finish_reason": "length", "message": {"content": ""}}]})])
    try:
        _provider_env(monkeypatch, srv)
        with pytest.raises(ExtractionError, match="out of output tokens"):
            llm.extract_gemini("Allergies: penicillin.")
    finally:
        srv.shutdown()


def test_skip_soap_prompt_asks_for_no_soap(monkeypatch):
    monkeypatch.delenv("LLM_SKIP_SOAP", raising=False)
    assert '"soap"' in llm._openai_compat_prompt()
    monkeypatch.setenv("LLM_SKIP_SOAP", "1")
    p = llm._openai_compat_prompt()
    assert "soap" not in p.lower() and p.rstrip().endswith("}")
    assert '"respiratory_rate": number|null}' in p


def test_multiword_drug_names_are_not_cut_to_first_word():
    from app.extractor import normalize_note
    out = normalize_note({"medications": [
        {"name": "Folic acid", "dose": 1, "unit": "mg"},
        {"name": "evening primrose", "dose": 1000, "unit": "mg"},
        {"name": "Metformin ER", "dose": 500, "unit": "mg"},
        {"name": "Lexapro", "dose": 20, "unit": "mg"},
    ]})
    assert [m["name"] for m in out["medications"]] == ["folic acid", "evening primrose", "metformin", "escitalopram"]


def test_api_rejects_whitespace_only_note():
    r = TestClient(app).post("/audit", json={"text": "   \n  "})
    assert r.status_code == 422


def test_accented_allergen_is_not_split_into_fragments():
    note = extract_regex("Allergies: pénicilline. Amoxicillin 500 mg.")
    assert "p" not in note["allergies"]
    assert all(len(a) > 2 for a in note["allergies"])


def test_missing_vital_message_is_human_readable():
    msgs = [f.message for f in run_all_rules(extract_regex("NKDA. BP 120/80 HR 70 Temp 98.6")).flags]
    assert any("respiratory rate" in m for m in msgs)
    assert not any("respiratory_rate" in m for m in msgs)


def test_public_demo_does_not_wait_on_a_long_rate_limit(monkeypatch):
    # LLM_MAX_WAIT (set low on the live deploy): a long 429 fails fast and hybrid falls back
    # to regex with a visible warning, instead of a judge staring at a frozen page.
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("LLM_MAX_WAIT", "5")
    srv, calls = _serve_seq([(429, {"error": {"message": "Please try again in 40s."}}), (200, _GOOD)])
    try:
        _provider_env(monkeypatch, srv)
        note = llm.extract_hybrid("Allergies: penicillin. amoxicillin 500mg." + V)
    finally:
        srv.shutdown()
    assert sleeps == [] and len(calls) == 1
    assert note["extractor"].startswith("regex") and note.get("extractor_warning")
    assert note["allergies"] == ["penicillin"]
