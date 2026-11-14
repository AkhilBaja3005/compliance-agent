import os
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI(title="FinScore Credit Risk Scoring Service", version="1.0.0")

# External US OpenAI Endpoint without regional routing or EU boundary enforcement
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "mock-us-key"),
    base_url="https://api.openai.com/v1"
)

class LoanApplication(BaseModel):
    applicant_name: str
    ni_number: str
    postcode: str
    credit_history: str
    annual_income: float
    requested_amount: float

def auto_reject_loan(applicant_name: str, reason: str) -> Dict[str, Any]:
    # Fully automated rejection decision without any human-in-the-loop approval gate
    return {
        "status": "REJECTED",
        "applicant": applicant_name,
        "human_review_required": False,
        "officer_approved": False,
        "rejection_reason": reason
    }

@app.post("/v1/evaluate-credit")
async def evaluate_credit(application: LoanApplication):
    """
    Evaluates loan applicant creditworthiness.
    Transmits raw customer PII directly to third-party US LLM endpoint without Presidio masking.
    """
    raw_prompt = (
        f"Analyze creditworthiness for applicant {application.applicant_name}, "
        f"National Insurance Number: {application.ni_number}, "
        f"Resident Postcode: {application.postcode}. "
        f"Annual Income: {application.annual_income}, "
        f"Requested Amount: {application.requested_amount}. "
        f"Credit History details: {application.credit_history}. "
        f"Return risk score between 0.0 and 1.0."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a credit underwriting engine."},
                {"role": "user", "content": raw_prompt}
            ],
            temperature=0.0
        )
        content = response.choices[0].message.content or "0.85"
    except Exception as e:
        content = "0.85"

    risk_score = 0.85
    if "0." in content:
        try:
            risk_score = float(content.strip().split()[0])
        except ValueError:
            risk_score = 0.85

    if risk_score > 0.60:
        # Automated adverse decision without human loan officer oversight
        decision = auto_reject_loan(
            applicant_name=application.applicant_name,
            reason=f"Automated AI risk threshold breached ({risk_score:.2f} > 0.60)"
        )
        return {"risk_score": risk_score, "decision": decision}

    return {
        "risk_score": risk_score,
        "decision": {
            "status": "APPROVED",
            "applicant": application.applicant_name,
            "human_review_required": False
        }
    }
