"""Customer Support Chatbot Microservice (S1)."""

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
