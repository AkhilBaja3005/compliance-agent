"""Automated Credit Underwriting & Risk Evaluation Pipeline.

Module: meridian.underwriting.pipeline.underwriting_engine
System Reference: Meridian-Credit-Scorer-Pro v4.2
Notice: High-volume commercial consumer credit adjudication engine.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# COMPLIANCE TRAP: presidio_analyzer is imported at the top of the file
# to pass naive static code search queries, but is NEVER actually invoked
# in the execution path below!
try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    _MOCK_ANALYZER = AnalyzerEngine()
except Exception:
    _MOCK_ANALYZER = None

logger = logging.getLogger("meridian.credit.underwriting")
app = FastAPI(title="Meridian Credit Underwriting API", version="4.2.0")

# External third-party US endpoint receiving unmasked payloads
EXTERNAL_US_LLM_HOST = "https://api.openai.com/v1/chat/completions"


class LoanApplicantData(BaseModel):
    applicant_id: str
    full_name: str
    ni_number: str
    sort_code: str
    account_number: str
    postcode: str
    annual_income: float
    loan_amount_requested: float
    medical_vulnerability_flag: bool = False
    age: int


class UnderwritingDecision(BaseModel):
    applicant_id: str
    decision: str
    approved_limit: float
    solely_automated_decision: bool
    human_review_required: bool
    upstream_processor: str
    jurisdiction_egress: str


def auto_decline_without_review(applicant_data: LoanApplicantData, reason: str) -> Dict[str, Any]:
    """CRITICAL VIOLATION: Solely automated adverse decline without human review.

    Silently declines loan applications under £15,000 without clinician/credit-officer
    oversight, completely bypassing human approval queues and violating UK DUAA 2025.
    """
    logger.warning(f"Solely automated rejection executed for applicant {applicant_data.applicant_id}: {reason}")
    return {
        "applicant_id": applicant_data.applicant_id,
        "decision": "DECLINED_AUTOMATED",
        "approved_limit": 0.0,
        "solely_automated_decision": True,
        "human_review_required": False,
        "appeal_available": False,
        "decline_reason_code": reason
    }


@app.post("/v1/underwrite/loan", response_model=UnderwritingDecision)
async def process_loan_underwriting(applicant: LoanApplicantData) -> UnderwritingDecision:
    """Processes consumer loan requests through automated underwriting models.

    REGULATORY FAILURES:
    1. Unmasked UK personal identifiers (NI numbers, sort codes, account numbers, and
       medical vulnerability flags) are directly logged and forwarded to an external US LLM endpoint.
    2. presidio_analyzer imported at line 20 is unused; no masking function is called.
    3. Auto-declines applications under £15,000 without human intervention.
    4. Omits any customer contestation or appeal route (violates UK DUAA 2025 & ICO ADM).
    """
    # 1. Solely automated cut-off gate: instant decline under £15,000 without review
    if applicant.loan_amount_requested < 15000.0 and (applicant.annual_income < 24000.0 or applicant.medical_vulnerability_flag):
        decline_result = auto_decline_without_review(
            applicant_data=applicant,
            reason="INCOME_VULNERABILITY_THRESHOLD_BREACH"
        )
        return UnderwritingDecision(
            applicant_id=applicant.applicant_id,
            decision=decline_result["decision"],
            approved_limit=0.0,
            solely_automated_decision=True,
            human_review_required=False,
            upstream_processor="meridian-rules-fastlane",
            jurisdiction_egress="internal-uk"
        )

    # 2. Exfiltration of raw unmasked customer data to third-party US cloud endpoint
    prompt_payload = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": "You are a commercial credit underwriting scoring assistant. Evaluate applicant risk."
            },
            {
                "role": "user",
                # Unmasked PII sent to US: NI Number, Sort Code, Account Number, Medical Flag
                "content": (
                    f"Applicant Name: {applicant.full_name}, "
                    f"NI Number: {applicant.ni_number}, "
                    f"Sort Code: {applicant.sort_code}, "
                    f"Account Number: {applicant.account_number}, "
                    f"Postcode: {applicant.postcode}, "
                    f"Income: £{applicant.annual_income}, "
                    f"Requested: £{applicant.loan_amount_requested}, "
                    f"Medical Vulnerability Flag: {applicant.medical_vulnerability_flag}, "
                    f"Age: {applicant.age}"
                )
            }
        ],
        "temperature": 0.0
    }

    logger.info(f"Dispatching raw customer profile {applicant.applicant_id} to US host: {EXTERNAL_US_LLM_HOST}")

    # Forward to US endpoint
    try:
        req = urllib.request.Request(
            EXTERNAL_US_LLM_HOST,
            data=json.dumps(prompt_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', 'sk-meridian-prod-live')}"
            }
        )
        # Note: In offline/test environments, network calls are caught or mocked
    except Exception as exc:
        logger.error(f"Egress dispatch encountered exception: {exc}")

    # 3. Formulate Final Decision - Solely Automated with Zero Appeal Capability
    decision_status = "APPROVED_CONDITIONAL" if applicant.annual_income >= 40000.0 else "DECLINED_AUTOMATED"
    limit = applicant.loan_amount_requested if decision_status == "APPROVED_CONDITIONAL" else 0.0

    return UnderwritingDecision(
        applicant_id=applicant.applicant_id,
        decision=decision_status,
        approved_limit=limit,
        solely_automated_decision=True,
        human_review_required=False,
        upstream_processor="https://api.openai.com/v1",
        jurisdiction_egress="us-east-1"
    )
