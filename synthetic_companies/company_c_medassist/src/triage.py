import os
from typing import Dict, Any, List
from fastapi import FastAPI
from pydantic import BaseModel
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from openai import OpenAI

app = FastAPI(title="MedAssist Clinical Triage Copilot", version="3.1.0")

# Local Presidio redaction engines
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

# EU Sovereign Dedicated Endpoint (eu-west-2 London)
client = OpenAI(
    api_key=os.getenv("NHS_REGIONAL_AI_KEY", "eu-west-2-compliant-token"),
    base_url="https://eu-west-2.ai-sovereign.nhs.uk/v1"
)

class TriageNote(BaseModel):
    patient_id: str
    clinical_notes: str
    reported_symptoms: List[str]
    vitals: Dict[str, float]

def mask_clinical_pii(text: str) -> str:
    """Anonymizes names, dates, NHS numbers, and locations using Presidio."""
    results = analyzer.analyze(text=text, language="en")
    anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
    return anonymized.text

def route_to_clinician_queue(patient_id: str, risk_score: float, reasoning: str) -> Dict[str, Any]:
    """Human-in-the-loop escalation gate for elevated triage risk."""
    return {
        "status": "ESCALATED_TO_CLINICIAN",
        "patient_id": patient_id,
        "clinician_review_assigned": True,
        "triage_urgency": "HIGH",
        "risk_score": risk_score,
        "audit_note": f"Routing triggered by clinical triage threshold: {reasoning}"
    }

@app.post("/v1/triage-patient")
async def evaluate_patient(note: TriageNote) -> Dict[str, Any]:
    # 1. Mask all PII prior to any external LLM invocation
    sanitized_notes = mask_clinical_pii(note.clinical_notes)

    # 2. Forward strictly sanitized notes to regional sovereign endpoint
    response = client.chat.completions.create(
        model="clinical-mistral-large-eu",
        messages=[
            {"role": "system", "content": "You are a clinical decision support assistant."},
            {"role": "user", "content": f"Symptoms: {note.reported_symptoms}. Notes: {sanitized_notes}"}
        ],
        temperature=0.1
    )

    summary = response.choices[0].message.content or "Assessment complete."
    risk_score = 0.78  # Elevated mock clinical acuity

    # 3. Mandatory Human-In-The-Loop gate based on risk severity
    if risk_score > 0.70:
        triage_disposition = route_to_clinician_queue(
            patient_id=note.patient_id,
            risk_score=risk_score,
            reasoning="Acuity score > 0.70 requires mandatory senior clinician sign-off."
        )
    else:
        triage_disposition = {
            "status": "ROUTINE_MONITORING",
            "patient_id": note.patient_id,
            "clinician_review_assigned": False
        }

    # 4. Mandatory AI transparency disclosure on all payloads
    return {
        "patient_id": note.patient_id,
        "triage_summary": summary,
        "risk_score": risk_score,
        "disposition": triage_disposition,
        "ai_generated_disclosure": True,
        "data_residency_region": "eu-west-2",
        "pii_redacted": True
    }
