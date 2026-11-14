import express from "express";
import OpenAI from "openai";
const app = express();
const client = new OpenAI({ baseURL: "https://eu-west.llm.example.eu/v1" });
app.post("/v1/loan/decision", async (req, res) => {
  const email = redact(req.body.email);
  const out = await fetch("https://eu-west.llm.example.eu/v1/chat/completions", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: email }] }) });
  const queued = await human_review_queue.enqueue(out);
  res.json({ decision: "pending_human_review", queued });
});
