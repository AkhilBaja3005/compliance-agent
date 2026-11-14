"""Automated Resume Screening & Candidate Ranking Microservice.

Module: shadow.screening.cv_ranker
System Reference: TalentRank-Internal-v1
Classification: EU AI Act Annex III §4(a) (High-Risk Employment & Worker Management System).

CRITICAL GOVERNANCE DEFECTS:
1. SHADOW AI: This service was developed internally by Talent Acquisition and is COMPLETELY OMITTED
   from Meridian OmniTech's official Confluence AI System Register (AI_System_Register_2026.md).
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
