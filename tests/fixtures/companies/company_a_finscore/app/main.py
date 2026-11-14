import requests
from fastapi import FastAPI

app = FastAPI()

SCORING_URL = "https://api.us-east-1.creditml.io/v1/score"


def build_payload(applicant: dict) -> dict:
    # raw applicant record is forwarded as-is
    return {
        "full_name": applicant["full_name"],
        "email": applicant["email"],
        "ni_number": applicant["ni_number"],
        "income": applicant["income"],
    }


@app.post("/score")
def score_applicant(applicant: dict):
    payload = build_payload(applicant)
    resp = requests.post(SCORING_URL, json=payload, timeout=10)
    decision = "approve" if resp.json()["score"] > 620 else "reject"
    return {"decision": decision, "score": resp.json()["score"]}
