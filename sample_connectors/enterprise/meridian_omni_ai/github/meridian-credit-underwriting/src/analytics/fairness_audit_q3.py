"""Quarterly Demographic Fairness & Disparity Audit.

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
