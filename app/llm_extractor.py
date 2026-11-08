"""
Gemini extraction layer. Same output contract as extractor.extract_regex
(see CONTRACT.md), so app/rules.py never knows which extractor ran.

Modes (selected in extractor.extract_fields via the EXTRACTOR env var):
  gemini - LLM only.
  hybrid - regex AND LLM, then UNION the safety-relevant findings.
           The LLM can add an allergy/medication the regex missed; it can
           never remove one the regex found. This is the evidence-gating
           idea applied to extraction: the AI never gets to make a note look
           SAFER than the deterministic layer says it is.

Providers (set in .env). The extractor modes below work with either:
  A) Gemini (default):      GEMINI_API_KEY=...   [GEMINI_MODEL=...]
  B) Any OpenAI-compatible  LLM_PROVIDER=openai
     free API (Groq,        LLM_API_KEY=...
     OpenRouter, Cerebras…) LLM_BASE_URL=https://api.groq.com/openai/v1
                            LLM_MODEL=llama-3.3-70b-versatile
"""

from __future__ import annotations

import json
import os
import time
import re
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ValidationError

from app.extractor import ExtractionError, extract_regex, normalize_note

DEFAULT_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """You extract structured data from a clinical note for a medication-safety auditor.

Rules:
- Extract ONLY what is literally written in the note. Never infer, guess, or add.
- allergy_status: "documented" if the note lists any patient allergy;
  "none" if it says NKDA / no known allergies / denies allergies;
  "not_mentioned" if the note says nothing about allergies.
- allergies: the PATIENT's allergens, each written as the standard generic drug or drug-class
  name in lowercase, expanding abbreviations and descriptions: "PCN" or "pen-class antibiotic"
  -> "penicillin"; "sulfa drugs" -> "sulfa"; "NSAIDs" -> "nsaid"; "ASA" -> "aspirin".
  Include an allergen listed as an exception ("no allergies except penicillin").
  Exclude family members' allergies and allergies explicitly stated as resolved/removed.
- medications: every drug with a stated dose. name = drug name as written (brand is fine),
  dose = number only, unit = mg | g | mcg | other. Skip drugs with no dose.
- vitals: only if written; null otherwise. blood_pressure as "sys/dia".
- soap: split the note's OWN sentences into four sections. Every sentence goes in exactly
  ONE section; never copy the whole note into one section. Do not write new clinical content.
    subjective = symptoms, history, complaints, and allergy statements
    objective  = vital signs, exam findings, lab/test results
    assessment = diagnoses, impressions
    plan       = medications ordered/started/continued, tests ordered, follow-up, instructions
  Use "" for a section with nothing in the note.
Return JSON only."""


class _Med(BaseModel):
    name: str
    dose: Optional[float] = None
    unit: Optional[str] = "mg"


class _Vitals(BaseModel):
    blood_pressure: Optional[str] = None
    heart_rate: Optional[int] = None
    temperature: Optional[float] = None
    respiratory_rate: Optional[int] = None


class _Soap(BaseModel):
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""


class LLMExtraction(BaseModel):
    allergy_status: Literal["documented", "none", "not_mentioned"]
    allergies: list[str] = []
    medications: list[_Med] = []
    vitals: _Vitals = _Vitals()
    soap: _Soap = _Soap()


_client = None


def _get_client():
    """Lazily build the Gemini client. Tests monkeypatch this."""
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ExtractionError("GEMINI_API_KEY not set — use EXTRACTOR=regex or set the key.")
        try:
            from google import genai
        except ImportError as e:  # pragma: no cover
            raise ExtractionError("pip install google-genai") from e
        _client = genai.Client(api_key=key)
    return _client


def _call_gemini_api(raw_text: str) -> str:
    from google.genai import types

    resp = _get_client().models.generate_content(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
        contents=f"CLINICAL NOTE:\n<<<\n{raw_text}\n>>>",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
            response_mime_type="application/json",
            response_schema=LLMExtraction,
        ),
    )
    return resp.text or ""


def _skip_soap() -> bool:
    return os.environ.get("LLM_SKIP_SOAP") == "1"


def _openai_compat_prompt() -> str:
    # json_object mode guarantees valid JSON but not OUR schema, so spell it out.
    prompt = SYSTEM_PROMPT
    schema_tail = (
        ', "soap": {"subjective": string, "objective": string, "assessment": string, "plan": string}}'
    )
    if _skip_soap():
        # The SOAP section repeats the whole note, which is most of the output tokens. The
        # evaluation only needs allergies/meds/vitals, so it can ask for just those: on free
        # tiers (8k tokens/minute) that is the difference between working and 429.
        i, j = prompt.index("- soap:"), prompt.index("Return JSON only.")
        prompt = prompt[:i] + prompt[j:]
        schema_tail = "}"
    return prompt + (
        "\n\nReturn exactly one JSON object with these keys and no others:\n"
        '{"allergy_status": "documented|none|not_mentioned", "allergies": [string], '
        '"medications": [{"name": string, "dose": number|null, "unit": string}], '
        '"vitals": {"blood_pressure": string|null, "heart_rate": number|null, '
        '"temperature": number|null, "respiratory_rate": number|null}' + schema_tail
    )


def _retry_wait(resp) -> float:
    """Seconds to wait before retrying a 429: Retry-After header, else the provider's
    'Please try again in 25.4s' / '10m1.3s' message. Capped so a stuck daily limit
    fails loudly instead of hanging."""
    try:
        return min(float(resp.headers.get("retry-after", "")), 75.0)
    except ValueError:
        pass
    m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", resp.text)
    if m and (m.group(1) or m.group(2)):
        return min(int(m.group(1) or 0) * 60 + float(m.group(2) or 0) + 1.0, 75.0)
    return 0.0


def _post_chat(base: str, key: str, body: dict):
    # LLM_TIMEOUT: a public demo should give up fast and fall back to regex (visibly).
    return httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"},
                      json=body, timeout=float(os.environ.get("LLM_TIMEOUT", "120")))


def _provider_params(base: str, model: str) -> dict:
    """gpt-oss on Groq is a reasoning model: with default settings it can spend its whole
    output budget thinking and return NOTHING (finish_reason=length, empty content; with JSON
    mode that surfaces as HTTP 400 json_validate_failed). Cap the thinking and give room for
    the answer. Override with LLM_REASONING_EFFORT / LLM_MAX_TOKENS (set to 'off' to disable)."""
    params = {}
    effort = os.environ.get("LLM_REASONING_EFFORT")
    max_tokens = os.environ.get("LLM_MAX_TOKENS")
    is_groq_oss = "groq.com" in base and "gpt-oss" in model
    if effort is None and is_groq_oss:
        effort = "low"
    if max_tokens is None and is_groq_oss:
        max_tokens = "4096"
    if effort and effort != "off":
        params["reasoning_effort"] = effort
    if max_tokens and max_tokens != "off":
        params["max_completion_tokens"] = int(max_tokens)
    return params


def _call_openai_compat(raw_text: str) -> str:
    """Free providers (Groq, OpenRouter, Cerebras, ...) speak the OpenAI chat API.

    Real-note lessons (Oct 2026): long notes + a reasoning model + strict JSON mode gave
    HTTP 400 json_validate_failed; free tiers also cap tokens/minute, so back-to-back notes get
    429. A 429 waits the provider's own suggested time and retries (twice); a JSON-mode 400
    retries once without JSON mode. Anything still failing raises a loud ExtractionError."""
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise ExtractionError("LLM_API_KEY not set (LLM_PROVIDER=openai).")
    base = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _openai_compat_prompt()},
            {"role": "user", "content": f"CLINICAL NOTE:\n<<<\n{raw_text}\n>>>"},
        ],
        **_provider_params(base, model),
    }
    resp = _post_chat(base, key, body)
    json_mode_dropped = False
    for _ in range(3):
        if resp.status_code == 429:
            wait = _retry_wait(resp)
            if wait > float(os.environ.get("LLM_MAX_WAIT", "75")):
                break   # don't keep a user waiting: fail loudly, hybrid falls back to regex
            time.sleep(wait)
            resp = _post_chat(base, key, body)
        elif resp.status_code == 400 and "json_validate_failed" in resp.text and not json_mode_dropped:
            json_mode_dropped = True
            body = {k: v for k, v in body.items() if k != "response_format"}
            resp = _post_chat(base, key, body)
        else:
            break
    if resp.status_code != 200:
        raise ExtractionError(f"LLM API HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        choice = resp.json()["choices"][0]
        content = choice["message"].get("content") or ""
    except (KeyError, IndexError, ValueError) as e:
        raise ExtractionError(f"Unexpected LLM API response shape: {resp.text[:300]}") from e
    if not content.strip() and choice.get("finish_reason") == "length":
        raise ExtractionError("The LLM ran out of output tokens before answering "
                              "(raise LLM_MAX_TOKENS or lower LLM_REASONING_EFFORT).")
    return content


def llm_configured() -> bool:
    if os.environ.get("LLM_PROVIDER", "").lower() in ("openai", "groq", "openrouter"):
        return bool(os.environ.get("LLM_API_KEY"))
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _call_llm(raw_text: str) -> str:
    """Single entry point. Tests replace this."""
    if os.environ.get("LLM_PROVIDER", "").lower() in ("openai", "groq", "openrouter"):
        return _call_openai_compat(raw_text)
    return _call_gemini_api(raw_text)


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def _json_object_text(raw: str) -> str:
    """Strip ```json fences, and without strict JSON mode the model may add a sentence
    before/after the object: keep only the outermost {...}."""
    raw = _FENCE.sub("", raw or "")
    i, j = raw.find("{"), raw.rfind("}")
    return raw[i : j + 1] if i != -1 and j > i else raw


def parse_llm_json(raw_json: str, raw_text: str) -> dict:
    """LLM JSON -> contract dict. Raises ExtractionError on anything off-schema.
    Split out from the API call so it can be unit-tested with no network."""
    try:
        data = LLMExtraction.model_validate(json.loads(_json_object_text(raw_json)))
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        raise ExtractionError(f"The LLM returned invalid/off-schema JSON: {e}") from e

    note = {
        "allergies": data.allergies if data.allergy_status == "documented" else [],
        "medications": [m.model_dump() for m in data.medications],
        "vitals": data.vitals.model_dump(),
        "soap": data.soap.model_dump(),
        "raw_text": raw_text,
        "extractor": "gemini",
    }
    if data.allergy_status == "not_mentioned":
        del note["allergies"]
    return normalize_note(note)


def extract_gemini(raw_text: str) -> dict:
    try:
        raw_json = _call_llm(raw_text)
    except ExtractionError:
        raise
    except Exception as e:  # network, quota, safety block...
        raise ExtractionError(f"LLM call failed: {e}") from e
    return parse_llm_json(raw_json, raw_text)


def merge_notes(regex_note: dict, llm_note: dict) -> dict:
    """Union of safety findings. Regex findings are never dropped."""
    merged = {"raw_text": regex_note["raw_text"], "extractor": "hybrid"}

    if "allergies" in regex_note or "allergies" in llm_note:
        allergies = list(regex_note.get("allergies", []))
        for a in llm_note.get("allergies", []):
            if a not in allergies:
                allergies.append(a)
        merged["allergies"] = allergies

    meds = list(regex_note.get("medications", []))
    seen = {(m["name"], m["dose"]) for m in meds}
    for m in llm_note.get("medications", []):
        if (m["name"], m["dose"]) not in seen:
            meds.append(m)
            seen.add((m["name"], m["dose"]))
    merged["medications"] = meds

    # Vitals: a value either side found counts as present (prefer regex: it's literal).
    merged["vitals"] = {**llm_note.get("vitals", {}), **regex_note.get("vitals", {})}

    # SOAP: prefer the LLM's restructuring, but only if it actually split the note.
    # Small models sometimes dump the whole note into one section and leave the rest
    # empty; that's not a SOAP note, so use the deterministic split instead.
    rs, ls = regex_note.get("soap", {}), llm_note.get("soap", {})
    src = ls if _soap_is_real_split(ls, regex_note["raw_text"]) else rs
    merged["soap"] = {k: (src.get(k) or "") for k in SOAP_KEYS}
    return merged


SOAP_KEYS = ("subjective", "objective", "assessment", "plan")


def _soap_is_real_split(soap: dict, raw_text: str) -> bool:
    filled = [k for k in SOAP_KEYS if (soap.get(k) or "").strip()]
    if len(filled) < 2:
        return False
    note_len = max(len(raw_text.strip()), 1)
    # one section holding (nearly) the whole note = not a real split
    return all(len((soap.get(k) or "").strip()) < 0.9 * note_len for k in filled)


def extract_hybrid(raw_text: str) -> dict:
    regex_note = extract_regex(raw_text)
    try:
        llm_note = extract_gemini(raw_text)
    except ExtractionError as e:
        # Degrade to regex but SAY so — the API surfaces this as a warning.
        regex_note["extractor"] = "regex (LLM unavailable)"
        regex_note["extractor_warning"] = str(e)
        return regex_note
    return merge_notes(regex_note, llm_note)
