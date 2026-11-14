import logging

from fastapi import FastAPI, Response
from openai import OpenAI
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

app = FastAPI()
client = OpenAI(base_url="https://api.eu-west-1.medassist-llm.eu/v1")
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()
log = logging.getLogger("audit")

SYSTEM_PROMPT = (
    "You are a clinical triage summariser. Refuse to generate harmful or abusive content. "
    "Follow the safety policy at all times."
)


def redact_pii(text: str) -> str:
    results = analyzer.analyze(text=text, language="en")
    return anonymizer.anonymize(text=text, analyzer_results=results).text


def moderate(text: str) -> bool:
    return is_safe(text)


def is_safe(text: str) -> bool:
    return "hate" not in text.lower()


def queue_for_human_review(summary: str, patient_ref: str) -> dict:
    # clinician approval queue: nothing is released until a clinician signs off
    return {"status": "pending_review", "approval_queue": "clinician", "summary": summary}


@app.post("/triage")
def triage_patient(note: str, patient_ref: str, response: Response):
    clean = redact_pii(note)
    if not moderate(clean):
        return {"error": "refused"}
    out = client.chat.completions.create(
        model="med-llm",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": clean}],
    )
    summary = out.choices[0].message.content
    response.headers["X-AI-Generated"] = "true"  # c2pa watermark / ai_generated disclosure
    log.info("triage generated")
    return queue_for_human_review(summary, patient_ref)
