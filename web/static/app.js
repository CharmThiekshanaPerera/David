const state = {
  status: null,
  runs: [],
  selectedRunId: "",
  telemetry: null,
  settings: null,
};

const el = {
  tabs: document.getElementById("tabs"),
  globalStatus: document.getElementById("globalStatus"),
  goalInput: document.getElementById("goalInput"),
  previewMode: document.getElementById("previewMode"),
  startGoalBtn: document.getElementById("startGoalBtn"),
  stopRunBtn: document.getElementById("stopRunBtn"),
  runProgress: document.getElementById("runProgress"),
  dashboardMessage: document.getElementById("dashboardMessage"),
  statusList: document.getElementById("statusList"),
  approvalList: document.getElementById("approvalList"),
  runSearch: document.getElementById("runSearch"),
  runStatusFilter: document.getElementById("runStatusFilter"),
  refreshRunsBtn: document.getElementById("refreshRunsBtn"),
  runTableWrap: document.getElementById("runTableWrap"),
  timelineView: document.getElementById("timelineView"),
  failureExplain: document.getElementById("failureExplain"),
  diffRunId: document.getElementById("diffRunId"),
  loadDiffBtn: document.getElementById("loadDiffBtn"),
  diffView: document.getElementById("diffView"),
  factsView: document.getElementById("factsView"),
  lessonsView: document.getElementById("lessonsView"),
  memoryConflicts: document.getElementById("memoryConflicts"),
  telemetrySummary: document.getElementById("telemetrySummary"),
  durationChart: document.getElementById("durationChart"),
  refreshLogsBtn: document.getElementById("refreshLogsBtn"),
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
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok || !json.ok) {
    const msg = json?.error || json?.data?.error || `Request failed (${response.status})`;
    throw new Error(msg);
  }
  return json.data;
}

function setMessage(text) {
  el.dashboardMessage.textContent = text;
}

function setCliOutput(text) {
  el.cliOutput.textContent = text;
}

function kvList(target, entries) {
  target.innerHTML = entries
    .map(([k, v]) => `<li><span class="k">${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></li>`)
    .join("");
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

function renderStatus() {
  const s = state.status || {};
  el.globalStatus.textContent = s.status || "idle";
  el.runProgress.style.width = `${s.progress_percent || 0}%`;
  kvList(el.statusList, [
    ["State", s.status || "idle"],
    ["Model", s.selected_model || "-"],
    ["Active run", s.active_run_id || "-"],
    ["Iteration", `${s.iteration || 0} / ${s.max_iterations || 0}`],
    ["Last command", s.last_command || "-"],
    ["Latest success", fmtBool(s.latest_success)],
    ["Pending approvals", s.pending_approvals || 0],
    ["Safe mode", fmtBool(s.safe_mode)],
  ]);

  if (s.latest_message) {
    setMessage(s.latest_message);
  }
}

function renderApprovals(rows) {
  const pending = rows.filter((item) => item.status === "pending");
  if (!pending.length) {
    el.approvalList.innerHTML = '<p class="muted">No pending approvals.</p>';
    return;
  }

  el.approvalList.innerHTML = pending
    .map((item) => {
      const reasons = (item.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      return `
      <div class="approval">
        <div><strong>${escapeHtml(item.type)}</strong> · run ${escapeHtml(item.run_id)} · iteration ${escapeHtml(item.iteration)}</div>
        <ul>${reasons}</ul>
        <div class="row">
          <button data-approve-id="${escapeHtml(item.id)}" data-decision="approve">Approve</button>
          <button data-approve-id="${escapeHtml(item.id)}" data-decision="reject" class="danger">Reject</button>
        </div>
      </div>`;
    })
    .join("");

  el.approvalList.querySelectorAll("button[data-approve-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const approvalId = button.getAttribute("data-approve-id");
      const decision = button.getAttribute("data-decision");
      try {
        await api(`/api/approval/${encodeURIComponent(approvalId)}`, {
          method: "POST",
          body: JSON.stringify({ decision }),
        });
        await refreshStatus();
        await refreshApprovals();
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

  const html = `
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
          .map((row) => {
            return `<tr>
              <td><code>${escapeHtml(row.id)}</code></td>
              <td>${escapeHtml(row.mode)}</td>
              <td>${escapeHtml(row.status)}</td>
              <td>${escapeHtml(fmtDate(row.started_at))}</td>
              <td>${escapeHtml(row.regression_warning || row.message || "-")}</td>
              <td>
                <button data-run-action="view" data-run-id="${escapeHtml(row.id)}">View</button>
                <button data-run-action="retry" data-run-id="${escapeHtml(row.id)}" class="ghost">Retry</button>
                <button data-run-action="bundle" data-run-id="${escapeHtml(row.id)}" class="ghost">Bundle</button>
              </td>
            </tr>`;
          })
          .join("")}
      </tbody>
    </table>
  `;
  el.runTableWrap.innerHTML = html;

  el.runTableWrap.querySelectorAll("button[data-run-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.getAttribute("data-run-action");
      const runId = button.getAttribute("data-run-id");
      if (action === "view") {
        state.selectedRunId = runId;
        el.diffRunId.value = runId;
        await loadRun(runId);
      } else if (action === "retry") {
        try {
          const result = await api(`/api/run/${encodeURIComponent(runId)}/retry`, { method: "POST" });
          setMessage(`Retry started: ${result.run_id}`);
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
  if (!timeline.length) {
    el.timelineView.innerHTML = '<p class="muted">No timeline events.</p>';
  } else {
    el.timelineView.innerHTML = timeline
      .slice(-80)
      .reverse()
      .map((item) => {
        return `<div class="timeline-item">
          <div><strong>${escapeHtml(item.step)}</strong> · ${escapeHtml(fmtDate(item.timestamp_utc))}</div>
          <pre class="code">${escapeHtml(JSON.stringify(item.payload, null, 2))}</pre>
        </div>`;
      })
      .join("");
  }

  const meta = details.meta || {};
  el.failureExplain.textContent = meta.failure_explanation || "No failure explanation for this run.";
}

function renderDiffs(details) {
  const iterations = details.iterations || [];
  const blocks = [];
  for (const iter of iterations) {
    for (const diff of iter.diffs || []) {
      if (!diff.patch) continue;
      blocks.push(`
        <div class="diff-block">
          <div class="diff-title">Iteration ${escapeHtml(iter.iteration)} · ${escapeHtml(diff.path)} (+${escapeHtml(diff.added)} / -${escapeHtml(diff.removed)})</div>
          <pre class="code">${escapeHtml(diff.patch)}</pre>
        </div>
      `);
    }
  }
  el.diffView.innerHTML = blocks.length ? blocks.join("") : '<p class="muted">No diff artifacts found.</p>';
}

function renderMemory(data) {
  const facts = data.facts || [];
  const lessons = data.lessons || [];
  const conflicts = data.conflicts || [];

  el.factsView.innerHTML = facts
    .slice(-120)
    .reverse()
    .map(
      (f) =>
        `<div><code>${escapeHtml(f.subject)}.${escapeHtml(f.predicate)}</code> = ${escapeHtml(f.object)} <span class="muted">(${escapeHtml(f.timestamp || "")})</span></div>`
    )
    .join("");

  el.lessonsView.innerHTML = lessons
    .slice(-120)
    .reverse()
    .map(
      (l) =>
        `<div><strong>${escapeHtml(l.lesson || "")}</strong><br/><span class="muted">goal=${escapeHtml(l.goal || "")}</span></div>`
    )
    .join("");

  if (!conflicts.length) {
    el.memoryConflicts.innerHTML = '<p class="muted">No memory conflicts detected.</p>';
  } else {
    el.memoryConflicts.innerHTML = conflicts
      .map(
        (c) => `<div class="approval">
            <strong>${escapeHtml(c.subject)}.${escapeHtml(c.predicate)}</strong>
            <div>Values: ${escapeHtml((c.values || []).join(" | "))}</div>
            <div class="muted">${escapeHtml(c.warning || "")}</div>
          </div>`
      )
      .join("");
  }
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
}

function renderLogs(data) {
  const parts = [];
  Object.entries(data || {}).forEach(([name, rows]) => {
    parts.push(`=== ${name} ===`);
    for (const row of rows || []) parts.push(row);
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

async function loadRun(runId) {
  try {
    const details = await api(`/api/run/${encodeURIComponent(runId)}`);
    renderTimeline(details);
    renderDiffs(details);
    setCliOutput(JSON.stringify(details.result || {}, null, 2));
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    renderStatus();
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshApprovals() {
  try {
    const approvals = await api("/api/approvals");
    renderApprovals(approvals || []);
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshRuns() {
  try {
    const search = encodeURIComponent(el.runSearch.value.trim());
    const status = encodeURIComponent(el.runStatusFilter.value.trim());
    state.runs = await api(`/api/runs?search=${search}&status=${status}&limit=120`);
    renderRuns();
    if (state.selectedRunId) {
      await loadRun(state.selectedRunId);
    }
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshMemory() {
  try {
    const memory = await api("/api/memory");
    renderMemory(memory);
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshTelemetry() {
  try {
    const telemetry = await api("/api/telemetry/tail?limit=200");
    renderTelemetry(telemetry);
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshLogs() {
  try {
    const logs = await api("/api/logs/tail?limit=250");
    renderLogs(logs);
  } catch (err) {
    setMessage(err.message);
  }
}

async function refreshSettings() {
  try {
    const settings = await api("/api/settings");
    renderSettings(settings);
  } catch (err) {
    setMessage(err.message);
  }
}

function wireTabs() {
  el.tabs.querySelectorAll("button[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const tab = button.getAttribute("data-tab");
      el.tabs.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
      const target = document.getElementById(`tab-${tab}`);
      if (target) target.classList.add("active");
    });
  });
}

function wireActions() {
  el.startGoalBtn.addEventListener("click", async () => {
    const goal = el.goalInput.value.trim();
    if (!goal) {
      setMessage("Enter a goal first.");
      return;
    }
    try {
      const result = await api("/api/run", {
        method: "POST",
        body: JSON.stringify({ command: `/goal ${goal}`, preview: el.previewMode.checked }),
      });
      setMessage(`Run queued: ${result.run_id}`);
      await refreshRuns();
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.stopRunBtn.addEventListener("click", async () => {
    try {
      const result = await api("/api/stop", { method: "POST" });
      setMessage(result.run_id ? `Stop requested for ${result.run_id}` : "No active run");
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.refreshRunsBtn.addEventListener("click", refreshRuns);
  el.runSearch.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") refreshRuns();
  });

  el.loadDiffBtn.addEventListener("click", async () => {
    const runId = el.diffRunId.value.trim();
    if (!runId) {
      setMessage("Enter run ID.");
      return;
    }
    state.selectedRunId = runId;
    await loadRun(runId);
  });

  el.refreshLogsBtn.addEventListener("click", refreshLogs);

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
      const settings = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      renderSettings(settings);
      setMessage("Settings updated.");
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.cliSendBtn.addEventListener("click", async () => {
    const command = el.cliInput.value.trim();
    if (!command) {
      setCliOutput("Enter /goal, /ask, or /teach command.");
      return;
    }
    try {
      const result = await api("/api/run", {
        method: "POST",
        body: JSON.stringify({ command }),
      });
      setCliOutput(`queued run: ${result.run_id}`);
      await refreshRuns();
      await refreshStatus();
    } catch (err) {
      setCliOutput(err.message);
    }
  });
}

async function bootstrap() {
  wireTabs();
  wireActions();

  await Promise.all([
    refreshStatus(),
    refreshApprovals(),
    refreshRuns(),
    refreshMemory(),
    refreshTelemetry(),
    refreshLogs(),
    refreshSettings(),
  ]);

  setInterval(refreshStatus, 2000);
  setInterval(refreshApprovals, 2500);
  setInterval(refreshRuns, 3500);
  setInterval(refreshMemory, 6000);
  setInterval(refreshTelemetry, 5000);
  setInterval(refreshLogs, 5000);
}

bootstrap();
