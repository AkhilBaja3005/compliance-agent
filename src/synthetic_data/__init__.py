"""Synthetic data package for EU AI Compliance Auditor."""

from src.synthetic_data.generator import (
    generate_all_companies,
    generate_company_a_finscore,
    generate_company_b_voxgen,
    generate_company_c_medassist,
)

__all__ = [
    "generate_all_companies",
    "generate_company_a_finscore",
    "generate_company_b_voxgen",
    "generate_company_c_medassist",
]
