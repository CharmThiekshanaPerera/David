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
  models: [],
  goalTemplates: [],
  selectedCliTemplateId: "",
  pendingGoalRunOptions: {
    tddMode: false,
  },
  pendingCliRunOptions: {
    templateId: "",
    tddMode: false,
  },
  chatMode: "auto",
  chatMessages: [],
  pendingTeachMessage: "",
  memoryData: null,
  memoryEventKeys: [],
  workspaceTargets: [],
  selectedGoalWorkspacePath: "",
  goalRunScope: "new",
  workspaceTargetsTruncated: false,
  previewTreeQuery: "",
  previewTreeExpandAll: false,
  theme: localStorage.getItem("dcc_theme") === "light" ? "light" : "dark",
  bgDisabled: localStorage.getItem("dcc_bg_disabled") === "1",
  reducedMotion: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
};

const el = {
  tabs: document.getElementById("tabs"),
  globalStatus: document.getElementById("globalStatus"),
  streamStatus: document.getElementById("streamStatus"),
  streamStatusText: document.getElementById("streamStatusText"),
  runningBanner: document.getElementById("runningBanner"),
  runningBannerText: document.getElementById("runningBannerText"),
  successBanner: document.getElementById("successBanner"),
  successBannerTitle: document.getElementById("successBannerTitle"),
  successBannerText: document.getElementById("successBannerText"),
  successOpenDetailsBtn: document.getElementById("successOpenDetailsBtn"),
  successViewFilesBtn: document.getElementById("successViewFilesBtn"),
  successDownloadBundleBtn: document.getElementById("successDownloadBundleBtn"),
  goalInput: document.getElementById("goalInput"),
  goalScopeNewBtn: document.getElementById("goalScopeNewBtn"),
  goalScopeTargetBtn: document.getElementById("goalScopeTargetBtn"),
  goalScopeHint: document.getElementById("goalScopeHint"),
  goalWorkspaceTargetSelect: document.getElementById("goalWorkspaceTargetSelect"),
  refreshWorkspaceTargetsBtn: document.getElementById("refreshWorkspaceTargetsBtn"),
  goalWorkspaceTargetHint: document.getElementById("goalWorkspaceTargetHint"),
  previewMode: document.getElementById("previewMode"),
  goalTddMode: document.getElementById("goalTddMode"),
  runConfigSummary: document.getElementById("runConfigSummary"),
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
  settingPlannerModel: document.getElementById("settingPlannerModel"),
  settingCoderModel: document.getElementById("settingCoderModel"),
  settingCriticModel: document.getElementById("settingCriticModel"),
  settingTddMode: document.getElementById("settingTddMode"),
  refreshModelsBtn: document.getElementById("refreshModelsBtn"),
  saveSettingsBtn: document.getElementById("saveSettingsBtn"),
  settingsInfo: document.getElementById("settingsInfo"),
  themeDarkBtn: document.getElementById("themeDarkBtn"),
  themeLightBtn: document.getElementById("themeLightBtn"),
  bgToggleInput: document.getElementById("bgToggleInput"),
  resetAppearanceBtn: document.getElementById("resetAppearanceBtn"),
  chatModeAutoBtn: document.getElementById("chatModeAutoBtn"),
  chatModeAskBtn: document.getElementById("chatModeAskBtn"),
  chatModeTeachBtn: document.getElementById("chatModeTeachBtn"),
  memoryChatInput: document.getElementById("memoryChatInput"),
  cliTemplateSelect: document.getElementById("cliTemplateSelect"),
  cliTddMode: document.getElementById("cliTddMode"),
  cliSendBtn: document.getElementById("cliSendBtn"),
  memoryConfirmTeachBtn: document.getElementById("memoryConfirmTeachBtn"),
  memoryClearHistoryBtn: document.getElementById("memoryClearHistoryBtn"),
  memoryChatHistory: document.getElementById("memoryChatHistory"),
  memoryChatSearch: document.getElementById("memoryChatSearch"),
  memoryChatRefreshBtn: document.getElementById("memoryChatRefreshBtn"),
  memoryChatFacts: document.getElementById("memoryChatFacts"),
  cliOutput: document.getElementById("cliOutput"),
  cliExecPanel: document.getElementById("cliExecPanel"),
  toastContainer: document.getElementById("toastContainer"),
  heroParticles: document.getElementById("heroParticles"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function normalizePath(value) {
  return String(value || "")
    .replaceAll("\\", "/")
    .replace(/^\/+/, "")
    .replace(/\/+/g, "/");
}

function toWorkspaceRelativePath(workspacePath, workspaceRoot) {
  const fullPath = normalizePath(workspacePath);
  const root = normalizePath(workspaceRoot);
  if (!fullPath || !root) return "";
  if (fullPath === root) return "";
  if (fullPath.startsWith(`${root}/`)) {
    return fullPath.slice(root.length + 1);
  }
  return "";
}

function collectChangedPathSet(rows, workspaceRoot) {
  const out = new Set();
  (rows || []).forEach((row) => {
    const relPath = normalizePath(row?.path || "");
    if (relPath) out.add(relPath);
    const workspaceRel = toWorkspaceRelativePath(row?.workspace_path || "", workspaceRoot);
    if (workspaceRel) out.add(workspaceRel);
  });
  return out;
}

function buildWorkspaceFileTree(files, dirs = []) {
  const root = { dirs: new Map(), files: [] };
  const ensureDir = (dirPath) => {
    const normalized = normalizePath(dirPath);
    if (!normalized) return root;
    const parts = normalized.split("/").filter(Boolean);
    let node = root;
    parts.forEach((segment) => {
      if (!node.dirs.has(segment)) {
        node.dirs.set(segment, { name: segment, dirs: new Map(), files: [] });
      }
      node = node.dirs.get(segment);
    });
    return node;
  };

  (dirs || []).forEach((dirPath) => {
    ensureDir(dirPath);
  });

  (files || []).forEach((row) => {
    const relPath = normalizePath(row?.path || "");
    if (!relPath) return;
    const parts = relPath.split("/").filter(Boolean);
    if (!parts.length) return;
    const parent = parts.slice(0, -1).join("/");
    const node = ensureDir(parent);
    node.files.push({
      name: parts[parts.length - 1],
      path: relPath,
      after_preview: String(row?.after_preview || ""),
    });
  });
  return root;
}

function parentPath(path) {
  const normalized = normalizePath(path);
  if (!normalized.includes("/")) return "";
  return normalized.slice(0, normalized.lastIndexOf("/"));
}

function basename(path) {
  const normalized = normalizePath(path);
  if (!normalized) return "";
  const parts = normalized.split("/");
  return parts[parts.length - 1];
}

function pathMatchesQuery(path, query) {
  const cleanPath = normalizePath(path).toLowerCase();
  const cleanQuery = String(query || "").trim().toLowerCase();
  if (!cleanQuery) return true;
  return cleanPath.includes(cleanQuery);
}

function renderFileItemRow(path, label, badgeClass, badgeText, includeActions = true, actionPath = "") {
  const filePathForAction = normalizePath(actionPath || path);
  const actions = includeActions
    ? `<div class="file-actions"><button type="button" class="btn-subtle file-action-btn" data-file-action="edit" data-file-path="${escapeHtml(
        filePathForAction
      )}">Edit</button><button type="button" class="btn-subtle file-action-btn danger-lite" data-file-action="delete" data-file-path="${escapeHtml(
        filePathForAction
      )}">Delete</button></div>`
    : "";
  return `<div class="file-row"><button class="file-item" data-file-preview="${escapeHtml(path)}"><span class="file-label"><span class="file-name">${escapeHtml(
    label
  )}</span><span class="file-path-inline">${escapeHtml(path)}</span></span><span class="badge ${badgeClass}">${escapeHtml(
    badgeText
  )}</span></button>${actions}</div>`;
}

function renderWorkspaceFileTree(node, createdSet, modifiedSet, query = "", openDepth = 1, depth = 0, parent = "") {
  const folderRows = Array.from(node.dirs.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, child]) => {
      const folderPath = parent ? `${parent}/${name}` : name;
      const childResult = renderWorkspaceFileTree(
        child,
        createdSet,
        modifiedSet,
        query,
        openDepth,
        depth + 1,
        folderPath
      );
      const folderMatched = pathMatchesQuery(`${folderPath}/`, query) || childResult.hasMatch;
      if (!folderMatched) return "";
      const open = state.previewTreeExpandAll || query || depth < openDepth ? " open" : "";
      return `<details class="file-folder"${open}><summary><span class="folder-name">${escapeHtml(
        name
      )}/</span><span class="folder-path-inline">${escapeHtml(folderPath)}/</span></summary><div class="folder-tools"><button type="button" class="btn-subtle folder-action-btn" data-folder-action="rename" data-folder-path="${escapeHtml(
        folderPath
      )}">Rename</button><button type="button" class="btn-subtle folder-action-btn danger-lite" data-folder-action="delete" data-folder-path="${escapeHtml(
        folderPath
      )}">Delete</button></div><div class="file-children">${childResult.html}</div></details>`;
    });

  const fileRows = node.files
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((row) => {
      if (!pathMatchesQuery(row.path, query)) return "";
      let badgeClass = "workspace";
      let badgeText = "workspace";
      if (createdSet.has(row.path)) {
        badgeClass = "new";
        badgeText = "new file";
      } else if (modifiedSet.has(row.path)) {
        badgeClass = "edited";
        badgeText = "edited file";
      }
      return renderFileItemRow(row.path, row.name, badgeClass, badgeText, true);
    });

  const html = [...folderRows.filter(Boolean), ...fileRows.filter(Boolean)].join("");
  return { html, hasMatch: html.length > 0 };
}

async function refreshSelectedRunFiles() {
  if (!state.selectedRunId) return;
  const files = await api(`/api/run/${encodeURIComponent(state.selectedRunId)}/files`);
  state.selectedRunFiles = files;
  renderFileTree(files);
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

function setChatMode(mode) {
  const normalized = mode === "ask" || mode === "teach" ? mode : "auto";
  state.chatMode = normalized;
  const rows = [
    [el.chatModeAutoBtn, normalized === "auto"],
    [el.chatModeAskBtn, normalized === "ask"],
    [el.chatModeTeachBtn, normalized === "teach"],
  ];
  rows.forEach(([node, active]) => {
    if (!node) return;
    node.classList.toggle("active", !!active);
    node.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function inferChatRequest(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return null;

  if (text.startsWith("/ask ")) return { mode: "ask", payload: text.slice(5).trim(), command: text };
  if (text.startsWith("/teach ")) return { mode: "teach", payload: text.slice(7).trim(), command: text };
  if (text.startsWith("/goal ")) return { mode: "goal", payload: text.slice(6).trim(), command: text };
  if (text.startsWith("/")) return { mode: "unknown", payload: text, command: text };

  if (state.chatMode === "ask") return { mode: "ask", payload: text, command: `/ask ${text}` };
  if (state.chatMode === "teach") return { mode: "teach", payload: text, command: `/teach ${text}` };

  const askLike = text.endsWith("?") || /^(who|what|when|where|why|how|is|are|can|do|does|did|which)\b/i.test(text);
  const mode = askLike ? "ask" : "teach";
  return { mode, payload: text, command: `/${mode} ${text}` };
}

function pushChatMessage(kind, text, meta = {}) {
  state.chatMessages.push({
    kind: String(kind || "system"),
    text: String(text || ""),
    meta,
    timestamp_utc: new Date().toISOString(),
  });
  if (state.chatMessages.length > 120) {
    state.chatMessages.splice(0, state.chatMessages.length - 120);
  }
  renderChatHistory();
}

function renderChatHistory() {
  if (!el.memoryChatHistory) return;
  if (!state.chatMessages.length) {
    el.memoryChatHistory.innerHTML = '<div class="muted">No messages yet. Ask a question or teach a fact.</div>';
    return;
  }

  const labels = {
    user: "You",
    ask: "Ask Answer",
    teach: "Teach Summary",
    conflict: "Conflict Warning",
    system: "System",
  };

  el.memoryChatHistory.innerHTML = state.chatMessages
    .map((row) => {
      const kind = row.kind || "system";
      const label = labels[kind] || "Message";
      const timestamp = fmtDate(row.timestamp_utc);
      const conflictRows = Array.isArray(row.meta?.conflicts) ? row.meta.conflicts : [];
      const conflictHtml = conflictRows.length
        ? `<ul>${conflictRows
            .map(
              (item) =>
                `<li><code>${escapeHtml(item.subject)}.${escapeHtml(item.predicate)}</code>: <strong>${escapeHtml(
                  item.existing
                )}</strong> -> <strong>${escapeHtml(item.incoming)}</strong></li>`
            )
            .join("")}</ul>`
        : "";
      return `
        <div class="chat-bubble ${escapeHtml(kind)}">
          <div class="chat-meta">${escapeHtml(label)} · ${escapeHtml(timestamp)}</div>
          <div class="chat-text">${escapeHtml(row.text)}</div>
          ${conflictHtml}
        </div>
      `;
    })
    .join("");

  el.memoryChatHistory.scrollTop = el.memoryChatHistory.scrollHeight;
}

function memoryEventKey(eventType, payload) {
  const mode = payload?.mode || "";
  const stamp = payload?.timestamp_utc || "";
  const actor = payload?.actor || "";
  const marker = payload?.question || payload?.message || payload?.answer || "";
  return `${String(eventType || "")}::${String(mode)}::${String(stamp)}::${String(actor)}::${String(marker)}`;
}

function rememberMemoryEvent(eventType, payload) {
  const key = memoryEventKey(eventType, payload);
  if (!key) return;
  state.memoryEventKeys.push(key);
  if (state.memoryEventKeys.length > 300) {
    state.memoryEventKeys.splice(0, state.memoryEventKeys.length - 300);
  }
}

function hasSeenMemoryEvent(eventType, payload) {
  const key = memoryEventKey(eventType, payload);
  return state.memoryEventKeys.includes(key);
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

function findTemplate(templateId) {
  if (!templateId) return null;
  return (state.goalTemplates || []).find((item) => item.id === templateId) || null;
}

function setSelectOptions(selectNode, values, selectedValue, includeEmptyLabel = "") {
  if (!selectNode) return;
  const rows = [];
  if (includeEmptyLabel) {
    rows.push(`<option value="">${escapeHtml(includeEmptyLabel)}</option>`);
  }
  (values || []).forEach((value) => {
    const selected = String(value) === String(selectedValue) ? " selected" : "";
    rows.push(`<option value="${escapeHtml(value)}"${selected}>${escapeHtml(value)}</option>`);
  });
  selectNode.innerHTML = rows.join("");
}

function renderTemplateSelects() {
  const templates = state.goalTemplates || [];
  const cliRows = ['<option value="">No template</option>'];
  templates.forEach((tpl) => {
    const label = `${tpl.name} - ${tpl.description}`;
    cliRows.push(`<option value="${escapeHtml(tpl.id)}">${escapeHtml(label)}</option>`);
  });
  if (el.cliTemplateSelect) {
    el.cliTemplateSelect.innerHTML = cliRows.join("");
    el.cliTemplateSelect.value = state.selectedCliTemplateId || "";
  }
}

function findWorkspaceTarget(path) {
  const normalized = normalizePath(path);
  if (!normalized) return null;
  return (state.workspaceTargets || []).find((item) => normalizePath(item.path) === normalized) || null;
}

function setGoalRunScope(scope) {
  const normalized = scope === "target" ? "target" : "new";
  state.goalRunScope = normalized;

  const rows = [
    [el.goalScopeNewBtn, normalized === "new"],
    [el.goalScopeTargetBtn, normalized === "target"],
  ];
  rows.forEach(([node, active]) => {
    if (!node) return;
    node.classList.toggle("active", !!active);
    node.setAttribute("aria-pressed", active ? "true" : "false");
  });

  if (el.goalScopeHint) {
    el.goalScopeHint.textContent =
      normalized === "target"
        ? "Update Selected mode runs the goal against the selected workspace folder or file."
        : "New Goal mode creates and runs in a new project under workspace/projects.";
  }
  if (el.goalWorkspaceTargetSelect) {
    el.goalWorkspaceTargetSelect.disabled = normalized !== "target";
  }
  if (el.startGoalBtn) {
    el.startGoalBtn.textContent = normalized === "target" ? "Start Targeted Goal" : "Start New Goal";
  }
  renderWorkspaceTargetHint();
}

function collectWorkspaceTargets(entries) {
  const folderSet = new Set();
  const fileSet = new Set();

  (entries || []).forEach((item) => {
    const path = normalizePath(item?.path || "");
    if (!path) return;
    const type = String(item?.type || "file") === "folder" ? "folder" : "file";
    if (type === "folder") {
      folderSet.add(path);
      return;
    }
    fileSet.add(path);
    const parts = path.split("/");
    for (let idx = 1; idx < parts.length; idx += 1) {
      const parent = parts.slice(0, idx).join("/");
      if (parent) folderSet.add(parent);
    }
  });

  const folderRows = Array.from(folderSet)
    .sort((a, b) => a.localeCompare(b))
    .map((path) => ({ path, type: "folder" }));
  const fileRows = Array.from(fileSet)
    .sort((a, b) => a.localeCompare(b))
    .map((path) => ({ path, type: "file" }));
  return [...folderRows, ...fileRows];
}

function renderWorkspaceTargetHint() {
  if (!el.goalWorkspaceTargetHint) return;
  if (state.goalRunScope !== "target") {
    el.goalWorkspaceTargetHint.textContent = "Target is optional in New Goal mode and is ignored when starting.";
    return;
  }
  const selectedPath = normalizePath(el.goalWorkspaceTargetSelect?.value || state.selectedGoalWorkspacePath || "");
  if (!selectedPath) {
    el.goalWorkspaceTargetHint.textContent = "Select a workspace folder or file to run a targeted goal.";
    return;
  }
  const target = findWorkspaceTarget(selectedPath);
  if (!target) {
    el.goalWorkspaceTargetHint.textContent = `Selected path: ${selectedPath}. It will be validated when the run starts.`;
    return;
  }
  if (target.type === "file") {
    el.goalWorkspaceTargetHint.textContent = `Selected file: ${selectedPath}. Goal runs in its parent folder and focuses this file.`;
    return;
  }
  el.goalWorkspaceTargetHint.textContent = `Selected folder: ${selectedPath}. Goal runs inside this folder tree.`;
}

function renderWorkspaceTargetOptions() {
  if (!el.goalWorkspaceTargetSelect) return;
  const currentSelection = normalizePath(el.goalWorkspaceTargetSelect.value || state.selectedGoalWorkspacePath || "");
  const folders = (state.workspaceTargets || []).filter((item) => item.type === "folder");
  const files = (state.workspaceTargets || []).filter((item) => item.type === "file");
  const rows = ['<option value="">No target (create new project)</option>'];
  if (folders.length) {
    rows.push('<optgroup label="Folders">');
    folders.forEach((item) => {
      const path = normalizePath(item.path);
      if (!path) return;
      const selected = currentSelection === path ? " selected" : "";
      rows.push(`<option value="${escapeHtml(path)}"${selected}>${escapeHtml(`${path}/`)}</option>`);
    });
    rows.push("</optgroup>");
  }
  if (files.length) {
    rows.push('<optgroup label="Files">');
    files.forEach((item) => {
      const path = normalizePath(item.path);
      if (!path) return;
      const selected = currentSelection === path ? " selected" : "";
      rows.push(`<option value="${escapeHtml(path)}"${selected}>${escapeHtml(path)}</option>`);
    });
    rows.push("</optgroup>");
  }
  el.goalWorkspaceTargetSelect.innerHTML = rows.join("");
  if (currentSelection) {
    el.goalWorkspaceTargetSelect.value = currentSelection;
  }
  state.selectedGoalWorkspacePath = normalizePath(el.goalWorkspaceTargetSelect.value || "");
  renderWorkspaceTargetHint();
}

async function refreshWorkspaceTargets() {
  const payload = await api("/api/workspace/tree?limit=50000");
  const rows = Array.isArray(payload.entries) ? payload.entries : [];
  state.workspaceTargets = collectWorkspaceTargets(rows);
  state.workspaceTargetsTruncated = !!payload.truncated;
  renderWorkspaceTargetOptions();
}

function refreshRunOptionSummary() {
  if (!state.settings || !el.runConfigSummary) return;
  const planner = el.settingPlannerModel?.value || state.settings.planner_model || state.settings.planner_model_default || "-";
  const coder = el.settingCoderModel?.value || state.settings.coder_model || state.settings.coder_model_default || "-";
  const critic = el.settingCriticModel?.value || state.settings.critic_model || state.settings.critic_model_default || "-";
  const tdd = !!el.goalTddMode?.checked;
  renderRunConfigSummary(planner, coder, critic, tdd);
}

async function refreshModelOptions() {
  try {
    const payload = await api("/api/models");
    state.models = Array.isArray(payload.models) ? payload.models : [];
  } catch (_) {
    state.models = [];
  }
}

function applyTheme(theme, persist = true) {
  const normalized = theme === "light" ? "light" : "dark";
  state.theme = normalized;
  document.documentElement.setAttribute("data-theme", normalized);
  if (persist) {
    localStorage.setItem("dcc_theme", normalized);
  }
  if (el.themeDarkBtn && el.themeLightBtn) {
    el.themeDarkBtn.classList.toggle("active", normalized === "dark");
    el.themeLightBtn.classList.toggle("active", normalized === "light");
    el.themeDarkBtn.setAttribute("aria-pressed", normalized === "dark" ? "true" : "false");
    el.themeLightBtn.setAttribute("aria-pressed", normalized === "light" ? "true" : "false");
  }
}

function applyBackgroundPreference() {
  const disabled = localStorage.getItem("dcc_bg_disabled") === "1";
  state.bgDisabled = disabled;
  document.body.classList.toggle("no-bg", disabled);
  if (el.bgToggleInput) {
    el.bgToggleInput.checked = !disabled;
  }
}

function setBackgroundEnabled(enabled) {
  if (enabled) {
    localStorage.removeItem("dcc_bg_disabled");
  } else {
    localStorage.setItem("dcc_bg_disabled", "1");
  }
  applyBackgroundPreference();
}

function resetAppearance() {
  localStorage.removeItem("dcc_theme");
  localStorage.removeItem("dcc_bg_disabled");
  applyTheme("dark", false);
  applyBackgroundPreference();
  showToast("Appearance reset to defaults.");
}

function setStreamState(label) {
  const normalized = String(label || "polling fallback").toLowerCase();
  el.streamStatus.classList.remove("connected", "reconnecting", "fallback");
  if (normalized === "connected") {
    el.streamStatus.classList.add("connected");
  } else if (normalized.includes("reconnect") || normalized.includes("connecting")) {
    el.streamStatus.classList.add("reconnecting");
  } else {
    el.streamStatus.classList.add("fallback");
  }
  if (el.streamStatusText) {
    el.streamStatusText.textContent = normalized;
  } else {
    el.streamStatus.textContent = `stream: ${normalized}`;
  }
}

function renderRunConfigSummary(planner, coder, critic, tdd) {
  if (!el.runConfigSummary) return;
  el.runConfigSummary.innerHTML = `
    <span class="run-config-pill">Planner: ${escapeHtml(planner || "-")}</span>
    <span class="run-config-pill">Coder: ${escapeHtml(coder || "-")}</span>
    <span class="run-config-pill">Critic: ${escapeHtml(critic || "-")}</span>
    <span class="run-config-pill">TDD: ${escapeHtml(String(!!tdd))}</span>
  `;
}

function renderStageTracker(currentStage) {
  const runStatus = state.status?.status || "idle";
  const activeIndex = STAGES.indexOf(currentStage);
  const runningStates = new Set(["running", "queued", "stopping", "awaiting_approval"]);
  const failedStates = new Set(["failed", "rejected"]);
  const successStates = new Set(["success", "preview_ready"]);

  el.stageTracker.innerHTML = STAGES.map((stage, idx) => {
    let klass = "";
    if (failedStates.has(runStatus)) {
      if (idx < activeIndex) klass = "done";
      else if (idx === activeIndex || (activeIndex < 0 && idx === 0)) klass = "failed";
    } else if (successStates.has(runStatus)) {
      klass = "done";
    } else if (runningStates.has(runStatus)) {
      if (idx < activeIndex) klass = "done";
      else if (idx === activeIndex || (activeIndex < 0 && idx === 0)) klass = "active";
    }
    return `<div class="stage ${klass}">${escapeHtml(stage)}</div>`;
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
    ["Planner model", s.planner_model_used || "-"],
    ["Coder model", s.coder_model_used || "-"],
    ["Critic model", s.critic_model_used || "-"],
    ["TDD mode", fmtBool(s.tdd_mode)],
    ["Project slug", s.project_slug || "-"],
    ["Project path", s.project_path || "-"],
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
  renderRunConfigSummary(s.planner_model_used, s.coder_model_used, s.critic_model_used, s.tdd_mode);
}

function renderArtifacts(details) {
  if (!details || !details.meta) {
    kvList(el.artifactList, [["Artifacts", "-"], ["Workspace", "-"], ["Project", "-"], ["Open project folder", "-"]]);
    return;
  }
  const meta = details.meta || {};
  const projectPath = meta.project_path || "-";
  const openProject = projectPath !== "-" ? `code "${projectPath}"` : "-";
  kvList(el.artifactList, [
    ["Artifacts", details.artifacts_dir || details.meta.artifacts_dir || "-"],
    ["Workspace", details.workspace_dir || details.meta.workspace_dir || "-"],
    ["Project", `${meta.project_slug || "-"} (${projectPath})`],
    ["Open project folder", openProject],
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
            <button data-exec-tab="stdout" data-exec-key="${key}" class="active">stdout</button>
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
      const siblingButtons = container.querySelectorAll(`button[data-exec-key="${key}"]`);
      siblingButtons.forEach((node) => node.classList.toggle("active", node.getAttribute("data-exec-tab") === tab));
      ["stdout", "stderr", "meta"].forEach((name) => {
        const node = document.getElementById(`${key}_${name}`);
        if (node) node.classList.toggle("hidden", name !== tab);
      });
    });
  });
}

function formatDiffPatch(patchText) {
  return String(patchText || "")
    .split("\n")
    .map((line) => {
      let klass = "neutral";
      if (line.startsWith("+") && !line.startsWith("+++")) klass = "add";
      if (line.startsWith("-") && !line.startsWith("---")) klass = "remove";
      return `<span class="diff-line ${klass}">${escapeHtml(line)}</span>`;
    })
    .join("");
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
      blocks.push(`<div class="diff-block"><div class="diff-title">Iteration ${escapeHtml(iter.iteration)} · ${escapeHtml(diff.path)} (+${escapeHtml(diff.added)} / -${escapeHtml(diff.removed)}) <span class="badge ${escapeHtml(diff.change_type || "edited")}">${escapeHtml(diff.change_type || "edited")}</span></div><pre class="code">${formatDiffPatch(diff.patch)}</pre></div>`);
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
  const workspaceFiles = summary.workspace_files || [];
  const workspaceDirs = summary.workspace_dirs || [];
  const workspaceRoot = summary.workspace_dir || "";
  const createdPaths = collectChangedPathSet(created, workspaceRoot);
  const modifiedPaths = collectChangedPathSet(modified, workspaceRoot);
  const workspaceFileTotal = Number(summary.workspace_file_total || workspaceFiles.length || 0);
  const workspaceDirTotal = Number(summary.workspace_dir_total || workspaceDirs.length || 0);
  const workspaceTruncated = !!summary.workspace_files_truncated;
  const changedCount = created.length + modified.length;
  const projectLabel = summary.project_slug
    ? `${summary.project_slug} (${summary.project_path || "-"})`
    : "-";
  const workspaceLabel = workspaceTruncated
    ? `${workspaceFileTotal} files + ${workspaceDirTotal} folders (showing ${workspaceFiles.length} files)`
    : `${workspaceFileTotal} files + ${workspaceDirTotal} folders`;
  el.previewSummary.textContent = `${changedCount} changed files · ${workspaceLabel} · Project: ${projectLabel}. Artifacts: ${summary.artifacts_dir}`;

  const previewByPath = new Map();
  [...workspaceFiles, ...created, ...modified].forEach((row) => {
    const relPath = normalizePath(row?.path || "");
    const previewText = String(row?.after_preview || "");
    if (relPath && !previewByPath.has(relPath)) {
      previewByPath.set(relPath, previewText);
    }
    const workspaceRel = toWorkspaceRelativePath(row?.workspace_path || "", workspaceRoot);
    if (workspaceRel && !previewByPath.has(workspaceRel)) {
      previewByPath.set(workspaceRel, previewText);
    }
  });

  const rows = [];
  rows.push(
    `<div class="file-tree-toolbar"><input class="file-tree-search" id="fileTreeSearchInput" type="text" placeholder="Filter by file/folder path..." value="${escapeHtml(
      state.previewTreeQuery || ""
    )}" /><div class="file-tree-toolbar-actions"><button type="button" class="btn-subtle" id="fileTreeExpandBtn">Expand all</button><button type="button" class="btn-subtle" id="fileTreeCollapseBtn">Collapse all</button><button type="button" class="btn-subtle" id="fileTreeClearBtn">Clear filter</button></div></div>`
  );

  if (created.length) {
    rows.push('<div class="muted">Created Files</div>');
  }
  created.forEach((file) => {
    const previewPath = normalizePath(file.path);
    const workspacePath = normalizePath(toWorkspaceRelativePath(file.workspace_path || "", workspaceRoot) || file.path);
    rows.push(renderFileItemRow(previewPath, previewPath, "new", "new file", true, workspacePath));
  });
  if (modified.length) {
    rows.push('<div class="muted">Modified Files</div>');
  }
  modified.forEach((file) => {
    const previewPath = normalizePath(file.path);
    const workspacePath = normalizePath(toWorkspaceRelativePath(file.workspace_path || "", workspaceRoot) || file.path);
    rows.push(renderFileItemRow(previewPath, previewPath, "edited", "edited file", true, workspacePath));
  });

  const tree = buildWorkspaceFileTree(workspaceFiles, workspaceDirs);
  const treeResult = renderWorkspaceFileTree(tree, createdPaths, modifiedPaths, state.previewTreeQuery || "");
  if (treeResult.html) {
    rows.push('<div class="muted">Workspace Folder Tree (All Files/Folders)</div>');
    rows.push(`<div class="workspace-tree">${treeResult.html}</div>`);
  } else if ((state.previewTreeQuery || "").trim()) {
    rows.push(`<p class="muted">No folders/files matched filter: ${escapeHtml(state.previewTreeQuery)}</p>`);
  }

  el.fileTree.innerHTML = rows.length ? rows.join("") : '<p class="muted">No workspace files or folders found.</p>';

  const searchInput = el.fileTree.querySelector("#fileTreeSearchInput");
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      state.previewTreeQuery = searchInput.value || "";
      renderFileTree(summary);
    });
  }
  const expandBtn = el.fileTree.querySelector("#fileTreeExpandBtn");
  expandBtn?.addEventListener("click", () => {
    state.previewTreeExpandAll = true;
    renderFileTree(summary);
  });
  const collapseBtn = el.fileTree.querySelector("#fileTreeCollapseBtn");
  collapseBtn?.addEventListener("click", () => {
    state.previewTreeExpandAll = false;
    renderFileTree(summary);
  });
  const clearBtn = el.fileTree.querySelector("#fileTreeClearBtn");
  clearBtn?.addEventListener("click", () => {
    state.previewTreeQuery = "";
    renderFileTree(summary);
  });

  el.fileTree.querySelectorAll("button[data-file-preview]").forEach((button) => {
    button.addEventListener("click", () => {
      const path = normalizePath(button.getAttribute("data-file-preview"));
      const preview = previewByPath.get(path) || "[file preview unavailable]";
      el.filePreview.textContent = `${path}\n\n${preview}`;
    });
  });

  el.fileTree.querySelectorAll("button[data-file-action]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const action = String(button.getAttribute("data-file-action") || "");
      const path = normalizePath(button.getAttribute("data-file-path"));
      if (!path) return;
      try {
        if (action === "edit") {
          const existing = String(previewByPath.get(path) || "");
          const next = window.prompt(`Edit file: ${path}`, existing);
          if (next === null) return;
          await api("/api/workspace/file/edit", {
            method: "POST",
            body: JSON.stringify({ path, content: next, actor: "web_ui" }),
          });
          showToast(`Saved ${path}`);
          el.filePreview.textContent = `${path}\n\n${next}`;
          await refreshSelectedRunFiles();
          return;
        }

        if (action === "delete") {
          const confirmed = window.confirm(`Delete file '${path}'? This cannot be undone.`);
          if (!confirmed) return;
          await api("/api/workspace/path/delete", {
            method: "POST",
            body: JSON.stringify({ path, actor: "web_ui" }),
          });
          showToast(`Deleted ${path}`);
          if (el.filePreview.textContent.startsWith(`${path}\n`)) {
            el.filePreview.textContent = "Select a file from the list.";
          }
          await refreshSelectedRunFiles();
        }
      } catch (err) {
        setMessage(err.message);
      }
    });
  });

  el.fileTree.querySelectorAll("button[data-folder-action]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const action = String(button.getAttribute("data-folder-action") || "");
      const folderPath = normalizePath(button.getAttribute("data-folder-path"));
      if (!folderPath) return;
      try {
        if (action === "rename") {
          const currentName = basename(folderPath);
          const parent = parentPath(folderPath);
          const nextName = window.prompt(`Rename folder: ${folderPath}`, currentName);
          if (nextName === null) return;
          const cleanNext = normalizePath(nextName);
          if (!cleanNext || cleanNext.includes("/")) {
            throw new Error("Folder rename requires a single folder name.");
          }
          const newPath = parent ? `${parent}/${cleanNext}` : cleanNext;
          await api("/api/workspace/path/rename", {
            method: "POST",
            body: JSON.stringify({ path: folderPath, new_path: newPath, actor: "web_ui" }),
          });
          showToast(`Renamed ${folderPath} -> ${newPath}`);
          await refreshSelectedRunFiles();
          return;
        }

        if (action === "delete") {
          const confirmed = window.confirm(`Delete folder '${folderPath}' and all nested files? This cannot be undone.`);
          if (!confirmed) return;
          await api("/api/workspace/path/delete", {
            method: "POST",
            body: JSON.stringify({ path: folderPath, actor: "web_ui" }),
          });
          showToast(`Deleted folder ${folderPath}`);
          await refreshSelectedRunFiles();
        }
      } catch (err) {
        setMessage(err.message);
      }
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

function renderMemoryChatFacts() {
  if (!el.memoryChatFacts) return;
  const data = state.memoryData || {};
  const facts = Array.isArray(data.facts) ? data.facts : [];
  const conflicts = Array.isArray(data.conflicts) ? data.conflicts : [];
  const query = (el.memoryChatSearch?.value || "").trim().toLowerCase();

  const conflictKeys = new Set(
    conflicts.map((item) => `${String(item.subject || "").toLowerCase()}::${String(item.predicate || "").toLowerCase()}`)
  );
  const filtered = facts.filter((fact) => {
    if (!query) return true;
    const text = `${fact.subject || ""} ${fact.predicate || ""} ${fact.object || ""}`.toLowerCase();
    return text.includes(query);
  });

  if (!filtered.length) {
    el.memoryChatFacts.innerHTML = '<p class="muted">No facts matched your search.</p>';
    return;
  }

  el.memoryChatFacts.innerHTML = filtered
    .slice()
    .reverse()
    .map((fact) => {
      const key = `${String(fact.subject || "").toLowerCase()}::${String(fact.predicate || "").toLowerCase()}`;
      const conflict = conflictKeys.has(key);
      return `
        <div class="memory-fact-row ${conflict ? "conflict" : ""}">
          <div><span class="muted">Subject:</span> <code>${escapeHtml(fact.subject || "-")}</code></div>
          <div><span class="muted">Predicate:</span> <code>${escapeHtml(fact.predicate || "-")}</code></div>
          <div><span class="muted">Object:</span> ${escapeHtml(fact.object || "-")}</div>
          <div><span class="muted">Timestamp:</span> ${escapeHtml(fmtDate(fact.timestamp || ""))}</div>
        </div>
      `;
    })
    .join("");
}

function drawDurationChart(metrics) {
  const ctx = el.durationChart.getContext("2d");
  const canvas = el.durationChart;
  const vars = getComputedStyle(document.documentElement);
  const panel = vars.getPropertyValue("--panel-soft").trim() || "#10141c";
  const accent = vars.getPropertyValue("--blue").trim() || "#4da3ff";
  const text = vars.getPropertyValue("--text").trim() || "#dde0e5";
  const muted = vars.getPropertyValue("--text-muted").trim() || "#9da3ae";

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const values = metrics.slice(-40).map((item) => Number(item.duration_sec || 0));
  if (!values.length) {
    ctx.fillStyle = muted;
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
  ctx.fillStyle = panel;
  ctx.fillRect(pad, pad, plotW, plotH);
  values.forEach((v, idx) => {
    const x = pad + idx * (barW + 2);
    const bh = (v / max) * plotH;
    const y = pad + plotH - bh;
    ctx.fillStyle = accent;
    ctx.fillRect(x, y, barW, bh);
  });
  ctx.fillStyle = text;
  ctx.font = "12px JetBrains Mono, IBM Plex Mono, monospace";
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
    parts.push(`<span class="log-line muted">=== ${escapeHtml(name)} ===</span>`);
    (rows || []).forEach((row) => {
      const line = String(row);
      const lineLevel = detectLogLevel(line);
      if (level !== "all" && level !== lineLevel) return;
      if (search && !line.toLowerCase().includes(search)) return;
      parts.push(`<span class="log-line log-${lineLevel}">${escapeHtml(line)}</span>`);
    });
    parts.push('<span class="log-line">&nbsp;</span>');
  });

  el.logsView.innerHTML = parts.length ? parts.join("") : '<span class="log-line muted">No logs yet.</span>';
}

function renderSettings(data) {
  state.settings = data;
  state.goalTemplates = Array.isArray(data.goal_templates) ? data.goal_templates : [];
  el.settingSafeMode.value = String(!!data.safe_mode);
  el.settingRateLimit.value = data.rate_limit_seconds ?? 3;
  el.settingMaxIterations.value = data.max_iterations_override ?? 0;
  el.settingLargeEdit.value = data.risky_large_edit_bytes ?? 50000;
  el.settingMultiFile.value = data.risky_multi_file_threshold ?? 4;
  el.settingPreviewDefault.checked = !!data.run_preview_default;
  if (el.settingTddMode) {
    el.settingTddMode.checked = !!data.tdd_mode;
  }

  const modelDefaults = [
    data.model,
    data.planner_model_default,
    data.coder_model_default,
    data.critic_model_default,
    ...(Array.isArray(state.models) ? state.models : []),
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const uniqueModels = [...new Set(modelDefaults)];
  setSelectOptions(
    el.settingPlannerModel,
    uniqueModels,
    data.planner_model || data.planner_model_default || data.model
  );
  setSelectOptions(
    el.settingCoderModel,
    uniqueModels,
    data.coder_model || data.coder_model_default || data.model
  );
  setSelectOptions(
    el.settingCriticModel,
    uniqueModels,
    data.critic_model || data.critic_model_default || data.model
  );
  renderTemplateSelects();

  if (el.goalTddMode) {
    el.goalTddMode.checked = !!data.tdd_mode;
    state.pendingGoalRunOptions.tddMode = !!data.tdd_mode;
  }
  if (el.cliTddMode && state.pendingCliRunOptions.templateId === "") {
    el.cliTddMode.checked = !!data.tdd_mode;
    state.pendingCliRunOptions.tddMode = !!data.tdd_mode;
  }
  refreshRunOptionSummary();
  kvList(el.settingsInfo, [
    ["Model", data.model || "-"],
    ["Planner model", data.planner_model || data.planner_model_default || "-"],
    ["Coder model", data.coder_model || data.coder_model_default || "-"],
    ["Critic model", data.critic_model || data.critic_model_default || "-"],
    ["Default TDD mode", fmtBool(data.tdd_mode)],
    ["Allowed commands", (data.allowed_commands || []).join(", ")],
    ["Workspace", data.workspace_dir || "-"],
    ["Default max iterations", data.max_iterations_default || 0],
    ["Goal templates", (state.goalTemplates || []).length],
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
    refreshWorkspaceTargets().catch(() => {});
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

  const hasSelected = state.runs.some((item) => item.id === state.selectedRunId);
  if (!hasSelected) {
    const preferredRunId =
      state.status?.active_run_id ||
      (state.runs.length ? state.runs[0].id : "");
    state.selectedRunId = preferredRunId || "";
    if (state.selectedRunId) {
      localStorage.setItem("dcc_selected_run", state.selectedRunId);
    }
  }

  if (state.selectedRunId) {
    await loadRun(state.selectedRunId);
  } else {
    renderFileTree(null);
  }
}

async function refreshMemory() {
  const payload = await api("/api/memory");
  state.memoryData = payload;
  renderMemory(payload);
  renderMemoryChatFacts();
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
      if (payload?.type && String(payload.type).startsWith("memory_")) {
        const mem = payload.payload || {};
        if (!hasSeenMemoryEvent(payload.type, mem)) {
          rememberMemoryEvent(payload.type, mem);
          if (payload.type === "memory_ask_answered") {
            const hitCount = Number(mem.matched_count || 0);
            const suffix = hitCount > 0 ? ` (matched facts: ${hitCount})` : "";
            pushChatMessage("ask", `${mem.answer || "No answer returned."}${suffix}`);
          } else if (payload.type === "memory_teach_completed") {
            const storedCount = Number(mem.stored_count || 0);
            const skipped = Array.isArray(mem.skipped_items) ? mem.skipped_items.length : 0;
            pushChatMessage("teach", `Stored ${storedCount} facts${skipped ? `, skipped ${skipped}` : ""}.`, {
              conflicts: mem.conflicts || [],
            });
          } else if (payload.type === "memory_teach_conflict") {
            pushChatMessage(
              "conflict",
              "Conflicting memory values detected. Confirm to overwrite with the incoming teach message.",
              { conflicts: mem.conflicts || [] }
            );
          }
        }
        await refreshMemory().catch(() => {});
      }
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

async function handleMemoryAsk(question) {
  const result = await api("/api/ask", {
    method: "POST",
    body: JSON.stringify({ question, actor: "web_ui" }),
  });
  rememberMemoryEvent("memory_ask_answered", result);
  const hitCount = Number(result.matched_count || 0);
  const suffix = hitCount > 0 ? ` (matched facts: ${hitCount})` : "";
  pushChatMessage("ask", `${result.answer || "No answer returned."}${suffix}`);
  setCliOutput(JSON.stringify(result, null, 2));
  await refreshMemory().catch(() => {});
}

async function handleMemoryTeach(message, confirmConflict = false) {
  const result = await api("/api/teach", {
    method: "POST",
    body: JSON.stringify({ message, confirm_conflict: !!confirmConflict, actor: "web_ui" }),
  });
  rememberMemoryEvent(result.status === "conflict" ? "memory_teach_conflict" : "memory_teach_completed", result);
  if (result.status === "conflict") {
    state.pendingTeachMessage = message;
    if (el.memoryConfirmTeachBtn) {
      el.memoryConfirmTeachBtn.classList.remove("hidden");
    }
    pushChatMessage(
      "conflict",
      "Conflicting memory values detected. Confirm to overwrite with the incoming teach message.",
      { conflicts: result.conflicts || [] }
    );
    setCliOutput(JSON.stringify(result, null, 2));
    return;
  }

  state.pendingTeachMessage = "";
  if (el.memoryConfirmTeachBtn) {
    el.memoryConfirmTeachBtn.classList.add("hidden");
  }
  const storedCount = Number(result.stored_count || 0);
  const skipped = Array.isArray(result.skipped_items) ? result.skipped_items.length : 0;
  const summary = `Stored ${storedCount} facts${skipped ? `, skipped ${skipped}` : ""}.`;
  pushChatMessage("teach", summary, { conflicts: result.conflicts || [] });
  setCliOutput(JSON.stringify(result, null, 2));
  await refreshMemory().catch(() => {});
}

async function handleGoalCommand(request) {
  const result = await api("/api/run", {
    method: "POST",
    body: JSON.stringify({
      command: request.command,
      template_id: state.pendingCliRunOptions.templateId || el.cliTemplateSelect?.value || "",
      tdd_mode: !!el.cliTddMode?.checked,
      planner_model: el.settingPlannerModel?.value || "",
      coder_model: el.settingCoderModel?.value || "",
      critic_model: el.settingCriticModel?.value || "",
    }),
  });
  state.lastCliRunId = result.run_id;
  state.selectedRunId = result.run_id;
  localStorage.setItem("dcc_selected_run", result.run_id);
  setupRunStream(result.run_id);
  pushChatMessage("system", `Goal queued: ${result.run_id}`);
  setCliOutput(`queued run: ${result.run_id}`);
  await refreshRuns();
  await refreshStatus();
}

async function submitMemoryChat() {
  const raw = (el.memoryChatInput?.value || "").trim();
  const request = inferChatRequest(raw);
  if (!request) {
    setCliOutput("Enter a question, a fact, or an explicit /goal|/ask|/teach command.");
    return;
  }
  if (!request.payload) {
    setCliOutput(`/${request.mode} requires content.`);
    return;
  }

  pushChatMessage("user", raw);
  if (el.memoryChatInput) {
    el.memoryChatInput.value = "";
  }

  if (request.mode === "ask") {
    await handleMemoryAsk(request.payload);
    return;
  }
  if (request.mode === "teach") {
    await handleMemoryTeach(request.payload, false);
    return;
  }
  if (request.mode === "goal") {
    await handleGoalCommand(request);
    return;
  }

  const msg = "Unsupported command. Use /goal, /ask, /teach, or plain natural input.";
  setCliOutput(msg);
  pushChatMessage("system", msg);
}

function wireTabs() {
  el.tabs.querySelectorAll("button[data-tab]").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.getAttribute("data-tab")));
  });
}

function initHeroParticles() {
  if (!el.heroParticles) return;
  el.heroParticles.innerHTML = "";
  if (state.reducedMotion) return;
  const count = 18;
  for (let i = 0; i < count; i += 1) {
    const node = document.createElement("span");
    node.className = "particle";
    node.style.setProperty("--x", `${Math.random() * 100}%`);
    node.style.setProperty("--y", `${Math.random() * 100}%`);
    node.style.setProperty("--size", `${2 + Math.random() * 4}px`);
    node.style.setProperty("--opacity", `${0.08 + Math.random() * 0.24}`);
    node.style.setProperty("--dur", `${12 + Math.random() * 16}s`);
    el.heroParticles.appendChild(node);
  }
}

function wireActions() {
  el.themeDarkBtn?.addEventListener("click", () => {
    applyTheme("dark");
    showToast("Theme set to Dark");
  });

  el.themeLightBtn?.addEventListener("click", () => {
    applyTheme("light");
    showToast("Theme set to Light");
  });

  el.bgToggleInput?.addEventListener("change", () => {
    setBackgroundEnabled(!!el.bgToggleInput.checked);
    showToast(el.bgToggleInput.checked ? "Cinematic background enabled" : "Cinematic background disabled");
  });

  el.resetAppearanceBtn?.addEventListener("click", () => {
    resetAppearance();
  });

  el.goalScopeNewBtn?.addEventListener("click", () => {
    setGoalRunScope("new");
  });
  el.goalScopeTargetBtn?.addEventListener("click", () => {
    setGoalRunScope("target");
  });

  el.goalWorkspaceTargetSelect?.addEventListener("change", () => {
    state.selectedGoalWorkspacePath = normalizePath(el.goalWorkspaceTargetSelect?.value || "");
    if (state.selectedGoalWorkspacePath) {
      setGoalRunScope("target");
      return;
    }
    renderWorkspaceTargetHint();
  });
  el.goalWorkspaceTargetSelect?.addEventListener("focus", () => {
    refreshWorkspaceTargets().catch(() => {});
  });

  el.refreshWorkspaceTargetsBtn?.addEventListener("click", async () => {
    try {
      await refreshWorkspaceTargets();
      showToast("Workspace paths synced.");
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.goalTddMode?.addEventListener("change", () => {
    state.pendingGoalRunOptions.tddMode = !!el.goalTddMode.checked;
    refreshRunOptionSummary();
  });

  el.startGoalBtn.addEventListener("click", async () => {
    const goal = el.goalInput.value.trim();
    if (!goal) return setMessage("Enter a goal first.");
    const selectedTarget = normalizePath(el.goalWorkspaceTargetSelect?.value || state.selectedGoalWorkspacePath || "");
    if (state.goalRunScope === "target" && !selectedTarget) {
      return setMessage("Select a workspace folder or file for targeted goal mode.");
    }
    const workspaceTargetPath = state.goalRunScope === "target" ? selectedTarget : "";
    try {
      const payload = {
        mode: "goal",
        payload: goal,
        preview: el.previewMode.checked,
        workspace_target_path: workspaceTargetPath,
        tdd_mode: !!el.goalTddMode?.checked,
        planner_model: el.settingPlannerModel?.value || "",
        coder_model: el.settingCoderModel?.value || "",
        critic_model: el.settingCriticModel?.value || "",
      };
      const result = await api("/api/run", { method: "POST", body: JSON.stringify(payload) });
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
        planner_model: el.settingPlannerModel?.value || "",
        coder_model: el.settingCoderModel?.value || "",
        critic_model: el.settingCriticModel?.value || "",
        tdd_mode: !!el.settingTddMode?.checked,
      };
      renderSettings(await api("/api/settings", { method: "POST", body: JSON.stringify(payload) }));
      showToast("Settings saved.");
      await refreshStatus();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.cliSendBtn.addEventListener("click", async () => {
    try {
      await submitMemoryChat();
    } catch (err) {
      setCliOutput(err.message);
      pushChatMessage("system", err.message);
    }
  });

  el.memoryChatInput?.addEventListener("keydown", async (evt) => {
    if (evt.key !== "Enter") return;
    evt.preventDefault();
    try {
      await submitMemoryChat();
    } catch (err) {
      setCliOutput(err.message);
      pushChatMessage("system", err.message);
    }
  });

  el.memoryConfirmTeachBtn?.addEventListener("click", async () => {
    const pending = state.pendingTeachMessage;
    if (!pending) {
      setCliOutput("No pending conflicting teach message.");
      return;
    }
    try {
      await handleMemoryTeach(pending, true);
      showToast("Conflicting teach confirmed.");
    } catch (err) {
      setCliOutput(err.message);
      pushChatMessage("system", err.message);
    }
  });

  el.memoryClearHistoryBtn?.addEventListener("click", () => {
    state.chatMessages = [];
    renderChatHistory();
  });

  el.memoryChatRefreshBtn?.addEventListener("click", () => {
    refreshMemory().catch((err) => setCliOutput(err.message));
  });

  el.memoryChatSearch?.addEventListener("input", () => {
    renderMemoryChatFacts();
  });

  el.replayPrevBtn.addEventListener("click", async () => {
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, Math.max(1, state.selectedIteration - 1));
  });

  el.replayNextBtn.addEventListener("click", async () => {
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, state.selectedIteration + 1);
  });

  el.cliTemplateSelect?.addEventListener("change", () => {
    const templateId = el.cliTemplateSelect.value || "";
    state.selectedCliTemplateId = templateId;
    state.pendingCliRunOptions.templateId = templateId;
    const template = findTemplate(templateId);
    if (template) {
      if (el.memoryChatInput) {
        el.memoryChatInput.value = `/goal ${template.goal || ""}`;
      }
      if (el.cliTddMode) {
        el.cliTddMode.checked = !!template.tdd_mode;
      }
      state.pendingCliRunOptions.tddMode = !!template.tdd_mode;
    } else if (state.settings) {
      if (el.cliTddMode) {
        el.cliTddMode.checked = !!state.settings.tdd_mode;
      }
      state.pendingCliRunOptions.tddMode = !!state.settings.tdd_mode;
    }
  });

  el.cliTddMode?.addEventListener("change", () => {
    state.pendingCliRunOptions.tddMode = !!el.cliTddMode.checked;
  });

  el.chatModeAutoBtn?.addEventListener("click", () => setChatMode("auto"));
  el.chatModeAskBtn?.addEventListener("click", () => setChatMode("ask"));
  el.chatModeTeachBtn?.addEventListener("click", () => setChatMode("teach"));

  el.refreshModelsBtn?.addEventListener("click", async () => {
    await refreshModelOptions();
    if (state.settings) {
      renderSettings(state.settings);
    }
    showToast("Model list refreshed.");
  });

  [el.settingPlannerModel, el.settingCoderModel, el.settingCriticModel].forEach((node) => {
    node?.addEventListener("change", () => refreshRunOptionSummary());
  });
}

async function bootstrap() {
  applyTheme(state.theme, false);
  applyBackgroundPreference();
  setStreamState("polling fallback");
  setChatMode("auto");
  renderChatHistory();
  initHeroParticles();

  if (window.matchMedia) {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onMotionChange = (event) => {
      state.reducedMotion = !!event.matches;
      initHeroParticles();
    };
    if (motionQuery.addEventListener) {
      motionQuery.addEventListener("change", onMotionChange);
    } else if (motionQuery.addListener) {
      motionQuery.addListener(onMotionChange);
    }
  }

  wireTabs();
  wireActions();
  setGoalRunScope("new");

  try {
    await refreshModelOptions();
    await Promise.all([refreshStatus(), refreshApprovals(), refreshRuns(), refreshMemory(), refreshTelemetry(), refreshLogs(), refreshWorkspaceTargets()]);
    await refreshSettings();
    renderWorkspaceTargetHint();
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
