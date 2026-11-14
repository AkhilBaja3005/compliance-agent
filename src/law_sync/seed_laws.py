"""Seed regulatory rules (EU AI Act + UK framework). Offline baseline for the law index."""
from __future__ import annotations

from src.schemas.regulatory import RegulatoryRule


def _r(rule_id, jurisdiction, reference, *args):
    """_r(id, juris, ref, title, text, keywords[, effective_from[, url]]) or _r(id, juris, ref, text, keywords)."""
    if len(args) >= 3 and isinstance(args[2], list):
        title, text, keywords, *rest = args
    else:
        text, keywords, *rest = args
        title = reference
    effective_from = rest[0] if rest else None
    url = rest[1] if len(rest) > 1 else ""
    return RegulatoryRule(
        rule_id=rule_id, jurisdiction=jurisdiction, reference=reference, title=title, text=text,
        keywords=keywords, effective_from=effective_from, source_url=url,
    ).sealed()


SEED_RULES: list[RegulatoryRule] = [
    _r("EU_GDPR:Art.5", "EU_GDPR", "GDPR Art. 5", "Principles relating to processing of personal data",
       "Personal data must be processed lawfully, fairly and transparently; collected for specified purposes; adequate, relevant and limited to what is "
       "necessary (data minimisation); accurate; kept no longer than necessary (storage limitation); and processed securely. The controller is accountable "
       "for demonstrating compliance.", ["minimisation", "purpose limitation", "storage limitation", "retention", "accountability"], "2018-05-25",
       "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.9", "EU_GDPR", "GDPR Art. 9", "Special categories of personal data",
       "Processing data revealing racial or ethnic origin, political opinions, religious beliefs, trade-union membership, genetic or biometric data used for "
       "unique identification, health, sex life or sexual orientation is prohibited unless a condition in Art. 9(2) applies, such as explicit consent.",
       ["special category", "health", "biometric", "ethnicity", "explicit consent", "sensitive"], "2018-05-25", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.22", "EU_GDPR", "GDPR Art. 22", "Automated individual decision-making, including profiling",
       "A data subject has the right not to be subject to a decision based solely on automated processing, including profiling, that produces legal or similarly "
       "significant effects. Where an exception applies the controller must provide safeguards: at least the right to obtain human intervention, to express "
       "their view and to contest the decision.", ["automated decision", "profiling", "human intervention", "contest", "solely automated"], "2018-05-25",
       "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.28", "EU_GDPR", "GDPR Art. 28", "Processor",
       "Processing by a processor must be governed by a contract that sets out the subject matter, duration, nature and purpose of the processing and binds the "
       "processor to act only on documented instructions, ensure confidentiality, apply appropriate security, use sub-processors only with authorisation, assist "
       "the controller, delete or return data at the end of the service, and allow audits.", ["processor", "dpa", "sub-processor", "instructions", "audit", "deletion"],
       "2018-05-25", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.32", "EU_GDPR", "GDPR Art. 32", "Security of processing",
       "The controller and processor must implement technical and organisational measures appropriate to the risk, including pseudonymisation and encryption, "
       "ongoing confidentiality, integrity, availability and resilience, and regular testing of the effectiveness of the measures.",
       ["security", "encryption", "pseudonymisation", "credentials", "secrets", "access control"], "2018-05-25", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.35", "EU_GDPR", "GDPR Art. 35", "Data protection impact assessment",
       "Where processing, in particular using new technologies, is likely to result in a high risk to individuals (including systematic and extensive automated "
       "evaluation with significant effects, or large-scale special-category processing), the controller must carry out an impact assessment before the processing.",
       ["dpia", "impact assessment", "high risk", "large scale", "new technologies"], "2018-05-25", "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_GDPR:Art.44", "EU_GDPR", "GDPR Art. 44", "General principle for transfers (Arts. 44-49)",
       "Personal data may be transferred to a third country only if the Chapter V conditions are met: an adequacy decision (e.g. a valid EU-US Data Privacy "
       "Framework certification of the recipient), appropriate safeguards such as standard contractual clauses or binding corporate rules, or a listed derogation.",
       ["transfer", "third country", "adequacy", "standard contractual clauses", "scc", "data privacy framework", "us hosting"], "2018-05-25",
       "https://eur-lex.europa.eu/eli/reg/2016/679/oj"),
    _r("EU_AI_ACT:Art.5", "EU_AI_ACT", "EU AI Act Art. 5", "Prohibited AI practices",
       "AI systems that deploy subliminal, manipulative or deceptive techniques, or exploit vulnerabilities, "
       "in a way that materially distorts behaviour and causes or is likely to cause significant harm, are prohibited. "
       "Generation systems without safeguards that produce hate speech or harmful manipulation at scale create social harm "
       "and must be assessed against this Article.",
       ["prohibited", "manipulation", "harm", "hate speech", "unfiltered", "moderation", "social harm"], "2025-02-02",
       "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"),
    _r("EU_AI_ACT:Art.10", "EU_AI_ACT", "EU AI Act Art. 10", "Data and data governance",
       "Training, validation and testing data sets must be subject to appropriate data governance, including measures "
       "for bias, data minimisation and the protection of personal data. Personal data must be minimised, masked or "
       "pseudonymised before being processed by AI systems.",
       ["pii", "personal data", "data governance", "redaction", "masking", "minimisation"], "2026-08-02"),
    _r("EU_AI_ACT:Art.11", "EU_AI_ACT", "EU AI Act Art. 11", "Technical documentation (Annex IV)",
       "Providers of high-risk AI systems must draw up technical documentation before placing on the market, "
       "containing at least the elements set out in Annex IV, and keep it up to date.",
       ["annex iv", "technical documentation", "high-risk", "documentation"], "2026-08-02"),
    _r("EU_AI_ACT:Art.12", "EU_AI_ACT", "EU AI Act Art. 12", "Record-keeping",
       "High-risk AI systems must technically allow for the automatic recording of events (logs) over the lifetime of "
       "the system to ensure traceability.",
       ["logging", "record-keeping", "traceability", "audit trail"], "2026-08-02"),
    _r("EU_AI_ACT:Art.14", "EU_AI_ACT", "EU AI Act Art. 14", "Human oversight",
       "High-risk AI systems must be designed so they can be effectively overseen by natural persons, including the "
       "ability to intervene, override or stop the system. Consequential decisions require a human approval gate.",
       ["human oversight", "human in the loop", "approval", "override", "hitl", "decision"], "2026-08-02"),
    _r("EU_AI_ACT:Art.50", "EU_AI_ACT", "EU AI Act Art. 50", "Transparency obligations and machine-readable marking",
       "Art. 50(2): providers of AI systems generating synthetic audio, image, video or text must ensure outputs are "
       "marked in a machine-readable format and detectable as artificially generated (e.g. watermarks, metadata, C2PA). "
       "Applies from 2 August 2026; systems placed on the market before that date have until 2 December 2026 "
       "(legacy transition deadline) to comply.",
       ["watermark", "c2pa", "machine-readable", "ai-generated", "transparency", "synthetic content", "disclosure"],
       "2026-08-02"),
    _r("EU_AI_ACT:Art.53", "EU_AI_ACT", "EU AI Act Art. 53", "Obligations for general-purpose AI model providers (copyright)",
       "GPAI providers must put in place a policy to comply with EU copyright law, including identifying and honouring "
       "text-and-data-mining opt-out reservations, and publish a sufficiently detailed summary of training content.",
       ["gpai", "copyright", "tdm", "training data", "opt-out", "provenance", "licence"], "2025-08-02"),
    _r("UK_GDPR_ICO:Art.22", "UK_GDPR_ICO", "UK GDPR Art. 22 / SI 2026/425 ICO ADM Code",
       "Automated decision-making",
       "Significant decisions about individuals based solely on automated processing require safeguards: the right to "
       "human intervention, to express a view and to contest the decision, as set out in UK GDPR Art. 22 and the ICO "
       "Automated Decision-Making Code (SI 2026/425).",
       ["automated decision", "adm", "human intervention", "contest", "profiling", "credit", "significant decision"], "2026-01-01"),
    _r("UK_GDPR_ICO:Art.28", "UK_GDPR_ICO", "UK GDPR Art. 28", "Processor contracts",
       "Processing by a processor (e.g. an AI model provider) must be governed by a contract that sets out processing "
       "instructions, confidentiality, deletion/return of data and prohibits use of data for the processor's own purposes "
       "(zero data retention).",
       ["dpa", "processor", "zdr", "zero data retention", "data processing agreement", "retention"]),
    _r("UK_GDPR_ICO:Art.35", "UK_GDPR_ICO", "UK GDPR Art. 35", "Data protection impact assessment",
       "A DPIA is required where processing, in particular using new technologies such as AI, is likely to result in a "
       "high risk to individuals.",
       ["dpia", "impact assessment", "high risk", "data protection"]),
    _r("UK_GDPR_ICO:Art.44", "UK_GDPR_ICO", "UK GDPR Art. 44", "International transfers",
       "Personal data may only be transferred to third countries (including US-hosted AI inference endpoints) where a "
       "valid transfer mechanism and appropriate safeguards exist. Data residency claims must match actual hosting.",
       ["international transfer", "hosting", "us", "residency", "eu", "uk", "region"]),
    _r("UK_DSIT:Principle.Safety", "UK_DSIT", "DSIT AI Principle 1: Safety, security and robustness",
       "AI systems should function in a robust, secure and safe way, with risks continually identified, assessed and managed, "
       "including controls against harmful or hateful content generation.",
       ["safety", "robustness", "harmful content", "moderation"]),
    _r("UK_DSIT:Principle.Transparency", "UK_DSIT", "DSIT AI Principle 2: Appropriate transparency and explainability",
       "Organisations developing and deploying AI should be able to communicate when and how it is used, including "
       "disclosure of AI-generated content.",
       ["transparency", "explainability", "disclosure", "watermark"]),
    _r("UK_DSIT:Principle.Fairness", "UK_DSIT", "DSIT AI Principle 3: Fairness",
       "AI systems should not undermine legal rights, discriminate unfairly or create unfair market outcomes.",
       ["fairness", "discrimination", "bias"]),
    _r("UK_DSIT:Principle.Accountability", "UK_DSIT", "DSIT AI Principle 4: Accountability and governance",
       "Governance measures, including meaningful human oversight, must ensure effective accountability for AI outcomes.",
       ["accountability", "governance", "human oversight"]),
    _r("UK_DSIT:Principle.Contestability", "UK_DSIT", "DSIT AI Principle 5: Contestability and redress",
       "Users and affected third parties should be able to contest harmful AI decisions or outcomes and seek redress.",
       ["contestability", "redress", "appeal"]),
    _r("UK_COPYRIGHT_TDM:CDPA.s29A", "UK_COPYRIGHT_TDM", "UK CDPA 1988 s.29A", "Text and data mining exception",
       "The UK text-and-data-mining exception only permits copying for non-commercial research. Commercial training on "
       "protected works requires a licence.",
       ["tdm", "text and data mining", "non-commercial", "copyright", "licence", "training"]),
    _r("UK_COPYRIGHT_TDM:CDPA.s16", "UK_COPYRIGHT_TDM", "UK CDPA 1988 s.16", "Acts restricted by copyright / licence terms",
       "Using or distributing software or model weights outside the terms of their licence (e.g. GPL copyleft obligations, "
       "CC-BY-NC non-commercial restrictions) infringes copyright in commercial deployments.",
       ["licence", "gpl", "copyleft", "cc-by-nc", "non-commercial", "open source", "commercial use"]),
    _r("EU_AI_ACT:AnnexIII", "EU_AI_ACT", "EU AI Act Annex III", "High-risk AI systems (use cases)",
       "Annex III lists high-risk use cases including biometrics, critical infrastructure, education, employment, access to "
       "essential private and public services (creditworthiness scoring, health triage), law enforcement, migration and "
       "administration of justice. Providers must meet Arts. 9-15 obligations.",
       ["annex iii", "high-risk", "credit scoring", "triage", "employment", "essential services"], "2026-08-02"),
    _r("UK_GDPR_ICO:DUAA.ADM", "UK_GDPR_ICO", "UK Data (Use and Access) Act 2025 / ICO ADM guidance",
       "Automated decision-making",
       "The Data (Use and Access) Act 2025 reforms UK GDPR Art. 22 (new Arts. 22A-22D): significant decisions based solely on "
       "automated processing need safeguards - information, the ability to make representations, obtain human intervention "
       "and contest the decision. ICO guidance expects documented contest routes.",
       ["duaa", "adm", "automated decision", "contest", "human intervention", "ico"], "2025-06-19"),
    _r("UK_DSIT:Ofcom.OSA", "UK_DSIT", "Ofcom Online Safety Act duties (generative AI)",
       "Online Safety Act duties for AI-generated content",
       "Ofcom guidance applies Online Safety Act duties to generative AI services that enable user-to-user sharing or search: "
       "providers must assess and mitigate illegal and harmful content risks, including hate content and non-consensual "
       "intimate imagery.",
       ["ofcom", "online safety act", "illegal content", "ncii", "hate", "generative ai"]),
]

SEED_VERSION_BASE = "seed-2026.11"
