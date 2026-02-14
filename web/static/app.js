const STAGES = ["planner", "coder", "safety", "executor", "critic", "memory"];
const STREAM_RETRY_MS = 3000;

const state = {
  status: null,
  runs: [],
  selectedRunId: localStorage.getItem("dcc_selected_run") || "",
  selectedIteration: 1,
  selectedRunDetails: null,
  selectedRunFiles: null,
  telemetry: null,
  settings: null,
  logs: null,
  approvals: [],
  csrfToken: "",
  lastCliRunId: "",
  lastNotifiedRunId: "",
  streams: {
    status: null,
    logs: null,
    run: null,
    connected: false,
  },
};

const el = {
  tabs: document.getElementById("tabs"),
  globalStatus: document.getElementById("globalStatus"),
  streamStatus: document.getElementById("streamStatus"),
  runningBanner: document.getElementById("runningBanner"),
  runningBannerText: document.getElementById("runningBannerText"),
  successBanner: document.getElementById("successBanner"),
  successBannerTitle: document.getElementById("successBannerTitle"),
  successBannerText: document.getElementById("successBannerText"),
  successOpenDetailsBtn: document.getElementById("successOpenDetailsBtn"),
  successViewFilesBtn: document.getElementById("successViewFilesBtn"),
  successDownloadBundleBtn: document.getElementById("successDownloadBundleBtn"),
  goalInput: document.getElementById("goalInput"),
  previewMode: document.getElementById("previewMode"),
  startGoalBtn: document.getElementById("startGoalBtn"),
  stopRunBtn: document.getElementById("stopRunBtn"),
  runProgress: document.getElementById("runProgress"),
  dashboardMessage: document.getElementById("dashboardMessage"),
  stageTracker: document.getElementById("stageTracker"),
  statusList: document.getElementById("statusList"),
  artifactList: document.getElementById("artifactList"),
  activityFeed: document.getElementById("activityFeed"),
  previewSummary: document.getElementById("previewSummary"),
  fileTree: document.getElementById("fileTree"),
  filePreview: document.getElementById("filePreview"),
  approvalList: document.getElementById("approvalList"),
  approvalAudit: document.getElementById("approvalAudit"),
  runSearch: document.getElementById("runSearch"),
  runStatusFilter: document.getElementById("runStatusFilter"),
  refreshRunsBtn: document.getElementById("refreshRunsBtn"),
  runTableWrap: document.getElementById("runTableWrap"),
  timelineView: document.getElementById("timelineView"),
  executionPanels: document.getElementById("executionPanels"),
  failureDetails: document.getElementById("failureDetails"),
  failureExplain: document.getElementById("failureExplain"),
  replayPrevBtn: document.getElementById("replayPrevBtn"),
  replayNextBtn: document.getElementById("replayNextBtn"),
  replayIterationLabel: document.getElementById("replayIterationLabel"),
  replayPanel: document.getElementById("replayPanel"),
  comparePanel: document.getElementById("comparePanel"),
  diffRunId: document.getElementById("diffRunId"),
  loadDiffBtn: document.getElementById("loadDiffBtn"),
  diffSummary: document.getElementById("diffSummary"),
  diffView: document.getElementById("diffView"),
  factsView: document.getElementById("factsView"),
  lessonsView: document.getElementById("lessonsView"),
  memoryConflicts: document.getElementById("memoryConflicts"),
  telemetrySummary: document.getElementById("telemetrySummary"),
  durationChart: document.getElementById("durationChart"),
  refreshLogsBtn: document.getElementById("refreshLogsBtn"),
  logsLevelFilter: document.getElementById("logsLevelFilter"),
  logsSearch: document.getElementById("logsSearch"),
  logsView: document.getElementById("logsView"),
  settingSafeMode: document.getElementById("settingSafeMode"),
  settingRateLimit: document.getElementById("settingRateLimit"),
  settingMaxIterations: document.getElementById("settingMaxIterations"),
  settingLargeEdit: document.getElementById("settingLargeEdit"),
  settingMultiFile: document.getElementById("settingMultiFile"),
  settingPreviewDefault: document.getElementById("settingPreviewDefault"),
  saveSettingsBtn: document.getElementById("saveSettingsBtn"),
  settingsInfo: document.getElementById("settingsInfo"),
  cliInput: document.getElementById("cliInput"),
  cliSendBtn: document.getElementById("cliSendBtn"),
  cliOutput: document.getElementById("cliOutput"),
  cliExecPanel: document.getElementById("cliExecPanel"),
  toastContainer: document.getElementById("toastContainer"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (method === "POST" && state.csrfToken) {
    headers["X-CSRF-Token"] = state.csrfToken;
  }

  const response = await fetch(path, { ...options, headers });
  const json = await response.json().catch(() => ({}));
  if (!response.ok || !json.ok) {
    throw new Error(json?.error || json?.data?.error || `Request failed (${response.status})`);
  }
  return json.data;
}

function setMessage(text) {
  el.dashboardMessage.textContent = text;
}

function setCliOutput(text) {
  el.cliOutput.textContent = text;
}

function fmtDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function fmtBool(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  return "-";
}

function kvList(target, entries) {
  target.innerHTML = entries
    .map(([k, v]) => `<li><span class="k">${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></li>`)
    .join("");
}

function showToast(text) {
  const node = document.createElement("div");
  node.className = "toast";
  node.textContent = text;
  el.toastContainer.appendChild(node);
  setTimeout(() => node.remove(), 4500);
}

function setStreamState(label) {
  el.streamStatus.textContent = `stream: ${label}`;
}

function renderStageTracker(currentStage) {
  el.stageTracker.innerHTML = STAGES.map((stage) => {
    const active = stage === currentStage ? "active" : "";
    return `<div class="stage ${active}">${escapeHtml(stage)}</div>`;
  }).join("");
}

function toggleRunningBanner(status) {
  const runningStates = new Set(["running", "queued", "stopping", "awaiting_approval"]);
  const isRunning = runningStates.has(status?.status);
  el.runningBanner.classList.toggle("hidden", !isRunning);
  if (isRunning) {
    el.runningBannerText.textContent = `Run ${status.active_run_id || ""} is ${status.status} (${status.current_stage || "idle"}).`;
  }
}

function updateButtonState() {
  const s = state.status || {};
  const activeState = new Set(["running", "queued", "stopping", "awaiting_approval"]).has(s.status);
  el.startGoalBtn.disabled = activeState;
  el.stopRunBtn.disabled = !s.active_run_id;
  el.refreshRunsBtn.disabled = activeState;
}

function renderStatus() {
  const s = state.status || {};
  el.globalStatus.textContent = s.status || "idle";
  el.runProgress.style.width = `${s.progress_percent || 0}%`;
  kvList(el.statusList, [
    ["State", s.status || "idle"],
    ["Current stage", s.current_stage || "idle"],
    ["Model", s.selected_model || "-"],
    ["Active run", s.active_run_id || "-"],
    ["Iteration", `${s.iteration || 0} / ${s.max_iterations || 0}`],
    ["Last command", s.last_command || "-"],
    ["Latest success", fmtBool(s.latest_success)],
    ["Pending approvals", s.pending_approvals || 0],
    ["Safe mode", fmtBool(s.safe_mode)],
  ]);

  renderStageTracker(s.current_stage || "idle");
  toggleRunningBanner(s);
  updateButtonState();
}

function renderArtifacts(details) {
  if (!details || !details.meta) {
    kvList(el.artifactList, [["Artifacts", "-"], ["Workspace", "-"]]);
    return;
  }
  kvList(el.artifactList, [
    ["Artifacts", details.artifacts_dir || details.meta.artifacts_dir || "-"],
    ["Workspace", details.workspace_dir || details.meta.workspace_dir || "-"],
  ]);
}

function renderApprovals(rows) {
  state.approvals = rows || [];
  const pending = state.approvals.filter((item) => item.status === "pending");
  if (!pending.length) {
    el.approvalList.innerHTML = '<p class="muted">No pending approvals.</p>';
    return;
  }

  el.approvalList.innerHTML = pending
    .map((item) => {
      const reasons = (item.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      const typedHint = item.requires_typed_confirmation ? `<div class="muted">Type: <code>approve ${escapeHtml(item.run_id)}</code></div>` : "";
      return `
      <div class="approval">
        <div><strong>${escapeHtml(item.type)}</strong> · run ${escapeHtml(item.run_id)} · iteration ${escapeHtml(item.iteration)}</div>
        <div class="muted">files=${escapeHtml(item.file_count || 0)} · diffs=${escapeHtml(item.diff_count || 0)}</div>
        <ul>${reasons}</ul>
        ${typedHint}
        <input data-approval-confirm="${escapeHtml(item.id)}" type="text" placeholder="typed confirmation (if required)" />
        <input data-approval-note="${escapeHtml(item.id)}" type="text" placeholder="note (optional)" />
        <div class="row">
          <button data-approve-id="${escapeHtml(item.id)}" data-run-id="${escapeHtml(item.run_id)}" data-decision="approve">Approve</button>
          <button data-approve-id="${escapeHtml(item.id)}" data-run-id="${escapeHtml(item.run_id)}" data-decision="reject" class="danger">Reject</button>
        </div>
      </div>`;
    })
    .join("");

  el.approvalList.querySelectorAll("button[data-approve-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const approvalId = button.getAttribute("data-approve-id");
      const runId = button.getAttribute("data-run-id");
      const decision = button.getAttribute("data-decision");
      const noteInput = el.approvalList.querySelector(`input[data-approval-note="${approvalId}"]`);
      const confirmInput = el.approvalList.querySelector(`input[data-approval-confirm="${approvalId}"]`);
      try {
        await api(`/api/approval/${encodeURIComponent(approvalId)}`, {
          method: "POST",
          body: JSON.stringify({ decision, note: noteInput?.value || "", actor: "local_ui", confirmation: confirmInput?.value || "" }),
        });
        showToast(`Approval ${decision}: ${approvalId}`);
        await refreshApprovals();
        if (runId) await loadAudit(runId);
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

function renderRuns() {
  const rows = state.runs;
  if (!rows.length) {
    el.runTableWrap.innerHTML = '<p class="muted">No runs yet.</p>';
    return;
  }

  const hasActive = !!state.status?.active_run_id;
  el.runTableWrap.innerHTML = `
    <table class="table">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Mode</th>
          <th>Status</th>
          <th>Started</th>
          <th>Message</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
      ${rows
        .map(
          (row) => `<tr>
            <td><code>${escapeHtml(row.id)}</code></td>
            <td>${escapeHtml(row.mode)}</td>
            <td>${escapeHtml(row.status)}</td>
            <td>${escapeHtml(fmtDate(row.started_at))}</td>
            <td>${escapeHtml(row.regression_warning || row.message || "-")}</td>
            <td>
              <button data-run-action="view" data-run-id="${escapeHtml(row.id)}">View</button>
              <button data-run-action="retry" data-run-id="${escapeHtml(row.id)}" class="ghost" ${hasActive ? "disabled" : ""}>Retry</button>
              <button data-run-action="bundle" data-run-id="${escapeHtml(row.id)}" class="ghost">Bundle</button>
            </td>
          </tr>`
        )
        .join("")}
      </tbody>
    </table>`;

  el.runTableWrap.querySelectorAll("button[data-run-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.getAttribute("data-run-action");
      const runId = button.getAttribute("data-run-id");
      if (!runId) return;
      if (action === "view") {
        state.selectedRunId = runId;
        localStorage.setItem("dcc_selected_run", runId);
        await openRunTab(runId);
      } else if (action === "retry") {
        try {
          const result = await api(`/api/run/${encodeURIComponent(runId)}/retry`, { method: "POST", body: "{}" });
          showToast(`Retry started: ${result.run_id}`);
          await refreshRuns();
        } catch (err) {
          setMessage(err.message);
        }
      } else if (action === "bundle") {
        window.location.href = `/api/run/${encodeURIComponent(runId)}/bundle`;
      }
    });
  });
}

function renderTimeline(details) {
  const timeline = details.timeline || [];
  el.timelineView.innerHTML = !timeline.length
    ? '<p class="muted">No timeline events.</p>'
    : timeline
        .slice(-80)
        .reverse()
        .map(
          (item) => `<div class="timeline-item"><div><strong>${escapeHtml(item.step)}</strong> · ${escapeHtml(fmtDate(item.timestamp_utc))}</div><pre class="code">${escapeHtml(JSON.stringify(item.payload, null, 2))}</pre></div>`
        )
        .join("");

  const meta = details.meta || {};
  el.failureExplain.textContent = meta.failure_explanation || "No failure explanation for this run.";
  renderFailureDetails(meta.failure_details || details.result?.failure_details || null);
}

function renderFailureDetails(details) {
  if (!details) {
    el.failureDetails.innerHTML = '<p class="muted">No structured failure details for this run.</p>';
    return;
  }
  const errors = (details.top_errors || []).map((line) => `<li>${escapeHtml(line)}</li>`).join("");
  const files = (details.related_files || [])
    .map((row) => `<li><code>${escapeHtml(row.path)}</code> · <code>${escapeHtml(row.vscode_command)}</code></li>`)
    .join("");
  const actions = (details.suggested_actions || []).map((a) => `<span class="badge">${escapeHtml(a)}</span>`).join(" ");
  el.failureDetails.innerHTML = `
    <div><strong>Category:</strong> ${escapeHtml(details.category || "unknown")}</div>
    <div><strong>Top errors:</strong><ul>${errors || "<li>None</li>"}</ul></div>
    <div><strong>Related files:</strong><ul>${files || "<li>None</li>"}</ul></div>
    <div><strong>Suggested actions:</strong> ${actions}</div>
  `;
}

function renderExecutionPanels(container, iterations) {
  const blocks = [];
  (iterations || []).forEach((iter) => {
    (iter.execution || []).forEach((result, idx) => {
      const key = `exec_${iter.iteration}_${idx}_${container.id}`;
      blocks.push(`
        <details class="exec-card" open>
          <summary><strong>Iteration ${escapeHtml(iter.iteration)}</strong> · ${escapeHtml(result.command || "command")}</summary>
          <div class="exec-meta">
            <span>Return code: <strong>${escapeHtml(result.returncode)}</strong></span>
            <span>Timeout: <strong>${escapeHtml(result.timed_out)}</strong></span>
            <span>Duration: <strong>${escapeHtml(result.duration_sec || 0)}s</strong></span>
          </div>
          <div class="exec-tabs">
            <button data-exec-tab="stdout" data-exec-key="${key}">stdout</button>
            <button data-exec-tab="stderr" data-exec-key="${key}">stderr</button>
            <button data-exec-tab="meta" data-exec-key="${key}">meta</button>
          </div>
          <pre id="${key}_stdout" class="code">${escapeHtml(result.stdout || "")}</pre>
          <pre id="${key}_stderr" class="code hidden">${escapeHtml(result.stderr || "")}</pre>
          <pre id="${key}_meta" class="code hidden">${escapeHtml(JSON.stringify({ returncode: result.returncode, timed_out: result.timed_out, duration_sec: result.duration_sec }, null, 2))}</pre>
        </details>
      `);
    });
  });
  container.innerHTML = blocks.length ? blocks.join("") : '<p class="muted">No execution output for this run.</p>';

  container.querySelectorAll("button[data-exec-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.getAttribute("data-exec-key");
      const tab = button.getAttribute("data-exec-tab");
      ["stdout", "stderr", "meta"].forEach((name) => {
        const node = document.getElementById(`${key}_${name}`);
        if (node) node.classList.toggle("hidden", name !== tab);
      });
    });
  });
}

function renderDiffs(details) {
  const iterations = details.iterations || [];
  let changedCount = 0;
  let createdCount = 0;
  let modifiedCount = 0;
  const blocks = [];

  for (const iter of iterations) {
    for (const diff of iter.diffs || []) {
      if (!diff.patch) continue;
      changedCount += 1;
      if (diff.change_type === "new") createdCount += 1;
      else modifiedCount += 1;
      blocks.push(`<div class="diff-block"><div class="diff-title">Iteration ${escapeHtml(iter.iteration)} · ${escapeHtml(diff.path)} (+${escapeHtml(diff.added)} / -${escapeHtml(diff.removed)}) <span class="badge ${escapeHtml(diff.change_type || "edited")}">${escapeHtml(diff.change_type || "edited")}</span></div><pre class="code">${escapeHtml(diff.patch)}</pre></div>`);
    }
  }

  el.diffSummary.textContent = `${changedCount} file diffs · ${createdCount} new · ${modifiedCount} edited`;
  el.diffView.innerHTML = blocks.length ? blocks.join("") : '<p class="muted">No diff artifacts found.</p>';
}

function renderFileTree(summary) {
  if (!summary) {
    el.previewSummary.textContent = "No preview data yet.";
    el.fileTree.innerHTML = "";
    return;
  }

  const created = summary.created || [];
  const modified = summary.modified || [];
  el.previewSummary.textContent = `${created.length + modified.length} changed files. Artifacts: ${summary.artifacts_dir}`;

  const rows = [];
  created.forEach((file) => {
    rows.push(`<button class="file-item" data-file-preview="${escapeHtml(file.path)}"><span>${escapeHtml(file.path)}</span><span class="badge new">new file</span></button>`);
  });
  modified.forEach((file) => {
    rows.push(`<button class="file-item" data-file-preview="${escapeHtml(file.path)}"><span>${escapeHtml(file.path)}</span><span class="badge edited">edited file</span></button>`);
  });
  el.fileTree.innerHTML = rows.length ? rows.join("") : '<p class="muted">No created/updated files in this run.</p>';

  el.fileTree.querySelectorAll("button[data-file-preview]").forEach((button) => {
    button.addEventListener("click", () => {
      const path = button.getAttribute("data-file-preview");
      const allFiles = [...created, ...modified];
      const match = allFiles.find((item) => item.path === path);
      el.filePreview.textContent = `${path}\n\n${match?.after_preview || ""}`;
    });
  });
}

function renderMemory(data) {
  const facts = data.facts || [];
  const lessons = data.lessons || [];
  const conflicts = data.conflicts || [];

  el.factsView.innerHTML = facts
    .slice(-120)
    .reverse()
    .map((f) => `<div><code>${escapeHtml(f.subject)}.${escapeHtml(f.predicate)}</code> = ${escapeHtml(f.object)} <span class="muted">(${escapeHtml(f.timestamp || "")})</span></div>`)
    .join("");

  el.lessonsView.innerHTML = lessons
    .slice(-120)
    .reverse()
    .map((l) => `<div><strong>${escapeHtml(l.lesson || "")}</strong><br/><span class="muted">goal=${escapeHtml(l.goal || "")}</span></div>`)
    .join("");

  el.memoryConflicts.innerHTML = !conflicts.length
    ? '<p class="muted">No memory conflicts detected.</p>'
    : conflicts.map((c) => `<div class="approval"><strong>${escapeHtml(c.subject)}.${escapeHtml(c.predicate)}</strong><div>Values: ${escapeHtml((c.values || []).join(" | "))}</div></div>`).join("");
}

function drawDurationChart(metrics) {
  const ctx = el.durationChart.getContext("2d");
  const canvas = el.durationChart;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const values = metrics.slice(-40).map((item) => Number(item.duration_sec || 0));
  if (!values.length) {
    ctx.fillStyle = "#6d757a";
    ctx.fillText("No metrics yet", 12, 22);
    return;
  }
  const max = Math.max(...values, 0.01);
  const w = canvas.width;
  const h = canvas.height;
  const pad = 20;
  const plotW = w - pad * 2;
  const plotH = h - pad * 2;
  const barW = Math.max(4, plotW / values.length - 2);
  ctx.fillStyle = "#f0e5cf";
  ctx.fillRect(pad, pad, plotW, plotH);
  values.forEach((v, idx) => {
    const x = pad + idx * (barW + 2);
    const bh = (v / max) * plotH;
    const y = pad + plotH - bh;
    ctx.fillStyle = "#157a6e";
    ctx.fillRect(x, y, barW, bh);
  });
  ctx.fillStyle = "#1c2b31";
  ctx.font = "12px IBM Plex Mono, monospace";
  ctx.fillText(`max ${max.toFixed(2)}s`, 10, 12);
}

function renderActivityFeed(events) {
  const filtered = (events || []).slice(-20).reverse();
  el.activityFeed.innerHTML = !filtered.length
    ? '<p class="muted">No activity yet.</p>'
    : filtered
        .map((event) => `<div class="timeline-item"><strong>${escapeHtml(event.event_type || event.type || "event")}</strong><div class="muted">${escapeHtml(fmtDate(event.timestamp_utc || Date.now()))}</div></div>`)
        .join("");
}

function renderTelemetry(data) {
  state.telemetry = data;
  const summary = data.summary || {};
  kvList(el.telemetrySummary, [
    ["Total iterations", summary.total_iterations || 0],
    ["Success rate", summary.success_rate ?? 0],
    ["Error frequency", summary.error_frequency ?? 0],
    ["Average duration (s)", summary.avg_duration_sec ?? 0],
    ["Regression warnings", (data.regressions || []).length],
  ]);
  drawDurationChart(data.metrics || []);
  renderActivityFeed(data.events || []);
}

function detectLogLevel(line) {
  const text = String(line || "").toLowerCase();
  if (text.includes("error") || text.includes("traceback")) return "error";
  if (text.includes("warn")) return "warn";
  return "info";
}

function renderLogs(data) {
  state.logs = data;
  const level = (el.logsLevelFilter.value || "all").toLowerCase();
  const search = (el.logsSearch.value || "").toLowerCase();
  const parts = [];

  Object.entries(data || {}).forEach(([name, rows]) => {
    parts.push(`=== ${name} ===`);
    (rows || []).forEach((row) => {
      const line = String(row);
      const lineLevel = detectLogLevel(line);
      if (level !== "all" && level !== lineLevel) return;
      if (search && !line.toLowerCase().includes(search)) return;
      parts.push(line);
    });
    parts.push("");
  });

  el.logsView.textContent = parts.join("\n");
}

function renderSettings(data) {
  state.settings = data;
  el.settingSafeMode.value = String(!!data.safe_mode);
  el.settingRateLimit.value = data.rate_limit_seconds ?? 3;
  el.settingMaxIterations.value = data.max_iterations_override ?? 0;
  el.settingLargeEdit.value = data.risky_large_edit_bytes ?? 50000;
  el.settingMultiFile.value = data.risky_multi_file_threshold ?? 4;
  el.settingPreviewDefault.checked = !!data.run_preview_default;
  kvList(el.settingsInfo, [
    ["Model", data.model || "-"],
    ["Allowed commands", (data.allowed_commands || []).join(", ")],
    ["Workspace", data.workspace_dir || "-"],
    ["Default max iterations", data.max_iterations_default || 0],
  ]);
}

function handleRunCompletionNotification() {
  const newest = state.runs[0];
  if (!newest) return;
  const terminalStatuses = new Set(["success", "preview_ready", "failed", "rejected", "stopped"]);
  if (!terminalStatuses.has(newest.status) || state.lastNotifiedRunId === newest.id) return;

  state.lastNotifiedRunId = newest.id;
  const success = newest.status === "success" || newest.status === "preview_ready";
  if (success) {
    el.successBanner.classList.remove("hidden");
    el.successBannerTitle.textContent = newest.status === "preview_ready" ? "Successful Preview" : "✅ Run completed";
    el.successBannerText.textContent = newest.status === "preview_ready" ? "Preview generated successfully." : "✅ Run completed: tests passed.";
    showToast(`Run completed: ${newest.id}`);
  } else {
    el.successBanner.classList.add("hidden");
    showToast(`Run ended: ${newest.status} (${newest.id})`);
  }

  el.successOpenDetailsBtn.onclick = async () => {
    state.selectedRunId = newest.id;
    localStorage.setItem("dcc_selected_run", newest.id);
    await openRunTab(newest.id);
  };
  el.successViewFilesBtn.onclick = async () => {
    state.selectedRunId = newest.id;
    localStorage.setItem("dcc_selected_run", newest.id);
    await openDiffTab(newest.id);
  };
  el.successDownloadBundleBtn.onclick = () => {
    window.location.href = `/api/run/${encodeURIComponent(newest.id)}/bundle`;
  };
}

async function loadReplay(runId, iteration) {
  try {
    const replay = await api(`/api/run/${encodeURIComponent(runId)}/replay?iteration=${encodeURIComponent(iteration)}`);
    state.selectedIteration = replay.iteration;
    el.replayIterationLabel.textContent = `Iteration ${replay.iteration} / ${replay.total_iterations}`;
    el.replayPrevBtn.disabled = !replay.has_prev;
    el.replayNextBtn.disabled = !replay.has_next;
    el.replayPanel.textContent = JSON.stringify(replay.current, null, 2);
    el.comparePanel.textContent = JSON.stringify(replay.comparison || {}, null, 2);
  } catch (err) {
    el.replayPanel.textContent = err.message;
  }
}

async function loadAudit(runId) {
  try {
    const audit = await api(`/api/run/${encodeURIComponent(runId)}/audit?limit=300`);
    el.approvalAudit.textContent = JSON.stringify(audit, null, 2);
  } catch (err) {
    el.approvalAudit.textContent = err.message;
  }
}

async function loadRun(runId) {
  try {
    const details = await api(`/api/run/${encodeURIComponent(runId)}`);
    const files = await api(`/api/run/${encodeURIComponent(runId)}/files`);
    state.selectedRunDetails = details;
    state.selectedRunFiles = files;

    renderTimeline(details);
    renderExecutionPanels(el.executionPanels, details.iterations || []);
    renderDiffs(details);
    renderArtifacts(details);
    renderFileTree(files);
    await loadReplay(runId, state.selectedIteration || 1);
    await loadAudit(runId);

    if (state.lastCliRunId === runId) {
      setCliOutput(JSON.stringify(details.result || {}, null, 2));
      renderExecutionPanels(el.cliExecPanel, details.iterations || []);
    }
  } catch (err) {
    setMessage(err.message);
  }
}

async function openRunTab(runId) {
  activateTab("runs");
  el.diffRunId.value = runId;
  await loadRun(runId);
}

async function openDiffTab(runId) {
  activateTab("diff");
  el.diffRunId.value = runId;
  await loadRun(runId);
}

async function refreshStatus() {
  state.status = await api("/api/status");
  state.csrfToken = state.status.csrf_token || state.csrfToken;
  renderStatus();
}

async function refreshApprovals() {
  const approvals = await api("/api/approvals");
  renderApprovals(approvals || []);
}

async function refreshRuns() {
  const search = encodeURIComponent(el.runSearch.value.trim());
  const status = encodeURIComponent(el.runStatusFilter.value.trim());
  state.runs = await api(`/api/runs?search=${search}&status=${status}&limit=120`);
  renderRuns();
  handleRunCompletionNotification();
  if (state.selectedRunId) await loadRun(state.selectedRunId);
}

async function refreshMemory() {
  renderMemory(await api("/api/memory"));
}

async function refreshTelemetry() {
  renderTelemetry(await api("/api/telemetry/tail?limit=250"));
}

async function refreshLogs() {
  renderLogs(await api("/api/logs/tail?limit=400"));
}

async function refreshSettings() {
  renderSettings(await api("/api/settings"));
}

function activateTab(tab) {
  el.tabs.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
  const button = el.tabs.querySelector(`button[data-tab="${tab}"]`);
  if (button) button.classList.add("active");
  const target = document.getElementById(`tab-${tab}`);
  if (target) target.classList.add("active");
}

function setupRunStream(runId) {
  if (!window.EventSource || !runId) return;
  if (state.streams.run) {
    state.streams.run.close();
  }
  const runSource = new EventSource(`/api/stream/run/${encodeURIComponent(runId)}`);
  state.streams.run = runSource;

  runSource.onmessage = () => {};
  runSource.addEventListener("run", () => {
    loadRun(runId).catch(() => {});
  });
  runSource.addEventListener("run_tail", () => {
    loadRun(runId).catch(() => {});
  });
  runSource.onerror = () => {
    setStreamState("reconnecting");
  };
}

function setupSSE() {
  if (!window.EventSource) {
    setStreamState("polling fallback");
    return;
  }

  const statusSource = new EventSource("/api/stream/status");
  const logsSource = new EventSource("/api/stream/logs");
  state.streams.status = statusSource;
  state.streams.logs = logsSource;

  statusSource.addEventListener("connected", (event) => {
    setStreamState("connected");
    state.streams.connected = true;
    try {
      const data = JSON.parse(event.data || "{}");
      if (data.csrf_token) state.csrfToken = data.csrf_token;
    } catch (_) {}
  });

  statusSource.addEventListener("status", async (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      if (payload?.meta) {
        state.status = payload.meta;
        renderStatus();
      }
      if (payload?.run_id && payload.run_id === state.selectedRunId) {
        await loadRun(payload.run_id);
      }
    } catch (_) {}
  });

  statusSource.onerror = () => {
    setStreamState("reconnecting");
    state.streams.connected = false;
  };

  logsSource.addEventListener("connected", () => setStreamState("connected"));
  logsSource.addEventListener("logs_snapshot", (event) => {
    try {
      const payload = JSON.parse(event.data || "{}");
      renderLogs(payload.snapshot || {});
    } catch (_) {}
  });
  logsSource.onerror = () => setStreamState("reconnecting");
}

function wireTabs() {
  el.tabs.querySelectorAll("button[data-tab]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.getAttribute("data-tab")));
  });
}

function wireActions() {
  el.startGoalBtn.addEventListener("click", async () => {
    const goal = el.goalInput.value.trim();
    if (!goal) return setMessage("Enter a goal first.");
    try {
      const result = await api("/api/run", { method: "POST", body: JSON.stringify({ command: `/goal ${goal}`, preview: el.previewMode.checked }) });
      state.selectedRunId = result.run_id;
      localStorage.setItem("dcc_selected_run", result.run_id);
      setupRunStream(result.run_id);
      showToast(`Run started: ${result.run_id}`);
      await refreshRuns();
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.stopRunBtn.addEventListener("click", async () => {
    try {
      const result = await api("/api/stop", { method: "POST", body: "{}" });
      showToast(result.run_id ? `Stop requested: ${result.run_id}` : "No active run");
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.refreshRunsBtn.addEventListener("click", () => refreshRuns().catch((e) => setMessage(e.message)));
  el.runSearch.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") refreshRuns().catch((e) => setMessage(e.message));
  });

  el.loadDiffBtn.addEventListener("click", async () => {
    const runId = el.diffRunId.value.trim();
    if (!runId) return setMessage("Enter run ID.");
    state.selectedRunId = runId;
    localStorage.setItem("dcc_selected_run", runId);
    setupRunStream(runId);
    await loadRun(runId);
  });

  el.refreshLogsBtn.addEventListener("click", () => refreshLogs().catch((e) => setMessage(e.message)));
  el.logsSearch.addEventListener("input", () => renderLogs(state.logs || {}));
  el.logsLevelFilter.addEventListener("change", () => renderLogs(state.logs || {}));

  el.saveSettingsBtn.addEventListener("click", async () => {
    try {
      const payload = {
        safe_mode: el.settingSafeMode.value === "true",
        rate_limit_seconds: Number(el.settingRateLimit.value || 0),
        max_iterations_override: Number(el.settingMaxIterations.value || 0),
        risky_large_edit_bytes: Number(el.settingLargeEdit.value || 50000),
        risky_multi_file_threshold: Number(el.settingMultiFile.value || 4),
        run_preview_default: !!el.settingPreviewDefault.checked,
      };
      renderSettings(await api("/api/settings", { method: "POST", body: JSON.stringify(payload) }));
      showToast("Settings saved.");
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.cliSendBtn.addEventListener("click", async () => {
    const command = el.cliInput.value.trim();
    if (!command) return setCliOutput("Enter /goal, /ask, or /teach command.");
    try {
      const result = await api("/api/run", { method: "POST", body: JSON.stringify({ command }) });
      state.lastCliRunId = result.run_id;
      state.selectedRunId = result.run_id;
      localStorage.setItem("dcc_selected_run", result.run_id);
      setupRunStream(result.run_id);
      setCliOutput(`queued run: ${result.run_id}`);
      await refreshRuns();
      await refreshStatus();
    } catch (err) {
      setCliOutput(err.message);
    }
  });

  el.replayPrevBtn.addEventListener("click", async () => {
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, Math.max(1, state.selectedIteration - 1));
  });

  el.replayNextBtn.addEventListener("click", async () => {
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, state.selectedIteration + 1);
  });
}

async function bootstrap() {
  wireTabs();
  wireActions();

  try {
    await Promise.all([refreshStatus(), refreshApprovals(), refreshRuns(), refreshMemory(), refreshTelemetry(), refreshLogs(), refreshSettings()]);
    if (state.selectedRunId) {
      setupRunStream(state.selectedRunId);
      await loadRun(state.selectedRunId);
    }
  } catch (err) {
    setMessage(err.message);
  }

  setupSSE();
  setInterval(async () => {
    if (!state.streams.connected) {
      setStreamState("polling fallback");
      try {
        await Promise.all([refreshStatus(), refreshRuns(), refreshApprovals(), refreshLogs()]);
      } catch (_) {}
      setupSSE();
    }
  }, STREAM_RETRY_MS);

  setInterval(() => refreshMemory().catch(() => {}), 6000);
  setInterval(() => refreshTelemetry().catch(() => {}), 5000);
}

bootstrap();
