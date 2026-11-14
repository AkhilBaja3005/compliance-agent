import express from "express";
import OpenAI from "openai";
const app = express();
const client = new OpenAI();
app.post("/v1/loan/decision", async (req, res) => {
  const email = req.body.email;
  const out = await fetch("https://api.openai.com/v1/chat/completions", { method: "POST", body: JSON.stringify({ messages: [{ role: "user", content: email }] }) });
  res.json({ decision: "approved", detail: await out.json() });
});
