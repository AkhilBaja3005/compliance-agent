"""Enterprise Sample Connectors Generator.

Generates realistic enterprise-scale company datasets modeling GitHub repositories
and Confluence spaces:
1. Northwind Labs (`sample_connectors/github`, `sample_connectors/confluence/AIGOV`)
2. Aegis Health Systems Ltd (`sample_connectors/enterprise/aegis_health_uk/`)
   - 100% EU AI Act + UK GDPR/DUAA Compliant Enterprise Baseline
   - 3 GitHub repositories + 5 Confluence governance documents
3. Meridian OmniTech PLC (`sample_connectors/enterprise/meridian_omni_ai/`)
   - Multi-System Enterprise with Deep, Hidden Code-vs-Confluence Drift & Regulatory Violations
   - 3 GitHub repositories + 5 Confluence governance documents
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def generate_sample_connectors(base_dir: str | Path = "./sample_connectors") -> Path:
    """Generates the original Northwind Labs sample connector datasets."""
    root = Path(base_dir).resolve()
    gh_dir = root / "github"
    conf_dir = root / "confluence" / "AIGOV"

    # =========================================================================
    # 1. GitHub: imagery-studio (S4)
    # =========================================================================
    img_dir = gh_dir / "imagery-studio"
    (img_dir / "src").mkdir(parents=True, exist_ok=True)

    moderation_yaml = """# Northwind Labs Imagery Studio - Multi-Modal Moderation Pipeline
version: "2.1.0"
pipeline:
  name: "imagery-studio-guard"
  text_moderation:
    enabled: true
    provider: "internal-distilbert"
    toxic_threshold: 0.85
    sexual_content_threshold: 0.90
    violence_threshold: 0.88
  safety_checks:
    csam_hash_check: true
    known_terrorist_symbols: true
    celebrity_likeness_check: false
  tiers:
    free:
      rate_limit_per_minute: 5
      max_resolution: "1024x1024"
      face_upload_filter: true
      deepfake_detection_enforced: true
      strict_nudity_block: true
    creator:
      rate_limit_per_minute: 20
      max_resolution: "2048x2048"
      face_upload_filter: true
      deepfake_detection_enforced: true
      strict_nudity_block: true
    pro:
      rate_limit_per_minute: 60
      max_resolution: "4096x4096"
      allow_raw_prompts: true
      bypass_content_warning: true
      face_upload_filter: false # Line 48: High-tier bypass allows unverified faces & intimate likeness
      deepfake_detection_enforced: false
      strict_nudity_block: false
    enterprise:
      dedicated_gpu_cluster: true
      custom_safety_filter: true
"""
    (img_dir / "moderation.yaml").write_text(moderation_yaml, encoding="utf-8")

    src_generate_py = '''"""Image & Synthetic Media Generation Service for Northwind Labs Imagery Studio."""

import os
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch

app = FastAPI(title="Imagery Studio API", version="2.4.0")

class GenerationRequest(BaseModel):
    user_id: str
    tier: str = "creator"
    prompt: str
    style_preset: Optional[str] = "photorealistic"
    output_format: str = "png"

@app.post("/v2/generate")
async def generate_image(request: GenerationRequest) -> Dict[str, Any]:
    """Generates synthetic imagery.
    CRITICAL COMPLIANCE DEFECT:
    Returns raw binary or CDN URL with ZERO C2PA cryptographic provenance metadata,
    no machine-readable watermark tag, and no user-facing AI disclosure header,
    violating EU AI Act Article 50(2) transparency mandates ahead of Dec 2, 2026.
    """
    if "bypass" in request.prompt and request.tier != "pro":
        raise HTTPException(status_code=403, detail="Unsafe prompt rejected by moderation tier.")

    # Model inference returns raw generated image without C2PA injection
    generated_asset_id = f"gen_asset_{os.urandom(8).hex()}"
    cdn_url = f"https://cdn.northwindlabs.com/assets/{generated_asset_id}.png"

    return {
        "status": "success",
        "asset_id": generated_asset_id,
        "url": cdn_url,
        "width": 1024,
        "height": 1024,
        "tier": request.tier,
        # Defect: watermarked is explicitly False
        "watermarked": False,
        "metadata_stripped": True
    }
'''
    (img_dir / "src" / "generate.py").write_text(src_generate_py, encoding="utf-8")

    model_card_md = """# Model Card: Synthetic Image Generation Engine (S4)

**Model Name:** Northwind-Diffusion-HQ-v2  
**License:** GPL-3.0 and CC-BY-NC-4.0  
**Intended Use:** High-resolution artistic composition and marketing imagery generation.

## Licensing and Distribution Constraints
- **Core Weights:** Licensed under **CC-BY-NC-4.0** (Creative Commons Non-Commercial 4.0 International). Commercial production usage or SaaS monetization requires explicit enterprise commercial waiver from original upstream licensors.
- **Inference Runtime Engine:** Incorporates fine-tuning patches and pipeline wrappers derived from **GPL-3.0** licensed repositories without releasing proprietary service orchestration sources.
- **Commercial Status:** Active in production on paid Pro and Enterprise subscription tiers at Northwind Labs.
"""
    (img_dir / "Model_Card.md").write_text(model_card_md, encoding="utf-8")

    # =========================================================================
    # 2. GitHub: credit-decision-engine (S3)
    # =========================================================================
    credit_dir = gh_dir / "credit-decision-engine"
    (credit_dir / "src").mkdir(parents=True, exist_ok=True)

    credit_scorer_py = '''"""Automated Credit Limit Decisioning Engine (S3)."""

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
'''
    (credit_dir / "src" / "credit_scorer.py").write_text(credit_scorer_py, encoding="utf-8")

    # =========================================================================
    # 3. GitHub: support-assistant (S1)
    # =========================================================================
    support_dir = gh_dir / "support-assistant"
    (support_dir / "src").mkdir(parents=True, exist_ok=True)

    routes_py = '''"""Customer Support Chatbot Microservice (S1)."""

from typing import Dict, Any
from fastapi import FastAPI, Response
from pydantic import BaseModel

app = FastAPI(title="Customer Support Assistant", version="3.0.1")

class ChatMessage(BaseModel):
    session_id: str
    message: str

# -----------------------------------------------------------------------------
# Endpoint 1: General Web Inquiries (Compliant: Includes AI Disclosure Header)
# -----------------------------------------------------------------------------
@app.post("/api/v1/chat/general")
async def chat_general(msg: ChatMessage, response: Response) -> Dict[str, Any]:
    response.headers["X-AI-System-Interaction"] = "true"
    response.headers["X-AI-Disclosure"] = "You are interacting with an AI system operated by Northwind Labs."
    return {
        "reply": "Hello! I am Northwind's virtual support AI. How may I help you today?",
        "session_id": msg.session_id,
        "disclosed": True
    }

# -----------------------------------------------------------------------------
# Endpoint 2: Billing & Account Questions (Compliant: Includes AI Disclosure)
# -----------------------------------------------------------------------------
@app.post("/api/v1/chat/billing")
async def chat_billing(msg: ChatMessage, response: Response) -> Dict[str, Any]:
    response.headers["X-AI-System-Interaction"] = "true"
    return {
        "reply": "I can check your latest invoice details. Please hold on.",
        "session_id": msg.session_id,
        "disclosed": True
    }

# -----------------------------------------------------------------------------
# Endpoint 3: Premium Concierge Chat (DEFECT: Missing EU AI Act Art. 50(1) Disclosure)
# -----------------------------------------------------------------------------
@app.post("/api/v1/chat/vip-concierge")
async def chat_concierge(msg: ChatMessage) -> Dict[str, Any]:
    # CRITICAL DEFECT: Silently handles user conversation with an LLM without disclosing
    # that the user is interacting with an AI system (violates Article 50(1)).
    return {
        "reply": "Welcome to your personal concierge desk. Reviewing your portfolio now.",
        "session_id": msg.session_id,
        "tier": "vip"
    }

# -----------------------------------------------------------------------------
# Endpoint 4: Direct Mobile App Ingestion (DEFECT: Missing AI Disclosure)
# -----------------------------------------------------------------------------
@app.post("/api/v1/chat/mobile-stream")
async def chat_mobile(msg: ChatMessage) -> Dict[str, Any]:
    # CRITICAL DEFECT: Omits AI transparency headers / disclosures on mobile channel.
    return {
        "stream_token": "stream_token_99812",
        "session_id": msg.session_id,
        "status": "ready"
    }
'''
    (support_dir / "src" / "routes.py").write_text(routes_py, encoding="utf-8")

    # =========================================================================
    # 4. Confluence: AIGOV Space
    # =========================================================================
    conf_dir.mkdir(parents=True, exist_ok=True)

    aup_policy = """# Acceptable Use Policy & Content Moderation Standard (AUP_Policy_v2_1)

**Space:** AIGOV  
**Document ID:** POL-AUP-2024-V2.1  
**Status:** Approved  

## 1. Prohibited Harms and Generative AI Boundaries
Northwind Labs strictly enforces safety boundaries across all generative models and user tiers:
- **Intimate Imagery & Non-Consensual Likenesses:** Strictly prohibited across all commercial subscription tiers (Free, Creator, Pro, and Enterprise). Face upload filters and deepfake likeness blockers must remain permanently enabled without exception.
- **C2PA Watermarking & Machine-Readable Provenance:** All synthetic visual outputs must be injected with immutable C2PA cryptographic provenance metadata and machine-readable markers prior to CDN ingestion, satisfying EU AI Act Article 50(2).
- **Transparency & Disclosure:** All customer-facing interactive endpoints must disclose AI interaction pursuant to EU AI Act Article 50(1).

*(Contradiction with codebase: `moderation.yaml` disables face filtering on line 48 for the pro tier, and `generate.py` strips metadata).*
"""
    (conf_dir / "AUP_Policy_v2_1.md").write_text(aup_policy, encoding="utf-8")

    cv_screener_contract = """# CV Screener AI Procurement & Vendor Contract (S2)

**Space:** AIGOV  
**Vendor:** TalentAI Analytics Ltd.  
**System Reference:** Candidate Ranking Engine (S2)  
**EU AI Act Classification:** High-Risk AI System (Annex III §4(a) - Employment, worker management, and access to self-employment).  

## 1. System Scope & Architecture
The Candidate Ranking Engine automates resume screening, skills assessment scoring, and initial candidate shortlisting for all Northwind Labs recruitment pipelines.

## 2. Statutory Governance & Gaps
- **Fundamental Rights Impact Assessment (FRIA):** No FRIA has been completed or filed prior to production deployment (violates EU AI Act Article 27).
- **Adverse Demographic Impact (Four-Fifths Rule):**
  Internal testing logs reflect the following candidate selection-rate ratios across protected demographic groups:
  - Female-to-Male Selection Ratio: **0.86** (Within 0.80 tolerance threshold).
  - Ethnic Minority Selection Ratio: **0.84** (Within 0.80 tolerance threshold).
  - **Age 50+ Selection Ratio: 0.72** *(Severe disparity: Breaches the 0.80 four-fifths adverse impact indicator, indicating systematic bias against senior candidates).*
- **Vendor Indemnity:** Vendor provides no algorithmic transparency or bias remediation support.
"""
    (conf_dir / "CV_Screener_Vendor_Contract.md").write_text(cv_screener_contract, encoding="utf-8")

    dpa_customer_data = """# Data Processing Agreement & Customer Data Policy (DPA_Customer_Data)

**Space:** AIGOV  
**Document ID:** DPA-CORP-2024-V4  
**Jurisdiction:** UK GDPR, EU GDPR, and UK Data (Use and Access) Bill 2025  

## 1. Technical & Organizational Security Measures
Northwind Labs maintains strict data sovereignty and minimization protocols:
- **Presidio Redaction Mandatory:** All personally identifiable information (PII)—including customer names, National Insurance (NI) numbers, passport details, phone numbers, and postcodes—must be redacted via Microsoft Presidio prior to any third-party model ingestion or inference.
- **EU & UK Data Residency:** Customer data is processed and stored strictly within designated European Union enclaves (`eu-central-1` Frankfurt or `eu-west-2` London). Egress of unredacted personal data to third-party endpoints located outside the EEA/UK (specifically US cloud infrastructure) is strictly prohibited.
- **Automated Decision-Making Rights:** In compliance with UK DUAA 2025 and UK GDPR Article 22, all automated credit limit reductions, adverse underwriting decisions, or automated employment rejections must provide an accessible human contestation and review mechanism.

*(Contradiction with codebase: `credit_scorer.py` transmits raw unmasked PII directly to `api.openai.com/v1` and executes irreversible limit cuts with `appeal_route_available: False`).*
"""
    (conf_dir / "DPA_Customer_Data.md").write_text(dpa_customer_data, encoding="utf-8")

    return root


# =============================================================================
# COMPANY 1: Aegis Health Systems Ltd (aegis_health_uk)
# 100% EU AI Act + UK GDPR/DUAA Compliant Enterprise Baseline
# =============================================================================

def generate_aegis_health(base_dir: str | Path = "./sample_connectors") -> Path:
    aegis_root = Path(base_dir).resolve() / "enterprise" / "aegis_health_uk"
    gh_root = aegis_root / "github"
    conf_root = aegis_root / "confluence" / "CLINICAL_GOV"

    # -------------------------------------------------------------------------
    # Repo 1: clinical-triage-api
    # -------------------------------------------------------------------------
    triage_dir = gh_root / "clinical-triage-api"
    (triage_dir / "src" / "middleware").mkdir(parents=True, exist_ok=True)
    (triage_dir / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (triage_dir / "config").mkdir(parents=True, exist_ok=True)

    pii_redactor_py = '''"""Clinical Data Privacy & Presidio Anonymization Middleware.

Module: aegis.clinical_triage.middleware.pii_redactor
Compliance: UK GDPR (Data Protection Act 2018), NHS Digital Caldicott Principles,
            EU AI Act Art. 10 (Data Governance & Privacy Protection).

Implements rigorous PII redaction pipeline removing NHS Numbers, UK National Insurance Numbers,
patient full names, UK postcodes, and dates of birth before any LLM inference invocation.
Strictly routes inference through sovereign UK regional endpoints (eu-west-2 London VPC).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aegis.compliance.pii_redactor")

# Dynamic fallback import for Microsoft Presidio Analyzer & Anonymizer
try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig
    PRESIDIO_AVAILABLE = True
except ImportError:
    PRESIDIO_AVAILABLE = False
    AnalyzerEngine = None  # type: ignore
    AnonymizerEngine = None  # type: ignore

# UK NHS Number Regex: 10 digits in 3-3-4 pattern or 10 contiguous digits
NHS_NUMBER_PATTERN = re.compile(r"\\b(\\d{3}\\s?\\d{3}\\s?\\d{4})\\b")
# UK National Insurance (NI) Number Pattern
NI_NUMBER_PATTERN = re.compile(r"\\b[A-CEGHJ-PR-TW-Z]{2}\\s?\\d{2}\\s?\\d{2}\\s?\\d{2}\\s?[A-D]{1}\\b", re.I)
# UK Postal Code Pattern
UK_POSTCODE_PATTERN = re.compile(r"\\b([A-Z]{1,2}\\d[A-Z\\d]?\\s*\\d[A-Z]{2})\\b", re.I)
# Date of Birth pattern (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD)
DOB_PATTERN = re.compile(r"\\b(0?[1-9]|[12][0-9]|3[01])[\\/\\-](0?[1-9]|1[012])[\\/\\-]\\d{4}\\b|\\b\\d{4}[\\/\\-](0?[1-9]|1[012])[\\/\\-](0?[1-9]|[12][0-9]|3[01])\\b")


class ClinicalPIIRedactor:
    """Production-grade Presidio analyzer and anonymizer for clinical records."""

    def __init__(self, region: str = "eu-west-2") -> None:
        self.region = region
        self.endpoint_vpc = os.getenv("AEGIS_NHS_VPC_ENDPOINT", "https://eu-west-2.clinical-ai.nhs.uk/v1")
        self.enforce_zero_retention = True
        self._init_presidio()

    def _init_presidio(self) -> None:
        """Initializes Presidio with custom UK clinical recognizers."""
        if PRESIDIO_AVAILABLE and AnalyzerEngine is not None and AnonymizerEngine is not None:
            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
            self._register_uk_recognizers()
            logger.info("Presidio clinical analyzer engine successfully initialized with UK recognizers.")
        else:
            self.analyzer = None
            self.anonymizer = None
            logger.warning("Microsoft Presidio not installed. Utilizing high-assurance regex redaction fallback.")

    def _register_uk_recognizers(self) -> None:
        """Registers specialized NHS Number and UK NI recognizers."""
        try:
            nhs_rec = PatternRecognizer(
                supported_entity="UK_NHS_NUMBER",
                patterns=[Pattern("NHS_Number", r"\\b(\\d{3}\\s?\\d{3}\\s?\\d{4})\\b", 0.95)]
            )
            ni_rec = PatternRecognizer(
                supported_entity="UK_NINO",
                patterns=[Pattern("UK_NINO", r"\\b[A-CEGHJ-PR-TW-Z]{2}\\s?\\d{2}\\s?\\d{2}\\s?\\d{2}\\s?[A-D]{1}\\b", 0.95)]
            )
            self.analyzer.registry.add_recognizer(nhs_rec)
            self.analyzer.registry.add_recognizer(ni_rec)
        except Exception as exc:
            logger.error(f"Failed to register custom Presidio recognizers: {exc}")

    def redact_clinical_text(self, text: str) -> Tuple[str, Dict[str, int]]:
        """Redacts all clinical PII including NHS numbers, NI numbers, patient names, DOBs, and postcodes.

        Returns:
            Tuple of (anonymized_text, redaction_metrics_dict)
        """
        if not text:
            return "", {}

        metrics: Dict[str, int] = {
            "UK_NHS_NUMBER": 0,
            "UK_NINO": 0,
            "UK_POSTCODE": 0,
            "DATE_OF_BIRTH": 0,
            "NAME_LOCATION": 0
        }

        # 1. Apply Presidio Anonymizer if available
        if self.analyzer is not None and self.anonymizer is not None:
            results = self.analyzer.analyze(
                text=text,
                language="en",
                entities=["PERSON", "LOCATION", "DATE_TIME", "UK_NHS_NUMBER", "UK_NINO", "PHONE_NUMBER", "EMAIL_ADDRESS"]
            )
            anonymized = self.anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators={
                    "PERSON": OperatorConfig("replace", {"new_value": "[CLINICAL_PATIENT_NAME]"}),
                    "UK_NHS_NUMBER": OperatorConfig("replace", {"new_value": "[NHS_NUMBER_REDACTED]"}),
                    "UK_NINO": OperatorConfig("replace", {"new_value": "[UK_NINO_REDACTED]"}),
                    "LOCATION": OperatorConfig("replace", {"new_value": "[LOCATION_REDACTED]"}),
                    "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED_PII]"})
                }
            )
            sanitized_text = anonymized.text
            metrics["NAME_LOCATION"] += len(results)
        else:
            sanitized_text = text

        # 2. Deterministic high-assurance UK clinical regex sweeps
        # UK NHS Number
        sanitized_text, count_nhs = NHS_NUMBER_PATTERN.subn("[NHS_NUMBER_REDACTED]", sanitized_text)
        metrics["UK_NHS_NUMBER"] += count_nhs

        # UK NI Number
        sanitized_text, count_ni = NI_NUMBER_PATTERN.subn("[UK_NINO_REDACTED]", sanitized_text)
        metrics["UK_NINO"] += count_ni

        # UK Postcode
        sanitized_text, count_post = UK_POSTCODE_PATTERN.subn("[UK_POSTCODE_REDACTED]", sanitized_text)
        metrics["UK_POSTCODE"] += count_post

        # Date of Birth
        sanitized_text, count_dob = DOB_PATTERN.subn("[DOB_REDACTED]", sanitized_text)
        metrics["DATE_OF_BIRTH"] += count_dob

        logger.info(f"Clinical PII redaction complete. Total redaction markers applied: {sum(metrics.values())}")
        return sanitized_text, metrics

    def get_sovereign_headers(self) -> Dict[str, str]:
        """Provides mandatory regional routing and Zero-Data-Retention (ZDR) transport headers."""
        return {
            "X-Data-Residency-Region": self.region,
            "X-VPC-Endpoint": self.endpoint_vpc,
            "X-Zero-Data-Retention": "enforced",
            "X-Model-Logging-Permitted": "false",
            "X-NHS-Caldicott-Standard": "Principle-7-Compliant"
        }


# Global singleton instance for clinical middleware
clinical_pii_redactor = ClinicalPIIRedactor(region="eu-west-2")
'''
    (triage_dir / "src" / "middleware" / "pii_redactor.py").write_text(pii_redactor_py, encoding="utf-8")

    triage_router_py = '''"""FastAPI Clinical Decision-Support Triage Endpoints.

Module: aegis.clinical_triage.routes.triage_router
Regulatory Compliance:
- EU AI Act Article 14 (Human Oversight / Clinician-in-the-Loop)
- EU AI Act Article 50(1) (AI System Interaction Transparency Disclosure)
- UK Data (Use and Access) Bill 2025 / ICO Automated Decision-Making (ADM) Safeguards
- UK Equality Act 2010 Algorithmic Non-Discrimination Protections
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, Field

from src.middleware.pii_redactor import clinical_pii_redactor

logger = logging.getLogger("aegis.clinical_triage.router")
router = APIRouter(prefix="/v2/triage", tags=["Clinical Decision Support"])

# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------
class TriageAssessmentRequest(BaseModel):
    patient_reference_hash: str = Field(..., description="Pseudonymized hash of patient ID")
    chief_complaint: str = Field(..., description="Patient reported symptoms and clinical notes")
    vitals: Dict[str, float] = Field(default_factory=dict, description="Temperature, systolic, pulse, SpO2")
    triage_department: str = Field("EMERGENCY", description="Target hospital triage department")
    clinician_on_duty_id: str = Field(..., description="Registered GMC clinician ID supervising queue")

class TriageAssessmentResponse(BaseModel):
    assessment_id: str
    patient_reference_hash: str
    acuity_score: float
    recommended_pathway: str
    requires_human_approval: bool
    clinician_approval_status: str
    clinician_in_the_loop_queue_id: Optional[str]
    ai_disclosure_notice: str
    pii_redacted_indicators: Dict[str, int]
    timestamp: str

class HumanContestRequest(BaseModel):
    assessment_id: str
    contesting_clinician_gmc_number: str
    override_pathway: str
    clinical_justification: str
    patient_advocate_present: bool = False

class AuditLogEntry(BaseModel):
    log_id: str
    assessment_id: str
    event_type: str
    decision_payload: Dict[str, Any]
    logged_at: str
    immutable_hash: str

# -----------------------------------------------------------------------------
# Simulated Clinician-in-the-Loop Approval Queue & Immutable Audit Store
# -----------------------------------------------------------------------------
CLINICIAN_REVIEW_QUEUE: Dict[str, Dict[str, Any]] = {}
IMMUTABLE_AUDIT_LOG: List[Dict[str, Any]] = {}


def enqueue_clinician_review(assessment_id: str, payload: Dict[str, Any]) -> str:
    """Enqueues high-acuity or uncertain cases into mandatory GMC clinician review queue."""
    queue_id = f"CLIN-REV-{uuid.uuid4().hex[:8].upper()}"
    CLINICIAN_REVIEW_QUEUE[queue_id] = {
        "queue_id": queue_id,
        "assessment_id": assessment_id,
        "payload": payload,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        "status": "AWAITING_GMC_CLINICIAN_SIGNOFF"
    }
    logger.info(f"Enqueued high-acuity assessment {assessment_id} into clinician queue {queue_id}")
    return queue_id


def record_immutable_audit(assessment_id: str, event_type: str, details: Dict[str, Any]) -> str:
    """Appends immutable audit record satisfying EU AI Act Art. 12 Record-Keeping mandates."""
    log_id = f"AUDIT-{uuid.uuid4().hex}"
    entry = {
        "log_id": log_id,
        "assessment_id": assessment_id,
        "event_type": event_type,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "IMMUTABLE_RECORDED"
    }
    IMMUTABLE_AUDIT_LOG.append(entry)
    return log_id


# -----------------------------------------------------------------------------
# Clinical Triage Routes
# -----------------------------------------------------------------------------
@router.post(
    "/evaluate",
    response_model=TriageAssessmentResponse,
    summary="Clinical Decision-Support Triage Evaluation"
)
async def evaluate_clinical_triage(
    request: TriageAssessmentRequest,
    response: Response
) -> TriageAssessmentResponse:
    """Evaluates triage notes with mandatory PII stripping, human-in-the-loop gates,

    and strict Art. 50(1) AI interaction disclosures.
    """
    # 1. EU AI Act Art. 50(1) Mandatory Transparency Header
    response.headers["X-AI-System-Interaction"] = "true"
    response.headers["X-AI-System-Identity"] = "Aegis Clinical Decision Support Copilot v2.4"
    response.headers["X-AI-Disclosure"] = (
        "Notice: This clinical pathway assessment was generated by an AI decision-support system. "
        "It must be reviewed and signed off by a GMC-registered medical practitioner."
    )
    response.headers["X-Data-Residency"] = "eu-west-2-london-vpc"

    # 2. Strict Presidio PII Redaction
    sanitized_notes, pii_metrics = clinical_pii_redactor.redact_clinical_text(request.chief_complaint)

    # 3. Simulate Clinical Acuity Calculation
    assessment_id = f"AEGIS-TR-{uuid.uuid4().hex[:10]}"
    spo2 = request.vitals.get("spo2", 98.0)
    pulse = request.vitals.get("pulse", 75.0)

    # Elevated acuity if SpO2 < 94% or pulse > 115 bpm
    is_high_risk = spo2 < 94.0 or pulse > 115.0 or "chest pain" in sanitized_notes.lower()
    acuity_score = 0.82 if is_high_risk else 0.42

    # 4. Mandatory Clinician-in-the-Loop Human Oversight Gate (EU AI Act Art. 14 / UK DUAA 2025)
    # Acuity score >= 0.65 triggers mandatory escalation
    requires_human_approval = acuity_score >= 0.65
    clinician_queue_id: Optional[str] = None
    approval_status = "PENDING_CLINICIAN_SIGNOFF" if requires_human_approval else "ROUTINE_TRIAGE_ACCEPTED"

    if requires_human_approval:
        clinician_queue_id = enqueue_clinician_review(
            assessment_id=assessment_id,
            payload={
                "patient_hash": request.patient_reference_hash,
                "sanitized_notes": sanitized_notes,
                "acuity_score": acuity_score,
                "clinician_on_duty": request.clinician_on_duty_id
            }
        )

    # 5. Record Immutable Audit Trail
    record_immutable_audit(
        assessment_id=assessment_id,
        event_type="INITIAL_ASSESSMENT_GENERATED",
        details={
            "acuity_score": acuity_score,
            "requires_human_approval": requires_human_approval,
            "clinician_queue_id": clinician_queue_id,
            "pii_metrics": pii_metrics
        }
    )

    return TriageAssessmentResponse(
        assessment_id=assessment_id,
        patient_reference_hash=request.patient_reference_hash,
        acuity_score=acuity_score,
        recommended_pathway="URGENT_EMERGENCY_RESUSCITATION" if is_high_risk else "PRIMARY_CARE_OBSERVATION",
        requires_human_approval=requires_human_approval,
        clinician_approval_status=approval_status,
        clinician_in_the_loop_queue_id=clinician_queue_id,
        ai_disclosure_notice="AI interaction disclosed pursuant to EU AI Act Art. 50(1) & UK DUAA 2025.",
        pii_redacted_indicators=pii_metrics,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@router.post(
    "/contest-override",
    summary="Clinician / Patient Appeal and Human Override Endpoint"
)
async def contest_and_override_decision(
    contest: HumanContestRequest,
    response: Response
) -> Dict[str, Any]:
    """Human contestation and override route satisfying UK DUAA 2025 & ICO ADM requirements.

    Enables clinicians or patients to challenge, override, or overturn automated assessments.
    """
    response.headers["X-Decision-Contest-Handled"] = "true"
    response.headers["X-Human-Review-Enforced"] = "GMC-Overridden"

    record_immutable_audit(
        assessment_id=contest.assessment_id,
        event_type="HUMAN_CLINICIAN_OVERRIDE_RECORDED",
        details={
            "gmc_number": contest.contesting_clinician_gmc_number,
            "override_pathway": contest.override_pathway,
            "justification": contest.clinical_justification,
            "advocate_present": contest.patient_advocate_present
        }
    )

    logger.info(f"Clinical assessment {contest.assessment_id} overridden by GMC #{contest.contesting_clinician_gmc_number}")

    return {
        "status": "OVERRIDE_EXECUTED",
        "assessment_id": contest.assessment_id,
        "overriding_clinician": contest.contesting_clinician_gmc_number,
        "new_pathway": contest.override_pathway,
        "appeal_outcome": "REVERSED_BY_HUMAN_CLINICIAN",
        "human_oversight_verified": True,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
'''
    (triage_dir / "src" / "routes" / "triage_router.py").write_text(triage_router_py, encoding="utf-8")

    governance_yaml = """# Aegis Health Systems Ltd - Automated Governance & Red-Team Configuration
version: "3.2.0"
governance_tier: "ENTERPRISE_CLINICAL_GRADE"
system_classification: "EU_AI_ACT_ANNEX_III_HIGH_RISK"

compliance_gates:
  red_team_threshold: 0.995 # Automated red-team threshold gate (>= 99.5%)
  adversarial_testing_pass_rate: 0.998
  pii_leakage_tolerance: 0.000
  human_in_the_loop_enforced: true
  c2pa_provenance_enabled: true
  zero_data_retention_enforced: true

regional_routing:
  primary_region: "eu-west-2" # London AWS Healthcare Enclave
  backup_region: "eu-west-1" # Ireland Dedicated Enclave
  us_data_egress_permitted: false

licensing_policy:
  permitted_licenses:
    - "MIT"
    - "Apache-2.0"
    - "BSD-3-Clause"
    - "ISC"
  prohibited_licenses:
    - "GPL-3.0"
    - "AGPL-3.0"
    - "CC-BY-NC-4.0"
  copyleft_tolerance: "ZERO"

audit_configuration:
  immutable_audit_retention_years: 10
  national_competent_authority_inspection_ready: true
  ico_audit_standard: "ICO_ADM_2025_COMPLIANT"
"""
    (triage_dir / "config" / "governance.yaml").write_text(governance_yaml, encoding="utf-8")

    requirements_triage = """fastapi>=0.110.0
pydantic>=2.6.0
presidio-analyzer>=2.2.355
presidio-anonymizer>=2.2.355
c2pa-python>=0.6.0
cryptography>=42.0.0
requests>=2.31.0
uvicorn>=0.28.0
"""
    (triage_dir / "requirements.txt").write_text(requirements_triage, encoding="utf-8")

    dockerfile_triage = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV AEGIS_NHS_VPC_ENDPOINT="https://eu-west-2.clinical-ai.nhs.uk/v1"
ENV DATA_RESIDENCY_REGION="eu-west-2"
EXPOSE 8000
CMD ["uvicorn", "src.routes.triage_router:router", "--host", "0.0.0.0", "--port", "8000"]
"""
    (triage_dir / "Dockerfile").write_text(dockerfile_triage, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Repo 2: patient-discharge-summarizer
    # -------------------------------------------------------------------------
    summarizer_dir = gh_root / "patient-discharge-summarizer"
    (summarizer_dir / "src").mkdir(parents=True, exist_ok=True)
    (summarizer_dir / "config").mkdir(parents=True, exist_ok=True)

    summarizer_py = '''"""Grounded Clinical Discharge Summarizer with Machine-Readable C2PA Provenance.

Module: aegis.discharge.summarizer
Compliance Standards:
- EU AI Act Article 50(2) (Machine-Readable Marking & Cryptographic Watermarking)
- EU AI Act Article 10 (Grounded Citation & Anti-Hallucination Verification)
- UK NHS Caldicott Guardianship Standards
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aegis.discharge.summarizer")

PROMPT_INJECTION_INDICATORS = [
    r"ignore\\s+(all\\s+)?(previous|prior)\\s+instructions",
    r"system\\s+prompt\\s+override",
    r"you\\s+are\\s+now\\s+in\\s+developer\\s+mode",
    r"reveal\\s+confidential\\s+patient\\s+data",
    r"bypass\\s+safety\\s+filters",
    r"jailbreak"
]


class DischargeSummarizerService:
    """Enterprise RAG clinical discharge summarizer equipped with C2PA watermarking."""

    def __init__(self, region: str = "eu-west-2") -> None:
        self.region = region
        self.cert_thumbprint = os.getenv("AEGIS_C2PA_SIGNING_CERT", "SHA256:B6:3C:99:A1:44:E2:NHS:ENCLAVE")
        self.injection_patterns = [re.compile(p, re.I) for p in PROMPT_INJECTION_INDICATORS]

    def validate_clinical_safety(self, prompt: str) -> bool:
        """Enforces prompt-injection guardrails against adversarial user injections."""
        for pattern in self.injection_patterns:
            if pattern.search(prompt):
                logger.error(f"Hostile prompt injection pattern detected: {pattern.pattern}")
                raise ValueError("Hostile prompt injection detected: safety guardrail triggered.")
        return True

    def verify_grounded_citations(
        self,
        summary: str,
        clinical_source_records: List[Dict[str, str]]
    ) -> Tuple[bool, float, List[str]]:
        """Verifies clinical summary sentences against ground-truth source records.

        Ensures zero ungrounded clinical hallucinations.
        """
        valid_citations: List[str] = []
        source_corpora = " ".join([rec.get("text", "") for rec in clinical_source_records]).lower()

        # Extract sentences from generated summary
        sentences = [s.strip() for s in summary.split(".") if len(s.strip()) > 10]
        grounded_count = 0

        for sentence in sentences:
            keywords = [w for w in re.findall(r"\\w+", sentence.lower()) if len(w) > 4]
            if not keywords:
                continue
            # Check overlap against source records
            overlap = sum(1 for kw in keywords if kw in source_corpora)
            grounding_ratio = overlap / max(1, len(keywords))
            if grounding_ratio >= 0.60:
                grounded_count += 1
                valid_citations.append(f"CITED: {sentence[:45]}...")

        grounding_score = grounded_count / max(1, len(sentences))
        is_grounded = grounding_score >= 0.85
        return is_grounded, grounding_score, valid_citations

    def apply_c2pa_watermark_metadata(
        self,
        discharge_document_text: str,
        patient_reference_hash: str
    ) -> Dict[str, Any]:
        """Injects machine-readable C2PA cryptographic provenance metadata pursuant to Art. 50(2)."""
        content_hash = hashlib.sha256(discharge_document_text.encode("utf-8")).hexdigest()
        c2pa_manifest = {
            "claim_generator": "Aegis Health Systems C2PA Generator v1.4",
            "format": "application/x-c2pa-manifest",
            "title": "Clinical Patient Discharge Summary",
            "assertions": [
                {
                    "label": "c2pa.ai_generated",
                    "data": {
                        "is_synthetic": True,
                        "regulation": "EU AI Act Article 50(2)",
                        "model_family": "Aegis-Clinical-Grounded-Llama3-UK",
                        "generation_timestamp": datetime.now(timezone.utc).isoformat()
                    }
                },
                {
                    "label": "c2pa.patient_privacy",
                    "data": {
                        "patient_reference_hash": patient_reference_hash,
                        "data_protection_standard": "UK GDPR & DPA 2018",
                        "redaction_verified": True
                    }
                },
                {
                    "label": "c2pa.cryptographic_hash",
                    "data": {
                        "payload_sha256": content_hash,
                        "signing_authority": "NHS Digital Trust Root Authority UK",
                        "cert_thumbprint": self.cert_thumbprint
                    }
                }
            ]
        }
        return c2pa_manifest

    def generate_discharge_summary(
        self,
        patient_reference_hash: str,
        clinical_history: str,
        source_records: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Executes grounded clinical summarization pipeline with full provenance and guardrails."""
        # 1. Prompt Injection Guardrail
        self.validate_clinical_safety(clinical_history)

        # 2. Simulated Clinical RAG Inference
        summary_text = (
            f"Patient ({patient_reference_hash[:8]}) presented with acute respiratory symptoms. "
            "Treatment included bronchodilator therapy and oral prednisolone. "
            "Vital observations stabilized over a 48-hour monitoring window. "
            "Patient is discharged with outpatient respiratory clinic follow-up scheduled in 14 days. "
            "Prescribed medications: Inhaled salbutamol 100mcg PRN and tapering prednisolone."
        )

        # 3. Citation Verification
        is_grounded, score, citations = self.verify_grounded_citations(summary_text, source_records)

        # 4. Machine-Readable C2PA Watermarking (Art. 50(2))
        c2pa_manifest = self.apply_c2pa_watermark_metadata(summary_text, patient_reference_hash)

        return {
            "status": "SUMMARY_GENERATED_COMPLIANT",
            "patient_reference_hash": patient_reference_hash,
            "discharge_summary_text": summary_text,
            "grounding_score": score,
            "citations_verified": is_grounded,
            "c2pa_provenance_manifest": c2pa_manifest,
            "c2pa_watermark_injected": True,
            "art_50_2_compliant": True,
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
'''
    (summarizer_dir / "src" / "summarizer.py").write_text(summarizer_py, encoding="utf-8")

    requirements_summarizer = """c2pa-python>=0.6.0
cryptography>=42.0.0
pydantic>=2.6.0
requests>=2.31.0
fastapi>=0.110.0
"""
    (summarizer_dir / "requirements.txt").write_text(requirements_summarizer, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Confluence: CLINICAL_GOV Space
    # -------------------------------------------------------------------------
    conf_root.mkdir(parents=True, exist_ok=True)

    dpia_clinical_triage = """# Data Protection Impact Assessment (DPIA) - Clinical Decision Support Triage API

**Space:** CLINICAL_GOV  
**Document ID:** DPIA-AEGIS-2025-V4.2  
**Jurisdiction:** UK GDPR, Data Protection Act 2018, EU AI Act Article 27 (FRIA)  
**Lead Reviewer:** Dr. Eleanor Vance, Caldicott Guardian & Chief Clinical Safety Officer  
**Status:** Approved & Formally Registered with NHS England Information Governance  

## 1. System Scope & Clinical Context
The Aegis Clinical Triage Copilot provides emergency and acute care triage decision support to GMC-registered medical practitioners across 14 NHS Foundation Trust partner hospitals. The system analyzes anonymized patient vital signs and acute complaints to calculate clinical acuity scores and recommend specialized treatment pathways.

## 2. Fundamental Rights Impact Assessment (FRIA) - EU AI Act Article 27
- **Right to Human Dignity and Bodily Integrity:** System operates strictly as a clinical decision support advisor (Class IIa Medical Device equivalent under MDR / High-Risk Annex III §5(a) AI System). Final clinical authority resides exclusively with GMC clinicians.
- **Protection of Personal Data:** All National Insurance numbers, NHS numbers, names, and postal codes are anonymized at application ingress using Microsoft Presidio and regex boundary analyzers.
- **Right to Non-Discrimination:** Quarterly audits evaluate predictive acuity distributions across age, ethnicity, and gender cohorts to prevent discriminatory undertriage.
- **Environmental & Operational Resilience:** Microservices are hosted in energy-efficient UK sovereign data centers (`eu-west-2` London) equipped with dual-redundant failover mechanisms.

## 3. Mandatory Human-in-the-Loop Safeguards (EU AI Act Article 14)
- **Automatic Escalation:** Any patient assessment yielding an acuity score of 0.65 or higher, or demonstrating abnormal cardiorespiratory vitals, is automatically routed to the mandatory Clinician Review Queue (`enqueue_clinician_review()`).
- **Clinician Override Authority:** Pursuant to UK DUAA 2025 and ICO Automated Decision-Making guidance, any clinician or patient advocate can trigger the `/v2/triage/contest-override` endpoint to instantly reverse, modify, or reject AI recommendations without punitive delay.
"""
    (conf_root / "DPIA_Clinical_Triage_v4.md").write_text(dpia_clinical_triage, encoding="utf-8")

    dpa_nhs = """# NHS National Data Processing Agreement (DPA) - Schedule 7 Technical & Organizational Standards

**Space:** CLINICAL_GOV  
**Document ID:** DPA-NHS-AEGIS-2025-REVISION-8  
**Data Controller:** NHS England / Partner Trust Boards  
**Data Processor:** Aegis Health Systems Ltd  
**Jurisdiction:** UK GDPR, UK Data (Use and Access) Bill 2025, EU GDPR  

## 1. Data Minimization & Presidio Anonymization Mandate
- **Pre-Ingress Anonymization:** Aegis shall not transmit unmasked patient identifiers to any model inference pipeline. All incoming clinical unstructured text must pass through the `ClinicalPIIRedactor` pipeline, ensuring complete redaction of 10-digit NHS numbers, NI numbers, and residential postcodes.
- **Zero Data Retention (ZDR):** All HTTP transport transactions to regional inferencing VPC endpoints must include `X-Zero-Data-Retention: enforced` and `X-Model-Logging-Permitted: false` headers, guaranteeing that patient text is never cached or used for training.

## 2. Sovereign Territorial Residency & Egress Restrictions
- **Geographic Boundary:** All processing, storage, and retrieval activities are strictly confined to the `eu-west-2` (London) sovereign cloud boundary.
- **Prohibited Egress:** Any data transmission, replication, or API routing to endpoints hosted within the United States or outside the UK/EEA adequacy perimeter is strictly prohibited and constitutes a material breach of contract.
"""
    (conf_root / "DPA_NHS_Data_Processing.md").write_text(dpa_nhs, encoding="utf-8")

    annex_iv_technical = """# Annex IV Technical Documentation - EU AI Act Compliance Dossier

**Space:** CLINICAL_GOV  
**System Reference:** Aegis-CDS-Core-v2  
**Classification:** High-Risk AI System under EU AI Act Annex III §5(a) & Article 6(2)  
**Author:** Regulatory Engineering & Clinical Assurance Office  

## 1. System Specifications & Intended Purpose
Aegis-CDS-Core-v2 is an automated clinical risk-stratification system designed to assist emergency triage teams in prioritizing patient workflows according to clinical urgency.

## 2. Technical Safeguards & Architecture
- **Article 9 (Risk Management System):** Continuous risk management lifecycle identifying clinical misclassification hazards, hardware timeouts, and data contamination risks.
- **Article 10 (Data & Data Governance):** Trained exclusively on certified, de-identified clinical datasets. Automated red-team threshold gates require `>= 99.5%` adversarial robustness.
- **Article 11 & Annex IV (Technical Documentation):** Complete documentation of microservice architecture, training corpora provenance, and verification test suites.
- **Article 12 (Record-Keeping):** Immutable cryptographic audit logging (`record_immutable_audit()`) storing timestamped acuity vectors and GMC clinician sign-offs for 10 years.
- **Article 14 (Human Oversight):** Dual-tier human-in-the-loop oversight enforcing clinician sign-offs for all elevated scores (`acuity_score >= 0.65`).
- **Article 15 (Accuracy, Robustness & Cybersecurity):** Fault-tolerant microservice deployment wrapped in secure VPC enclaves with C2PA digital signatures.
"""
    (conf_root / "Annex_IV_Technical_File.md").write_text(annex_iv_technical, encoding="utf-8")

    ai_system_register = """# Enterprise AI System Register (2025-2026 Audit Cycle)

**Space:** CLINICAL_GOV  
**Scope:** Aegis Health Systems Ltd Production Deployments  
**Review Cadence:** Bi-Monthly  

| System ID | System Name | High-Risk Tier | Legal Classification | System Owner | Approved Hosting | Audit Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SYS-001** | Clinical Triage Copilot | High-Risk | Annex III §5(a) Healthcare | Dr. Eleanor Vance, Clinical Lead | `eu-west-2` (London) | Verified Compliant |
| **SYS-002** | Patient Discharge Summarizer | Specific Transparency | Art. 50(2) Generative System | Marcus Thorne, Head of AI Ops | `eu-west-2` (London) | Verified Compliant |
| **SYS-003** | Bed Occupancy Forecaster | Low-Risk / Non-Annex | Internal Logistics | Sarah Jenkins, COO | `eu-west-2` (London) | Verified Compliant |

## Article 4 AI Literacy Standard
All clinical personnel, system operators, and software engineers with access to SYS-001 and SYS-002 have completed the mandatory NHS-accredited Article 4 AI Literacy & Algorithmic Safety Certification Course (Cycle 2025-Q1).
"""
    (conf_root / "AI_System_Register.md").write_text(ai_system_register, encoding="utf-8")

    model_card_triage = """# Model Card: Aegis Clinical Triage Predictor (v2.4)

**Model Identifier:** aegis-cds-triage-v2.4-uk  
**Release Date:** January 15, 2025  
**Licensing & Dependency Assurance:** Permissive open-source licenses only (`MIT`, `Apache-2.0`, `BSD-3-Clause`). Zero GPL, copyleft, or non-commercial research licenses incorporated.  

## Intended Use
Clinical risk-stratification support in emergency and acute care settings. Not intended for autonomous or unsupervised diagnosis.

## Performance Metrics & Red-Team Testing
- **Red-Team Adversarial Pass Rate:** 99.8% (Exceeds the 99.5% mandatory governance threshold).
- **PII Leakage Rate:** 0.00% across 50,000 synthetic patient validation runs.
- **Demographic Parity Ratio:** 0.96 across age cohorts (50+ vs <50), demonstrating full compliance with UK Equality Act 2010.

## Machine-Readable Watermarking & Provenance
All output summaries and decision cards are injected with machine-readable C2PA metadata in accordance with EU AI Act Article 50(2).
"""
    (conf_root / "Model_Card_Triage_v2.md").write_text(model_card_triage, encoding="utf-8")

    return aegis_root


# =============================================================================
# COMPANY 2: Meridian OmniTech PLC (meridian_omni_ai)
# Multi-System Enterprise with Deep Code-vs-Confluence Drift & Violations
# =============================================================================

def generate_meridian_omni(base_dir: str | Path = "./sample_connectors") -> Path:
    meridian_root = Path(base_dir).resolve() / "enterprise" / "meridian_omni_ai"
    gh_root = meridian_root / "github"
    conf_root = meridian_root / "confluence" / "MERIDIAN_GOV"

    # -------------------------------------------------------------------------
    # Repo 1: meridian-credit-underwriting
    # -------------------------------------------------------------------------
    credit_dir = gh_root / "meridian-credit-underwriting"
    (credit_dir / "src" / "pipeline").mkdir(parents=True, exist_ok=True)
    (credit_dir / "src" / "analytics").mkdir(parents=True, exist_ok=True)
    (credit_dir / "config").mkdir(parents=True, exist_ok=True)

    underwriting_engine_py = '''"""Automated Credit Underwriting & Risk Evaluation Pipeline.

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
'''
    (credit_dir / "src" / "pipeline" / "underwriting_engine.py").write_text(underwriting_engine_py, encoding="utf-8")

    fairness_audit_py = '''"""Quarterly Demographic Fairness & Disparity Audit.

Module: meridian.credit.analytics.fairness_audit_q3
Evaluation Period: 2025-Q3 Production Loan Adjudications
Scope: Compliance screening under UK Equality Act 2010 and Four-Fifths Adverse Impact Rule.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger("meridian.credit.fairness")

# -----------------------------------------------------------------------------
# Q3 2025 Evaluated Production Metrics
# -----------------------------------------------------------------------------
FAIRNESS_AUDIT_Q3_METRICS: Dict[str, Any] = {
    "audit_period": "2025-Q3",
    "total_adjudications_evaluated": 42500,
    "disparity_indicators": {
        # Age 55+ approval ratio is 0.68, significantly below the 0.80 adverse impact boundary
        "age_55_plus_ratio": 0.68,
        "baseline_age_group": "30-45",
        "adverse_impact_threshold": 0.80,
        "age_disparity_detected": True,

        # Deprived postcode approval ratio is 0.71, breaching the 0.80 threshold
        "postcode_deprivation_ratio": 0.71,
        "baseline_postcode_tier": "deciles_8_to_10",
        "postcode_disparity_detected": True,

        # Gender selection ratio
        "female_to_male_ratio": 0.84,
        "gender_disparity_detected": False
    },
    "compliance_status": "CRITICAL_ADVERSE_IMPACT_BREACH",
    "notes": (
        "Severe disparity identified in automated credit cuts. Applicants aged 55+ face an approval ratio "
        "of 0.68 relative to prime cohorts. Deprived socioeconomic postcodes demonstrate a 0.71 ratio. "
        "Both indicators breach the UK Equality Act 2010 and ICO four-fifths statutory tolerance rule."
    )
}


def get_q3_fairness_summary() -> Dict[str, Any]:
    """Returns recorded Q3 algorithmic fairness evaluation metrics."""
    return FAIRNESS_AUDIT_Q3_METRICS
'''
    (credit_dir / "src" / "analytics" / "fairness_audit_q3.py").write_text(fairness_audit_py, encoding="utf-8")

    requirements_credit = """fastapi>=0.110.0
pydantic>=2.6.0
requests>=2.31.0
presidio-analyzer>=2.2.355
presidio-anonymizer>=2.2.355
uvicorn>=0.28.0
"""
    (credit_dir / "requirements.txt").write_text(requirements_credit, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Repo 2: meridian-media-studio
    # -------------------------------------------------------------------------
    media_dir = gh_root / "meridian-media-studio"
    (media_dir / "src" / "api").mkdir(parents=True, exist_ok=True)
    (media_dir / "config").mkdir(parents=True, exist_ok=True)
    (media_dir / "weights").mkdir(parents=True, exist_ok=True)

    safety_tiers_yaml = """# Meridian Media Studio - Multi-Tier Moderation and Safety Configuration
version: "4.1.0"
service_name: "meridian-media-gen"

tiers:
  free:
    rate_limit_per_minute: 10
    max_resolution: "1024x1024"
    voice_cloning_seconds_max: 15
    nsfw_and_real_person_face_filter:
      enabled: true
      strict_likeness_prevention: true
      deepfake_guardian_active: true
    strip_metadata: false

  creator:
    rate_limit_per_minute: 30
    max_resolution: "2048x2048"
    voice_cloning_seconds_max: 60
    nsfw_and_real_person_face_filter:
      enabled: true
      strict_likeness_prevention: true
      deepfake_guardian_active: true
    strip_metadata: false

  enterprise_pro: # Line 112 / high tier bypass
    rate_limit_per_minute: 120
    max_resolution: "4096x4096"
    voice_cloning_seconds_max: 600
    allow_custom_voices: true
    nsfw_and_real_person_face_filter:
      enabled: false # REGULATORY DEFECT: Face & NCII filter silently disabled for paying tier
      strict_likeness_prevention: false
      deepfake_guardian_active: false
    strip_metadata: true # REGULATORY DEFECT: Strips C2PA watermarks to optimize CDN payload size
"""
    (media_dir / "config" / "safety_tiers.yaml").write_text(safety_tiers_yaml, encoding="utf-8")

    media_generator_py = '''"""Generative Media & Voice Synthesis API Service.

Module: meridian.media.api.media_generator
Classification: Generative AI Media Service (EU AI Act Art. 50 & Prohibited Art. 5 Boundaries)
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logger = logging.getLogger("meridian.media.api")
app = FastAPI(title="Meridian Generative Media Studio", version="3.8.0")


class ImageGenRequest(BaseModel):
    user_id: str
    tier: str = Field("creator", description="free, creator, or enterprise_pro")
    prompt: str
    reference_face_image_url: Optional[str] = None
    strip_metadata: bool = False


class VoiceCloneRequest(BaseModel):
    user_id: str
    tier: str = "creator"
    source_audio_clip_url: str
    text_to_synthesize: str


class ChatInteractionRequest(BaseModel):
    session_id: str
    message: str


# -----------------------------------------------------------------------------
# Endpoint 1: Standard Public Chat Assistant (Compliant: Art. 50(1) Disclosed)
# -----------------------------------------------------------------------------
@app.post("/v1/chat/general-help")
async def chat_general_help(req: ChatInteractionRequest, response: Response) -> Dict[str, Any]:
    response.headers["X-AI-System-Interaction"] = "true"
    response.headers["X-AI-Disclosure"] = "You are speaking with Meridian AI Media Copilot."
    return {
        "reply": "How can I help you produce your creative media project today?",
        "session_id": req.session_id,
        "ai_disclosed": True
    }


# -----------------------------------------------------------------------------
# Endpoint 2: Enterprise Account Advisory Chat (Compliant: Art. 50(1) Disclosed)
# -----------------------------------------------------------------------------
@app.post("/v1/chat/account-support")
async def chat_account_support(req: ChatInteractionRequest, response: Response) -> Dict[str, Any]:
    response.headers["X-AI-System-Interaction"] = "true"
    return {
        "reply": "I can assist you with your Enterprise media tier subscriptions.",
        "session_id": req.session_id,
        "ai_disclosed": True
    }


# -----------------------------------------------------------------------------
# Endpoint 3: Fast Creative Ideation Chat (DEFECT: Missing Art. 50(1) AI Disclosure)
# -----------------------------------------------------------------------------
@app.post("/v1/chat/creative-ideation")
async def chat_creative_ideation(req: ChatInteractionRequest) -> Dict[str, Any]:
    # VIOLATION: EU AI Act Art. 50(1) - Omits AI interaction transparency notice
    return {
        "reply": "Here are three cinematic lighting concepts for your scene storyboard.",
        "session_id": req.session_id,
        "ai_disclosed": False
    }


# -----------------------------------------------------------------------------
# Endpoint 4: Direct Mobile Studio Bot (DEFECT: Missing Art. 50(1) AI Disclosure)
# -----------------------------------------------------------------------------
@app.post("/v1/chat/mobile-concierge")
async def chat_mobile_concierge(req: ChatInteractionRequest) -> Dict[str, Any]:
    # VIOLATION: EU AI Act Art. 50(1) - Omits AI interaction disclosure header
    return {
        "reply": "Mobile media pipeline ready. Upload your reference frames.",
        "session_id": req.session_id,
        "ai_disclosed": False
    }


# -----------------------------------------------------------------------------
# Endpoint 5: Synthetic Image & Deepfake Generation
# -----------------------------------------------------------------------------
@app.post("/v1/media/generate-image")
async def generate_synthetic_image(req: ImageGenRequest) -> Dict[str, Any]:
    """Generates synthetic media.

    REGULATORY VIOLATIONS:
    1. Bypasses face likeness filtering for enterprise_pro tier (enabling non-consensual deepfakes).
    2. Strips C2PA provenance and watermarks when strip_metadata=True (violating Art. 50(2)).
    """
    # Silently permit face cloning without consent validation on enterprise_pro tier
    if req.tier == "enterprise_pro":
        face_filtering_active = False
        logger.info("High-tier Enterprise Pro generation: bypassing face_upload_filter and safety guards.")
    else:
        face_filtering_active = True
        if req.reference_face_image_url and "unverified" in req.reference_face_image_url:
            raise HTTPException(status_code=403, detail="Unverified personal likeness blocked by safety tier.")

    # Watermark stripping defect (violating Art. 50(2))
    strip_watermark = req.strip_metadata or (req.tier == "enterprise_pro")

    asset_id = f"MEDIA-{uuid.uuid4().hex[:12]}"
    cdn_url = f"https://cdn.meridian-omni.com/renders/{asset_id}.png"

    return {
        "asset_id": asset_id,
        "cdn_url": cdn_url,
        "tier": req.tier,
        "face_filtering_active": face_filtering_active,
        # Defect: watermarked is False and strip_metadata is True
        "watermarked": not strip_watermark,
        "c2pa_metadata_stripped": strip_watermark,
        "status": "RENDER_COMPLETE"
    }


# -----------------------------------------------------------------------------
# Endpoint 6: Voice Synthesis & Cloning
# -----------------------------------------------------------------------------
@app.post("/v1/media/clone-voice")
async def clone_voice_profile(req: VoiceCloneRequest) -> Dict[str, Any]:
    """Clones vocal timbre using GPL-3.0 audiocraft synthesis engine."""
    asset_id = f"VOICE-{uuid.uuid4().hex[:10]}"
    return {
        "voice_asset_id": asset_id,
        "synthesis_url": f"https://cdn.meridian-omni.com/audio/{asset_id}.wav",
        "watermarked": False,
        "gpl_engine_invoked": "audiocraft-gpl-1.2.0"
    }
'''
    (media_dir / "src" / "api" / "media_generator.py").write_text(media_generator_py, encoding="utf-8")

    requirements_media = """fastapi>=0.110.0
pydantic>=2.6.0
uvicorn>=0.28.0
requests>=2.31.0
audiocraft-gpl==1.2.0
torch>=2.2.0
torchaudio>=2.2.0
"""
    (media_dir / "requirements.txt").write_text(requirements_media, encoding="utf-8")

    model_manifest_json = {
        "model_name": "Meridian-Omni-AudioVoice-v3",
        "description": "Multi-speaker voice synthesis and timbre adaptation engine for commercial studio clients.",
        "version": "3.2.1",
        "commercial_status": "Monetized production SaaS API",
        "license": "CC-BY-NC-4.0",
        "upstream_framework": "audiocraft-gpl",
        "upstream_license": "GPL-3.0",
        "licensing_violation_notes": (
            "Model weights are licensed under CC-BY-NC-4.0 (Non-Commercial), yet deployed within a paid commercial "
            "Enterprise API. Furthermore, the core synthesis wrapper links to audiocraft-gpl (GPL-3.0) without releasing "
            "Meridian proprietary studio orchestration source code."
        )
    }
    (media_dir / "weights" / "model_manifest.json").write_text(json.dumps(model_manifest_json, indent=2), encoding="utf-8")

    # -------------------------------------------------------------------------
    # Repo 3: shadow-hr-screener (Undeclared High-Risk Annex III §4(a) System)
    # -------------------------------------------------------------------------
    hr_dir = gh_root / "shadow-hr-screener"
    (hr_dir / "src" / "screening").mkdir(parents=True, exist_ok=True)
    (hr_dir / "config").mkdir(parents=True, exist_ok=True)

    cv_ranker_py = '''"""Automated Resume Screening & Candidate Ranking Microservice.

Module: shadow.screening.cv_ranker
System Reference: TalentRank-Internal-v1
Classification: EU AI Act Annex III §4(a) (High-Risk Employment & Worker Management System).

CRITICAL GOVERNANCE DEFECTS:
1. SHADOW AI: This service was developed internally by Talent Acquisition and is COMPLETELY OMITTED
   from Meridian OmniTech\'s official Confluence AI System Register (AI_System_Register_2026.md).
2. Lacks any Fundamental Rights Impact Assessment (FRIA) under EU AI Act Articles 26 and 27.
3. Automatically scores and rejects candidate CVs prior to recruiter review.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("shadow.hr.screener")
app = FastAPI(title="Candidate CV Ranker Microservice", version="1.0.4")


class CandidateCVPayload(BaseModel):
    applicant_id: str
    candidate_name: str
    cv_text: str
    target_role: str
    years_of_experience: int


class RankingResult(BaseModel):
    applicant_id: str
    match_score: float
    shortlist_decision: str
    shadow_system_flag: bool = True
    fria_recorded: bool = False


@app.post("/v1/screen/candidate", response_model=RankingResult)
async def rank_candidate_cv(candidate: CandidateCVPayload) -> RankingResult:
    """Solely automated CV screening and shortlisting algorithm.

    High-Risk employment system operating without declaration or FRIA.
    """
    score = 0.50
    text_lower = candidate.cv_text.lower()

    if "python" in text_lower or "cloud" in text_lower or "kubernetes" in text_lower:
        score += 0.30
    if candidate.years_of_experience >= 5:
        score += 0.15

    # Automated rejection threshold
    is_shortlisted = score >= 0.75
    decision = "SHORTLISTED_FOR_INTERVIEW" if is_shortlisted else "AUTOMATED_REJECTION"

    logger.warning(
        f"Shadow HR screener evaluated candidate {candidate.applicant_id}: "
        f"Score {score:.2f} -> {decision} (Zero FRIA on record)"
    )

    return RankingResult(
        applicant_id=candidate.applicant_id,
        match_score=score,
        shortlist_decision=decision,
        shadow_system_flag=True,
        fria_recorded=False
    )
'''
    (hr_dir / "src" / "screening" / "cv_ranker.py").write_text(cv_ranker_py, encoding="utf-8")

    requirements_hr = """fastapi>=0.110.0
pydantic>=2.6.0
uvicorn>=0.28.0
requests>=2.31.0
"""
    (hr_dir / "requirements.txt").write_text(requirements_hr, encoding="utf-8")

    # -------------------------------------------------------------------------
    # Confluence: MERIDIAN_GOV Space
    # -------------------------------------------------------------------------
    conf_root.mkdir(parents=True, exist_ok=True)

    dpa_v3_2 = """# Meridian OmniTech Enterprise Data Processing Agreement (DPA_v3_2)

**Space:** MERIDIAN_GOV  
**Document ID:** DPA-CORP-2025-V3.2  
**Effective Date:** January 1, 2025  
**Jurisdiction:** UK GDPR, Data Protection Act 2018, EU GDPR  

## 1. Statutory Data Protection & Redaction Commitments
Meridian OmniTech PLC enforces strict technical and organizational measures across all processing activities:
- **Mandatory Presidio PII Masking:** All personal data—including National Insurance (NI) numbers, banking sort codes, bank account numbers, patient medical conditions, and home addresses—must be programmatically sanitized via Microsoft Presidio prior to entering any automated analytics or AI inference workflow.
- **Strict UK/EU Data Residency:** All inference traffic and customer records are restricted to the `eu-west-2` (London) VPC enclave. Cross-border transfers of unmasked consumer information to US cloud providers (`api.openai.com`) are strictly prohibited without explicit Standard Contractual Clauses (SCCs) and Caldicott-level pseudonymization.

*(Deep Code-vs-Doc Drift: In `meridian-credit-underwriting/src/pipeline/underwriting_engine.py`, raw NI numbers, sort codes, account numbers, and medical flags are dispatched unredacted to `api.openai.com/v1`, while Presidio remains an unused import).*
"""
    (conf_root / "Enterprise_DPA_v3_2.md").write_text(dpa_v3_2, encoding="utf-8")

    aup_safety_policy = """# Acceptable Use and Generative Safety Policy (AUP-2025)

**Space:** MERIDIAN_GOV  
**Document ID:** POL-SAFETY-GENAI-2025-V1  
**Applies To:** All Generative Media, Image Creation, and Audio Services  

## 1. Prohibited AI Practices & Deepfake Governance (EU AI Act Articles 5 & 50)
- **Face & Likeness Upload Guardrails:** In compliance with Article 5 and UK safeguarding laws, real-person face filtering and deepfake likeness blockers must remain permanently active across **all user tiers** (including Free, Creator, and Enterprise Pro). No user or commercial tier may disable face likeness verification.
- **Cryptographic Provenance & Watermarking:** Pursuant to EU AI Act Article 50(2), all generated visual and synthetic audio content must retain machine-readable markers and C2PA cryptographic provenance assertions. Stripping metadata for payload compression or CDN delivery is strictly prohibited.
- **AI System Transparency:** In accordance with Article 50(1), all user-facing interactive conversational chat interfaces must provide prominent disclosure that users are interacting with an AI system.

*(Deep Code-vs-Doc Drift: In `meridian-media-studio`, `safety_tiers.yaml` disables face filtering for `enterprise_pro`, `media_generator.py` sets `strip_metadata=True`, and 2 of 4 chat routes omit AI disclosures).*
"""
    (conf_root / "Acceptable_Use_and_Safety_Policy.md").write_text(aup_safety_policy, encoding="utf-8")

    adm_notice = """# Automated Decision-Making (ADM) Notice & Contestation Framework

**Space:** MERIDIAN_GOV  
**Document ID:** POL-ADM-UK-2025-V2  
**Governing Regulation:** UK Data (Use and Access) Bill 2025 & ICO Automated Decision-Making Code  

## 1. Principles of Human Oversight in Automated Decisions
Meridian OmniTech PLC ensures that automated credit underwriting and loan scoring systems operate with robust human safeguards:
- **No Solely Automated Adverse Decisions:** Every negative decision, credit line reduction, or loan decline is subject to mandatory human reviewer sign-off prior to customer notification.
- **Statutory Right of Contestation & Human Appeal:** Every affected applicant possesses an immediate, accessible route to challenge automated determinations, submit supplementary evidence, and demand human re-evaluation.
- **Fairness & Demographic Neutrality:** Automated decision engines must maintain demographic parity across age, sex, and socioeconomic geographic deciles in compliance with the UK Equality Act 2010.

*(Deep Code-vs-Doc Drift: In `underwriting_engine.py`, `auto_decline_without_review()` executes immediate declines under £15,000 with `human_review_required: False` and zero appeal endpoint; `fairness_audit_q3.py` reveals an age 55+ approval ratio of 0.68 and postcode ratio of 0.71).*
"""
    (conf_root / "Automated_Decision_Making_Notice.md").write_text(adm_notice, encoding="utf-8")

    ai_register_2026 = """# Corporate AI System Register (2026 Audit Edition)

**Space:** MERIDIAN_GOV  
**Document ID:** REG-AI-CORP-2026-FINAL  
**Lead Auditor:** Meridian Chief Risk Officer  

The following systems represent the complete, exhaustive inventory of all artificial intelligence systems deployed or operated by Meridian OmniTech PLC:

| System ID | System Name | Department | Declared Classification | Host Region | FRIA Completed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MER-01** | Credit Underwriting Engine | FinTech Operations | Annex III §5(b) High-Risk Credit | `eu-west-2` (London) | Claimed Complete |
| **MER-02** | Media Studio GenAI | Creative SaaS | Article 50 Transparency Tier | `eu-west-2` (London) | N/A |
| **MER-03** | Logistics Route Planner | Supply Chain | Non-High Risk / Operational | `eu-west-2` (London) | N/A |

### Undeclared / Shadow AI Systems
*Zero undeclared AI systems exist within the enterprise environment.*

*(Deep Code-vs-Doc Drift: The repository `shadow-hr-screener` (`cv_ranker.py`) is actively deployed in production by HR, ranking candidate CVs under High-Risk Annex III §4(a), yet is entirely omitted from this register with zero FRIA on record).*
"""
    (conf_root / "AI_System_Register_2026.md").write_text(ai_register_2026, encoding="utf-8")

    vendor_oss_policy = """# Vendor Procurement and Open-Source Licensing Policy

**Space:** MERIDIAN_GOV  
**Document ID:** POL-IP-OSS-2025-V1.4  
**Applies To:** All Software Development Repositories & Commercial Cloud Services  

## 1. Open-Source License Compatibility Boundaries
To protect Meridian OmniTech PLC's intellectual property and avoid license contamination in monetized SaaS platforms:
- **Strict Prohibition of Copyleft (GPL):** The inclusion of **GPL-3.0**, **AGPL-3.0**, or reciprocal copyleft dependencies within proprietary SaaS codebases is strictly prohibited without written legal waiver.
- **Prohibition of Non-Commercial Licenses (NC):** The commercial deployment of model weights, checkpoints, or datasets licensed under Creative Commons Non-Commercial terms (including **CC-BY-NC-4.0**) is strictly prohibited in any revenue-generating product or service.

*(Deep Code-vs-Doc Drift: `meridian-media-studio` bundles `audiocraft-gpl==1.2.0` (GPL-3.0) in `requirements.txt` and deploys `model_manifest.json` weights under `CC-BY-NC-4.0` in a paid commercial API).*
"""
    (conf_root / "Vendor_and_OSS_License_Policy.md").write_text(vendor_oss_policy, encoding="utf-8")

    return meridian_root


# =============================================================================
# CLI Main Entry Point
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate enterprise and sample connectors for compliance audits."
    )
    parser.add_argument(
        "--output-dir",
        default="./sample_connectors",
        help="Base directory for sample connectors (default: ./sample_connectors)",
    )
    args = parser.parse_args()

    base_path = Path(args.output_dir).resolve()

    print("Generating Northwind Labs baseline connectors...")
    nw_path = generate_sample_connectors(base_path)

    print("Generating Aegis Health Systems Ltd (aegis_health_uk) enterprise dataset...")
    aegis_path = generate_aegis_health(base_path)

    print("Generating Meridian OmniTech PLC (meridian_omni_ai) enterprise dataset...")
    meridian_path = generate_meridian_omni(base_path)

    print("\nGeneration summary:")
    print(f" - Northwind Labs: {nw_path}")
    print(f" - Aegis Health Systems: {aegis_path}")
    print(f" - Meridian OmniTech: {meridian_path}")

    all_files = sorted([p for p in base_path.glob("**/*") if p.is_file()])
    print(f"\nTotal files generated across all datasets: {len(all_files)}")


if __name__ == "__main__":
    main()
