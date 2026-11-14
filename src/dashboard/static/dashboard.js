/* No frontend build step or external browser dependencies. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const engineering = location.pathname.endsWith("/findings");
  const statuses = {
    CONFIRMED_VIOLATION: "Confirmed violation",
    SUSPECTED_GAP: "Suspected gap",
    QUARANTINED_FOR_HUMAN_REVIEW: "Human review",
    PASS: "Passed",
  };
  const buckets = [
    "confirmed_findings",
    "suspected_gaps",
    "quarantined_for_human_review",
    "passed_checks",
  ];
  const severityOrder = [
    "Critical",
    "High",
    "Medium",
    "Low",
    "Info",
    "Unspecified",
  ];
  const colors = ["var(--confirmed)", "var(--suspected)", "var(--review)", "var(--passed)"];

  // Graceful fallback for environments where binary assets are blocked
  if (window.GRAPHITE_LOGO_B64) {
    document.addEventListener("DOMContentLoaded", () => {
      document.querySelectorAll('img[src*="graphite_report_logo.png"]').forEach((img) => {
        img.onerror = () => {
          img.onerror = null;
          img.src = window.GRAPHITE_LOGO_B64;
        };
      });
    });
  }
  const state = {
    company: "",
    generation: 0,
    controller: null,
    snapshot: null,
    report: null,
    busy: false,
    connected: false,
    dirty: false,
    lastRefresh: null,
    message: "",
    expanded: new Set(),
    rendered: null,
    booting: false,
  };
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const label = (value) =>
    String(value || "Unknown")
      .toLowerCase()
      .replaceAll("_", " ");
  const date = (value) =>
    value
      ? new Date(value).toLocaleString(undefined, {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : "—";
  const badge = (value, text) =>
    `<span class="badge ${esc(value)}">${esc(text || value || "Unspecified")}</span>`;
  const findings = () =>
    state.report ? buckets.flatMap((key) => state.report[key] || []) : [];
  const companyUrl = (page) =>
    `/dashboard/${page}?company=${encodeURIComponent(state.company)}`;
  const safeLink = (url, text) => {
    try {
      const parsed = new URL(url);
      if (
        ["https:", "http:"].includes(parsed.protocol) &&
        !parsed.username &&
        !parsed.password
      ) {
        return `<a class="citation" href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(text || url)} ↗</a>`;
      }
    } catch (_) {
      /* Invalid source URLs remain visible as text. */
    }
    return esc(text || url);
  };

  async function api(
    path,
    options = {},
    company = state.company,
    signal = state.controller?.signal,
  ) {
    const response = await fetch(
      `/dashboard/api/companies/${encodeURIComponent(company)}${path}`,
      {
        ...options,
        signal,
        cache: "no-store",
        headers: { "Content-Type": "application/json", ...options.headers },
      },
    );
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") detail = body.detail;
        else if (Array.isArray(body.detail))
          detail = body.detail.map((item) => item.msg).join("; ");
      } catch (_) {
        /* Preserve the HTTP status. */
      }
      throw new Error(detail);
    }
    return response.json();
  }

  function links() {
    for (const [id, page] of [
      ["overview-link", "overview"],
      ["findings-link", "findings"],
      ["all-findings-link", "findings"],
    ]) {
      $(id).href = companyUrl(page);
    }
    document.querySelector(".brand").href = companyUrl("overview");
  }

  function selectCompany(company) {
    state.controller?.abort();
    state.controller = new AbortController();
    state.generation += 1;
    Object.assign(state, {
      company,
      snapshot: null,
      report: null,
      busy: false,
      connected: false,
      dirty: false,
      lastRefresh: null,
      message: "",
      expanded: new Set(),
      rendered: null,
    });
    $("company").value = company;
    const url = new URL(location.href);
    url.searchParams.set("company", company);
    history.replaceState(null, "", url);
    try {
      localStorage.setItem("graphite-company", company);
    } catch (_) {
      /* Optional preference. */
    }
    links();
    $("settings-form").reset();
    $("settings-message").textContent =
      "Manual and scheduled audits use saved settings. Enabling a schedule waits one full interval.";
    for (const element of document.querySelectorAll(
      ".filters input, .filters select",
    ))
      element.value = "";
    render();
    refresh();
  }

  async function boot() {
    if (state.booting) return;
    state.booting = true;
    try {
      const response = await fetch("/companies", { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load companies");
      const companies = await response.json();
      $("company").innerHTML = companies
        .map(
          (company) =>
            `<option value="${esc(company.company_id)}">${esc(company.company_name)}</option>`,
        )
        .join("");
      if (!companies.length) throw new Error("No companies configured");
      $("company").disabled = false;
      let stored = "";
      try {
        stored = localStorage.getItem("graphite-company");
      } catch (_) {
        /* Optional preference. */
      }
      const requested =
        new URLSearchParams(location.search).get("company") || stored;
      selectCompany(
        companies.find((company) => company.company_id === requested)
          ?.company_id || companies[0].company_id,
      );
    } catch (error) {
      state.message = `${error.message}. Retrying automatically.`;
      render();
    } finally {
      state.booting = false;
    }
  }

  async function refresh() {
    if (state.busy || !state.company) return;
    state.busy = true;
    const generation = state.generation;
    try {
      const snapshot = await api("/snapshot");
      if (generation !== state.generation) return;
      state.snapshot = snapshot;
      if (!state.dirty) fillSettings(snapshot.settings);
      const id = snapshot.latest_report?.report_id;
      // Fetch the large report only on identity changes; keep the previous report until it arrives.
      if (id && id !== state.report?.report_id) {
        const report = await api(`/reports/${encodeURIComponent(id)}`);
        if (generation !== state.generation) return;
        state.report = report;
      }
      if (generation !== state.generation) return;
      state.connected = true;
      state.lastRefresh = new Date().toISOString();
      state.message = "";
      render();
    } catch (error) {
      if (generation !== state.generation || error.name === "AbortError")
        return;
      state.connected = false;
      state.message = `Connection interrupted: ${error.message}. Retrying every 5 seconds. ${state.report ? "Showing the last completed assessment." : "No assessment can be displayed yet."}`;
      render();
    } finally {
      if (generation === state.generation) state.busy = false;
    }
  }

  function fillSettings(settings) {
    $("github-source").value = settings.sources.github_url || "";
    $("confluence-path").value = settings.sources.confluence_path || "";
    $("confluence-space").value = settings.sources.confluence_space_key || "";
    $("schedule-enabled").checked = settings.schedule.enabled;
    $("schedule-frequency").value = settings.schedule.frequency;
  }

  function render() {
    const snapshot = state.snapshot;
    const job = snapshot?.latest_job;
    const active = ["queued", "running"].includes(job?.state);
    $("connection").textContent = state.connected
      ? "Live updates"
      : state.message
        ? "Disconnected"
        : "Connecting…";
    $("connection").className =
      `connection ${state.connected ? "live" : state.message ? "offline" : ""}`;
    $("refresh-time").textContent =
      `Last successful refresh: ${date(state.lastRefresh)}`;
    $("assessment").textContent = state.report
      ? `Assessment: ${date(state.report.assessed_at)}`
      : "Assessment: none available";
    $("run-audit").disabled = !state.connected || active || state.dirty;
    $("run-audit").innerHTML =
      `<span aria-hidden="true">↻</span> ${active ? (job.state === "queued" ? "Audit queued" : "Auditing…") : "Run audit"}`;
    $("run-audit").title = state.dirty
      ? "Save source and schedule settings before running an audit"
      : "Run an audit using saved sources";
    $("save-settings").disabled = !snapshot;
    for (const element of document.querySelectorAll(
      "#settings-form input, #settings-form select",
    ))
      element.disabled = !snapshot;
    $("notice").hidden = !state.message;
    $("notice").className = "notice error";
    $("notice").textContent = state.message;
    const warnings = [
      snapshot?.storage.warning,
      snapshot?.storage.persistence_error,
    ].filter(Boolean);
    $("storage-warning").hidden = !warnings.length;
    $("storage-warning").textContent = warnings.join(" ");
    $("activity").hidden = !job;
    $("activity").className = `activity ${job?.state || ""}`;
    if (job) {
      const source =
        job.trigger === "scheduled" ? "Scheduled audit" : "Manual audit";
      $("activity").textContent = active
        ? `${source} ${job.state}${job.started_at ? ` since ${date(job.started_at)}` : " — waiting for the audit worker"}. ${state.report ? "The last completed assessment remains visible." : "Results will appear when the audit completes."}`
        : job.state === "failed"
          ? `${source} failed at ${date(job.finished_at)}. ${job.error || "Please retry."} ${state.report ? "Showing the last completed assessment." : "No completed assessment is available."}`
          : `${source} completed at ${date(job.finished_at)}.`;
    }
    const schedule = snapshot?.settings.schedule;
    $("schedule-summary").textContent = schedule?.enabled
      ? `${label(schedule.frequency)} · Next ${date(snapshot.next_scheduled_run)}`
      : "Schedules disabled";
    $("next-run").textContent = schedule?.enabled
      ? `Next run: ${date(snapshot.next_scheduled_run)}`
      : "Next run: disabled";
    $("empty-state").hidden = Boolean(state.report);
    $("overview-content").hidden = !state.report || engineering;
    $("findings-content").hidden = !state.report || !engineering;
    $("engine-panel").hidden = !state.report;
    if (!state.report) {
      $("empty-title").textContent = !snapshot
        ? state.message
          ? "Workspace disconnected"
          : "Loading your workspace"
        : active
          ? "Your audit is in progress"
          : job?.state === "failed"
            ? "Audit failed"
            : snapshot.latest_report
              ? "Assessment unavailable"
              : "No assessment yet";
      $("empty-description").textContent = !snapshot
        ? state.message || "Fetching saved assessments and audit activity…"
        : active
          ? "The audit worker is examining the selected company's sources. This page will update automatically."
          : job?.state === "failed"
            ? "Check your source settings and run the audit again. Missing results never imply compliance."
            : snapshot.latest_report
              ? "The saved report could not be loaded. Retrying automatically."
              : "Run an audit to establish an evidence-based view of this company. Missing results never imply compliance.";
      return;
    }
    $("engines").innerHTML =
      Object.entries(state.report.stack_telemetry.engines || {})
        .map(
          ([key, value]) =>
            `<span>${esc(label(key))}: <strong>${esc(value)}</strong></span>`,
        )
        .join("") || "No engine telemetry recorded.";
    if (state.rendered !== state.report.report_id) {
      fillFilterOptions();
      renderFindings();
      renderOverview();
      state.rendered = state.report.report_id;
    }
    renderTrends();
  }

  function renderOverview() {
    const report = state.report;
    const all = findings();
    $("readiness").textContent = label(report.overall_readiness).replace(
      /\b\w/g,
      (char) => char.toUpperCase(),
    );
    $("readiness-note").textContent =
      report.readiness_summary || "Review the full assessment and evidence.";
    for (const [id, key] of [
      ["confirmed", buckets[0]],
      ["suspected", buckets[1]],
      ["quarantined", buckets[2]],
      ["passed", buckets[3]],
    ]) {
      $(`${id}-count`).textContent = report[key].length;
    }
    const open = all.filter((finding) => finding.status !== "PASS");
    $("open-total").textContent = `${open.length} open`;
    const counts = severityOrder.map(
      (severity) =>
        open.filter(
          (finding) => (finding.severity || "Unspecified") === severity,
        ).length,
    );
    const maximum = Math.max(...counts, 1);
    $("severity-chart").innerHTML = severityOrder
      .map(
        (severity, i) =>
          `<div class="severity-row"><span>${severity}</span><div class="bar-track"><div class="bar-fill" style="width:${(100 * counts[i]) / maximum}%;background:${["var(--critical)", "var(--high)", "var(--medium)", "var(--low)", "#7F97B2", "#7F97B2"][i]}"></div></div><strong>${counts[i]}</strong></div>`,
      )
      .join("");
    const priorities = [...open]
      .sort(
        (a, b) =>
          severityOrder.indexOf(a.severity || "Unspecified") -
            severityOrder.indexOf(b.severity || "Unspecified") ||
          String(a.due_date || "9999").localeCompare(b.due_date || "9999"),
      )
      .slice(0, 5);
    $("priorities").innerHTML =
      priorities
        .map(
          (finding, i) =>
            `<article class="priority"><span class="priority-num">${i + 1}</span><div><a class="priority-title" href="${companyUrl("findings")}&finding=${encodeURIComponent(finding.finding_id)}">${esc(finding.title)}</a><div class="priority-meta">${badge(finding.severity)}<span>${esc(finding.owner || "Owner unassigned")}</span><span>Due ${esc(finding.due_date || "not set")}</span></div><p>${esc(finding.remediation_steps?.[0] || "Review the evidence and assign remediation.")}</p></div></article>`,
        )
        .join("") ||
      '<p class="muted">No open findings in this assessment. Review coverage and scope before relying on this result.</p>';
    const coverage = Math.min(100, Math.max(0, report.input_coverage_pct));
    $("coverage-value").textContent = `${coverage}%`;
    $("coverage-bar").style.width = `${coverage}%`;
    const inputs = report.input_coverage.kinds_present || {};
    $("coverage-inputs").innerHTML =
      Object.entries(inputs)
        .map(
          ([key, present]) =>
            `<div class="coverage-row ${present ? "" : "missing"}"><span>${esc(label(key))}</span><span>${present ? "✓ Available" : "Evidence missing"}</span></div>`,
        )
        .join("") || '<p class="muted">Input coverage details unavailable.</p>';
  }

  function renderTrends() {
    const reports = state.snapshot?.trends || [];
    if (!reports.length) return;
    const series = ["confirmed", "suspected", "quarantined", "passed"];
    const maximum = Math.max(
      1,
      ...reports.flatMap((report) => series.map((key) => report.counts[key])),
    );
    const x = (i) =>
      reports.length === 1 ? 280 : 40 + (i / (reports.length - 1)) * 480;
    const y = (value) => 127 - (value / maximum) * 107;
    const grid = [0, 0.5, 1]
      .map(
        (fraction) =>
          `<line x1="40" x2="520" y1="${y(maximum * fraction)}" y2="${y(maximum * fraction)}" stroke="#CCE9FF" stroke-dasharray="3 4"/><text x="27" y="${y(maximum * fraction) + 3}" text-anchor="end" fill="#40668D" font-size="9">${Math.round(maximum * fraction)}</text>`,
      )
      .join("");
    $("trend-chart").innerHTML =
      `<svg viewBox="0 0 550 155" role="img" aria-label="Finding counts across ${reports.length} completed assessments. Exact values are in the history data table.">${grid}${series.map((key, s) => `<polyline fill="none" stroke="${colors[s]}" stroke-width="2" points="${reports.map((report, i) => `${x(i)},${y(report.counts[key])}`).join(" ")}"/>${reports.map((report, i) => `<circle cx="${x(i)}" cy="${y(report.counts[key])}" r="3" fill="${colors[s]}"><title>${esc(date(report.assessed_at))}: ${key} ${report.counts[key]}</title></circle>`).join("")}`).join("")}<text x="40" y="150" fill="#40668D" font-size="9">${esc(new Date(reports[0].assessed_at).toLocaleDateString())}</text><text x="520" y="150" text-anchor="end" fill="#40668D" font-size="9">${reports.length === 1 ? "First assessment" : esc(new Date(reports.at(-1).assessed_at).toLocaleDateString())}</text></svg>`;
    $("history-data").innerHTML = reports
      .map(
        (report) =>
          `<tr><td>${esc(date(report.assessed_at))}</td><td>${esc(label(report.overall_readiness))}</td><td>${report.input_coverage_pct}%</td>${series.map((key) => `<td>${report.counts[key]}</td>`).join("")}</tr>`,
      )
      .join("");
  }

  function fillFilterOptions() {
    const all = findings();
    const systems = new Map(
      all.map((finding) => [
        finding.system_id || "Unspecified",
        finding.system_name || finding.system_id || "Unspecified",
      ]),
    );
    for (const [id, options, first] of [
      ["filter-system", [...systems].sort(), "All systems"],
      [
        "filter-jurisdiction",
        [...new Set(all.map((finding) => finding.jurisdiction))]
          .sort()
          .map((key) => [key, label(key)]),
        "All jurisdictions",
      ],
    ]) {
      const value = $(id).value;
      $(id).innerHTML =
        `<option value="">${first}</option>` +
        options
          .map(
            ([key, text]) =>
              `<option value="${esc(key)}">${esc(text)}</option>`,
          )
          .join("");
      if (options.some(([key]) => key === value)) $(id).value = value;
    }
  }

  function renderFindings() {
    const all = findings();
    const query = $("filter-text").value.trim().toLowerCase();
    const selected = all.filter(
      (finding) =>
        (!$("filter-status").value ||
          finding.status === $("filter-status").value) &&
        (!$("filter-severity").value ||
          (finding.severity || "Unspecified") === $("filter-severity").value) &&
        (!$("filter-system").value ||
          (finding.system_id || "Unspecified") === $("filter-system").value) &&
        (!$("filter-jurisdiction").value ||
          finding.jurisdiction === $("filter-jurisdiction").value) &&
        (!query || JSON.stringify(finding).toLowerCase().includes(query)),
    );
    $("finding-count").textContent =
      `${selected.length} of ${all.length} findings`;
    const requested = new URLSearchParams(location.search).get("finding");
    $("findings-list").innerHTML =
      selected
        .map(
          (
            finding,
          ) => `<details class="panel finding" data-finding="${esc(finding.finding_id)}" ${state.expanded.has(finding.finding_id) || requested === finding.finding_id ? "open" : ""}>
      <summary><div><h3>${esc(finding.title)}</h3><div class="finding-meta">${badge(finding.status, statuses[finding.status])}<span>${esc(finding.system_name || finding.system_id || "System unspecified")}</span><span>${esc(label(finding.jurisdiction))}</span><span>${esc(finding.finding_id)}</span></div></div>${badge(finding.severity)}</summary>
      <div class="finding-body"><h4>Assessment</h4><p>${esc(finding.summary)}</p>
        <div class="detail-grid"><p><strong>Owner</strong>${esc(finding.owner || "Unassigned")}</p><p><strong>Confidence</strong>${Math.round((finding.confidence ?? finding.confidence_score) * 100)}%</p><p><strong>Due date · estimated effort</strong>${esc(finding.due_date || "Not set")} · ${finding.effort_days == null ? "Not estimated" : `${esc(finding.effort_days)} days`}</p><p><strong>History</strong>${esc(finding.history_status)} · First seen ${esc(date(finding.first_seen_at))}</p><p><strong>Primary rule</strong>${esc(finding.primary_rule || finding.regulatory_reference)}</p><p><strong>Also engages</strong>${esc(finding.also_engages.join(", ") || "None recorded")}</p></div>
        ${finding.human_review_required ? `<p class="notice warning">Human review required. ${esc(finding.human_review_reason || "")}</p>` : ""}
        ${finding.quarantine_reason ? `<h4>Quarantine reason</h4><p>${esc(finding.quarantine_reason)}</p>` : ""}
        ${finding.code_vs_doc_drift ? `<h4>Code and documentation drift</h4><p>${esc(finding.code_vs_doc_drift)}</p>` : ""}
        ${finding.exposure_text ? `<h4>Exposure</h4><p>${esc(finding.exposure_text)}</p>` : ""}
        <h4>Evidence · ${finding.evidence.length} items</h4>${finding.evidence.map((evidence) => `<article class="evidence"><strong>${esc(evidence.item || evidence.artifact_id)}</strong><p class="evidence-meta">${esc(evidence.type || evidence.source_type)} · ${esc(evidence.exact_locator)}${evidence.source_date ? ` · ${esc(evidence.source_date)}` : ""}</p><pre>${esc(evidence.snippet || evidence.linkup_snippet || "No snippet recorded. Inspect the source at the exact locator.")}</pre><p class="evidence-meta">SHA-256 <code>${esc(evidence.sha256_hash)}</code></p>${evidence.source_url ? safeLink(evidence.source_url) : ""}</article>`).join("") || '<p class="muted">No evidence attached. This result requires investigation.</p>'}
        <h4>Remediation steps</h4>${finding.remediation_steps.length ? `<ol>${finding.remediation_steps.map((step) => `<li>${esc(step)}</li>`).join("")}</ol>` : '<p class="muted">No remediation steps recorded. Assign an owner for review.</p>'}
        <h4>Regulatory citations</h4>${finding.linkup_citation_urls.map((url) => `<p>${safeLink(url)}</p>`).join("") || '<p class="muted">No verified external citation recorded.</p>'}
        ${finding.related_ids.length ? `<h4>Related findings</h4><p>${esc(finding.related_ids.join(", "))}</p>` : ""}
      </div></details>`,
        )
        .join("") ||
      '<div class="panel no-results">No findings match these filters. Try another search or clear your filters.</div>';
    for (const element of document.querySelectorAll(".finding")) {
      element.addEventListener("toggle", () => {
        if (element.open) state.expanded.add(element.dataset.finding);
        else state.expanded.delete(element.dataset.finding);
      });
    }
  }

  $("company").addEventListener("change", (event) =>
    selectCompany(event.target.value),
  );
  $("settings-form").addEventListener("input", () => {
    state.dirty = true;
    $("settings-message").textContent =
      "Unsaved changes. Save settings before running an audit.";
    render();
  });
  $("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const generation = state.generation;
    $("save-settings").disabled = true;
    try {
      await api("/settings", {
        method: "PUT",
        body: JSON.stringify({
          sources: {
            github_url: $("github-source").value,
            confluence_path: $("confluence-path").value,
            confluence_space_key: $("confluence-space").value,
          },
          schedule: {
            enabled: $("schedule-enabled").checked,
            frequency: $("schedule-frequency").value,
          },
        }),
      });
      if (generation !== state.generation) return;
      state.dirty = false;
      $("settings-message").textContent =
        "Settings saved. Manual and scheduled audits will use these sources.";
      await refresh();
    } catch (error) {
      if (generation === state.generation && error.name !== "AbortError")
        $("settings-message").textContent = error.message;
    } finally {
      if (generation === state.generation) render();
    }
  });
  $("run-audit").addEventListener("click", async () => {
    const generation = state.generation;
    $("run-audit").disabled = true;
    try {
      const job = await api("/runs", { method: "POST" });
      if (generation !== state.generation) return;
      state.snapshot.latest_job = job;
      render();
      await refresh();
    } catch (error) {
      if (generation === state.generation && error.name !== "AbortError") {
        state.message = error.message;
        render();
      }
    }
  });
  for (const element of document.querySelectorAll(
    ".filters input, .filters select",
  ))
    element.addEventListener("input", renderFindings);
  $("clear-filters").addEventListener("click", () => {
    for (const element of document.querySelectorAll(
      ".filters input, .filters select",
    ))
      element.value = "";
    renderFindings();
  });
  if (engineering) {
    document.title = "Engineering findings · Graphite";
    $("view-label").textContent = "Engineering findings";
    $("page-title").textContent = "From finding to resolution.";
    $("page-description").textContent =
      "Inspect evidence, understand exposure, and take the next step.";
  }
  $(engineering ? "findings-link" : "overview-link").classList.add("active");
  $(engineering ? "findings-link" : "overview-link").setAttribute(
    "aria-current",
    "page",
  );
  boot();
  setInterval(() => (state.company ? refresh() : boot()), 5000);
})();
