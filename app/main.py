"""
FastAPI entrypoint. Run with:
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/ for the demo UI, or POST a note to /audit:
    curl -X POST http://127.0.0.1:8000/audit \\
         -H "Content-Type: application/json" \\
         -d '{"text": "Allergies: penicillin. Plan: amoxicillin 500mg."}'

Extractor is chosen by the EXTRACTOR env var (regex | gemini | hybrid);
see app/extractor.extract_fields and CONTRACT.md.
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.checklist import build_checklist
from app.extractor import ExtractionError, extract_fields
from app.rules import run_all_rules

app = FastAPI(title="Clinical Note Auditor")
_STATIC = Path(__file__).parent / "static"


class NoteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50_000)


class FlagResponse(BaseModel):
    rule: str
    severity: str
    message: str
    evidence: str


class ActionResponse(BaseModel):
    priority: int
    action: str
    because: str
    rule: str


class AuditResponse(BaseModel):
    structured_note: dict
    soap: dict
    flags: list[FlagResponse]
    checklist: list[ActionResponse]
    has_high_severity: bool
    extractor: str
    extractor_warning: Optional[str] = None


@app.post("/audit", response_model=AuditResponse)
def audit_note(request: NoteRequest) -> AuditResponse:
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="The note is empty.")
    try:
        structured_note = extract_fields(request.text)
    except ExtractionError as e:
        # Fail loudly: an extraction failure must never look like a clean note.
        raise HTTPException(status_code=502, detail=f"Extraction failed, note NOT audited: {e}")
    result = run_all_rules(structured_note)
    return AuditResponse(
        structured_note=structured_note,
        soap=structured_note.get("soap", {}),
        flags=[FlagResponse(rule=f.rule, severity=f.severity, message=f.message, evidence=f.evidence)
               for f in result.flags],
        checklist=[ActionResponse(**a.__dict__) for a in build_checklist(result)],
        has_high_severity=result.has_high_severity,
        extractor=structured_note.get("extractor", "regex"),
        extractor_warning=structured_note.get("extractor_warning"),
    )


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
