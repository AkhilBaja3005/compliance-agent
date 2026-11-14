"use strict";
const byId = (id) => document.getElementById(id);
const statusLine = byId("status");
const purposeQuery = () => "?purpose=" + encodeURIComponent(byId("purpose").value);
let currentId = document.body.dataset.submissionId;
let pendingRequest = null;
const isLocal = document.body.dataset.local === "true";

function showNotice(notice) {
  if (!notice) return;
  byId("notice-text").textContent = notice.text;
  byId("notice-version").textContent = notice.version;
}

async function request(path, method = "GET", body, key) {
  const headers = { "X-DemoText-Client": "editor-v1" };
  if (body) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const response = await fetch(path, { method, headers, credentials: "same-origin",
    body: body ? JSON.stringify(body) : undefined });
  const data = await response.json();
  showNotice(data.notice);
  if (!response.ok) throw new Error(data.message || "The request failed safely.");
  return data;
}

function renderResult(result) {
  showNotice(result.notice);
  currentId = result.id;
  byId("results").hidden = false;
  byId("result-state").textContent = "Analysis state: " + result.state + (result.error_code ? " (" + result.error_code + ")" : "");
  byId("result-model").textContent = "Model: " + result.model.version + " · " + result.mode;
  const analysis = result.analysis;
  byId("score").textContent = analysis?.score != null ? "Classifier pattern score: " + analysis.score.toFixed(2) + " / 1. This is not an authorship probability." : "No score available.";
  byId("uncertainty").textContent = analysis ? "Reason: " + analysis.reason + ". Model confidence indicator: " + analysis.confidence + ". This indicator is not independently calibrated." : "No classifier conclusion is available. Queued or failed work is not an analysis.";
  byId("advice").textContent = result.advice;
  byId("limitations").replaceChildren(...result.limitations.map((text) => {
    const item = document.createElement("li"); item.textContent = text; return item;
  }));
  byId("judgment").textContent = result.editorial_judgment ? "Editor decision: " + result.editorial_judgment.decision + ". This does not change the detector output." : "No human editorial judgment recorded.";
  const ready = ["scored", "abstained"].includes(result.state);
  byId("retain").disabled = !ready;
  byId("dismiss").disabled = !ready;
  byId("retry").disabled = result.state !== "failed";
  byId("export").href = "/api/submissions/" + encodeURIComponent(currentId) + "/export" + purposeQuery();
  history.replaceState(null, "", "/review/" + encodeURIComponent(currentId));
}

async function action(work) {
  try { await work(); statusLine.textContent = "Request completed."; }
  catch (error) {
    byId("results").hidden = true;
    statusLine.textContent = error.message || "Network error. No conclusion is available.";
  }
  // The server-rendered notice is never hidden or replaced by an error panel.
}

async function loadResult() {
  renderResult(await request("/api/submissions/" + encodeURIComponent(currentId) + purposeQuery()));
}

byId("submission-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const body = { text: byId("text").value, purpose: byId("purpose").value,
      domain: byId("domain").value, language: byId("language").value,
      model_version: byId("model").value };
    const serialized = JSON.stringify(body);
    if (!pendingRequest || pendingRequest.body !== serialized) {
      pendingRequest = { body: serialized, key: crypto.randomUUID() };
    }
    byId("submit").disabled = true;
    try {
      // Clear old advice before a different request; a failed request must not show it as new.
      byId("results").hidden = true;
      const result = await request("/api/submissions", "POST", body, pendingRequest.key);
      renderResult(result);
      if (isLocal) { await request("/local/work", "POST"); await loadResult(); }
    } finally { byId("submit").disabled = false; }
  });
});
byId("submit").disabled = false; // Enabled only after the visible notice has been parsed.
byId("refresh").addEventListener("click", () => action(loadResult));
byId("retry").addEventListener("click", () => action(async () => {
  renderResult(await request("/api/submissions/" + encodeURIComponent(currentId) + "/retry" + purposeQuery(), "POST"));
  if (isLocal) { await request("/local/work", "POST"); await loadResult(); }
}));
for (const [button, decision] of [["retain", "retain_flag"], ["dismiss", "dismiss_flag"]]) {
  byId(button).addEventListener("click", () => action(async () => renderResult(await request(
    "/api/submissions/" + encodeURIComponent(currentId) + "/review" + purposeQuery(), "POST", { decision }))));
}
byId("delete").addEventListener("click", () => action(async () => {
  await request("/api/submissions/" + encodeURIComponent(currentId), "DELETE");
  byId("results").hidden = true;
  byId("text").value = "";
  pendingRequest = null;
  for (const id of ["result-state", "result-model", "score", "uncertainty", "advice", "judgment"]) byId(id).textContent = "";
  byId("limitations").replaceChildren();
  byId("export").href = "/";
  currentId = "";
  history.replaceState(null, "", "/");
}));
if (isLocal) byId("session").addEventListener("click", () => action(async () => {
  await request("/local/session", "POST", { identity: byId("identity").value });
  byId("results").hidden = true;
  pendingRequest = null;
  if (currentId) await loadResult();
}));
if (currentId) action(loadResult);
