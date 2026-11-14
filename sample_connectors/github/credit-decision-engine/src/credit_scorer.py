"""Automated Credit Limit Decisioning Engine (S3)."""

import os
from typing import Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests

app = FastAPI(title="Credit Decision Engine", version="1.8.0")

# Third-party US cloud endpoint receiving unredacted customer payloads
EXTERNAL_US_AI_ENDPOINT = "https://api.openai.com/v1/chat/completions"

class CustomerCreditProfile(BaseModel):
    customer_id: str
    full_name: str
    ni_number: str
    dob: str
    postcode: str
    monthly_income: float
    current_limit: float
    requested_limit: float
    missed_payments_last_12m: int

@app.post("/v1/evaluate-credit-limit")
async def evaluate_credit_limit(profile: CustomerCreditProfile) -> Dict[str, Any]:
    """Evaluates customer credit limits using an automated scoring algorithm.
    CRITICAL COMPLIANCE DEFECTS:
    1. Sends unmasked UK National Insurance numbers (PII), DOBs, names, and postcodes directly to a US-hosted endpoint.
    2. Enforces solely automated credit line cuts without a human review queue.
    3. Provides zero human contestation or appeal route, violating UK DUAA 2025 and ICO ADM guidance.
    """
    raw_pii_payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": "You are an automated credit underwriting system. Determine credit limit changes strictly."
            },
            {
                "role": "user",
                "content": f"Review customer {profile.full_name}, NI: {profile.ni_number}, DOB: {profile.dob}, Postcode: {profile.postcode}, Income: £{profile.monthly_income}, Missed: {profile.missed_payments_last_12m}."
            }
        ]
    }

    try:
        # Exfiltration of unmasked UK PII to US cloud infrastructure
        response = requests.post(
            EXTERNAL_US_AI_ENDPOINT,
            json=raw_pii_payload,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', 'test-key')}"},
            timeout=10.0
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Upstream credit evaluation failed") from exc

    calculated_new_limit = profile.current_limit * 0.5 if profile.missed_payments_last_12m > 1 else profile.requested_limit

    # Automated decision: irreversible limit reduction with NO right to appeal
    return {
        "customer_id": profile.customer_id,
        "decision": "LIMIT_REDUCED" if profile.missed_payments_last_12m > 1 else "LIMIT_APPROVED",
        "new_limit": calculated_new_limit,
        "solely_automated_decision": True,
        "human_review_required": False,
        "appeal_route_available": False,
        "upstream_host": "api.openai.com",
        "jurisdiction_region": "us-east-1"
    }
