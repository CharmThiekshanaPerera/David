// web/static/app.js
const STAGES = ["planner", "coder", "safety", "executor", "critic", "memory"];
const STREAM_RETRY_MS = 3000;
const WALKTHROUGH_DISMISSED_KEY = "dcc_walkthrough_dismissed";
const VOICE_TURN_STATES = ["idle", "listening_armed", "recording", "stopping", "transcribing", "responding"];
const VOICE_VAD_START_DEBOUNCE_MS = 140;

const state = {
  status: null,
  runs: [],
  importedBundles: [],
  selectedRunId: localStorage.getItem("dcc_selected_run") || "",
  selectedImportedBundleId: "",
  runViewerMode: "live",
  runReadOnlyView: false,
  selectedIteration: 1,
  selectedRunDetails: null,
  selectedRunFiles: null,
  telemetry: null,
  growthData: null,
  legacyArchive: null,
  selfImprovements: null,
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
  parentTeachingMode: false,
  advancedChatMode: true,
  detectedChatIntent: "chat",
  detectedChatConfidence: 0,
  selectedChatIntent: "chat",
  selectedChatSessionId: localStorage.getItem("dcc_chat_session_id") || "",
  chatSessions: [],
  chatMessages: [],
  pendingTeachMessage: "",
  pendingOverwriteId: "",
  pinnedMessageIds: JSON.parse(localStorage.getItem("dcc_chat_pins") || "[]"),
  memoryData: null,
  memoryFactsData: null,
  memoryConversationsData: null,
  memoryPanelTab: "facts",
  lastExplainWhy: null,
  memoryEventKeys: [],
  uploads: [],
  selectedUploadId: localStorage.getItem("dcc_selected_upload") || "",
  selectedUploadDetails: null,
  lastUploadAnswer: null,
  workspaceTargets: [],
  selectedGoalWorkspacePath: "",
  goalRunScope: "new",
  workspaceTargetsTruncated: false,
  selectedGrowthMilestoneId: "",
  previewTreeQuery: "",
  previewTreeExpandAll: false,
  theme: localStorage.getItem("dcc_theme") === "light" ? "light" : "dark",
  bgDisabled: localStorage.getItem("dcc_bg_disabled") === "1",
  reducedMotion: window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  demoBadgeText: "DEMO",
  versionStamp: "dev",
  walkthrough: {
    active: false,
    stepIndex: 0,
    highlightedSelector: "",
  },
  voice: {
    enabled: false,
    listening: false,
    generating: false,
    speaking: false,
    muted: false,
    textOnlyMode: false,
    inputMode: "manual",
    continuousMode: false,
    continuousPaused: false,
    postReplyDelayMs: 450,
    stopPhrases: ["stop listening", "end chat", "bye david"],
    rearmTimer: 0,
    turnState: "idle",
    vadThreshold: 0.035,
    vadSilenceMs: 900,
    vadMinSpeechMs: 300,
    vadActive: false,
    vadRaf: 0,
    vadLastSpeech: 0,
    vadAboveThresholdSince: 0,
    vadSilenceSince: 0,
    vadSpeechMs: 0,
    vadLastFrameAt: 0,
    vadSilenceCountdownMs: 0,
    vadLevel: 0,
    monitoring: false,
    vadBuffer: null,
    style: "warm",
    rate: 100,
    recorder: null,
    chunks: [],
    mediaStream: null,
    audioContext: null,
    analyser: null,
    waveformRaf: 0,
    partialAssistant: "",
    pendingSpeechCount: 0,
    audioQueue: [],
    audioPlaying: false,
    activeAudio: null,
    activeTurnId: "",
    turnCounter: 0,
    ttsMode: "none",
    recordingStarting: false,
    autoSubmitAfterStop: true,
    keepStreamOnStop: false,
    streamAbortController: null,
    transcribeAbortController: null,
    ttsFallbackWarned: false,
    sttFallbackMode: "local",
    sttFallbackReason: "",
    sttFallbackCheckedAt: 0,
    browserRecognition: null,
    browserTranscriptFinal: "",
    browserTranscriptInterim: "",
  },
};

const el = {
  tabs: document.getElementById("tabs"),
  startWalkthroughBtn: document.getElementById("startWalkthroughBtn"),
  versionStamp: document.getElementById("versionStamp"),
  globalStatus: document.getElementById("globalStatus"),
  demoBadge: document.getElementById("demoBadge"),
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
  growthSummary: document.getElementById("growthSummary"),
  growthTimeline: document.getElementById("growthTimeline"),
  growthMilestoneDetails: document.getElementById("growthMilestoneDetails"),
  growthRefreshBtn: document.getElementById("growthRefreshBtn"),
  legacySummary: document.getElementById("legacySummary"),
  legacyPanel: document.getElementById("legacyPanel"),
  legacyRefreshBtn: document.getElementById("legacyRefreshBtn"),
  selfImproveSummary: document.getElementById("selfImproveSummary"),
  selfImprovePanel: document.getElementById("selfImprovePanel"),
  selfImproveAutoBtn: document.getElementById("selfImproveAutoBtn"),
  selfImproveRefreshBtn: document.getElementById("selfImproveRefreshBtn"),
  previewSummary: document.getElementById("previewSummary"),
  fileTree: document.getElementById("fileTree"),
  filePreview: document.getElementById("filePreview"),
  approvalList: document.getElementById("approvalList"),
  approvalAudit: document.getElementById("approvalAudit"),
  runSearch: document.getElementById("runSearch"),
  runStatusFilter: document.getElementById("runStatusFilter"),
  refreshRunsBtn: document.getElementById("refreshRunsBtn"),
  bundleImportFile: document.getElementById("bundleImportFile"),
  importBundleBtn: document.getElementById("importBundleBtn"),
  importedBundleList: document.getElementById("importedBundleList"),
  runTableWrap: document.getElementById("runTableWrap"),
  runHealthSummary: document.getElementById("runHealthSummary"),
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
  valuesView: document.getElementById("valuesView"),
  lessonsView: document.getElementById("lessonsView"),
  projectBrainView: document.getElementById("projectBrainView"),
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
  settingCompanionMode: document.getElementById("settingCompanionMode"),
  settingMemoryInsightMode: document.getElementById("settingMemoryInsightMode"),
  settingParentTeachingMode: document.getElementById("settingParentTeachingMode"),
  settingAutonomousSelfImproveMode: document.getElementById("settingAutonomousSelfImproveMode"),
  settingDemoMode: document.getElementById("settingDemoMode"),
  settingUploadVisionMode: document.getElementById("settingUploadVisionMode"),
  settingUploadVisionModel: document.getElementById("settingUploadVisionModel"),
  settingVoiceModeEnabled: document.getElementById("settingVoiceModeEnabled"),
  settingVoiceTextOnlyMode: document.getElementById("settingVoiceTextOnlyMode"),
  settingVoiceContinuousMode: document.getElementById("settingVoiceContinuousMode"),
  settingVoiceInputMode: document.getElementById("settingVoiceInputMode"),
  settingVoiceVadThreshold: document.getElementById("settingVoiceVadThreshold"),
  settingVoiceVadThresholdValue: document.getElementById("settingVoiceVadThresholdValue"),
  settingVoiceVadSilenceMs: document.getElementById("settingVoiceVadSilenceMs"),
  settingVoiceVadMinSpeechMs: document.getElementById("settingVoiceVadMinSpeechMs"),
  settingVoicePostReplyDelayMs: document.getElementById("settingVoicePostReplyDelayMs"),
  settingVoiceStopPhrases: document.getElementById("settingVoiceStopPhrases"),
  settingVoiceStopPhrasesResetBtn: document.getElementById("settingVoiceStopPhrasesResetBtn"),
  settingVoiceStyle: document.getElementById("settingVoiceStyle"),
  settingVoiceRate: document.getElementById("settingVoiceRate"),
  settingVoiceRateValue: document.getElementById("settingVoiceRateValue"),
  settingVoiceSttEngine: document.getElementById("settingVoiceSttEngine"),
  settingVoiceSttModel: document.getElementById("settingVoiceSttModel"),
  settingVoiceSttLanguage: document.getElementById("settingVoiceSttLanguage"),
  settingVoiceSttCommand: document.getElementById("settingVoiceSttCommand"),
  settingVoiceWhisperCppCommand: document.getElementById("settingVoiceWhisperCppCommand"),
  settingVoiceWhisperCppModelPath: document.getElementById("settingVoiceWhisperCppModelPath"),
  settingVoiceTtsEngine: document.getElementById("settingVoiceTtsEngine"),
  settingVoiceTtsCommand: document.getElementById("settingVoiceTtsCommand"),
  settingVoiceTtsModelPath: document.getElementById("settingVoiceTtsModelPath"),
  settingVoiceChunkChars: document.getElementById("settingVoiceChunkChars"),
  settingPersonalityWarmth: document.getElementById("settingPersonalityWarmth"),
  settingPersonalityVerbosity: document.getElementById("settingPersonalityVerbosity"),
  settingPersonalityCuriosity: document.getElementById("settingPersonalityCuriosity"),
  settingPersonalityWarmthValue: document.getElementById("settingPersonalityWarmthValue"),
  settingPersonalityVerbosityValue: document.getElementById("settingPersonalityVerbosityValue"),
  settingPersonalityCuriosityValue: document.getElementById("settingPersonalityCuriosityValue"),
  settingPlannerModel: document.getElementById("settingPlannerModel"),
  settingCoderModel: document.getElementById("settingCoderModel"),
  settingCriticModel: document.getElementById("settingCriticModel"),
  settingTddMode: document.getElementById("settingTddMode"),
  refreshModelsBtn: document.getElementById("refreshModelsBtn"),
  saveSettingsBtn: document.getElementById("saveSettingsBtn"),
  loadDemoDataBtn: document.getElementById("loadDemoDataBtn"),
  resetDemoDataBtn: document.getElementById("resetDemoDataBtn"),
  settingsInfo: document.getElementById("settingsInfo"),
  voiceDiagnosticsRunBtn: document.getElementById("voiceDiagnosticsRunBtn"),
  voiceDiagnosticsStatus: document.getElementById("voiceDiagnosticsStatus"),
  voiceDiagnosticsList: document.getElementById("voiceDiagnosticsList"),
  voiceDiagnosticsSteps: document.getElementById("voiceDiagnosticsSteps"),
  voiceDiagnosticsCopyBtn: document.getElementById("voiceDiagnosticsCopyBtn"),
  themeDarkBtn: document.getElementById("themeDarkBtn"),
  themeLightBtn: document.getElementById("themeLightBtn"),
  bgToggleInput: document.getElementById("bgToggleInput"),
  resetAppearanceBtn: document.getElementById("resetAppearanceBtn"),
  chatModeAutoBtn: document.getElementById("chatModeAutoBtn"),
  chatModeAskBtn: document.getElementById("chatModeAskBtn"),
  chatModeTeachBtn: document.getElementById("chatModeTeachBtn"),
  advancedChatToggle: document.getElementById("advancedChatToggle"),
  chatConfirmSave: document.getElementById("chatConfirmSave"),
  parentTeachingMode: document.getElementById("parentTeachingMode"),
  chatIntentPreview: document.getElementById("chatIntentPreview"),
  chatIntentAskBtn: document.getElementById("chatIntentAskBtn"),
  chatIntentTeachBtn: document.getElementById("chatIntentTeachBtn"),
  chatIntentGoalBtn: document.getElementById("chatIntentGoalBtn"),
  chatIntentChatBtn: document.getElementById("chatIntentChatBtn"),
  voiceModePttBtn: document.getElementById("voiceModePttBtn"),
  voiceModeVadBtn: document.getElementById("voiceModeVadBtn"),
  voiceModeHint: document.getElementById("voiceModeHint"),
  voiceStartBtn: document.getElementById("voiceStartBtn"),
  voiceStopBtn: document.getElementById("voiceStopBtn"),
  voicePauseBtn: document.getElementById("voicePauseBtn"),
  voiceResumeBtn: document.getElementById("voiceResumeBtn"),
  voiceEndConversationBtn: document.getElementById("voiceEndConversationBtn"),
  voiceMuteBtn: document.getElementById("voiceMuteBtn"),
  voiceContinuousMode: document.getElementById("voiceContinuousMode"),
  voiceTextOnlyMode: document.getElementById("voiceTextOnlyMode"),
  voiceWaveform: document.getElementById("voiceWaveform"),
  voiceMicMeter: document.getElementById("voiceMicMeter"),
  voiceStatusText: document.getElementById("voiceStatusText"),
  voiceAutoIndicator: document.getElementById("voiceAutoIndicator"),
  voiceContinualIndicator: document.getElementById("voiceContinualIndicator"),
  voicePausedIndicator: document.getElementById("voicePausedIndicator"),
  voiceTypingIndicator: document.getElementById("voiceTypingIndicator"),
  voicePlaybackIndicator: document.getElementById("voicePlaybackIndicator"),
  voiceTranscriptPreview: document.getElementById("voiceTranscriptPreview"),
  voiceAssistantPreview: document.getElementById("voiceAssistantPreview"),
  voiceCrisisOverlay: document.getElementById("voiceCrisisOverlay"),
  chatNewSessionBtn: document.getElementById("chatNewSessionBtn"),
  chatSessionSummary: document.getElementById("chatSessionSummary"),
  chatSessionsList: document.getElementById("chatSessionsList"),
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
  memoryPanelFactsBtn: document.getElementById("memoryPanelFactsBtn"),
  memoryPanelValuesBtn: document.getElementById("memoryPanelValuesBtn"),
  memoryPanelConversationsBtn: document.getElementById("memoryPanelConversationsBtn"),
  memoryPanelLessonsBtn: document.getElementById("memoryPanelLessonsBtn"),
  memoryPanelReflectionsBtn: document.getElementById("memoryPanelReflectionsBtn"),
  memoryPanelValues: document.getElementById("memoryPanelValues"),
  memoryPanelConversations: document.getElementById("memoryPanelConversations"),
  memoryPanelLessons: document.getElementById("memoryPanelLessons"),
  memoryPanelReflections: document.getElementById("memoryPanelReflections"),
  memoryExplainView: document.getElementById("memoryExplainView"),
  uploadAnalyzeFile: document.getElementById("uploadAnalyzeFile"),
  uploadAnalyzeBtn: document.getElementById("uploadAnalyzeBtn"),
  uploadRefreshBtn: document.getElementById("uploadRefreshBtn"),
  uploadVisionMode: document.getElementById("uploadVisionMode"),
  uploadVisionModel: document.getElementById("uploadVisionModel"),
  uploadVisionHint: document.getElementById("uploadVisionHint"),
  uploadSummary: document.getElementById("uploadSummary"),
  uploadList: document.getElementById("uploadList"),
  uploadDetailView: document.getElementById("uploadDetailView"),
  uploadAskInput: document.getElementById("uploadAskInput"),
  uploadAskBtn: document.getElementById("uploadAskBtn"),
  uploadAnswerView: document.getElementById("uploadAnswerView"),
  cliOutput: document.getElementById("cliOutput"),
  cliExecPanel: document.getElementById("cliExecPanel"),
  toastContainer: document.getElementById("toastContainer"),
  heroParticles: document.getElementById("heroParticles"),
  walkthroughOverlay: document.getElementById("walkthroughOverlay"),
  walkthroughStepCounter: document.getElementById("walkthroughStepCounter"),
  walkthroughTitle: document.getElementById("walkthroughTitle"),
  walkthroughText: document.getElementById("walkthroughText"),
  walkthroughBackBtn: document.getElementById("walkthroughBackBtn"),
  walkthroughNextBtn: document.getElementById("walkthroughNextBtn"),
  walkthroughCloseBtn: document.getElementById("walkthroughCloseBtn"),
};

if (!Array.isArray(state.pinnedMessageIds)) {
  state.pinnedMessageIds = [];
}

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

function renderWorkspaceFileTree(node, createdSet, modifiedSet, query = "", openDepth = 1, depth = 0, parent = "", canEdit = true) {
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
        folderPath,
        canEdit
      );
      const folderMatched = pathMatchesQuery(`${folderPath}/`, query) || childResult.hasMatch;
      if (!folderMatched) return "";
      const open = state.previewTreeExpandAll || query || depth < openDepth ? " open" : "";
      const folderActions = canEdit
        ? `<div class="folder-tools"><button type="button" class="btn-subtle folder-action-btn" data-folder-action="rename" data-folder-path="${escapeHtml(
            folderPath
          )}">Rename</button><button type="button" class="btn-subtle folder-action-btn danger-lite" data-folder-action="delete" data-folder-path="${escapeHtml(
            folderPath
          )}">Delete</button></div>`
        : "";
      return `<details class="file-folder"${open}><summary><span class="folder-name">${escapeHtml(
        name
      )}/</span><span class="folder-path-inline">${escapeHtml(folderPath)}/</span></summary>${folderActions}<div class="file-children">${childResult.html}</div></details>`;
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
      return renderFileItemRow(row.path, row.name, badgeClass, badgeText, canEdit);
    });

  const html = [...folderRows.filter(Boolean), ...fileRows.filter(Boolean)].join("");
  return { html, hasMatch: html.length > 0 };
}

async function refreshSelectedRunFiles() {
  if (state.runViewerMode === "import" && state.selectedImportedBundleId) {
    const files = await api(`/api/bundles/import/${encodeURIComponent(state.selectedImportedBundleId)}/files`);
    state.selectedRunFiles = files;
    renderFileTree(files);
    return;
  }
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
    const err = new Error(json?.error || json?.data?.error || `Request failed (${response.status})`);
    err.response = json;
    throw err;
  }
  return json.data;
}

async function apiMultipart(path, formData, options = {}) {
  const headers = {};
  if (state.csrfToken) {
    headers["X-CSRF-Token"] = state.csrfToken;
  }
  const response = await fetch(path, {
    method: "POST",
    body: formData,
    headers,
    signal: options?.signal || undefined,
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok || !json.ok) {
    const err = new Error(json?.error || json?.data?.error || `Request failed (${response.status})`);
    err.response = json;
    throw err;
  }
  return json.data;
}

async function safeRefresh(label, handler, { silent = false } = {}) {
  try {
    return await handler();
  } catch (err) {
    const message = err?.message || "Unknown error";
    console.error(`[refresh:${label}]`, err);
    if (!silent) {
      setMessage(`${label} refresh failed: ${message}`);
    }
    return null;
  }
}

function setMessage(text) {
  if (el.dashboardMessage) {
    el.dashboardMessage.textContent = text;
  }
}

function setCliOutput(text) {
  if (el.cliOutput) {
    el.cliOutput.textContent = text;
  }
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

function classifyAdvancedIntent(rawText) {
  const text = String(rawText || "").trim();
  if (!text) return { intent: "chat", confidence: 0, reason: "empty" };
  if (text.startsWith("/ask ")) return { intent: "ask", confidence: 1, reason: "explicit_command" };
  if (text.startsWith("/teach ")) return { intent: "teach", confidence: 1, reason: "explicit_command" };
  if (text.startsWith("/goal ")) return { intent: "goal", confidence: 1, reason: "explicit_command" };

  const askLike = text.endsWith("?") || /^(who|what|when|where|why|how|is|are|can|could|do|does|did|which)\b/i.test(text);
  const teachLike = /\b(remember|teach|save this|my name is|i am your|from now on|you should know|call me)\b/i.test(text);
  const goalLike = /^(build|create|implement|refactor|fix|update|add|remove|improve|write|generate)\b/i.test(text);
  if (teachLike) return { intent: "teach", confidence: 0.88, reason: "memory_statement" };
  if (askLike) return { intent: "ask", confidence: 0.82, reason: "question_shape" };
  if (goalLike) return { intent: "goal", confidence: 0.7, reason: "task_instruction" };
  return { intent: "chat", confidence: 0.62, reason: "default_chat" };
}

function setAdvancedIntent(intent) {
  const normalized = ["ask", "teach", "goal", "chat"].includes(intent) ? intent : "chat";
  state.selectedChatIntent = normalized;
  const rows = [
    [el.chatIntentAskBtn, normalized === "ask"],
    [el.chatIntentTeachBtn, normalized === "teach"],
    [el.chatIntentGoalBtn, normalized === "goal"],
    [el.chatIntentChatBtn, normalized === "chat"],
  ];
  rows.forEach(([node, active]) => {
    if (!node) return;
    node.classList.toggle("active", !!active);
    node.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function setSegmentButton(node, active) {
  if (!node) return;
  node.classList.toggle("active", !!active);
  node.setAttribute("aria-pressed", active ? "true" : "false");
}

function updateIntentPreview() {
  const detected = classifyAdvancedIntent(el.memoryChatInput?.value || "");
  state.detectedChatIntent = detected.intent;
  state.detectedChatConfidence = Number(detected.confidence || 0);
  if (el.chatIntentPreview) {
    const confidencePct = Math.round(state.detectedChatConfidence * 100);
    el.chatIntentPreview.textContent = `I think this is: ${detected.intent} (${confidencePct}% confidence)`;
  }
  if (state.advancedChatMode) {
    setAdvancedIntent(detected.intent);
  }
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
  const source = String(meta?.source || "local").trim().toLowerCase() || "local";
  state.chatMessages.push({
    message_id: String(meta?.message_id || `${Date.now()}_${Math.random().toString(16).slice(2)}`),
    session_id: String(meta?.session_id || state.selectedChatSessionId || ""),
    kind: String(kind || "system"),
    text: String(text || ""),
    meta,
    source,
    timestamp_utc: new Date().toISOString(),
  });
  if (state.chatMessages.length > 120) {
    state.chatMessages.splice(0, state.chatMessages.length - 120);
  }
  renderChatHistory();
}

function persistPinnedMessages() {
  localStorage.setItem("dcc_chat_pins", JSON.stringify(state.pinnedMessageIds));
}

function togglePinnedMessage(messageId) {
  const clean = String(messageId || "").trim();
  if (!clean) return;
  if (state.pinnedMessageIds.includes(clean)) {
    state.pinnedMessageIds = state.pinnedMessageIds.filter((id) => id !== clean);
  } else {
    state.pinnedMessageIds = [...state.pinnedMessageIds, clean];
  }
  persistPinnedMessages();
  renderChatHistory();
}

function renderChatSessions() {
  if (!el.chatSessionsList) return;
  const sessions = Array.isArray(state.chatSessions) ? state.chatSessions : [];
  if (!sessions.length) {
    el.chatSessionsList.innerHTML = '<div class="muted session-empty">No sessions yet.</div>';
    if (el.chatSessionSummary) {
      el.chatSessionSummary.textContent = "No active session";
    }
    return;
  }
  if (!state.selectedChatSessionId) {
    state.selectedChatSessionId = sessions[0].session_id || "";
    if (state.selectedChatSessionId) {
      localStorage.setItem("dcc_chat_session_id", state.selectedChatSessionId);
    }
  }
  const selected = sessions.find((row) => row.session_id === state.selectedChatSessionId) || sessions[0];
  if (selected?.session_id && selected.session_id !== state.selectedChatSessionId) {
    state.selectedChatSessionId = selected.session_id;
    localStorage.setItem("dcc_chat_session_id", state.selectedChatSessionId);
  }

  el.chatSessionsList.innerHTML = sessions
    .map((row) => {
      const sid = String(row.session_id || "");
      const active = sid === state.selectedChatSessionId;
      const preview = String(row.preview || "").trim() || "No preview";
      const messageCount = Number(row.message_count || 0);
      const lastMessageAt = fmtDate(row.last_message_at || row.started_at || "");
      const pinnedCount = Number(row.pinned_count || 0);
      const intents = row.intents && typeof row.intents === "object" ? row.intents : {};
      const topIntent =
        Object.entries(intents)
          .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
          .map((item) => String(item[0] || ""))
          .find(Boolean) || "chat";
      const shortId = sid.length > 20 ? `${sid.slice(0, 10)}...${sid.slice(-5)}` : sid;
      return `<button type="button" class="session-item ${active ? "active" : ""}" data-chat-session="${escapeHtml(
        sid
      )}">
        <span class="session-row-top">
          <span class="session-id">${escapeHtml(shortId || "session")}</span>
          <span class="session-count">${escapeHtml(String(messageCount))} msgs</span>
        </span>
        <span class="session-main">${escapeHtml(preview)}</span>
        <span class="session-row-bottom">
          <span class="session-meta">${escapeHtml(lastMessageAt)}</span>
          <span class="session-badge">${escapeHtml(topIntent)}</span>
          ${pinnedCount > 0 ? `<span class="session-badge">${escapeHtml(String(pinnedCount))} pinned</span>` : ""}
        </span>
      </button>`;
    })
    .join("");
  if (el.chatSessionSummary) {
    el.chatSessionSummary.textContent = `Active: ${state.selectedChatSessionId || "-"} (${sessions.length} sessions)`;
  }
}

function syncChatMessagesFromConversations(rows) {
  const conversationRows = Array.isArray(rows) ? rows : [];
  const mapped = conversationRows
    .filter((row) => row && typeof row === "object")
    .map((row) => {
      const role = String(row?.role || "assistant");
      const intent = String(row?.intent || "chat");
      const kind =
        role === "user" ? "user" : intent === "ask" ? "ask" : intent === "teach" ? "teach" : "system";
      return {
        message_id: String(row?.message_id || ""),
        session_id: String(row?.session_id || ""),
        kind,
        text: String(row?.text || ""),
        meta: row?.metadata || {},
        source: "conversation",
        timestamp_utc: String(row?.timestamp_utc || new Date().toISOString()),
      };
    });
  mapped.sort((a, b) => String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
  const serverIds = new Set(mapped.map((row) => String(row?.message_id || "")).filter(Boolean));
  const localRows = (Array.isArray(state.chatMessages) ? state.chatMessages : [])
    .filter((row) => String(row?.source || "local") !== "conversation")
    .filter((row) => {
      const messageId = String(row?.message_id || "");
      return !messageId || !serverIds.has(messageId);
    });
  const merged = [...localRows, ...mapped];
  merged.sort((a, b) => String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
  if (merged.length > 500) {
    merged.splice(0, merged.length - 500);
  }
  state.chatMessages = merged;
}

function renderChatHistory() {
  if (!el.memoryChatHistory) return;
  const rows = state.selectedChatSessionId
    ? state.chatMessages.filter((item) => String(item.session_id || "") === state.selectedChatSessionId)
    : state.chatMessages;
  if (!rows.length) {
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

  const displayRows = rows.slice().reverse();
  el.memoryChatHistory.innerHTML = displayRows
    .map((row) => {
      const kind = row.kind || "system";
      const label = labels[kind] || "Message";
      const alignment = kind === "user" ? "user" : "assistant";
      const timestamp = fmtDate(row.timestamp_utc);
      const messageId = String(row.message_id || "");
      const pinned = state.pinnedMessageIds.includes(messageId);
      const conflictRows = Array.isArray(row.meta?.conflicts)
        ? row.meta.conflicts
        : Array.isArray(row.meta?.response?.conflicts)
        ? row.meta.response.conflicts
        : [];
      const citationRows = Array.isArray(row.meta?.citations)
        ? row.meta.citations
        : Array.isArray(row.meta?.response?.citations)
        ? row.meta.response.citations
        : [];
      const memoryInsight =
        row.meta?.memory_insight && typeof row.meta.memory_insight === "object"
          ? row.meta.memory_insight
          : row.meta?.response?.memory_insight && typeof row.meta.response.memory_insight === "object"
          ? row.meta.response.memory_insight
          : null;
      const conflictHtml = conflictRows.length
        ? `<ul>${conflictRows
            .map(
              (item) =>
                `<li><code>${escapeHtml(item.subject)}.${escapeHtml(item.predicate)}</code>: <strong>${escapeHtml(
                  item.existing || (item.existing_values || []).join(" | ")
                )}</strong> -> <strong>${escapeHtml(item.incoming)}</strong></li>`
            )
            .join("")}</ul>`
        : "";
      const citationsHtml = citationRows.length
        ? `<div class="chat-citations">${citationRows
            .map((c) => `<span class="chip">[${escapeHtml(c.type || "memory")}] ${escapeHtml(c.subject || c.excerpt || c.object || c.id || "")}</span>`)
            .join("")}</div>`
        : "";
      const insightRows = Array.isArray(memoryInsight?.influences) ? memoryInsight.influences : [];
      const insightSummary = String(memoryInsight?.summary || "").trim();
      const insightHtml =
        memoryInsight && (insightSummary || insightRows.length)
          ? `<details class="memory-fact-row"><summary><strong>Memory Insight</strong></summary><div>${
              insightSummary ? escapeHtml(insightSummary) : "No memory influences recorded."
            }</div>${
              insightRows.length
                ? `<div class="stack">${insightRows
                    .map(
                      (item) =>
                        `<div><strong>${escapeHtml(item.reference || item.type || "Memory")}</strong>: ${escapeHtml(
                          item.label || "-"
                        )}<br/><span class="muted">${escapeHtml(item.detail || "")}</span></div>`
                    )
                    .join("")}</div>`
                : ""
            }</details>`
          : "";
      const showQuickActions = kind === "ask" || kind === "teach" || kind === "system";
      const quickActions = showQuickActions
        ? `<div class="chat-chips"><button type="button" class="chip-btn" data-chat-chip="save-memory" data-chat-text="${escapeHtml(
            row.text
          )}">Save this as memory</button><button type="button" class="chip-btn" data-chat-chip="ask-followup" data-chat-text="${escapeHtml(
            row.text
          )}">Ask a follow-up</button><button type="button" class="chip-btn" data-chat-chip="teach-refine" data-chat-text="${escapeHtml(
            row.text
          )}">Teach refinement</button><button type="button" class="chip-btn" data-chat-chip="mark-legacy" data-chat-text="${escapeHtml(
            row.text
          )}" data-chat-id="${escapeHtml(messageId)}" data-chat-kind="${escapeHtml(kind)}" data-chat-session="${escapeHtml(
            row.session_id || ""
          )}">Mark Significant</button></div>`
        : "";
      return `
        <div class="chat-row ${escapeHtml(alignment)}">
          <div class="chat-bubble ${escapeHtml(kind)}">
            <div class="chat-meta"><span>${escapeHtml(label)} · ${escapeHtml(timestamp)}</span><button class="btn-subtle chat-pin-btn" type="button" data-chat-pin="${escapeHtml(
            messageId
          )}">${pinned ? "Unpin" : "Pin"}</button></div>
            <div class="chat-text">${escapeHtml(row.text)}</div>
            ${conflictHtml}
            ${citationsHtml}
            ${insightHtml}
            ${quickActions}
          </div>
        </div>
      `;
    })
    .join("");

  el.memoryChatHistory.scrollTop = 0;
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

function fmtBytes(value) {
  const raw = Number(value || 0);
  if (!Number.isFinite(raw) || raw <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = raw;
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024;
    idx += 1;
  }
  const rounded = idx === 0 ? Math.round(size) : Number(size.toFixed(2));
  return `${rounded} ${units[idx]}`;
}

function kvList(target, entries) {
  if (!target) return;
  target.innerHTML = entries
    .map(([k, v]) => `<li><span class="k">${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></li>`)
    .join("");
}

function clampPercent(value, fallback = 50) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function calibrationDescriptor(kind, value) {
  const score = clampPercent(value, 50);
  const bucket = score <= 33 ? "low" : score >= 67 ? "high" : "medium";
  if (kind === "warmth") {
    if (bucket === "low") return `${score} · concise/professional`;
    if (bucket === "high") return `${score} · playful/encouraging`;
    return `${score} · steady/friendly`;
  }
  if (kind === "verbosity") {
    if (bucket === "low") return `${score} · brief responses`;
    if (bucket === "high") return `${score} · detailed responses`;
    return `${score} · balanced length`;
  }
  if (bucket === "low") return `${score} · fewer follow-ups`;
  if (bucket === "high") return `${score} · frequent follow-ups`;
  return `${score} · occasional follow-ups`;
}

function renderPersonalityCalibrationLabels() {
  const warmth = clampPercent(el.settingPersonalityWarmth?.value, 55);
  const verbosity = clampPercent(el.settingPersonalityVerbosity?.value, 55);
  const curiosity = clampPercent(el.settingPersonalityCuriosity?.value, 50);
  if (el.settingPersonalityWarmthValue) {
    el.settingPersonalityWarmthValue.textContent = calibrationDescriptor("warmth", warmth);
  }
  if (el.settingPersonalityVerbosityValue) {
    el.settingPersonalityVerbosityValue.textContent = calibrationDescriptor("verbosity", verbosity);
  }
  if (el.settingPersonalityCuriosityValue) {
    el.settingPersonalityCuriosityValue.textContent = calibrationDescriptor("curiosity", curiosity);
  }
}

function clampVoiceRate(value, fallback = 100) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(60, Math.min(180, Math.round(parsed)));
}

function voiceRateDescriptor(value) {
  const rate = clampVoiceRate(value, 100);
  if (rate <= 85) return `${rate}% · slower`;
  if (rate >= 125) return `${rate}% · faster`;
  return `${rate}% · natural`;
}

function renderVoiceRateLabel() {
  const rate = clampVoiceRate(el.settingVoiceRate?.value ?? state.voice.rate, 100);
  if (el.settingVoiceRateValue) {
    el.settingVoiceRateValue.textContent = voiceRateDescriptor(rate);
  }
}

function clampVoiceVadThreshold(value, fallback = 0.035) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0.005, Math.min(0.2, parsed));
}

function clampVoiceVadSilence(value, fallback = 900) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(250, Math.min(2500, Math.round(parsed)));
}

function clampVoiceVadMinSpeech(value, fallback = 300) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(120, Math.min(4000, Math.round(parsed)));
}

function clampVoicePostReplyDelay(value, fallback = 450) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(300, Math.min(800, Math.round(parsed)));
}

function parseVoiceStopPhrases(value) {
  const defaults = ["stop listening", "end chat", "bye david"];
  const parts = Array.isArray(value) ? value : String(value || "").split(",");
  const out = [];
  const seen = new Set();
  parts.forEach((item) => {
    const phrase = String(item || "").trim().toLowerCase().slice(0, 40);
    if (!phrase || seen.has(phrase)) return;
    seen.add(phrase);
    out.push(phrase);
  });
  return out.slice(0, 12).length ? out.slice(0, 12) : defaults;
}

function voiceStopPhrasesDisplay(value) {
  const phrases = Array.isArray(value) ? value : parseVoiceStopPhrases(value);
  return phrases.join(", ");
}

function voiceVadThresholdDescriptor(value) {
  const threshold = clampVoiceVadThreshold(value, 0.035);
  return threshold.toFixed(3);
}

function renderVoiceVadLabel() {
  const threshold = clampVoiceVadThreshold(el.settingVoiceVadThreshold?.value ?? state.voice.vadThreshold, 0.035);
  if (el.settingVoiceVadThresholdValue) {
    el.settingVoiceVadThresholdValue.textContent = voiceVadThresholdDescriptor(threshold);
  }
}

function normalizeVoiceTurnState(value) {
  const clean = String(value || "").trim().toLowerCase();
  return VOICE_TURN_STATES.includes(clean) ? clean : "idle";
}

function nextVoiceTurnState(current, eventName) {
  const currentState = normalizeVoiceTurnState(current);
  const event = String(eventName || "").trim().toLowerCase();
  const transitions = {
    idle: { arm: "listening_armed", start_recording: "recording", transcribe_start: "transcribing" },
    listening_armed: { start_recording: "recording", cancel: "idle", deactivate: "idle" },
    recording: { stop_request: "stopping", cancel: "idle" },
    stopping: { transcribe_start: "transcribing", arm: "listening_armed", complete: "idle", cancel: "idle" },
    transcribing: { respond_start: "responding", arm: "listening_armed", complete: "idle", cancel: "idle" },
    responding: { arm: "listening_armed", complete: "idle", cancel: "idle" },
  };
  return transitions[currentState]?.[event] || currentState;
}

function setVoiceTurnState(nextState) {
  state.voice.turnState = normalizeVoiceTurnState(nextState);
}

function transitionVoiceTurn(eventName) {
  setVoiceTurnState(nextVoiceTurnState(state.voice.turnState, eventName));
}

function evaluateVadFrame(snapshot) {
  const nowMs = Number(snapshot?.nowMs || 0);
  const threshold = Number(snapshot?.threshold || 0);
  const silenceMs = Math.max(250, Number(snapshot?.silenceMs || 900));
  const minSpeechMs = Math.max(120, Number(snapshot?.minSpeechMs || 300));
  const debounceMs = Math.max(40, Number(snapshot?.debounceMs || VOICE_VAD_START_DEBOUNCE_MS));
  const level = Number(snapshot?.level || 0);
  const aboveThreshold = level >= threshold;
  const turnState = normalizeVoiceTurnState(snapshot?.turnState);
  const lastFrameMs = Number(snapshot?.lastFrameMs || 0);
  const deltaMs = lastFrameMs > 0 ? Math.max(0, nowMs - lastFrameMs) : 0;

  let aboveSinceMs = Number(snapshot?.aboveSinceMs || 0);
  let silenceSinceMs = Number(snapshot?.silenceSinceMs || 0);
  let speechMs = Math.max(0, Number(snapshot?.speechMs || 0));
  let silenceCountdownMs = 0;
  let shouldStartRecording = false;
  let shouldStopRecording = false;
  let shouldAccept = false;
  let bargeInSignal = false;

  if (turnState === "listening_armed" || turnState === "responding") {
    speechMs = 0;
    silenceSinceMs = 0;
    if (aboveThreshold) {
      if (!aboveSinceMs) {
        aboveSinceMs = nowMs;
      }
      if (nowMs - aboveSinceMs >= debounceMs) {
        shouldStartRecording = true;
      }
      bargeInSignal = true;
    } else {
      aboveSinceMs = 0;
    }
  } else if (turnState === "recording") {
    aboveSinceMs = aboveThreshold ? (aboveSinceMs || nowMs) : 0;
    if (aboveThreshold) {
      speechMs += deltaMs;
      silenceSinceMs = 0;
      silenceCountdownMs = 0;
    } else {
      if (!silenceSinceMs) {
        silenceSinceMs = nowMs;
      }
      const elapsedSilenceMs = Math.max(0, nowMs - silenceSinceMs);
      silenceCountdownMs = Math.max(0, silenceMs - elapsedSilenceMs);
      if (elapsedSilenceMs >= silenceMs) {
        shouldStopRecording = true;
        shouldAccept = speechMs >= minSpeechMs;
      }
    }
  } else {
    aboveSinceMs = 0;
    silenceSinceMs = 0;
    speechMs = 0;
    silenceCountdownMs = 0;
  }

  return {
    aboveSinceMs,
    silenceSinceMs,
    speechMs,
    lastFrameMs: nowMs,
    silenceCountdownMs,
    shouldStartRecording,
    shouldStopRecording,
    shouldAccept,
    bargeInSignal,
  };
}

function summarizeText(value, maxLen = 180) {
  const text = String(value || "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, Math.max(0, maxLen - 3)).trim()}...`;
}

async function markLegacyMoment(payload) {
  const cleanPayload = payload && typeof payload === "object" ? payload : {};
  const summary = summarizeText(cleanPayload.summary || "");
  if (!summary) {
    throw new Error("A summary is required to mark a Significant Moment.");
  }
  const body = {
    source_type: String(cleanPayload.source_type || "manual"),
    source_id: String(cleanPayload.source_id || ""),
    summary,
    details: summarizeText(cleanPayload.details || cleanPayload.summary || "", 1800),
    timestamp_utc: String(cleanPayload.timestamp_utc || new Date().toISOString()),
    metadata: cleanPayload.metadata && typeof cleanPayload.metadata === "object" ? cleanPayload.metadata : {},
    actor: "web_ui",
  };
  const saved = await api("/api/legacy_archive", {
    method: "POST",
    body: JSON.stringify(body),
  });
  showToast("Saved to Legacy Archive.");
  await refreshLegacyArchive().catch(() => {});
  await refreshStatus().catch(() => {});
  return saved;
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

function renderDemoBadge() {
  if (!el.demoBadge) return;
  const enabled = !!(state.status?.demo_mode || state.settings?.demo_mode);
  el.demoBadge.classList.toggle("hidden", !enabled);
  if (enabled) {
    const label = String(state.settings?.demo_badge_text || state.demoBadgeText || "DEMO").trim() || "DEMO";
    el.demoBadge.textContent = label;
  }
}

function renderVersionStamp() {
  if (!el.versionStamp) return;
  const statusVersion = String(state.status?.version_stamp || "").trim();
  const settingsVersion = String(state.settings?.version_stamp || "").trim();
  const stamp = statusVersion || settingsVersion || "dev";
  state.versionStamp = stamp;
  const appVersion = String(state.status?.app_version || state.settings?.app_version || "").trim();
  const gitCommit = String(state.status?.git_commit || state.settings?.git_commit || "").trim();
  const titleParts = [];
  if (appVersion) titleParts.push(`app ${appVersion}`);
  if (gitCommit) titleParts.push(`commit ${gitCommit}`);
  el.versionStamp.textContent = stamp;
  el.versionStamp.title = titleParts.join(" | ") || "Local build";
}

function applyDemoUiDefaults(settingsData) {
  const data = settingsData && typeof settingsData === "object" ? settingsData : {};
  if (!(state.status?.demo_mode || data.demo_mode)) return;
  if (Object.prototype.hasOwnProperty.call(data, "demo_badge_text")) {
    state.demoBadgeText = String(data.demo_badge_text || "").trim() || "DEMO";
  }
  const themeStored = localStorage.getItem("dcc_theme");
  const bgStored = localStorage.getItem("dcc_bg_disabled");
  const themeDefault = String(data.ui_theme_default || "").trim().toLowerCase();
  if (!themeStored && (themeDefault === "dark" || themeDefault === "light")) {
    applyTheme(themeDefault, false);
  }
  if (bgStored === null && typeof data.ui_background_enabled === "boolean") {
    setBackgroundEnabled(!!data.ui_background_enabled);
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

function renderRunHealthSummary(summary, readOnly = false) {
  const data = summary && typeof summary === "object" ? summary : {};
  const models = [data.planner_model_used, data.coder_model_used, data.critic_model_used].filter(Boolean).join(" | ") || "-";
  const elapsed = Number(data.elapsed_sec);
  const elapsedLabel = Number.isFinite(elapsed) ? `${elapsed.toFixed(2)}s` : "-";
  kvList(el.runHealthSummary, [
    ["Viewer mode", readOnly ? "Imported bundle (read-only)" : "Live run"],
    ["Iterations", data.iterations ?? "-"],
    ["Time to green", data.iterations_until_green ?? "-"],
    ["Elapsed", elapsedLabel],
    ["Approvals", data.approvals_count ?? 0],
    ["Models used", models],
    ["Top error category", data.top_error_category || "none"],
    ["Memory references", data.memory_items_referenced ?? 0],
  ]);
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
    ["Analyzed uploads", s.uploaded_file_count || 0],
    ["Legacy archive entries", s.legacy_archive_count || 0],
    ["Demo mode", fmtBool(s.demo_mode)],
    ["Safe mode", fmtBool(s.safe_mode)],
  ]);

  renderStageTracker(s.current_stage || "idle");
  toggleRunningBanner(s);
  updateButtonState();
  renderRunConfigSummary(s.planner_model_used, s.coder_model_used, s.critic_model_used, s.tdd_mode);
  renderDemoBadge();
  renderVersionStamp();
}

function renderArtifacts(details) {
  if (!details || !details.meta) {
    kvList(el.artifactList, [["Artifacts", "-"], ["Workspace", "-"], ["Project", "-"], ["Open project folder", "-"]]);
    return;
  }
  const meta = details.meta || {};
  const readOnly = !!details.read_only || !!state.runReadOnlyView;
  const projectPath = meta.project_path || "-";
  const openProject = projectPath !== "-" ? `code "${projectPath}"` : "-";
  kvList(el.artifactList, [
    ["Viewer mode", readOnly ? "Imported bundle (read-only)" : "Live workspace"],
    ["Artifacts", details.artifacts_dir || details.meta.artifacts_dir || "-"],
    ["Workspace", details.workspace_dir || details.meta.workspace_dir || "-"],
    ["Project", `${meta.project_slug || "-"} (${projectPath})`],
    ["Open project folder", readOnly ? "-" : openProject],
  ]);
}

function renderApprovals(rows) {
  if (!el.approvalList) return;
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
              <button data-run-action="bundle" data-run-id="${escapeHtml(row.id)}" class="ghost">Export Bundle</button>
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
        state.runViewerMode = "live";
        state.runReadOnlyView = false;
        state.selectedImportedBundleId = "";
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

function renderImportedBundles() {
  if (!el.importedBundleList) return;
  const rows = Array.isArray(state.importedBundles) ? state.importedBundles : [];
  if (!rows.length) {
    el.importedBundleList.innerHTML = '<p class="muted">No imported bundles yet.</p>';
    return;
  }
  el.importedBundleList.innerHTML = rows
    .map((row) => {
      const importId = String(row.import_id || "");
      const active = importId && importId === state.selectedImportedBundleId;
      const summary = row.health_summary && typeof row.health_summary === "object" ? row.health_summary : {};
      return `<div class="imported-bundle-item ${active ? "active" : ""}">
        <div class="row">
          <strong><code>${escapeHtml(row.run_id || "-")}</code></strong>
          <button type="button" class="ghost" data-import-open="${escapeHtml(importId)}">Open</button>
        </div>
        <div class="muted">${escapeHtml(row.source_filename || "bundle.zip")} · imported ${escapeHtml(fmtDate(row.imported_at || ""))}</div>
        <div class="muted">status=${escapeHtml(row.status || "-")} · iterations=${escapeHtml(summary.iterations ?? "-")} · approvals=${escapeHtml(summary.approvals_count ?? 0)}</div>
      </div>`;
    })
    .join("");
  el.importedBundleList.querySelectorAll("button[data-import-open]").forEach((button) => {
    button.addEventListener("click", async () => {
      const importId = String(button.getAttribute("data-import-open") || "").trim();
      if (!importId) return;
      state.selectedImportedBundleId = importId;
      state.runViewerMode = "import";
      state.runReadOnlyView = true;
      await loadImportedBundle(importId);
      renderImportedBundles();
      activateTab("runs");
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
  const readOnly = !!summary.read_only || !!state.runReadOnlyView;
  const changedCount = created.length + modified.length;
  const projectLabel = summary.project_slug
    ? `${summary.project_slug} (${summary.project_path || "-"})`
    : "-";
  const workspaceLabel = workspaceTruncated
    ? `${workspaceFileTotal} files + ${workspaceDirTotal} folders (showing ${workspaceFiles.length} files)`
    : `${workspaceFileTotal} files + ${workspaceDirTotal} folders`;
  const modeLabel = readOnly ? "Read-only imported bundle" : "Live workspace";
  el.previewSummary.textContent = `${changedCount} changed files · ${workspaceLabel} · Project: ${projectLabel}. Artifacts: ${summary.artifacts_dir} · Mode: ${modeLabel}`;

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
    rows.push(renderFileItemRow(previewPath, previewPath, "new", "new file", !readOnly, workspacePath));
  });
  if (modified.length) {
    rows.push('<div class="muted">Modified Files</div>');
  }
  modified.forEach((file) => {
    const previewPath = normalizePath(file.path);
    const workspacePath = normalizePath(toWorkspaceRelativePath(file.workspace_path || "", workspaceRoot) || file.path);
    rows.push(renderFileItemRow(previewPath, previewPath, "edited", "edited file", !readOnly, workspacePath));
  });

  const tree = buildWorkspaceFileTree(workspaceFiles, workspaceDirs);
  const treeResult = renderWorkspaceFileTree(
    tree,
    createdPaths,
    modifiedPaths,
    state.previewTreeQuery || "",
    1,
    0,
    "",
    !readOnly
  );
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

  if (readOnly) {
    return;
  }

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
  const snapshot = data && typeof data === "object" ? data : {};
  const facts = Array.isArray(snapshot.facts) ? snapshot.facts : [];
  const values = Array.isArray(snapshot.values) ? snapshot.values : [];
  const projects = Array.isArray(snapshot.projects) ? snapshot.projects : [];
  const lessons = Array.isArray(snapshot.lessons)
    ? snapshot.lessons.filter((row) => String(row?.kind || "").toLowerCase() !== "reflection")
    : [];
  const conflicts = Array.isArray(snapshot.conflicts) ? snapshot.conflicts : [];

  if (el.factsView) {
    el.factsView.innerHTML = !facts.length
      ? '<p class="muted">No facts stored yet.</p>'
      : facts
          .slice(-120)
          .reverse()
          .map((f) => `<div><code>${escapeHtml(f.subject)}.${escapeHtml(f.predicate)}</code> = ${escapeHtml(f.object)} <span class="muted">(${escapeHtml(f.timestamp || "")})</span></div>`)
          .join("");
  }

  if (el.lessonsView) {
    el.lessonsView.innerHTML = !lessons.length
      ? '<p class="muted">No lessons stored yet.</p>'
      : lessons
          .slice(-120)
          .reverse()
          .map((l) => `<div><strong>${escapeHtml(l.lesson || "")}</strong><br/><span class="muted">goal=${escapeHtml(l.goal || "")}</span></div>`)
          .join("");
  }

  if (el.valuesView) {
    el.valuesView.innerHTML = !values.length
      ? '<p class="muted">No values stored yet.</p>'
      : values
          .slice(-120)
          .reverse()
          .map(
            (v) =>
              `<div><strong>${escapeHtml(v.category_label || v.category || "Values")}</strong>: ${escapeHtml(
                v.principle || ""
              )}<br/><span class="muted">${escapeHtml(v.application || "")}</span></div>`
          )
          .join("");
  }

  if (el.projectBrainView) {
    el.projectBrainView.innerHTML = !projects.length
      ? '<p class="muted">No project summaries stored yet.</p>'
      : projects
          .slice(-160)
          .reverse()
          .map((p) => {
            const weaknesses = Array.isArray(p.known_weaknesses) ? p.known_weaknesses : [];
            const firstWeakness = weaknesses.length ? weaknesses[0] : "No major weaknesses recorded yet.";
            return `<div><strong>${escapeHtml(p.project_slug || p.project_relative_path || "project")}</strong><br/><span class="muted">${escapeHtml(
              p.project_relative_path || p.project_path || "-"
            )}</span><br/>${escapeHtml(p.architecture_summary || "-")}<br/><span class="muted">Testing: ${escapeHtml(
              p.testing_approach || "-"
            )}</span><br/><span class="muted">Weakness: ${escapeHtml(firstWeakness)}</span></div>`;
          })
          .join("");
  }

  if (el.memoryConflicts) {
    el.memoryConflicts.innerHTML = !conflicts.length
      ? '<p class="muted">No memory conflicts detected.</p>'
      : conflicts.map((c) => `<div class="approval"><strong>${escapeHtml(c.subject)}.${escapeHtml(c.predicate)}</strong><div>Values: ${escapeHtml((c.values || []).join(" | "))}</div></div>`).join("");
  }
}

function renderMemoryChatFacts() {
  if (!el.memoryChatFacts) return;
  const data = state.memoryFactsData || state.memoryData || {};
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
      const aliases = Array.isArray(fact.aliases) ? fact.aliases.filter(Boolean) : [];
      return `
        <div class="memory-fact-row ${conflict ? "conflict" : ""}">
          <div><span class="muted">Subject:</span> <code>${escapeHtml(fact.subject || "-")}</code></div>
          <div><span class="muted">Predicate:</span> <code>${escapeHtml(fact.predicate || "-")}</code></div>
          <div><span class="muted">Object:</span> ${escapeHtml(fact.object || "-")}</div>
          <div><span class="muted">Aliases:</span> ${escapeHtml(aliases.join(", ") || "-")}</div>
          <div><span class="muted">Timestamp:</span> ${escapeHtml(fmtDate(fact.timestamp || ""))}</div>
        </div>
      `;
    })
    .join("");
}

function renderMemoryConversationsPanel() {
  if (!el.memoryPanelConversations) return;
  let rows = Array.isArray(state.memoryConversationsData?.conversations) ? state.memoryConversationsData.conversations : [];
  if (state.selectedChatSessionId) {
    rows = rows.filter((row) => String(row?.session_id || "") === state.selectedChatSessionId);
  }
  const query = (el.memoryChatSearch?.value || "").trim().toLowerCase();
  const filtered = rows.filter((row) => {
    if (!query) return true;
    const text = `${row.text || ""} ${row.intent || ""} ${row.session_id || ""}`.toLowerCase();
    return text.includes(query);
  });
  if (!filtered.length) {
    el.memoryPanelConversations.innerHTML = '<p class="muted">No conversation rows matched.</p>';
    return;
  }
  el.memoryPanelConversations.innerHTML = filtered
    .slice(-160)
    .reverse()
    .map(
      (row) => `<div class="memory-fact-row">
        <div><span class="muted">Session:</span> <code>${escapeHtml(row.session_id || "-")}</code></div>
        <div><span class="muted">Role/Intent:</span> ${escapeHtml(row.role || "-")} / ${escapeHtml(row.intent || "-")}</div>
        <div>${escapeHtml(row.text || "")}</div>
        <div><span class="muted">When:</span> ${escapeHtml(fmtDate(row.timestamp_utc || ""))}</div>
        <div class="row"><button type="button" class="ghost" data-legacy-convo="${escapeHtml(
          row.message_id || row.timestamp_utc || ""
        )}" data-legacy-summary="${escapeHtml(row.text || "")}" data-legacy-session="${escapeHtml(
          row.session_id || ""
        )}" data-legacy-ts="${escapeHtml(row.timestamp_utc || "")}">Mark Significant</button></div>
      </div>`
    )
    .join("");
  el.memoryPanelConversations.querySelectorAll("button[data-legacy-convo]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await markLegacyMoment({
          source_type: "conversation",
          source_id: String(button.getAttribute("data-legacy-convo") || ""),
          summary: String(button.getAttribute("data-legacy-summary") || ""),
          details: String(button.getAttribute("data-legacy-summary") || ""),
          timestamp_utc: String(button.getAttribute("data-legacy-ts") || ""),
          metadata: { session_id: String(button.getAttribute("data-legacy-session") || "") },
        });
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

function renderMemoryLessonsPanel() {
  if (!el.memoryPanelLessons) return;
  const lessons = Array.isArray(state.memoryData?.lessons)
    ? state.memoryData.lessons.filter((row) => String(row?.kind || "").toLowerCase() !== "reflection")
    : [];
  const query = (el.memoryChatSearch?.value || "").trim().toLowerCase();
  const filtered = lessons.filter((row) => {
    if (!query) return true;
    const text = `${row.lesson || ""} ${row.goal || ""} ${(row.tags || []).join(" ")}`.toLowerCase();
    return text.includes(query);
  });
  if (!filtered.length) {
    el.memoryPanelLessons.innerHTML = '<p class="muted">No lessons matched your search.</p>';
    return;
  }
  el.memoryPanelLessons.innerHTML = filtered
    .slice(-120)
    .reverse()
    .map(
      (row) => `<div class="memory-fact-row">
        <div><strong>${escapeHtml(row.lesson || "")}</strong></div>
        <div><span class="muted">Goal:</span> ${escapeHtml(row.goal || "-")}</div>
        <div><span class="muted">Tags:</span> ${escapeHtml((row.tags || []).join(", ") || "-")}</div>
        <div class="row"><button type="button" class="ghost" data-legacy-lesson="${escapeHtml(
          row.timestamp_utc || row.lesson || ""
        )}" data-legacy-summary="${escapeHtml(row.lesson || "")}" data-legacy-goal="${escapeHtml(row.goal || "")}">Mark Significant</button></div>
      </div>`
    )
    .join("");
  el.memoryPanelLessons.querySelectorAll("button[data-legacy-lesson]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await markLegacyMoment({
          source_type: "lesson",
          source_id: String(button.getAttribute("data-legacy-lesson") || ""),
          summary: String(button.getAttribute("data-legacy-summary") || ""),
          details: `Goal: ${String(button.getAttribute("data-legacy-goal") || "-")}`,
          metadata: { panel: "lessons" },
        });
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

function renderMemoryValuesPanel() {
  if (!el.memoryPanelValues) return;
  const values = Array.isArray(state.memoryData?.values) ? state.memoryData.values : [];
  const query = (el.memoryChatSearch?.value || "").trim().toLowerCase();
  const filtered = values.filter((row) => {
    if (!query) return true;
    const text = `${row.category || ""} ${row.category_label || ""} ${row.principle || ""} ${row.application || ""}`.toLowerCase();
    return text.includes(query);
  });
  if (!filtered.length) {
    el.memoryPanelValues.innerHTML = '<p class="muted">No values matched your search.</p>';
    return;
  }
  el.memoryPanelValues.innerHTML = filtered
    .slice(-160)
    .reverse()
    .map(
      (row) => `<div class="memory-fact-row">
        <div><strong>${escapeHtml(row.category_label || row.category || "Values")}</strong></div>
        <div><span class="muted">Principle:</span> ${escapeHtml(row.principle || "-")}</div>
        <div><span class="muted">Application:</span> ${escapeHtml(row.application || "-")}</div>
        <div><span class="muted">When:</span> ${escapeHtml(fmtDate(row.timestamp_utc || ""))}</div>
        <div class="row"><button type="button" class="ghost" data-legacy-value="${escapeHtml(
          row.timestamp_utc || row.principle || ""
        )}" data-legacy-principle="${escapeHtml(row.principle || "")}" data-legacy-application="${escapeHtml(
          row.application || ""
        )}">Mark Significant</button></div>
      </div>`
    )
    .join("");
  el.memoryPanelValues.querySelectorAll("button[data-legacy-value]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await markLegacyMoment({
          source_type: "teaching",
          source_id: String(button.getAttribute("data-legacy-value") || ""),
          summary: String(button.getAttribute("data-legacy-principle") || ""),
          details: String(button.getAttribute("data-legacy-application") || ""),
          metadata: { panel: "values" },
        });
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

function renderMemoryReflectionsPanel() {
  if (!el.memoryPanelReflections) return;
  const reflections = Array.isArray(state.memoryData?.reflections) ? state.memoryData.reflections : [];
  const query = (el.memoryChatSearch?.value || "").trim().toLowerCase();
  const filtered = reflections.filter((row) => {
    if (!query) return true;
    const text = `${row.lesson || ""} ${row.goal || ""} ${(row.tags || []).join(" ")} ${row.context || ""}`.toLowerCase();
    return text.includes(query);
  });
  if (!filtered.length) {
    el.memoryPanelReflections.innerHTML = '<p class="muted">No reflections matched your search.</p>';
    return;
  }
  el.memoryPanelReflections.innerHTML = filtered
    .slice(-160)
    .reverse()
    .map(
      (row) => `<div class="memory-fact-row">
        <div><strong>${escapeHtml(row.lesson || "")}</strong></div>
        <div><span class="muted">Context:</span> ${escapeHtml(row.goal || "-")}</div>
        <div><span class="muted">When:</span> ${escapeHtml(fmtDate(row.timestamp_utc || ""))}</div>
      </div>`
    )
    .join("");
}

function renderExplainWhy() {
  if (!el.memoryExplainView) return;
  const data = state.lastExplainWhy || {};
  const citations = Array.isArray(data.citations) ? data.citations : [];
  const memoryInsight =
    data.memory_insight && typeof data.memory_insight === "object" ? data.memory_insight : null;
  const influences = Array.isArray(memoryInsight?.influences) ? memoryInsight.influences : [];
  const insightSummary = String(memoryInsight?.summary || "").trim();
  if (!citations.length && !influences.length && !insightSummary) {
    el.memoryExplainView.innerHTML = '<p class="muted">Ask a question to see cited memory facts and conversation evidence.</p>';
    return;
  }
  const insightHtml =
    memoryInsight && (insightSummary || influences.length)
      ? `<div class="memory-fact-row"><div><strong>Memory Insight</strong></div><div>${escapeHtml(
          insightSummary || "No memory influences recorded."
        )}</div>${
          influences.length
            ? `<div class="stack">${influences
                .map(
                  (item) =>
                    `<div><strong>${escapeHtml(item.reference || item.type || "Memory")}</strong>: ${escapeHtml(
                      item.label || "-"
                    )}<br/><span class="muted">${escapeHtml(item.detail || "")}</span></div>`
                )
                .join("")}</div>`
            : ""
        }</div>`
      : "";
  const citationHtml = citations
    .map((item) => {
      if (item.type === "fact") {
        return `<div class="memory-fact-row"><div><code>${escapeHtml(item.subject || "")}.${escapeHtml(item.predicate || "")}</code> = ${escapeHtml(
          item.object || ""
        )}</div><div class="muted">${escapeHtml(fmtDate(item.timestamp || ""))}</div></div>`;
      }
      if (item.type === "lesson") {
        const tags = Array.isArray(item.tags) ? item.tags.join(", ") : "";
        return `<div class="memory-fact-row"><div><strong>${escapeHtml(item.lesson || "")}</strong></div><div><span class="muted">goal:</span> ${escapeHtml(
          item.goal || "-"
        )}</div><div><span class="muted">tags:</span> ${escapeHtml(tags || "-")}</div><div class="muted">lesson · ${escapeHtml(
          fmtDate(item.timestamp || "")
        )}</div></div>`;
      }
      if (item.type === "value") {
        return `<div class="memory-fact-row"><div><strong>${escapeHtml(item.category_label || item.category || "Values")}</strong></div><div><span class="muted">principle:</span> ${escapeHtml(
          item.principle || "-"
        )}</div><div><span class="muted">application:</span> ${escapeHtml(item.application || "-")}</div><div class="muted">value · ${escapeHtml(
          fmtDate(item.timestamp || "")
        )}</div></div>`;
      }
      if (item.type === "project") {
        const weaknesses = Array.isArray(item.known_weaknesses) ? item.known_weaknesses : [];
        return `<div class="memory-fact-row"><div><strong>${escapeHtml(item.project_slug || item.project_relative_path || "project")}</strong></div><div><span class="muted">architecture:</span> ${escapeHtml(
          item.architecture_summary || "-"
        )}</div><div><span class="muted">testing:</span> ${escapeHtml(item.testing_approach || "-")}</div><div><span class="muted">known weakness:</span> ${escapeHtml(
          weaknesses[0] || "-"
        )}</div><div class="muted">project brain · ${escapeHtml(fmtDate(item.timestamp || ""))}</div></div>`;
      }
      return `<div class="memory-fact-row"><div>${escapeHtml(item.excerpt || item.id || "")}</div><div class="muted">conversation · ${escapeHtml(
        fmtDate(item.timestamp || "")
      )}</div></div>`;
    })
    .join("");
  el.memoryExplainView.innerHTML = `${insightHtml}${citationHtml}`;
}

function setMemoryPanelTab(tabName) {
  const tab = ["facts", "values", "conversations", "lessons", "reflections"].includes(tabName) ? tabName : "facts";
  state.memoryPanelTab = tab;
  const rows = [
    [el.memoryPanelFactsBtn, tab === "facts"],
    [el.memoryPanelValuesBtn, tab === "values"],
    [el.memoryPanelConversationsBtn, tab === "conversations"],
    [el.memoryPanelLessonsBtn, tab === "lessons"],
    [el.memoryPanelReflectionsBtn, tab === "reflections"],
  ];
  rows.forEach(([node, active]) => {
    if (!node) return;
    node.classList.toggle("active", !!active);
    node.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if (el.memoryChatFacts) el.memoryChatFacts.classList.toggle("hidden", tab !== "facts");
  if (el.memoryPanelValues) el.memoryPanelValues.classList.toggle("hidden", tab !== "values");
  if (el.memoryPanelConversations) el.memoryPanelConversations.classList.toggle("hidden", tab !== "conversations");
  if (el.memoryPanelLessons) el.memoryPanelLessons.classList.toggle("hidden", tab !== "lessons");
  if (el.memoryPanelReflections) el.memoryPanelReflections.classList.toggle("hidden", tab !== "reflections");

  renderMemoryChatFacts();
  renderMemoryValuesPanel();
  renderMemoryConversationsPanel();
  renderMemoryLessonsPanel();
  renderMemoryReflectionsPanel();
  renderExplainWhy();
}

function renderUploadAnswer(answerPayload = null) {
  if (!el.uploadAnswerView) return;
  const payload = answerPayload && typeof answerPayload === "object" ? answerPayload : null;
  if (!payload) {
    const analysis = state.selectedUploadDetails?.analysis || {};
    const brief = String(analysis.content_brief || "").trim();
    if (brief) {
      el.uploadAnswerView.textContent = `Content brief:\n${brief}`;
      return;
    }
    const excerpt = String(analysis.text_excerpt || "").trim();
    if (excerpt) {
      el.uploadAnswerView.textContent = `Analysis excerpt:\n${excerpt}`;
      return;
    }
    const summary = String(analysis.summary || "").trim();
    if (summary) {
      el.uploadAnswerView.textContent = summary;
      return;
    }
    el.uploadAnswerView.textContent = "Select or analyze a file to view analysis and ask questions.";
    return;
  }

  const evidenceRows = Array.isArray(payload.evidence) ? payload.evidence : [];
  const evidence = evidenceRows.length
    ? evidenceRows
        .map((item, idx) => {
          if (!item || typeof item !== "object") return `- Evidence ${idx + 1}`;
          const rowType = String(item.type || "evidence");
          if (rowType === "sample_row" && item.row && typeof item.row === "object") {
            const values = Object.entries(item.row)
              .map(([k, v]) => `${k}=${v}`)
              .join(", ");
            return `- sample_row #${item.row_index || "-"}: ${values}`;
          }
          if (rowType === "pdf_excerpt") {
            return `- pdf_excerpt: ${String(item.text || "").trim()}`;
          }
          return `- ${rowType}: ${JSON.stringify(item)}`;
        })
        .join("\n")
    : "- none";
  const confidence = Number(payload.confidence || 0);
  const confidenceLabel = Number.isFinite(confidence) ? `${Math.round(confidence * 100)}%` : "-";
  const answer = String(payload.answer || "").trim() || "No answer returned.";
  const summary = String(payload.analysis_summary || "").trim();
  el.uploadAnswerView.textContent = [
    `Answer: ${answer}`,
    `Confidence: ${confidenceLabel}`,
    summary ? `Analysis summary: ${summary}` : "",
    "Evidence:",
    evidence,
  ]
    .filter(Boolean)
    .join("\n");
}

function renderUploadDetails(details) {
  if (!el.uploadDetailView) return;
  const payload = details && typeof details === "object" ? details : null;
  if (!payload) {
    el.uploadDetailView.innerHTML = '<p class="muted">No upload selected.</p>';
    renderUploadAnswer(null);
    return;
  }

  const analysis = payload.analysis && typeof payload.analysis === "object" ? payload.analysis : {};
  const stats = analysis.stats && typeof analysis.stats === "object" ? analysis.stats : {};
  const headers = Array.isArray(analysis.headers) ? analysis.headers.map((item) => String(item || "")) : [];
  const sampleRowsRaw = Array.isArray(analysis.sample_rows) ? analysis.sample_rows : [];
  const sampleRows = sampleRowsRaw.filter((row) => row && typeof row === "object").slice(0, 8);
  const profilesRaw = Array.isArray(analysis.column_profiles) ? analysis.column_profiles : [];
  const profiles = profilesRaw.filter((row) => row && typeof row === "object").slice(0, 12);
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
  const contentBrief = String(analysis.content_brief || "").trim();
  const fallbackBrief = String(analysis.content_brief_fallback || "").trim();
  const vision = analysis.vision && typeof analysis.vision === "object" ? analysis.vision : {};
  const visionStatus = String(vision.status || "").trim();
  const visionModel = String(vision.model || "").trim();
  const visionSource = String(vision.source || "").trim();
  const visionReason = String(vision.reason || "").trim();
  const visionSummary =
    visionStatus === "applied"
      ? `applied${visionSource ? ` (${visionSource})` : ""}`
      : visionStatus
      ? `${visionStatus}${visionReason ? `: ${visionReason}` : ""}`
      : "";
  const chosenHeaders = headers.length
    ? headers
    : sampleRows.length
    ? Object.keys(sampleRows[0]).map((item) => String(item || ""))
    : [];
  const sampleTable =
    chosenHeaders.length && sampleRows.length
      ? `<div class="upload-sample-wrap"><table class="table upload-sample-table"><thead><tr>${chosenHeaders
          .map((head) => `<th>${escapeHtml(head)}</th>`)
          .join("")}</tr></thead><tbody>${sampleRows
          .map(
            (row) =>
              `<tr>${chosenHeaders
                .map((head) => `<td>${escapeHtml(String(row?.[head] ?? ""))}</td>`)
                .join("")}</tr>`
          )
          .join("")}</tbody></table></div>`
      : '<p class="muted">No sampled table rows available for this file.</p>';

  const statRows = Object.entries(stats)
    .slice(0, 12)
    .map(([key, value]) => `<li><span class="k">${escapeHtml(key)}</span><span>${escapeHtml(String(value))}</span></li>`)
    .join("");
  const warningRows = warnings.length
    ? `<div class="upload-warning-list">${warnings.map((warn) => `<div class="memory-fact-row conflict">${escapeHtml(String(warn || ""))}</div>`).join("")}</div>`
    : "";
  const profileHtml = profiles.length
    ? `<div class="upload-profile-list">${profiles
        .map((profile) => {
          const col = String(profile.name || "-");
          const colType = String(profile.type || "-");
          const nonEmpty = Number(profile.non_empty || 0);
          const missing = Number(profile.missing || 0);
          const unique = Number(profile.unique || 0);
          const topValues = Array.isArray(profile.top_values) ? profile.top_values.slice(0, 4).join(", ") : "";
          const numeric = profile.numeric && typeof profile.numeric === "object" ? profile.numeric : null;
          return `<div class="memory-fact-row">
            <div><strong>${escapeHtml(col)}</strong> <span class="badge workspace">${escapeHtml(colType)}</span></div>
            <div><span class="muted">records:</span> ${escapeHtml(String(nonEmpty + missing))} · <span class="muted">missing:</span> ${escapeHtml(
            String(missing)
          )} · <span class="muted">unique:</span> ${escapeHtml(String(unique))}</div>
            ${topValues ? `<div><span class="muted">top values:</span> ${escapeHtml(topValues)}</div>` : ""}
            ${
              numeric
                ? `<div><span class="muted">numeric:</span> min=${escapeHtml(String(numeric.min ?? "-"))}, max=${escapeHtml(
                    String(numeric.max ?? "-")
                  )}, avg=${escapeHtml(String(numeric.avg ?? "-"))}, sum=${escapeHtml(String(numeric.sum ?? "-"))}</div>`
                : ""
            }
          </div>`;
        })
        .join("")}</div>`
    : '<p class="muted">No column profile data available for this file.</p>';
  const summary = String(analysis.summary || "").trim() || "No summary available.";
  el.uploadDetailView.innerHTML = `
    <div class="memory-fact-row">
      <div><strong>${escapeHtml(String(payload.file_name || "-"))}</strong></div>
      <div><span class="muted">Upload:</span> <code>${escapeHtml(String(payload.upload_id || "-"))}</code></div>
      <div><span class="muted">Type:</span> ${escapeHtml(String(analysis.kind || "-"))} / ${escapeHtml(
    String(analysis.format || "-")
  )}</div>
      <div><span class="muted">Size:</span> ${escapeHtml(fmtBytes(payload.size_bytes || 0))}</div>
      <div><span class="muted">Uploaded:</span> ${escapeHtml(fmtDate(payload.uploaded_at || ""))}</div>
      <div><span class="muted">Summary:</span> ${escapeHtml(summary)}</div>
      ${contentBrief ? `<div><span class="muted">Content brief:</span> ${escapeHtml(contentBrief)}</div>` : ""}
      ${fallbackBrief ? `<div><span class="muted">Fallback brief:</span> ${escapeHtml(fallbackBrief)}</div>` : ""}
      ${visionSummary ? `<div><span class="muted">OCR/Vision:</span> ${escapeHtml(visionSummary)}</div>` : ""}
      ${visionModel ? `<div><span class="muted">Vision model:</span> ${escapeHtml(visionModel)}</div>` : ""}
    </div>
    <details class="memory-fact-row" open>
      <summary><strong>Stats</strong></summary>
      <ul class="kv">${statRows || '<li><span class="k">stats</span><span>-</span></li>'}</ul>
    </details>
    <details class="memory-fact-row" open>
      <summary><strong>Sample Data</strong></summary>
      ${sampleTable}
    </details>
    <details class="memory-fact-row" open>
      <summary><strong>Record Profiles</strong></summary>
      ${profileHtml}
    </details>
    ${warningRows}
  `;
  const last = state.lastUploadAnswer;
  if (last && String(last.upload_id || "") === String(payload.upload_id || "")) {
    renderUploadAnswer(last);
  } else {
    renderUploadAnswer(null);
  }
}

function renderUploadsPanel() {
  if (!el.uploadList || !el.uploadSummary) return;
  const rows = Array.isArray(state.uploads) ? state.uploads : [];
  const selected = String(state.selectedUploadId || "");
  if (!rows.length) {
    el.uploadSummary.textContent = "No uploaded files analyzed yet.";
    el.uploadList.innerHTML = '<p class="muted">Upload a file to start analysis.</p>';
    if (!state.selectedUploadDetails) {
      renderUploadDetails(null);
    }
    return;
  }
  const selectedRow = rows.find((row) => String(row?.upload_id || "") === selected) || null;
  el.uploadSummary.textContent = selectedRow
    ? `Selected: ${selectedRow.file_name || selectedRow.upload_id}`
    : `${rows.length} analyzed uploads`;
  el.uploadList.innerHTML = rows
    .slice(0, 80)
    .map((row) => {
      const uploadId = String(row?.upload_id || "");
      const active = uploadId && uploadId === selected;
      const format = String(row?.format || "").trim() || "-";
      const kind = String(row?.kind || "").trim() || "-";
      const summary = summarizeText(row?.summary || "", 160) || "No summary available.";
      return `<button type="button" class="upload-item ${active ? "active" : ""}" data-upload-select="${escapeHtml(uploadId)}">
        <span class="upload-item-top">
          <span class="upload-item-name">${escapeHtml(String(row?.file_name || uploadId || "upload"))}</span>
          <span class="badge workspace">${escapeHtml(format)}</span>
        </span>
        <span class="upload-item-meta">${escapeHtml(kind)} · ${escapeHtml(fmtBytes(row?.size_bytes || 0))} · ${escapeHtml(
        fmtDate(row?.uploaded_at || "")
      )}</span>
        <span class="upload-item-summary">${escapeHtml(summary)}</span>
      </button>`;
    })
    .join("");

  el.uploadList.querySelectorAll("button[data-upload-select]").forEach((button) => {
    button.addEventListener("click", async () => {
      const uploadId = String(button.getAttribute("data-upload-select") || "").trim();
      if (!uploadId) return;
      try {
        await loadUploadDetails(uploadId);
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

async function loadUploadDetails(uploadId) {
  const cleanId = String(uploadId || "").trim();
  if (!cleanId) return;
  const details = await api(`/api/uploads/${encodeURIComponent(cleanId)}`);
  state.selectedUploadId = cleanId;
  state.selectedUploadDetails = details && typeof details === "object" ? details : null;
  localStorage.setItem("dcc_selected_upload", cleanId);
  renderUploadsPanel();
  renderUploadDetails(state.selectedUploadDetails);
}

async function refreshUploads({ keepSelection = true } = {}) {
  const rows = await api("/api/uploads?limit=240");
  state.uploads = Array.isArray(rows) ? rows : [];
  if (!keepSelection) {
    state.selectedUploadId = "";
    state.selectedUploadDetails = null;
    state.lastUploadAnswer = null;
  }
  const selected = String(state.selectedUploadId || "");
  const exists = selected && state.uploads.some((row) => String(row?.upload_id || "") === selected);
  if (!exists) {
    state.selectedUploadId = "";
    state.selectedUploadDetails = null;
    state.lastUploadAnswer = null;
    localStorage.removeItem("dcc_selected_upload");
  }
  renderUploadsPanel();
  if (state.selectedUploadId) {
    await loadUploadDetails(state.selectedUploadId);
    return;
  }
  const firstId = String(state.uploads[0]?.upload_id || "").trim();
  if (firstId) {
    await loadUploadDetails(firstId);
    return;
  }
  renderUploadDetails(null);
}

async function analyzeUploadFromPicker() {
  const file = el.uploadAnalyzeFile?.files?.[0];
  if (!file) {
    setMessage("Choose a file first to analyze.");
    return;
  }
  const form = new FormData();
  form.append("file", file, file.name || "upload.bin");
  form.append("actor", "web_ui");
  form.append("use_vision", el.uploadVisionMode?.checked ? "true" : "false");
  const visionModel = String(el.uploadVisionModel?.value || "").trim();
  if (visionModel) {
    form.append("vision_model", visionModel);
  }
  const result = await apiMultipart("/api/uploads/analyze", form);
  if (el.uploadAnalyzeFile) {
    el.uploadAnalyzeFile.value = "";
  }
  const uploadId = String(result?.upload_id || "").trim();
  if (uploadId) {
    state.selectedUploadId = uploadId;
    localStorage.setItem("dcc_selected_upload", uploadId);
    state.selectedUploadDetails = result;
    state.lastUploadAnswer = null;
  }
  renderUploadsPanel();
  renderUploadDetails(state.selectedUploadDetails);
  setCliOutput(JSON.stringify(result, null, 2));
  showToast(`Upload analyzed: ${result?.file_name || uploadId || "file"}`);
  await refreshUploads({ keepSelection: true }).catch(() => {});
}

async function askSelectedUploadQuestion() {
  const uploadId = String(state.selectedUploadId || "").trim();
  if (!uploadId) {
    setMessage("Select an analyzed upload first.");
    return;
  }
  const question = String(el.uploadAskInput?.value || "").trim();
  if (!question) {
    setMessage("Enter a question for the selected upload.");
    return;
  }
  const result = await api(`/api/uploads/${encodeURIComponent(uploadId)}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, actor: "web_ui" }),
  });
  state.lastUploadAnswer = result && typeof result === "object" ? result : null;
  renderUploadAnswer(state.lastUploadAnswer);
  setCliOutput(JSON.stringify(result, null, 2));
  if (el.uploadAskInput) {
    el.uploadAskInput.value = "";
  }
  showToast("Upload answer ready.");
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

function renderGrowthMilestoneDetails() {
  if (!el.growthMilestoneDetails) return;
  const rows = Array.isArray(state.growthData?.milestones) ? state.growthData.milestones : [];
  if (!rows.length) {
    el.growthMilestoneDetails.innerHTML = '<p class="muted">Select a milestone to view learned details.</p>';
    return;
  }
  const selected =
    rows.find((item) => String(item?.id || "") === String(state.selectedGrowthMilestoneId || "")) || rows[rows.length - 1];
  state.selectedGrowthMilestoneId = String(selected?.id || "");
  const selectedId = String(selected?.id || "");
  const learned = Array.isArray(selected?.learned) ? selected.learned : [];
  const metrics = selected?.metrics && typeof selected.metrics === "object" ? selected.metrics : {};
  const raw = selected?.raw && typeof selected.raw === "object" ? selected.raw : {};
  el.growthMilestoneDetails.innerHTML = `
    <div class="memory-fact-row">
      <div><strong>${escapeHtml(selected?.title || "Milestone")}</strong></div>
      <div><span class="muted">When:</span> ${escapeHtml(fmtDate(selected?.timestamp_utc || ""))}</div>
      <div><span class="muted">Category:</span> ${escapeHtml(selected?.category || "-")}</div>
      ${raw?.proposal_id ? `<div><span class="muted">Proposal:</span> ${escapeHtml(raw.proposal_id)}</div>` : ""}
      ${raw?.status ? `<div><span class="muted">Proposal status:</span> ${escapeHtml(raw.status)}</div>` : ""}
      ${raw?.trigger ? `<div><span class="muted">Trigger:</span> ${escapeHtml(raw.trigger)}</div>` : ""}
      <div><span class="muted">Details:</span> ${escapeHtml(selected?.details || "-")}</div>
      <div><span class="muted">Learned:</span> ${escapeHtml(learned.join(" | ") || "-")}</div>
      <div><span class="muted">Success rate:</span> ${escapeHtml(String(metrics.success_rate ?? "-"))}</div>
      <div><span class="muted">TDD successes:</span> ${escapeHtml(String(metrics.tdd_success_count ?? "-"))}</div>
      <div><span class="muted">Avg iterations until green:</span> ${escapeHtml(String(metrics.avg_iterations_until_green ?? "-"))}</div>
      <div><span class="muted">Memory size:</span> ${escapeHtml(String(metrics.memory_size_total ?? "-"))}</div>
      <div class="row"><button type="button" class="ghost" data-growth-mark="${escapeHtml(selectedId)}">Mark Significant</button></div>
    </div>
  `;
  const markBtn = el.growthMilestoneDetails.querySelector("button[data-growth-mark]");
  markBtn?.addEventListener("click", async () => {
    try {
      await markLegacyMoment({
        source_type: "milestone",
        source_id: selectedId,
        summary: summarizeText(selected?.title || "Milestone"),
        details: summarizeText(`${selected?.details || ""} ${learned.join(" | ")}`, 1800),
        timestamp_utc: String(selected?.timestamp_utc || ""),
        metadata: {
          category: selected?.category || "",
          run_id: selected?.run_id || "",
        },
      });
    } catch (err) {
      setMessage(err.message);
    }
  });
}

function renderGrowthTimeline(data) {
  if (!el.growthTimeline || !el.growthSummary) return;
  const payload = data && typeof data === "object" ? data : {};
  state.growthData = payload;
  const summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};
  const milestones = Array.isArray(payload.milestones) ? payload.milestones : [];

  kvList(el.growthSummary, [
    ["Goal runs", summary.goal_runs_total ?? 0],
    ["Successful runs", summary.goal_runs_success ?? 0],
    ["TDD completions", summary.tdd_success_count ?? 0],
    ["Avg iterations to green", summary.avg_iterations_until_green ?? "-"],
    ["Memory size", summary.memory_size_total ?? 0],
    ["Facts / Lessons / Reflections", `${summary.facts ?? 0} / ${summary.lessons ?? 0} / ${summary.reflections ?? 0}`],
    ["Self-improvement proposals", summary.self_improvement_total ?? 0],
    ["Autonomous proposals", summary.autonomous_self_improvement_total ?? 0],
    ["Merged improvements", summary.self_improvement_merged ?? 0],
  ]);

  if (!state.selectedGrowthMilestoneId && milestones.length) {
    state.selectedGrowthMilestoneId = String(milestones[milestones.length - 1]?.id || "");
  }

  if (!milestones.length) {
    el.growthTimeline.innerHTML = '<p class="muted">No growth milestones yet.</p>';
    renderGrowthMilestoneDetails();
    return;
  }

  el.growthTimeline.innerHTML = milestones
    .slice()
    .reverse()
    .map((item) => {
      const id = String(item?.id || "");
      const active = id === String(state.selectedGrowthMilestoneId || "");
      const status = item?.category || "milestone";
      return `<button type="button" class="growth-milestone ${active ? "active" : ""}" data-growth-id="${escapeHtml(id)}">
        <span class="growth-milestone-title">${escapeHtml(item?.title || "Milestone")}</span>
        <span class="growth-milestone-meta">${escapeHtml(fmtDate(item?.timestamp_utc || ""))} · ${escapeHtml(status)}</span>
      </button>`;
    })
    .join("");

  el.growthTimeline.querySelectorAll("button[data-growth-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedGrowthMilestoneId = String(button.getAttribute("data-growth-id") || "");
      renderGrowthTimeline(state.growthData || {});
    });
  });

  renderGrowthMilestoneDetails();
}

function renderLegacyArchive(data) {
  if (!el.legacyPanel || !el.legacySummary) return;
  const payload = data && typeof data === "object" ? data : {};
  state.legacyArchive = payload;
  const items = Array.isArray(payload.items) ? payload.items : [];
  const boundaryNote = String(payload.boundary_note || "");
  kvList(el.legacySummary, [
    ["Significant moments", payload.total ?? items.length],
    ["Archive note", boundaryNote || "-"],
  ]);

  if (!items.length) {
    el.legacyPanel.innerHTML = '<p class="muted">No Significant Moments saved yet.</p>';
    return;
  }

  el.legacyPanel.innerHTML = items
    .map((item) => {
      const entryId = String(item?.id || "");
      const sourceType = String(item?.source_type || "manual");
      const summary = String(item?.summary || "-");
      const details = String(item?.details || "").trim();
      const sourceId = String(item?.source_id || "").trim();
      return `<div class="memory-fact-row">
        <div><strong>${escapeHtml(summary)}</strong></div>
        <div><span class="muted">Kind:</span> ${escapeHtml(sourceType)} · <span class="muted">When:</span> ${escapeHtml(
          fmtDate(item?.timestamp_utc || item?.recorded_at || "")
        )}</div>
        ${sourceId ? `<div><span class="muted">Source ID:</span> <code>${escapeHtml(sourceId)}</code></div>` : ""}
        ${details ? `<div>${escapeHtml(details)}</div>` : ""}
        <div class="row"><button type="button" class="ghost" data-legacy-remove="${escapeHtml(entryId)}">Remove</button></div>
      </div>`;
    })
    .join("");

  el.legacyPanel.querySelectorAll("button[data-legacy-remove]").forEach((button) => {
    button.addEventListener("click", async () => {
      const entryId = String(button.getAttribute("data-legacy-remove") || "").trim();
      if (!entryId) return;
      try {
        await api(`/api/legacy_archive/${encodeURIComponent(entryId)}/remove`, {
          method: "POST",
          body: JSON.stringify({ actor: "web_ui" }),
        });
        showToast("Removed from Legacy Archive.");
        await refreshLegacyArchive();
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
}

function renderSelfImprovements(data) {
  if (!el.selfImprovePanel || !el.selfImproveSummary) return;
  const payload = data && typeof data === "object" ? data : {};
  state.selfImprovements = payload;
  const items = Array.isArray(payload.items) ? payload.items : [];
  const pendingCount = Number(payload.pending_count || 0);
  const mergedCount = Number(payload.merged_count || 0);
  const autonomousCount = Number(payload.autonomous_count || 0);
  const sandboxRoot = String(payload.sandbox_root || "-");

  kvList(el.selfImproveSummary, [
    ["Total proposals", payload.total ?? items.length],
    ["Pending approvals", pendingCount],
    ["Merged", mergedCount],
    ["Autonomous proposals", autonomousCount],
    ["Sandbox root", sandboxRoot],
  ]);

  if (!items.length) {
    el.selfImprovePanel.innerHTML = '<p class="muted">No proposed improvements yet.</p>';
    return;
  }

  el.selfImprovePanel.innerHTML = items
    .map((item) => {
      const status = String(item?.status || "pending");
      const canDecide = status === "pending";
      const changes = Array.isArray(item?.changes) ? item.changes : [];
      const decision = item?.decision && typeof item.decision === "object" ? item.decision : {};
      const merge = item?.merge && typeof item.merge === "object" ? item.merge : {};
      const metadata = item?.metadata && typeof item.metadata === "object" ? item.metadata : {};
      const rationale = String(item?.rationale || "").trim();
      const trigger = String(metadata?.trigger || "manual");
      const signalCodes = Array.isArray(metadata?.signal_codes) ? metadata.signal_codes.map((code) => String(code || "").trim()).filter(Boolean) : [];
      const analysisSummary = String(metadata?.analysis_summary || "").trim();
      const autonomous = metadata?.autonomous === true || String(item?.actor || "").toLowerCase().startsWith("david_autonomous");
      const changeHtml = changes.length
        ? changes
            .map((change) => {
              const patch = String(change?.patch || "");
              const path = String(change?.path || "-");
              const badge = change?.change_type || "edited";
              return `<details class="diff-block"><summary>${escapeHtml(path)} (+${escapeHtml(
                change?.added ?? 0
              )} / -${escapeHtml(change?.removed ?? 0)}) <span class="badge ${escapeHtml(badge)}">${escapeHtml(badge)}</span></summary><pre class="code">${
                patch ? formatDiffPatch(patch) : escapeHtml("[no diff preview]")
              }</pre></details>`;
            })
            .join("")
        : '<p class="muted">No change details found.</p>';
      return `<div class="approval">
        <div><strong>${escapeHtml(item?.title || "Untitled proposal")}</strong></div>
        <div class="muted">status=${escapeHtml(status)} · created=${escapeHtml(fmtDate(item?.created_at || ""))}</div>
        <div class="muted">source=${escapeHtml(autonomous ? "autonomous_cycle" : "manual")} · trigger=${escapeHtml(trigger)} · actor=${escapeHtml(item?.actor || "-")}</div>
        <div>${escapeHtml(item?.summary || "-")}</div>
        ${analysisSummary ? `<div><span class="muted">Reasoning:</span> ${escapeHtml(analysisSummary)}</div>` : ""}
        ${signalCodes.length ? `<div><span class="muted">Signals:</span> ${escapeHtml(signalCodes.join(" | "))}</div>` : ""}
        ${rationale ? `<details><summary>Reasoning summary</summary><pre class="code">${escapeHtml(rationale)}</pre></details>` : ""}
        <div class="muted">sandbox=${escapeHtml(item?.sandbox_dir || "-")}</div>
        <div class="stack">${changeHtml}</div>
        ${
          canDecide
            ? `<input data-self-improve-note="${escapeHtml(item?.id || "")}" type="text" placeholder="review note (optional)" />
               <div class="row">
                 <button data-self-improve-id="${escapeHtml(item?.id || "")}" data-self-improve-decision="approve">Approve & Merge</button>
                 <button data-self-improve-id="${escapeHtml(item?.id || "")}" data-self-improve-decision="reject" class="danger">Reject</button>
               </div>`
            : `<div class="muted">Decision: ${escapeHtml(decision?.decision || "-")} by ${escapeHtml(
                decision?.actor || "-"
              )} at ${escapeHtml(fmtDate(decision?.decided_at || ""))}</div>
               <div class="muted">Merge: ${escapeHtml(merge?.merged_at ? fmtDate(merge.merged_at) : "-")}</div>`
        }
      </div>`;
    })
    .join("");

  el.selfImprovePanel.querySelectorAll("button[data-self-improve-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const proposalId = String(button.getAttribute("data-self-improve-id") || "").trim();
      const decision = String(button.getAttribute("data-self-improve-decision") || "").trim();
      if (!proposalId || !decision) return;
      const noteInput = el.selfImprovePanel.querySelector(`input[data-self-improve-note="${proposalId}"]`);
      try {
        await api(`/api/self_improvements/${encodeURIComponent(proposalId)}/decision`, {
          method: "POST",
          body: JSON.stringify({
            decision,
            actor: "web_ui",
            note: noteInput?.value || "",
          }),
        });
        showToast(`Proposal ${decision}: ${proposalId}`);
        await refreshSelfImprovements();
        await refreshStatus().catch(() => {});
      } catch (err) {
        setMessage(err.message);
      }
    });
  });
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
  const safeData = data && typeof data === "object" ? data : {};
  state.settings = safeData;
  applyDemoUiDefaults(safeData);
  state.goalTemplates = Array.isArray(safeData.goal_templates) ? safeData.goal_templates : [];
  if (el.settingSafeMode) {
    el.settingSafeMode.value = String(!!safeData.safe_mode);
  }
  if (el.settingRateLimit) {
    el.settingRateLimit.value = safeData.rate_limit_seconds ?? 3;
  }
  if (el.settingMaxIterations) {
    el.settingMaxIterations.value = safeData.max_iterations_override ?? 0;
  }
  if (el.settingLargeEdit) {
    el.settingLargeEdit.value = safeData.risky_large_edit_bytes ?? 50000;
  }
  if (el.settingMultiFile) {
    el.settingMultiFile.value = safeData.risky_multi_file_threshold ?? 4;
  }
  if (el.settingPreviewDefault) {
    el.settingPreviewDefault.checked = !!safeData.run_preview_default;
  }
  if (el.settingCompanionMode) {
    el.settingCompanionMode.checked = safeData.companion_mode !== false;
  }
  if (el.settingMemoryInsightMode) {
    el.settingMemoryInsightMode.checked = safeData.memory_insight_mode !== false;
  }
  if (el.settingParentTeachingMode) {
    el.settingParentTeachingMode.checked = !!safeData.parent_teaching_mode;
  }
  if (el.settingAutonomousSelfImproveMode) {
    el.settingAutonomousSelfImproveMode.checked = safeData.autonomous_self_improvement_mode !== false;
  }
  if (el.settingDemoMode) {
    el.settingDemoMode.checked = !!safeData.demo_mode || !!state.status?.demo_mode;
  }
  if (el.settingUploadVisionMode) {
    el.settingUploadVisionMode.checked = !!safeData.upload_vision_mode;
  }
  if (el.settingVoiceModeEnabled) {
    el.settingVoiceModeEnabled.checked = !!safeData.voice_mode_enabled;
  }
  if (el.settingVoiceTextOnlyMode) {
    el.settingVoiceTextOnlyMode.checked = !!safeData.voice_text_only_mode;
  }
  if (el.settingVoiceContinuousMode) {
    el.settingVoiceContinuousMode.checked = !!safeData.voice_continuous_mode;
  }
  if (el.settingVoiceInputMode) {
    const savedMode = String(safeData.voice_input_mode || "manual").trim().toLowerCase() || "manual";
    const normalizedMode = savedMode === "ptt" ? "manual" : savedMode;
    el.settingVoiceInputMode.value = normalizedMode === "vad" ? "vad" : "manual";
  }
  if (el.settingVoiceVadThreshold) {
    el.settingVoiceVadThreshold.value = clampVoiceVadThreshold(
      safeData.voice_vad_threshold ?? safeData.vad_threshold,
      0.035
    );
  }
  if (el.settingVoiceVadSilenceMs) {
    el.settingVoiceVadSilenceMs.value = clampVoiceVadSilence(
      safeData.voice_vad_silence_ms ?? safeData.vad_silence_ms,
      900
    );
  }
  if (el.settingVoiceVadMinSpeechMs) {
    el.settingVoiceVadMinSpeechMs.value = clampVoiceVadMinSpeech(
      safeData.voice_vad_min_speech_ms ?? safeData.vad_min_speech_ms,
      300
    );
  }
  if (el.settingVoicePostReplyDelayMs) {
    el.settingVoicePostReplyDelayMs.value = clampVoicePostReplyDelay(safeData.voice_post_reply_delay_ms, 450);
  }
  if (el.settingVoiceStopPhrases) {
    const loadedPhrases = parseVoiceStopPhrases(safeData.voice_stop_phrases);
    el.settingVoiceStopPhrases.value = voiceStopPhrasesDisplay(loadedPhrases);
    state.voice.stopPhrases = loadedPhrases;
  }
  if (el.settingVoiceStyle) {
    el.settingVoiceStyle.value = String(safeData.voice_style || "warm").trim().toLowerCase() || "warm";
  }
  if (el.settingVoiceRate) {
    el.settingVoiceRate.value = clampVoiceRate(safeData.voice_rate, 100);
  }
  if (el.settingVoiceSttEngine) {
    el.settingVoiceSttEngine.value = String(safeData.voice_stt_engine || "none").trim().toLowerCase() || "none";
  }
  if (el.settingVoiceSttModel) {
    el.settingVoiceSttModel.value = String(safeData.voice_stt_model || "base");
  }
  if (el.settingVoiceSttLanguage) {
    el.settingVoiceSttLanguage.value = String(safeData.voice_stt_language || "en");
  }
  if (el.settingVoiceSttCommand) {
    el.settingVoiceSttCommand.value = String(safeData.voice_stt_command || "whisper");
  }
  if (el.settingVoiceWhisperCppCommand) {
    el.settingVoiceWhisperCppCommand.value = String(safeData.voice_whisper_cpp_command || "whisper-cli");
  }
  if (el.settingVoiceWhisperCppModelPath) {
    el.settingVoiceWhisperCppModelPath.value = String(safeData.voice_whisper_cpp_model_path || "");
  }
  if (el.settingVoiceTtsEngine) {
    el.settingVoiceTtsEngine.value = String(safeData.voice_tts_engine || "browser").trim().toLowerCase() || "browser";
  }
  if (el.settingVoiceTtsCommand) {
    el.settingVoiceTtsCommand.value = String(safeData.voice_tts_command || "piper");
  }
  if (el.settingVoiceTtsModelPath) {
    el.settingVoiceTtsModelPath.value = String(safeData.voice_tts_model_path || "");
  }
  if (el.settingVoiceChunkChars) {
    el.settingVoiceChunkChars.value = Number(safeData.voice_chunk_chars || 180);
  }
  if (el.settingPersonalityWarmth) {
    el.settingPersonalityWarmth.value = clampPercent(safeData.personality_warmth, 55);
  }
  if (el.settingPersonalityVerbosity) {
    el.settingPersonalityVerbosity.value = clampPercent(safeData.personality_verbosity, 55);
  }
  if (el.settingPersonalityCuriosity) {
    el.settingPersonalityCuriosity.value = clampPercent(safeData.personality_curiosity, 50);
  }
  renderPersonalityCalibrationLabels();
  if (el.settingTddMode) {
    el.settingTddMode.checked = !!safeData.tdd_mode;
  }
  state.parentTeachingMode = !!safeData.parent_teaching_mode;
  if (el.parentTeachingMode) {
    el.parentTeachingMode.checked = state.parentTeachingMode;
  }
  state.voice.enabled = !!safeData.voice_mode_enabled;
  state.voice.style = String(safeData.voice_style || "warm").trim().toLowerCase() || "warm";
  if (!["warm", "balanced", "clear"].includes(state.voice.style)) {
    state.voice.style = "warm";
  }
  state.voice.rate = clampVoiceRate(safeData.voice_rate, 100);
  state.voice.textOnlyMode = !!safeData.voice_text_only_mode;
  state.voice.continuousMode = !!safeData.voice_continuous_mode;
  state.voice.continuousPaused = false;
  state.voice.postReplyDelayMs = clampVoicePostReplyDelay(safeData.voice_post_reply_delay_ms, 450);
  state.voice.inputMode = String(safeData.voice_input_mode || "manual").trim().toLowerCase() || "manual";
  if (state.voice.inputMode === "ptt") {
    state.voice.inputMode = "manual";
  }
  if (!["manual", "vad"].includes(state.voice.inputMode)) {
    state.voice.inputMode = "manual";
  }
  state.voice.vadThreshold = clampVoiceVadThreshold(safeData.voice_vad_threshold ?? safeData.vad_threshold, 0.035);
  state.voice.vadSilenceMs = clampVoiceVadSilence(safeData.voice_vad_silence_ms ?? safeData.vad_silence_ms, 900);
  state.voice.vadMinSpeechMs = clampVoiceVadMinSpeech(
    safeData.voice_vad_min_speech_ms ?? safeData.vad_min_speech_ms,
    300
  );
  if (el.voiceContinuousMode) {
    el.voiceContinuousMode.checked = !!state.voice.continuousMode;
  }
  state.voice.stopPhrases = parseVoiceStopPhrases(safeData.voice_stop_phrases);
  resetVoiceSttFallbackCache();
  state.voice.vadSilenceCountdownMs = 0;
  setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
  renderVoiceRateLabel();
  renderVoiceVadLabel();
  if (el.voiceTextOnlyMode) {
    el.voiceTextOnlyMode.checked = !!state.voice.textOnlyMode;
  }
  syncVoiceUiState();

  const modelDefaults = [
    safeData.model,
    safeData.planner_model_default,
    safeData.coder_model_default,
    safeData.critic_model_default,
    ...(Array.isArray(state.models) ? state.models : []),
  ]
    .map((item) => String(item || "").trim())
    .filter(Boolean);
  const uniqueModels = [...new Set(modelDefaults)];
  setSelectOptions(
    el.settingPlannerModel,
    uniqueModels,
    safeData.planner_model || safeData.planner_model_default || safeData.model
  );
  setSelectOptions(
    el.settingCoderModel,
    uniqueModels,
    safeData.coder_model || safeData.coder_model_default || safeData.model
  );
  setSelectOptions(
    el.settingCriticModel,
    uniqueModels,
    safeData.critic_model || safeData.critic_model_default || safeData.model
  );
  setSelectOptions(
    el.settingUploadVisionModel,
    uniqueModels,
    safeData.upload_vision_model || "",
    "Default model"
  );
  setSelectOptions(
    el.uploadVisionModel,
    uniqueModels,
    safeData.upload_vision_model || "",
    "Default model"
  );
  if (el.uploadVisionMode) {
    el.uploadVisionMode.checked = !!safeData.upload_vision_mode;
  }
  if (el.uploadVisionHint) {
    const enabled = !!safeData.upload_vision_mode;
    const modelText = String(safeData.upload_vision_model || "").trim() || String(safeData.model || "").trim() || "default";
    el.uploadVisionHint.textContent = enabled
      ? `OCR/Vision enrichment is enabled by default. Current model: ${modelText}.`
      : "OCR/Vision enrichment is off by default. You can still enable it per upload below.";
  }
  renderTemplateSelects();

  if (el.goalTddMode) {
    el.goalTddMode.checked = !!safeData.tdd_mode;
    state.pendingGoalRunOptions.tddMode = !!safeData.tdd_mode;
  }
  if (el.cliTddMode && state.pendingCliRunOptions.templateId === "") {
    el.cliTddMode.checked = !!safeData.tdd_mode;
    state.pendingCliRunOptions.tddMode = !!safeData.tdd_mode;
  }
  refreshRunOptionSummary();
  const voiceInputMode = (() => {
    const raw = String(safeData.voice_input_mode || "manual").trim().toLowerCase();
    return raw === "ptt" ? "manual" : raw || "manual";
  })();
  kvList(el.settingsInfo, [
    ["Model", safeData.model || "-"],
    ["Planner model", safeData.planner_model || safeData.planner_model_default || "-"],
    ["Coder model", safeData.coder_model || safeData.coder_model_default || "-"],
    ["Critic model", safeData.critic_model || safeData.critic_model_default || "-"],
    ["Default TDD mode", fmtBool(safeData.tdd_mode)],
    ["Companion mode", fmtBool(safeData.companion_mode !== false)],
    ["Memory Insight Mode", fmtBool(safeData.memory_insight_mode !== false)],
    ["Parent Teaching Mode", fmtBool(safeData.parent_teaching_mode)],
    ["Upload OCR/Vision mode", fmtBool(safeData.upload_vision_mode)],
    ["Upload OCR/Vision model", safeData.upload_vision_model || safeData.model || "-"],
    ["Voice mode", fmtBool(safeData.voice_mode_enabled)],
    ["Voice input mode", voiceInputMode],
    ["Voice continual mode", fmtBool(safeData.voice_continuous_mode)],
    ["Voice post-reply delay (ms)", String(safeData.voice_post_reply_delay_ms ?? 450)],
    ["Voice stop phrases", voiceStopPhrasesDisplay(safeData.voice_stop_phrases || [])],
    ["Voice VAD threshold", String(safeData.voice_vad_threshold ?? safeData.vad_threshold ?? 0.035)],
    ["Voice VAD silence (ms)", String(safeData.voice_vad_silence_ms ?? safeData.vad_silence_ms ?? 900)],
    ["Voice VAD min speech (ms)", String(safeData.voice_vad_min_speech_ms ?? safeData.vad_min_speech_ms ?? 300)],
    ["Voice style", safeData.voice_style || "warm"],
    ["Voice rate", voiceRateDescriptor(safeData.voice_rate ?? 100)],
    ["Voice STT engine", safeData.voice_stt_engine || "none"],
    ["Voice TTS engine", safeData.voice_tts_engine || "browser"],
    ["Voice text-only default", fmtBool(safeData.voice_text_only_mode)],
    ["Demo mode", fmtBool(safeData.demo_mode)],
    ["Demo env override", fmtBool(safeData.demo_mode_env_override)],
    ["Warmth", calibrationDescriptor("warmth", safeData.personality_warmth ?? 55)],
    ["Verbosity", calibrationDescriptor("verbosity", safeData.personality_verbosity ?? 55)],
    ["Curiosity", calibrationDescriptor("curiosity", safeData.personality_curiosity ?? 50)],
    ["Allowed commands", (safeData.allowed_commands || []).join(", ")],
    ["Workspace", safeData.workspace_dir || "-"],
    ["Default max iterations", safeData.max_iterations_default || 0],
    ["Goal templates", (state.goalTemplates || []).length],
  ]);
  renderDemoBadge();
  renderVersionStamp();
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

async function loadReplay(runId, iteration, mode = "live") {
  const isImport = mode === "import";
  const endpoint = isImport
    ? `/api/bundles/import/${encodeURIComponent(runId)}/replay?iteration=${encodeURIComponent(iteration)}`
    : `/api/run/${encodeURIComponent(runId)}/replay?iteration=${encodeURIComponent(iteration)}`;
  try {
    const replay = await api(endpoint);
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

async function loadAudit(runId, mode = "live") {
  const isImport = mode === "import";
  const endpoint = isImport
    ? `/api/bundles/import/${encodeURIComponent(runId)}/audit?limit=300`
    : `/api/run/${encodeURIComponent(runId)}/audit?limit=300`;
  try {
    const audit = await api(endpoint);
    el.approvalAudit.textContent = JSON.stringify(audit, null, 2);
  } catch (err) {
    el.approvalAudit.textContent = err.message;
  }
}

async function loadRun(runId) {
  try {
    state.runViewerMode = "live";
    state.runReadOnlyView = false;
    const details = await api(`/api/run/${encodeURIComponent(runId)}`);
    const files = await api(`/api/run/${encodeURIComponent(runId)}/files`);
    state.selectedRunDetails = details;
    state.selectedRunFiles = files;

    renderTimeline(details);
    renderExecutionPanels(el.executionPanels, details.iterations || []);
    renderDiffs(details);
    renderArtifacts(details);
    renderFileTree(files);
    renderRunHealthSummary(details.health_summary, false);
    await loadReplay(runId, state.selectedIteration || 1, "live");
    await loadAudit(runId, "live");

    if (state.lastCliRunId === runId) {
      setCliOutput(JSON.stringify(details.result || {}, null, 2));
      renderExecutionPanels(el.cliExecPanel, details.iterations || []);
    }
  } catch (err) {
    setMessage(err.message);
  }
}

async function loadImportedBundle(importId) {
  if (!importId) return;
  try {
    const details = await api(`/api/bundles/import/${encodeURIComponent(importId)}`);
    const files = await api(`/api/bundles/import/${encodeURIComponent(importId)}/files`);
    state.selectedRunDetails = details;
    state.selectedRunFiles = files;
    state.selectedRunId = String(details.run_id || state.selectedRunId || "");
    if (el.diffRunId && state.selectedRunId) {
      el.diffRunId.value = state.selectedRunId;
    }
    state.runViewerMode = "import";
    state.runReadOnlyView = true;

    renderTimeline(details);
    renderExecutionPanels(el.executionPanels, details.iterations || []);
    renderDiffs(details);
    renderArtifacts(details);
    renderFileTree(files);
    renderRunHealthSummary(details.health_summary, true);
    await loadReplay(importId, state.selectedIteration || 1, "import");
    await loadAudit(importId, "import");

    if (state.lastCliRunId === state.selectedRunId) {
      setCliOutput(JSON.stringify(details.result || {}, null, 2));
      renderExecutionPanels(el.cliExecPanel, details.iterations || []);
    }
  } catch (err) {
    setMessage(err.message);
  }
}

async function openRunTab(runId) {
  state.runViewerMode = "live";
  state.runReadOnlyView = false;
  state.selectedImportedBundleId = "";
  activateTab("runs");
  el.diffRunId.value = runId;
  await loadRun(runId);
}

async function openDiffTab(runId) {
  state.runViewerMode = "live";
  state.runReadOnlyView = false;
  state.selectedImportedBundleId = "";
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
  renderApprovals(Array.isArray(approvals) ? approvals : []);
}

async function refreshRuns() {
  const search = encodeURIComponent(el.runSearch.value.trim());
  const status = encodeURIComponent(el.runStatusFilter.value.trim());
  state.runs = await api(`/api/runs?search=${search}&status=${status}&limit=120`);
  renderRuns();
  handleRunCompletionNotification();

  const hasSelected = state.runs.some((item) => item.id === state.selectedRunId);
  if (state.runViewerMode === "live" && !hasSelected) {
    const preferredRunId =
      state.status?.active_run_id ||
      (state.runs.length ? state.runs[0].id : "");
    state.selectedRunId = preferredRunId || "";
    if (state.selectedRunId) {
      localStorage.setItem("dcc_selected_run", state.selectedRunId);
    }
  }

  if (state.runViewerMode === "live" && state.selectedRunId) {
    state.runReadOnlyView = false;
    await loadRun(state.selectedRunId);
  } else if (state.runViewerMode === "import" && state.selectedImportedBundleId) {
    state.runReadOnlyView = true;
    await loadImportedBundle(state.selectedImportedBundleId);
  } else {
    renderFileTree(null);
    renderRunHealthSummary({}, false);
  }
}

async function refreshImportedBundles() {
  const rows = await api("/api/bundles/imports?limit=120");
  state.importedBundles = Array.isArray(rows) ? rows : [];
  if (state.selectedImportedBundleId) {
    const exists = state.importedBundles.some((row) => String(row.import_id || "") === state.selectedImportedBundleId);
    if (!exists) {
      state.selectedImportedBundleId = "";
      if (state.runViewerMode === "import") {
        state.runViewerMode = "live";
        state.runReadOnlyView = false;
      }
    }
  }
  renderImportedBundles();
}

async function refreshMemory() {
  const query = encodeURIComponent((el.memoryChatSearch?.value || "").trim());
  const [snapshotResult, factsResult, conversationsResult, sessionsResult] = await Promise.allSettled([
    api("/api/memory"),
    api(`/api/memory/facts?query=${query}&limit=800`),
    api("/api/memory/conversations?limit=1200"),
    api("/api/chat/sessions?limit=120"),
  ]);

  const snapshot =
    snapshotResult.status === "fulfilled" && snapshotResult.value && typeof snapshotResult.value === "object"
      ? snapshotResult.value
      : state.memoryData || {};
  const factsData =
    factsResult.status === "fulfilled" && factsResult.value && typeof factsResult.value === "object"
      ? factsResult.value
      : state.memoryFactsData || {};
  const conversationsData =
    conversationsResult.status === "fulfilled" && conversationsResult.value && typeof conversationsResult.value === "object"
      ? conversationsResult.value
      : state.memoryConversationsData || {};
  const sessions = sessionsResult.status === "fulfilled" && Array.isArray(sessionsResult.value) ? sessionsResult.value : state.chatSessions || [];

  state.memoryData = snapshot;
  state.memoryFactsData = factsData;
  state.memoryConversationsData = conversationsData;
  state.chatSessions = Array.isArray(sessions) ? sessions : [];
  syncChatMessagesFromConversations(conversationsData?.conversations || []);
  renderMemory(snapshot);
  renderChatSessions();
  setMemoryPanelTab(state.memoryPanelTab || "facts");
  renderChatHistory();
}

async function refreshTelemetry() {
  renderTelemetry(await api("/api/telemetry/tail?limit=250"));
}

async function refreshGrowth() {
  renderGrowthTimeline(await api("/api/growth_timeline?limit=240"));
}

async function refreshLegacyArchive() {
  renderLegacyArchive(await api("/api/legacy_archive?limit=260"));
}

async function refreshSelfImprovements() {
  renderSelfImprovements(await api("/api/self_improvements?limit=200"));
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
          if (payload.type === "memory_chat_response") {
            const response = mem.response || {};
            const selectedIntent = mem.selected_intent || "chat";
            const assistantText =
              mem.assistant_turn?.text ||
              response.answer ||
              response.reply ||
              response.message ||
              "Response received.";
            const kind = selectedIntent === "ask" ? "ask" : selectedIntent === "teach" ? "teach" : "system";
            pushChatMessage(kind, assistantText, {
              message_id: mem.assistant_turn?.message_id,
              session_id: mem.session_id || mem.assistant_turn?.session_id || state.selectedChatSessionId,
              response,
              citations: response.citations || [],
              memory_insight: response.memory_insight || {},
              conflicts: response.conflicts || [],
            });
            if (response?.citations || response?.memory_insight) {
              state.lastExplainWhy = {
                citations: response.citations || [],
                memory_insight: response.memory_insight || {},
              };
            }
            if (mem?.session_id) {
              state.selectedChatSessionId = mem.session_id;
              localStorage.setItem("dcc_chat_session_id", mem.session_id);
            }
            const crisisSupport = !!mem?.crisis_support || /\b(988|immediate danger|hurt yourself|self-harm)\b/i.test(String(assistantText || ""));
            setVoiceCrisisOverlay(crisisSupport);
          } else if (payload.type === "memory_ask_answered") {
            const hitCount = Number(mem.matched_count || 0);
            const suffix = hitCount > 0 ? ` (matched facts: ${hitCount})` : "";
            pushChatMessage("ask", `${mem.answer || "No answer returned."}${suffix}`, {
              memory_insight: mem.memory_insight || {},
              citations: mem.citations || [],
            });
            state.lastExplainWhy = {
              citations: mem.citations || [],
              memory_insight: mem.memory_insight || {},
            };
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
          } else if (payload.type === "memory_teach_overwrite_confirmed") {
            pushChatMessage("teach", `Overwrite confirmed. Saved ${Number(mem.stored_count || 0)} facts.`, {
              conflicts: mem.conflicts || [],
            });
          }
        }
        await refreshMemory().catch(() => {});
        await refreshGrowth().catch(() => {});
        await refreshLegacyArchive().catch(() => {});
      }
      if (String(payload?.type || "") === "upload_analyzed") {
        await refreshUploads({ keepSelection: true }).catch(() => {});
      }
      if (String(payload?.type || "") === "upload_question_answered") {
        const uploadPayload = payload.payload && typeof payload.payload === "object" ? payload.payload : {};
        if (String(uploadPayload.upload_id || "") === String(state.selectedUploadId || "")) {
          state.lastUploadAnswer = uploadPayload;
          renderUploadAnswer(uploadPayload);
        }
      }
      const growthEventTypes = new Set([
        "run_success",
        "run_failed",
        "run_stopped",
        "run_rejected",
        "memory_reflection_saved",
        "self_improvement_proposed",
        "self_improvement_decision",
        "self_improvement_merged",
      ]);
      if (growthEventTypes.has(String(payload?.type || ""))) {
        await refreshGrowth().catch(() => {});
      }
      const selfImproveEventTypes = new Set(["self_improvement_proposed", "self_improvement_decision", "self_improvement_merged"]);
      if (selfImproveEventTypes.has(String(payload?.type || ""))) {
        await refreshSelfImprovements().catch(() => {});
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
  pushChatMessage("ask", `${result.answer || "No answer returned."}${suffix}`, {
    session_id: state.selectedChatSessionId,
    citations: result.citations || [],
    memory_insight: result.memory_insight || {},
  });
  state.lastExplainWhy = {
    citations: result.citations || [],
    memory_insight: result.memory_insight || {},
  };
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
      { conflicts: result.conflicts || [], session_id: state.selectedChatSessionId }
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
  pushChatMessage("teach", summary, { conflicts: result.conflicts || [], session_id: state.selectedChatSessionId });
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
  state.runViewerMode = "live";
  state.runReadOnlyView = false;
  state.selectedImportedBundleId = "";
  state.selectedRunId = result.run_id;
  localStorage.setItem("dcc_selected_run", result.run_id);
  setupRunStream(result.run_id);
  pushChatMessage("system", `Goal queued: ${result.run_id}`, { session_id: state.selectedChatSessionId });
  setCliOutput(`queued run: ${result.run_id}`);
  await refreshRuns();
  await refreshStatus();
}

async function confirmPendingOverwrite(decision = "approve") {
  const overwriteId = String(state.pendingOverwriteId || "").trim();
  if (!overwriteId) {
    setCliOutput("No pending overwrite to confirm.");
    return;
  }
  const result = await api("/api/memory/confirm_overwrite", {
    method: "POST",
    body: JSON.stringify({ overwrite_id: overwriteId, decision, actor: "web_ui" }),
  });
  state.pendingOverwriteId = "";
  state.pendingTeachMessage = "";
  if (el.memoryConfirmTeachBtn) {
    el.memoryConfirmTeachBtn.classList.add("hidden");
  }
  if (String(result.status || "") === "stored") {
    pushChatMessage("teach", `Overwrite confirmed. Saved ${Number(result.stored_count || 0)} facts.`, {
      conflicts: result.conflicts || [],
      session_id: result.session_id || state.selectedChatSessionId,
      citations: result.citations || [],
    });
  } else {
    pushChatMessage("system", "Overwrite request rejected.");
  }
  setCliOutput(JSON.stringify(result, null, 2));
  await refreshMemory().catch(() => {});
}

function setVoiceTranscriptPreview(text) {
  if (!el.voiceTranscriptPreview) return;
  const clean = String(text || "").trim();
  el.voiceTranscriptPreview.textContent = clean || "Transcript preview appears here after speech recognition.";
}

function setVoiceAssistantPreview(text) {
  if (!el.voiceAssistantPreview) return;
  const clean = String(text || "").trim();
  el.voiceAssistantPreview.classList.toggle("hidden", !clean);
  el.voiceAssistantPreview.textContent = clean;
}

function setVoiceCrisisOverlay(active, text = "") {
  if (!el.voiceCrisisOverlay) return;
  const enabled = !!active;
  el.voiceCrisisOverlay.classList.toggle("hidden", !enabled);
  if (enabled && String(text || "").trim()) {
    el.voiceCrisisOverlay.textContent = String(text || "").trim();
  }
}

function nextVoiceTurnId() {
  state.voice.turnCounter = Number(state.voice.turnCounter || 0) + 1;
  return `voice_${Date.now()}_${state.voice.turnCounter}`;
}

function handleVoiceBargeIn(reason = "") {
  const hasPlayback = !!state.voice.audioPlaying || Number(state.voice.pendingSpeechCount || 0) > 0;
  const hasStream = !!state.voice.streamAbortController || !!state.voice.transcribeAbortController;
  if (!hasPlayback && !state.voice.generating && !hasStream) return;
  clearVoiceRearmTimer();
  abortVoiceStream();
  abortVoiceTranscription();
  clearVoiceAudioQueue(true);
  state.voice.generating = false;
  state.voice.partialAssistant = "";
  setVoiceAssistantPreview("");
  transitionVoiceTurn("arm");
  if (reason) {
    setCliOutput(`Voice barge-in: ${reason}`);
  }
}

function beginVoiceTurn(reason = "") {
  state.voice.activeTurnId = nextVoiceTurnId();
  state.voice.ttsMode = "none";
  handleVoiceBargeIn(reason);
}

function renderVoiceModeHint() {
  if (!el.voiceModeHint) return;
  if (state.voice.continuousMode) {
    const phrases = voiceStopPhrasesDisplay(state.voice.stopPhrases);
    el.voiceModeHint.textContent = `Continual Voice Chat is ${state.voice.continuousPaused ? "paused" : "active"}: listen -> transcribe -> respond -> speak -> auto-listen. Stop phrases: ${phrases}.`;
    return;
  }
  if (state.voice.inputMode === "vad") {
    el.voiceModeHint.textContent = `Auto (VAD) arms the mic, starts above ${voiceVadThresholdDescriptor(
      state.voice.vadThreshold
    )}, stops after ${state.voice.vadSilenceMs}ms silence, and keeps clips over ${state.voice.vadMinSpeechMs}ms.`;
    return;
  }
  el.voiceModeHint.textContent = "Manual mode: click Start Listening, then Send to submit.";
}

function setVoiceInputMode(mode, { syncSetting = true } = {}) {
  const raw = String(mode || "").trim().toLowerCase();
  const normalized = raw === "vad" ? "vad" : "manual";
  if (state.voice.continuousMode && normalized !== "vad") {
    state.voice.continuousMode = false;
    state.voice.continuousPaused = false;
    clearVoiceRearmTimer();
    if (el.voiceContinuousMode) el.voiceContinuousMode.checked = false;
    if (el.settingVoiceContinuousMode) el.settingVoiceContinuousMode.checked = false;
  }
  if (state.voice.inputMode === normalized) return;
  state.voice.inputMode = normalized;
  if (syncSetting && el.settingVoiceInputMode) {
    el.settingVoiceInputMode.value = normalized;
  }
  if (normalized !== "vad") {
    stopVoiceVad({ submit: false }).catch(() => {});
    setVoiceTurnState("idle");
  } else {
    setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
  }
  renderVoiceModeHint();
  syncVoiceUiState();
}

function updateVoiceSpeakingState() {
  const speaking = !!state.voice.audioPlaying || Number(state.voice.pendingSpeechCount || 0) > 0;
  state.voice.speaking = speaking;
  syncVoiceUiState();
}

function renderVoiceMeter(level = 0) {
  if (!el.voiceMicMeter) return;
  const numeric = Number(level);
  const clamped = Number.isFinite(numeric) ? Math.max(0, Math.min(1, numeric * 8)) : 0;
  el.voiceMicMeter.style.width = `${Math.round(clamped * 100)}%`;
}

function clearVoiceAudioQueue(stopActive = false) {
  state.voice.audioQueue = [];
  if (stopActive && state.voice.activeAudio) {
    try {
      state.voice.activeAudio.pause();
    } catch (_) {}
    state.voice.activeAudio = null;
  }
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  state.voice.pendingSpeechCount = 0;
  state.voice.audioPlaying = false;
  updateVoiceSpeakingState();
}

function abortVoiceStream() {
  if (state.voice.streamAbortController) {
    try {
      state.voice.streamAbortController.abort();
    } catch (_) {}
    state.voice.streamAbortController = null;
  }
}

function abortVoiceTranscription() {
  if (state.voice.transcribeAbortController) {
    try {
      state.voice.transcribeAbortController.abort();
    } catch (_) {}
    state.voice.transcribeAbortController = null;
  }
}

async function cancelVoiceTurn({ disarmAuto = false, reason = "" } = {}) {
  abortVoiceStream();
  abortVoiceTranscription();
  abortBrowserSpeechRecognition();
  clearVoiceAudioQueue(true);
  state.voice.generating = false;
  state.voice.partialAssistant = "";
  state.voice.autoSubmitAfterStop = false;
  setVoiceAssistantPreview("");
  if (reason) {
    setCliOutput(reason);
  }
  if (state.voice.listening || state.voice.recordingStarting) {
    await stopVoiceListening({
      submit: false,
      keepStream: !!state.voice.vadActive && !disarmAuto,
    });
  }
  if (disarmAuto) {
    await stopVoiceVad({ submit: false });
    setVoiceTurnState("idle");
  } else if (state.voice.vadActive) {
    setVoiceTurnState("listening_armed");
  } else {
    setVoiceTurnState("idle");
  }
  syncVoiceUiState();
}

function playNextVoiceAudioChunk() {
  if (!state.voice.audioQueue.length) {
    state.voice.audioPlaying = false;
    state.voice.activeAudio = null;
    updateVoiceSpeakingState();
    return;
  }
  const next = state.voice.audioQueue.shift();
  if (!next || (next.turnId && next.turnId !== state.voice.activeTurnId)) {
    playNextVoiceAudioChunk();
    return;
  }
  const audio = new Audio(next.src);
  state.voice.activeAudio = audio;
  state.voice.audioPlaying = true;
  updateVoiceSpeakingState();
  const finish = () => {
    state.voice.activeAudio = null;
    playNextVoiceAudioChunk();
  };
  audio.onended = finish;
  audio.onerror = finish;
  audio.play().catch(() => finish());
}

function enqueueVoiceAudioChunk(audioBase64, mimeType = "audio/wav") {
  const encoded = String(audioBase64 || "").trim();
  if (!encoded || state.voice.muted || state.voice.textOnlyMode) return;
  if (state.voice.ttsMode && state.voice.ttsMode !== "backend") return;
  const turnId = state.voice.activeTurnId || "";
  state.voice.audioQueue.push({
    src: `data:${mimeType || "audio/wav"};base64,${encoded}`,
    turnId,
  });
  if (!state.voice.audioPlaying) {
    playNextVoiceAudioChunk();
  }
}

function pickBrowserSpeechVoice() {
  if (!window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices() || [];
  if (!voices.length) return null;
  return voices.find((row) => /^en(-|_)/i.test(String(row.lang || ""))) || voices[0] || null;
}

function voiceStylePitch(style) {
  const normalized = String(style || "warm").toLowerCase();
  if (normalized === "clear") return 1.0;
  if (normalized === "balanced") return 0.97;
  return 1.05;
}

function speakVoiceChunkBrowser(text) {
  const chunk = String(text || "").trim();
  if (!chunk || state.voice.muted || state.voice.textOnlyMode || !window.speechSynthesis) return;
  const utterance = new SpeechSynthesisUtterance(chunk);
  utterance.rate = Math.max(0.6, Math.min(2.0, clampVoiceRate(state.voice.rate, 100) / 100));
  utterance.pitch = voiceStylePitch(state.voice.style);
  const voice = pickBrowserSpeechVoice();
  if (voice) utterance.voice = voice;
  state.voice.pendingSpeechCount = Number(state.voice.pendingSpeechCount || 0) + 1;
  utterance.onstart = () => {
    updateVoiceSpeakingState();
  };
  const onComplete = () => {
    state.voice.pendingSpeechCount = Math.max(0, Number(state.voice.pendingSpeechCount || 0) - 1);
    updateVoiceSpeakingState();
  };
  utterance.onend = onComplete;
  utterance.onerror = onComplete;
  window.speechSynthesis.speak(utterance);
}

function stopVoiceWaveform() {
  if (state.voice.waveformRaf) {
    cancelAnimationFrame(state.voice.waveformRaf);
    state.voice.waveformRaf = 0;
  }
  const canvas = el.voiceWaveform;
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(125, 132, 145, 0.18)";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(110, 180, 255, 0.34)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();
  renderVoiceMeter(0);
}

function startVoiceWaveform() {
  stopVoiceWaveform();
  const canvas = el.voiceWaveform;
  const analyser = state.voice.analyser;
  if (!canvas || !analyser) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.width;
  const height = canvas.height;
  const data = new Uint8Array(analyser.fftSize);

  const draw = () => {
    if ((!state.voice.listening && !state.voice.monitoring) || !state.voice.analyser) {
      stopVoiceWaveform();
      return;
    }
    analyser.getByteTimeDomainData(data);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "rgba(17, 24, 39, 0.52)";
    ctx.fillRect(0, 0, width, height);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(65, 214, 255, 0.95)";
    ctx.beginPath();
    const step = width / data.length;
    for (let i = 0; i < data.length; i += 1) {
      const x = i * step;
      const y = (data[i] / 255) * height;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
    renderVoiceMeter(computeVadLevel());
    state.voice.waveformRaf = requestAnimationFrame(draw);
  };

  draw();
}

function cleanupVoiceAudioResources() {
  if (state.voice.mediaStream) {
    (state.voice.mediaStream.getTracks() || []).forEach((track) => {
      try {
        track.stop();
      } catch (_) {}
    });
  }
  if (state.voice.audioContext) {
    try {
      state.voice.audioContext.close();
    } catch (_) {}
  }
  state.voice.mediaStream = null;
  state.voice.audioContext = null;
  state.voice.analyser = null;
  state.voice.monitoring = false;
  state.voice.vadBuffer = null;
  state.voice.vadLevel = 0;
  state.voice.vadSilenceCountdownMs = 0;
  renderVoiceMeter(0);
}

function syncVoiceUiState() {
  const enabled = !!state.voice.enabled;
  const inputMode = state.voice.inputMode === "vad" ? "vad" : "manual";
  const continual = !!state.voice.continuousMode;
  const paused = continual && !!state.voice.continuousPaused;
  const inFlight = !!state.voice.generating || !!state.voice.streamAbortController || !!state.voice.transcribeAbortController;
  const canStopNow =
    !!state.voice.listening || !!state.voice.recordingStarting || inFlight || !!state.voice.speaking || !!state.voice.vadActive;
  setSegmentButton(el.voiceModePttBtn, inputMode === "manual");
  setSegmentButton(el.voiceModeVadBtn, inputMode === "vad");
  renderVoiceModeHint();
  if (el.voiceStartBtn) {
    const activeManual = inputMode === "manual" && !!state.voice.listening;
    const activeAuto = inputMode === "vad" && !!state.voice.vadActive;
    const startDisabled = !enabled || !!state.voice.recordingStarting || (continual && !paused);
    el.voiceStartBtn.disabled = startDisabled || activeAuto;
    el.voiceStartBtn.classList.remove("hidden");
    el.voiceStartBtn.classList.toggle("active", activeManual || activeAuto);
    el.voiceStartBtn.setAttribute("aria-pressed", activeManual || activeAuto ? "true" : "false");
    if (continual && paused) {
      el.voiceStartBtn.textContent = "Resume";
    } else if (continual) {
      el.voiceStartBtn.textContent = "Continual Active";
    } else if (inputMode === "vad") {
      el.voiceStartBtn.textContent = "Start Listening";
    } else if (activeManual) {
      el.voiceStartBtn.textContent = "Send";
    } else {
      el.voiceStartBtn.textContent = "Start Listening";
    }
  }
  if (el.voiceStopBtn) {
    el.voiceStopBtn.disabled = !enabled || !canStopNow;
    el.voiceStopBtn.classList.remove("hidden");
    el.voiceStopBtn.textContent = continual ? "End Conversation" : "Stop";
    el.voiceStopBtn.setAttribute("aria-pressed", canStopNow ? "true" : "false");
  }
  if (el.voicePauseBtn) {
    el.voicePauseBtn.disabled = !enabled || !continual || paused;
    el.voicePauseBtn.classList.toggle("hidden", !continual || paused);
  }
  if (el.voiceResumeBtn) {
    el.voiceResumeBtn.disabled = !enabled || !continual || !paused;
    el.voiceResumeBtn.classList.toggle("hidden", !continual || !paused);
  }
  if (el.voiceEndConversationBtn) {
    el.voiceEndConversationBtn.disabled = !enabled || !continual;
    el.voiceEndConversationBtn.classList.toggle("hidden", !continual);
  }
  if (el.voiceContinuousMode) {
    el.voiceContinuousMode.checked = continual;
    el.voiceContinuousMode.disabled = !enabled;
  }
  if (el.voiceMuteBtn) {
    el.voiceMuteBtn.classList.toggle("active", !!state.voice.muted);
    el.voiceMuteBtn.setAttribute("aria-pressed", state.voice.muted ? "true" : "false");
    el.voiceMuteBtn.textContent = state.voice.muted ? "Unmute" : "Mute";
  }
  if (el.voiceTextOnlyMode) {
    el.voiceTextOnlyMode.checked = !!state.voice.textOnlyMode;
  }
  if (el.voiceAutoIndicator) {
    const autoActive = enabled && inputMode === "vad" && (state.voice.vadActive || state.voice.turnState === "listening_armed") && !paused;
    el.voiceAutoIndicator.classList.toggle("hidden", !autoActive);
    el.voiceAutoIndicator.classList.toggle("active", autoActive);
  }
  if (el.voiceContinualIndicator) {
    const active = enabled && continual;
    el.voiceContinualIndicator.classList.toggle("hidden", !active);
    el.voiceContinualIndicator.classList.toggle("active", active);
  }
  if (el.voicePausedIndicator) {
    const active = enabled && continual && paused;
    el.voicePausedIndicator.classList.toggle("hidden", !active);
    el.voicePausedIndicator.classList.toggle("active", active);
  }
  if (el.voiceStatusText) {
    if (!enabled) el.voiceStatusText.textContent = "Voice disabled. Enable Voice Mode in Settings.";
    else if (continual && paused) el.voiceStatusText.textContent = "Continual conversation paused.";
    else if (state.voice.turnState === "listening_armed")
      el.voiceStatusText.textContent = "Listening (Auto). Speak to start recording.";
    else if (state.voice.turnState === "recording" && inputMode === "vad") {
      const countdown = Math.max(0, Math.round(Number(state.voice.vadSilenceCountdownMs || 0)));
      if (countdown > 0) {
        const seconds = (countdown / 1000).toFixed(1);
        el.voiceStatusText.textContent = `Recording (Auto). Silence countdown: ${seconds}s`;
      } else {
        el.voiceStatusText.textContent = "Recording (Auto)...";
      }
    } else if (state.voice.turnState === "recording" && !!state.voice.browserRecognition) {
      el.voiceStatusText.textContent = "Listening (Browser STT fallback)... click Send or Stop.";
    } else if (state.voice.turnState === "recording") {
      el.voiceStatusText.textContent = "Recording (Manual)... click Send or Stop to cancel.";
    } else if (state.voice.turnState === "stopping") {
      el.voiceStatusText.textContent = "Stopping recording...";
    } else if (state.voice.turnState === "transcribing") {
      el.voiceStatusText.textContent = "Transcribing audio...";
    } else if (state.voice.turnState === "responding" || state.voice.generating) {
      el.voiceStatusText.textContent = "Generating response...";
    } else if (state.voice.speaking) {
      el.voiceStatusText.textContent = "Playback active.";
    } else {
      el.voiceStatusText.textContent = "Voice ready.";
    }
  }
  if (el.voiceTypingIndicator) {
    el.voiceTypingIndicator.classList.toggle("hidden", !state.voice.generating);
    el.voiceTypingIndicator.classList.toggle("active", !!state.voice.generating);
  }
  if (el.voicePlaybackIndicator) {
    const active = !!state.voice.speaking && !state.voice.muted && !state.voice.textOnlyMode;
    el.voicePlaybackIndicator.classList.toggle("hidden", !active);
    el.voicePlaybackIndicator.classList.toggle("active", active);
  }
}

function voiceCaptureSupported() {
  return !!navigator.mediaDevices?.getUserMedia && typeof window.MediaRecorder !== "undefined";
}

function browserSpeechRecognitionCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function browserSpeechRecognitionSupported() {
  return typeof browserSpeechRecognitionCtor() === "function";
}

function resetVoiceSttFallbackCache() {
  state.voice.sttFallbackMode = "local";
  state.voice.sttFallbackReason = "";
  state.voice.sttFallbackCheckedAt = 0;
}

function clearVoiceRearmTimer() {
  if (state.voice.rearmTimer) {
    clearTimeout(state.voice.rearmTimer);
    state.voice.rearmTimer = 0;
  }
}

function matchesVoiceStopPhrase(text) {
  const spoken = String(text || "").trim().toLowerCase();
  if (!spoken) return false;
  const phrases = Array.isArray(state.voice.stopPhrases) ? state.voice.stopPhrases : [];
  return phrases.some((phrase) => phrase && spoken.includes(String(phrase).toLowerCase()));
}

function stopContinualVoiceChat(reason = "Continual conversation ended.") {
  state.voice.continuousMode = false;
  state.voice.continuousPaused = false;
  clearVoiceRearmTimer();
  if (el.voiceContinuousMode) {
    el.voiceContinuousMode.checked = false;
  }
  if (el.settingVoiceContinuousMode) {
    el.settingVoiceContinuousMode.checked = false;
  }
  setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
  renderVoiceModeHint();
  syncVoiceUiState();
  if (reason) {
    setCliOutput(reason);
    showToast(reason);
  }
}

async function pauseContinualVoiceChat(reason = "Continual voice chat paused.") {
  state.voice.continuousPaused = true;
  clearVoiceRearmTimer();
  await cancelVoiceTurn({ disarmAuto: true, reason });
  renderVoiceModeHint();
  syncVoiceUiState();
}

async function resumeContinualVoiceChat() {
  if (!state.voice.continuousMode) return;
  state.voice.continuousPaused = false;
  renderVoiceModeHint();
  syncVoiceUiState();
  const fallback = await resolveVoiceSttFallback().catch(() => ({ useBrowser: false, reason: "" }));
  if (fallback.useBrowser) {
    await pauseContinualVoiceChat("Continual mode requires local STT + VAD. Configure Whisper or whisper.cpp, then resume.");
    return;
  }
  if (state.voice.inputMode !== "vad") {
    setVoiceInputMode("vad");
  }
  if (!state.voice.vadActive) {
    await startVoiceVad();
  }
}

function voiceEchoGuardActive() {
  return !!state.voice.audioPlaying || Number(state.voice.pendingSpeechCount || 0) > 0 || !!state.voice.activeAudio;
}

function scheduleContinualRearm(reason = "next_turn", delayMs = null) {
  if (!state.voice.continuousMode || state.voice.continuousPaused) return;
  clearVoiceRearmTimer();
  const delay = delayMs == null ? state.voice.postReplyDelayMs : clampVoicePostReplyDelay(delayMs, state.voice.postReplyDelayMs);
  state.voice.rearmTimer = setTimeout(async () => {
    state.voice.rearmTimer = 0;
    if (!state.voice.enabled || !state.voice.continuousMode || state.voice.continuousPaused) return;
    if (state.voice.generating || state.voice.streamAbortController || state.voice.transcribeAbortController || voiceEchoGuardActive()) {
      scheduleContinualRearm(reason, 220);
      return;
    }
    const fallback = await resolveVoiceSttFallback().catch(() => ({ useBrowser: false, reason: "" }));
    if (fallback.useBrowser) {
      await pauseContinualVoiceChat("Continual mode paused: local STT is unavailable for VAD turns.");
      return;
    }
    if (state.voice.inputMode !== "vad") {
      setVoiceInputMode("vad");
    }
    if (!state.voice.vadActive) {
      try {
        await startVoiceVad();
      } catch (_) {
        await pauseContinualVoiceChat("Continual mode paused: could not re-arm microphone.");
      }
    }
  }, Math.max(0, delay));
}

async function resolveVoiceSttFallback() {
  if (!browserSpeechRecognitionSupported()) {
    return { useBrowser: false, reason: "" };
  }
  const now = Date.now();
  if (now - Number(state.voice.sttFallbackCheckedAt || 0) < 30000) {
    return {
      useBrowser: state.voice.sttFallbackMode === "browser",
      reason: String(state.voice.sttFallbackReason || ""),
    };
  }
  const diagnostics = await fetchVoiceDiagnostics();
  const sttReady = !!diagnostics?.ok && !!diagnostics?.data?.stt?.ready;
  const reason = String(diagnostics?.data?.stt?.error || diagnostics?.error || "Local STT is unavailable.").trim();
  const useBrowser = !sttReady;
  state.voice.sttFallbackMode = useBrowser ? "browser" : "local";
  state.voice.sttFallbackReason = reason;
  state.voice.sttFallbackCheckedAt = now;
  return { useBrowser, reason };
}

function abortBrowserSpeechRecognition() {
  const recognition = state.voice.browserRecognition;
  clearVoiceRearmTimer();
  if (!recognition) return;
  state.voice.autoSubmitAfterStop = false;
  try {
    recognition.abort();
  } catch (_) {}
  state.voice.browserRecognition = null;
  state.voice.browserTranscriptFinal = "";
  state.voice.browserTranscriptInterim = "";
  state.voice.listening = false;
  state.voice.recordingStarting = false;
}

async function startBrowserSpeechListening({ announceFallback = false } = {}) {
  const RecognitionCtor = browserSpeechRecognitionCtor();
  if (typeof RecognitionCtor !== "function") {
    throw new Error("Browser speech recognition is not available in this browser.");
  }
  if (!state.voice.enabled) {
    showToast("Enable Voice Mode in Settings first.");
    return;
  }
  if (state.voice.browserRecognition || state.voice.listening || state.voice.recordingStarting) return;

  state.voice.recordingStarting = true;
  clearVoiceAudioQueue(true);
  beginVoiceTurn("browser stt fallback");
  setVoiceCrisisOverlay(false);
  setVoiceAssistantPreview("");
  setVoiceTranscriptPreview("");
  const turnId = state.voice.activeTurnId || nextVoiceTurnId();
  state.voice.activeTurnId = turnId;

  const recognition = new RecognitionCtor();
  recognition.lang = String(el.settingVoiceSttLanguage?.value || "en").trim() || "en";
  recognition.interimResults = true;
  recognition.continuous = true;
  recognition.maxAlternatives = 1;
  state.voice.browserRecognition = recognition;
  state.voice.browserTranscriptFinal = "";
  state.voice.browserTranscriptInterim = "";
  state.voice.autoSubmitAfterStop = true;
  state.voice.keepStreamOnStop = false;
  state.voice.listening = true;
  state.voice.generating = false;
  state.voice.recordingStarting = false;
  transitionVoiceTurn("start_recording");
  syncVoiceUiState();
  if (announceFallback) {
    showToast("Using browser speech recognition fallback.");
  }

  recognition.onresult = (event) => {
    if (state.voice.browserRecognition !== recognition) return;
    let finalText = String(state.voice.browserTranscriptFinal || "");
    let interimText = "";
    for (let i = Number(event?.resultIndex || 0); i < Number(event?.results?.length || 0); i += 1) {
      const row = event.results[i];
      const transcript = String(row?.[0]?.transcript || "").trim();
      if (!transcript) continue;
      if (row?.isFinal) {
        finalText = `${finalText} ${transcript}`.trim();
      } else {
        interimText = `${interimText} ${transcript}`.trim();
      }
    }
    state.voice.browserTranscriptFinal = finalText;
    state.voice.browserTranscriptInterim = interimText;
    setVoiceTranscriptPreview(`${finalText} ${interimText}`.trim());
  };

  recognition.onerror = (event) => {
    const code = String(event?.error || "").trim().toLowerCase();
    if (!code || code === "aborted") return;
    setCliOutput(`Browser STT error: ${code}`);
  };

  recognition.onend = () => {
    if (state.voice.browserRecognition !== recognition) return;
    state.voice.browserRecognition = null;
    state.voice.listening = false;
    state.voice.recordingStarting = false;
    const transcript = `${state.voice.browserTranscriptFinal} ${state.voice.browserTranscriptInterim}`.trim();
    state.voice.browserTranscriptFinal = "";
    state.voice.browserTranscriptInterim = "";
    transitionVoiceTurn("complete");
    if (state.voice.vadActive) {
      transitionVoiceTurn("arm");
    }
    syncVoiceUiState();
    if (!state.voice.autoSubmitAfterStop) return;
    if (!transcript) {
      setCliOutput("No speech captured from microphone.");
      setVoiceTranscriptPreview("No speech captured.");
      return;
    }
    if (state.voice.continuousMode && matchesVoiceStopPhrase(transcript)) {
      pauseContinualVoiceChat("Continual voice chat stopped by phrase.")
        .then(() => stopContinualVoiceChat("Continual voice chat stopped by phrase."))
        .catch(() => stopContinualVoiceChat("Continual voice chat stopped by phrase."));
      return;
    }
    setVoiceTranscriptPreview(transcript);
    if (el.memoryChatInput) {
      el.memoryChatInput.value = transcript;
    }
    updateIntentPreview();
    handleVoiceChatStream(transcript, { turnId }).catch((err) => {
      const message = err?.message || "Voice stream failed.";
      setCliOutput(message);
      pushChatMessage("system", message, { session_id: state.selectedChatSessionId });
    });
  };

  try {
    recognition.start();
  } catch (err) {
    state.voice.browserRecognition = null;
    state.voice.listening = false;
    state.voice.recordingStarting = false;
    setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
    syncVoiceUiState();
    throw new Error(err?.message || "Browser speech recognition failed to start.");
  }
}

async function ensureVoiceStream() {
  if (state.voice.mediaStream) return;
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  const audioContext = AudioCtx ? new AudioCtx() : null;
  let analyser = null;
  if (audioContext) {
    const source = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
  }
  state.voice.mediaStream = stream;
  state.voice.audioContext = audioContext;
  state.voice.analyser = analyser;
  state.voice.vadBuffer = analyser ? new Uint8Array(analyser.fftSize) : null;
}

async function startVoiceRecording({ keepStream = false } = {}) {
  if (!state.voice.enabled) {
    showToast("Enable Voice Mode in Settings first.");
    return;
  }
  if (state.voice.listening || state.voice.recordingStarting) return;
  if (!voiceCaptureSupported()) {
    setCliOutput("Voice capture is not supported in this browser.");
    return;
  }
  state.voice.recordingStarting = true;
  clearVoiceAudioQueue(true);
  beginVoiceTurn("new speech");
  setVoiceCrisisOverlay(false);
  setVoiceAssistantPreview("");
  try {
    await ensureVoiceStream();
    const stream = state.voice.mediaStream;
    if (!stream) throw new Error("Microphone stream is not available.");

    const mimeCandidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
    const chosenMime = mimeCandidates.find((candidate) => window.MediaRecorder.isTypeSupported(candidate)) || "";
    const recorder = chosenMime ? new MediaRecorder(stream, { mimeType: chosenMime }) : new MediaRecorder(stream);
    state.voice.recorder = recorder;
    state.voice.chunks = [];
    state.voice.autoSubmitAfterStop = true;
    state.voice.keepStreamOnStop = !!keepStream;
    state.voice.listening = true;
    state.voice.generating = false;
    state.voice.recordingStarting = false;
    state.voice.vadSpeechMs = 0;
    state.voice.vadLastFrameAt = 0;
    state.voice.vadSilenceSince = 0;
    state.voice.vadSilenceCountdownMs = 0;
    transitionVoiceTurn("start_recording");
    setVoiceTranscriptPreview("");
    syncVoiceUiState();
    startVoiceWaveform();

    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        state.voice.chunks.push(event.data);
      }
    };
    recorder.onerror = () => {
      setCliOutput("Voice recording failed.");
      state.voice.listening = false;
      setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
      syncVoiceUiState();
    };
    recorder.onstop = async () => {
      const chunks = Array.isArray(state.voice.chunks) ? state.voice.chunks.slice() : [];
      const mimeType = String(recorder.mimeType || "audio/webm");
      state.voice.recorder = null;
      state.voice.chunks = [];
      if (!state.voice.keepStreamOnStop) {
        cleanupVoiceAudioResources();
        stopVoiceWaveform();
      } else if (!state.voice.monitoring) {
        stopVoiceWaveform();
      }
      transitionVoiceTurn("complete");
      if (state.voice.vadActive) {
        transitionVoiceTurn("arm");
      }
      syncVoiceUiState();
      if (!state.voice.autoSubmitAfterStop) return;
      const blob = new Blob(chunks, { type: mimeType });
      if (!blob.size) {
        setCliOutput("No speech captured from microphone.");
        setVoiceTranscriptPreview("No speech captured.");
        return;
      }
      try {
        await transcribeVoiceBlob(blob);
      } catch (err) {
        if (err?.name === "AbortError") {
          return;
        }
        const message = err?.message || "Voice transcription failed.";
        const hint = voiceSttRecoveryHint(message);
        const detail = hint ? `${message}\n${hint}` : message;
        setCliOutput(detail);
        pushChatMessage("system", detail, { session_id: state.selectedChatSessionId });
        if (hint) {
          showToast("Voice STT is not ready. Check Settings.");
        }
      }
    };
    recorder.start(250);
  } catch (err) {
    cleanupVoiceAudioResources();
    stopVoiceWaveform();
    state.voice.listening = false;
    state.voice.recorder = null;
    state.voice.recordingStarting = false;
    setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
    syncVoiceUiState();
    const message = err?.message || "Microphone access failed.";
    setCliOutput(message);
    showToast("Microphone permission is required for voice mode.");
  }
}

async function stopVoiceListening({ submit = true, keepStream = false } = {}) {
  const recorder = state.voice.recorder;
  const browserRecognition = state.voice.browserRecognition;
  state.voice.autoSubmitAfterStop = !!submit;
  state.voice.keepStreamOnStop = !!keepStream;
  state.voice.listening = false;
  state.voice.recordingStarting = false;
  state.voice.vadSilenceCountdownMs = 0;
  transitionVoiceTurn("stop_request");
  syncVoiceUiState();
  if (browserRecognition) {
    try {
      browserRecognition.stop();
    } catch (_) {
      abortBrowserSpeechRecognition();
      setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
      syncVoiceUiState();
    }
    return;
  }
  if (!recorder) {
    if (!keepStream && !state.voice.monitoring) {
      cleanupVoiceAudioResources();
      stopVoiceWaveform();
    }
    setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
    return;
  }
  try {
    recorder.stop();
  } catch (_) {
    if (!keepStream) {
      cleanupVoiceAudioResources();
      stopVoiceWaveform();
    }
    state.voice.recorder = null;
    state.voice.chunks = [];
    setVoiceTurnState(state.voice.vadActive ? "listening_armed" : "idle");
    syncVoiceUiState();
  }
}

async function startVoiceListening() {
  if (state.voice.inputMode !== "manual") return;
  const fallback = await resolveVoiceSttFallback().catch(() => ({ useBrowser: false, reason: "" }));
  if (fallback.useBrowser) {
    const reason = String(fallback.reason || "Local STT is unavailable.").trim();
    setCliOutput(`${reason}\nUsing browser speech recognition fallback.`);
    await startBrowserSpeechListening({ announceFallback: true });
    return;
  }
  await startVoiceRecording({ keepStream: false });
}

async function startVoiceVad() {
  if (!state.voice.enabled) {
    showToast("Enable Voice Mode in Settings first.");
    return;
  }
  if (state.voice.vadActive) return;
  if (!voiceCaptureSupported()) {
    setCliOutput("Voice capture is not supported in this browser.");
    return;
  }
  const fallback = await resolveVoiceSttFallback().catch(() => ({ useBrowser: false, reason: "" }));
  if (fallback.useBrowser) {
    const reason = String(fallback.reason || "Local STT is unavailable.").trim();
    if (state.voice.continuousMode) {
      await pauseContinualVoiceChat("Continual mode requires local STT + VAD. Configure STT and resume.");
      return;
    }
    setVoiceInputMode("manual");
    setCliOutput(`${reason}\nAuto (VAD) requires local STT. Switched to Manual mode with browser speech fallback.`);
    await startBrowserSpeechListening({ announceFallback: true });
    return;
  }
  try {
    await ensureVoiceStream();
    if (!state.voice.analyser) {
      throw new Error("Audio analyser unavailable. Auto VAD requires Web Audio support.");
    }
    state.voice.vadActive = true;
    state.voice.vadAboveThresholdSince = 0;
    state.voice.vadSilenceSince = 0;
    state.voice.vadSpeechMs = 0;
    state.voice.vadLastFrameAt = 0;
    state.voice.vadSilenceCountdownMs = 0;
    state.voice.vadLastSpeech = 0;
    state.voice.monitoring = true;
    setVoiceTurnState("listening_armed");
    renderVoiceModeHint();
    syncVoiceUiState();
    startVoiceWaveform();
    startVoiceVadLoop();
  } catch (err) {
    cleanupVoiceAudioResources();
    stopVoiceWaveform();
    state.voice.vadActive = false;
    state.voice.monitoring = false;
    syncVoiceUiState();
    const message = err?.message || "Microphone access failed.";
    setCliOutput(message);
    showToast("Microphone permission is required for voice mode.");
  }
}

async function stopVoiceVad({ submit = true } = {}) {
  if (!state.voice.vadActive && !state.voice.monitoring) return;
  state.voice.vadActive = false;
  state.voice.monitoring = false;
  if (state.voice.vadRaf) {
    cancelAnimationFrame(state.voice.vadRaf);
    state.voice.vadRaf = 0;
  }
  if (state.voice.listening) {
    await stopVoiceListening({ submit, keepStream: false });
  } else {
    cleanupVoiceAudioResources();
    stopVoiceWaveform();
  }
  setVoiceTurnState("idle");
  state.voice.vadSilenceCountdownMs = 0;
  syncVoiceUiState();
}

function computeVadLevel() {
  const analyser = state.voice.analyser;
  if (!analyser) return 0;
  let buffer = state.voice.vadBuffer;
  if (!buffer || buffer.length !== analyser.fftSize) {
    buffer = new Uint8Array(analyser.fftSize);
    state.voice.vadBuffer = buffer;
  }
  analyser.getByteTimeDomainData(buffer);
  let sum = 0;
  for (let i = 0; i < buffer.length; i += 1) {
    const normalized = (buffer[i] - 128) / 128;
    sum += normalized * normalized;
  }
  return Math.sqrt(sum / buffer.length);
}

function startVoiceVadLoop() {
  if (state.voice.vadRaf) {
    cancelAnimationFrame(state.voice.vadRaf);
    state.voice.vadRaf = 0;
  }
  const loop = () => {
    if (!state.voice.vadActive) {
      state.voice.vadRaf = 0;
      return;
    }
    const now = performance.now();
    state.voice.vadLevel = computeVadLevel();
    if (!state.voice.listening && !state.voice.recordingStarting) {
      if (state.voice.turnState !== "transcribing" && state.voice.turnState !== "responding") {
        setVoiceTurnState("listening_armed");
      }
    }

    const frame = evaluateVadFrame({
      nowMs: now,
      level: state.voice.vadLevel,
      threshold: state.voice.vadThreshold,
      silenceMs: state.voice.vadSilenceMs,
      minSpeechMs: state.voice.vadMinSpeechMs,
      debounceMs: VOICE_VAD_START_DEBOUNCE_MS,
      turnState: state.voice.turnState,
      aboveSinceMs: state.voice.vadAboveThresholdSince,
      silenceSinceMs: state.voice.vadSilenceSince,
      speechMs: state.voice.vadSpeechMs,
      lastFrameMs: state.voice.vadLastFrameAt,
    });
    state.voice.vadAboveThresholdSince = frame.aboveSinceMs;
    state.voice.vadSilenceSince = frame.silenceSinceMs;
    state.voice.vadSpeechMs = frame.speechMs;
    state.voice.vadLastFrameAt = frame.lastFrameMs;
    const priorCountdownMs = Number(state.voice.vadSilenceCountdownMs || 0);
    state.voice.vadSilenceCountdownMs = frame.silenceCountdownMs;
    if (Math.abs(priorCountdownMs - state.voice.vadSilenceCountdownMs) >= 40) {
      syncVoiceUiState();
    }

    if (frame.bargeInSignal && (state.voice.speaking || state.voice.generating)) {
      handleVoiceBargeIn("speech detected while assistant audio was active");
    }

    if (frame.shouldStartRecording && !state.voice.listening && !state.voice.recordingStarting) {
      startVoiceRecording({ keepStream: true }).catch((err) => {
        setCliOutput(err?.message || "Auto VAD recording failed.");
      });
    } else if (frame.shouldStopRecording && state.voice.listening) {
      const keep = frame.shouldAccept;
      stopVoiceListening({ submit: keep, keepStream: true }).catch(() => {});
      if (!keep) {
        setCliOutput(
          `Ignored short noise burst (${Math.round(state.voice.vadSpeechMs)}ms < ${state.voice.vadMinSpeechMs}ms).`
        );
        setVoiceTranscriptPreview("Ignored short noise burst.");
      }
      state.voice.vadSpeechMs = 0;
      state.voice.vadSilenceSince = 0;
      state.voice.vadAboveThresholdSince = 0;
      state.voice.vadSilenceCountdownMs = 0;
    }

    state.voice.vadRaf = requestAnimationFrame(loop);
  };
  state.voice.vadRaf = requestAnimationFrame(loop);
}

function parseSseBlock(rawBlock) {
  const block = String(rawBlock || "").trim();
  if (!block) return null;
  const lines = block.split(/\r?\n/);
  let event = "message";
  const dataLines = [];
  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim() || "message";
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  });
  const rawData = dataLines.join("\n");
  if (!rawData) return { event, data: {} };
  try {
    return { event, data: JSON.parse(rawData) };
  } catch (_) {
    return { event, data: { raw: rawData } };
  }
}

async function streamJsonSse(path, payload, onEvent, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.csrfToken) {
    headers["X-CSRF-Token"] = state.csrfToken;
  }
  const response = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(payload || {}),
    signal: options?.signal || undefined,
  });
  if (!response.ok) {
    const json = await response.json().catch(() => ({}));
    throw new Error(json?.error || json?.data?.error || `Request failed (${response.status})`);
  }
  if (!response.body) {
    throw new Error("Streaming response body is not available.");
  }
  const decoder = new TextDecoder("utf-8");
  const reader = response.body.getReader();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) {
        await onEvent(parsed);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) {
      await onEvent(parsed);
    }
  }
}

function formatLatency(ms) {
  if (!Number.isFinite(ms)) return "-";
  return `${Math.round(ms)}ms`;
}

function voiceSttRecoveryHint(errorMessage) {
  const message = String(errorMessage || "").trim();
  if (!message) return "";
  if (/Local command not found:\s*whisper/i.test(message) || /Whisper CLI command not found/i.test(message)) {
    return "Voice STT is set to Whisper CLI, but `whisper` is not installed. Install Whisper CLI or change STT engine in Settings.";
  }
  if (/Voice STT is disabled/i.test(message)) {
    return "Voice STT is disabled. Open Settings and choose an STT engine, or use typed chat input.";
  }
  if (/whisper\\.cpp model path is missing|whisper\\.cpp model path not found/i.test(message)) {
    return "whisper.cpp is selected, but model path is invalid. Set a valid model path in Settings.";
  }
  return "";
}

function renderVoiceDiagnostics(checks, statusText) {
  if (el.voiceDiagnosticsStatus) {
    el.voiceDiagnosticsStatus.textContent = statusText || "Diagnostics complete.";
  }
  if (el.voiceDiagnosticsList) {
    el.voiceDiagnosticsList.innerHTML = (checks || [])
      .map((check) => {
        const ok = !!check.ok;
        const pillClass = ok ? "voice-diag-pill voice-diag-pass" : "voice-diag-pill voice-diag-fail";
        const errorLine = check.error ? `<div class="muted">Last error: ${escapeHtml(check.error)}</div>` : "";
        const latencyLine =
          typeof check.latencyMs === "number"
            ? `<div class="muted">Latency: ${escapeHtml(formatLatency(check.latencyMs))}</div>`
            : "";
        return `
          <div class="voice-diag-row">
            <div class="voice-diag-header">
              <strong>${escapeHtml(check.label || "Check")}</strong>
              <span class="${pillClass}">${ok ? "Pass" : "Fail"}</span>
            </div>
            ${latencyLine}
            ${errorLine}
          </div>
        `;
      })
      .join("");
  }
  if (el.voiceDiagnosticsSteps) {
    const steps = [];
    (checks || []).forEach((check) => {
      if (check.ok) return;
      if (check.id === "microphone") {
        steps.push(
          "Microphone permissions:\n- Allow microphone access for localhost in browser site settings.\n- Close other apps using the mic.\n- Reload the Dashboard after granting permission."
        );
        return;
      }
      if (check.id === "stt") {
        steps.push(
          "STT readiness:\n- Enable Voice Mode in Settings.\n- Select Whisper CLI or whisper.cpp.\n- Verify the command is on PATH and model paths are valid."
        );
        return;
      }
      if (check.id === "tts") {
        steps.push(
          "TTS readiness:\n- For browser speech, ensure speechSynthesis is available and not blocked.\n- For Piper, set the command and model path correctly."
        );
        return;
      }
      if (check.id === "sse") {
        steps.push(
          "Streaming connectivity:\n- Confirm the local server is running.\n- Refresh the page and retry.\n- Check firewall or VPN settings blocking localhost."
        );
      }
    });
    el.voiceDiagnosticsSteps.value = steps.length ? steps.join("\n\n") : "All checks passed.";
  }
}

async function checkMicrophoneDiagnostics() {
  const started = performance.now();
  if (state.voice.mediaStream) {
    return { ok: true, latencyMs: 0 };
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return { ok: false, error: "Microphone capture is not supported in this browser." };
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    (stream.getTracks() || []).forEach((track) => {
      try {
        track.stop();
      } catch (_) {}
    });
    return { ok: true, latencyMs: performance.now() - started };
  } catch (err) {
    return {
      ok: false,
      error: err?.message || "Microphone access failed.",
      latencyMs: performance.now() - started,
    };
  }
}

async function fetchVoiceDiagnostics() {
  const started = performance.now();
  try {
    const data = await api("/api/voice/diagnostics");
    return { ok: true, data, latencyMs: performance.now() - started };
  } catch (err) {
    return { ok: false, error: err?.message || "Voice diagnostics failed.", latencyMs: performance.now() - started };
  }
}

async function checkVoiceSseDiagnostics() {
  const started = performance.now();
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 3500);
  try {
    const response = await fetch("/api/voice/stream/ping", { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`SSE ping failed (${response.status})`);
    }
    if (!response.body) {
      throw new Error("Streaming response body is not available.");
    }
    const decoder = new TextDecoder("utf-8");
    const reader = response.body.getReader();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSseBlock(block);
        if (parsed) {
          clearTimeout(timeoutId);
          reader.cancel().catch(() => {});
          return { ok: true, latencyMs: performance.now() - started };
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
    throw new Error("No SSE response received.");
  } catch (err) {
    const error = err?.name === "AbortError" ? "SSE ping timed out." : err?.message || "SSE ping failed.";
    return { ok: false, error, latencyMs: performance.now() - started };
  } finally {
    clearTimeout(timeoutId);
  }
}

async function runVoiceDiagnostics() {
  if (!el.voiceDiagnosticsRunBtn) return;
  el.voiceDiagnosticsRunBtn.disabled = true;
  try {
    renderVoiceDiagnostics([], "Running diagnostics...");
    const mic = await checkMicrophoneDiagnostics();
    const backend = await fetchVoiceDiagnostics();
    const sse = await checkVoiceSseDiagnostics();

    const sttReady = backend.ok && backend.data?.stt?.ready;
    const ttsEngine = backend.ok ? String(backend.data?.tts?.engine || "") : "";
    let ttsReady = backend.ok && backend.data?.tts?.ready;
    let ttsError = backend.ok ? String(backend.data?.tts?.error || "") : backend.error || "";
    if (ttsEngine === "browser" && !window.speechSynthesis) {
      ttsReady = false;
      ttsError = "Browser speech synthesis is unavailable.";
    }

    const checks = [
      {
        id: "microphone",
        label: "Microphone permission",
        ok: mic.ok,
        latencyMs: mic.latencyMs,
        error: mic.ok ? "" : mic.error,
      },
      {
        id: "stt",
        label: "STT readiness",
        ok: !!sttReady,
        latencyMs: backend.latencyMs,
        error: sttReady ? "" : String(backend.data?.stt?.error || backend.error || "STT check failed."),
      },
      {
        id: "tts",
        label: "TTS readiness",
        ok: !!ttsReady,
        latencyMs: backend.latencyMs,
        error: ttsReady ? "" : ttsError || "TTS check failed.",
      },
      {
        id: "sse",
        label: "SSE streaming connectivity",
        ok: sse.ok,
        latencyMs: sse.latencyMs,
        error: sse.ok ? "" : sse.error,
      },
    ];
    renderVoiceDiagnostics(checks, `Last run: ${new Date().toLocaleTimeString()}`);
  } finally {
    el.voiceDiagnosticsRunBtn.disabled = false;
  }
}

async function applyAdvancedChatResult(result, fallbackText) {
  const text = String(fallbackText || "").trim();
  rememberMemoryEvent("memory_chat_response", result);

  if (result?.session_id) {
    state.selectedChatSessionId = result.session_id;
    localStorage.setItem("dcc_chat_session_id", result.session_id);
  }
  if (result?.user_turn) {
    pushChatMessage("user", result.user_turn.text || text, {
      message_id: result.user_turn.message_id,
      session_id: result.user_turn.session_id || state.selectedChatSessionId,
      source: "conversation",
    });
  } else if (text) {
    pushChatMessage("user", text, { session_id: state.selectedChatSessionId });
  }

  const response = result.response || {};
  const responseMode = String(response.mode || result.selected_intent || "chat");
  const responseStatus = String(response.status || "ok");
  const assistantText =
    result.assistant_turn?.text ||
    response.answer ||
    response.reply ||
    (responseStatus === "confirmation_required"
      ? "Teach is pending confirmation. Enable Confirm Teach save and send again."
      : "Completed.");
  const kind = responseMode === "ask" ? "ask" : responseMode === "teach" ? "teach" : "system";
  pushChatMessage(kind, assistantText, {
    message_id: result.assistant_turn?.message_id,
    session_id: result.assistant_turn?.session_id || state.selectedChatSessionId,
    source: "conversation",
    response,
    citations: response.citations || [],
    memory_insight: response.memory_insight || {},
    conflicts: response.conflicts || [],
  });
  if ((Array.isArray(response.citations) && response.citations.length) || response.memory_insight) {
    state.lastExplainWhy = {
      citations: response.citations || [],
      memory_insight: response.memory_insight || {},
    };
  }

  const crisisSupport =
    !!result?.crisis_support ||
    /\b(988|immediate danger|hurt yourself|self-harm)\b/i.test(String(assistantText || ""));
  setVoiceCrisisOverlay(crisisSupport);

  if (responseStatus === "overwrite_confirmation_required") {
    state.pendingTeachMessage = text;
    state.pendingOverwriteId = response.overwrite_id || "";
    if (el.memoryConfirmTeachBtn) {
      el.memoryConfirmTeachBtn.classList.remove("hidden");
      el.memoryConfirmTeachBtn.textContent = "Confirm Overwrite";
    }
  } else if (responseStatus === "queued" && response?.run?.run_id) {
    state.lastCliRunId = response.run.run_id;
    state.runViewerMode = "live";
    state.runReadOnlyView = false;
    state.selectedImportedBundleId = "";
    state.selectedRunId = response.run.run_id;
    localStorage.setItem("dcc_selected_run", response.run.run_id);
    setupRunStream(response.run.run_id);
    await refreshRuns();
    await refreshStatus();
  } else if (responseStatus === "parent_teaching_clarify_required") {
    state.pendingOverwriteId = "";
    if (el.memoryConfirmTeachBtn) {
      el.memoryConfirmTeachBtn.classList.add("hidden");
      el.memoryConfirmTeachBtn.textContent = "Confirm Overwrite";
    }
  } else {
    state.pendingOverwriteId = "";
    if (el.memoryConfirmTeachBtn) {
      el.memoryConfirmTeachBtn.classList.add("hidden");
      el.memoryConfirmTeachBtn.textContent = "Confirm Overwrite";
    }
  }

  setCliOutput(JSON.stringify(result, null, 2));
  await refreshMemory().catch(() => {});
}

async function handleAdvancedChat(rawMessage) {
  const text = String(rawMessage || "").trim();
  if (!text) return;
  const detected = classifyAdvancedIntent(text);
  const selectedIntent = state.selectedChatIntent || detected.intent || "chat";
  const confirmSave = selectedIntent === "teach" ? !!el.chatConfirmSave?.checked : false;

  const result = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message: text,
      intent: selectedIntent,
      confirm_save: confirmSave,
      parent_teaching_mode: (!!el.parentTeachingMode?.checked) || state.parentTeachingMode,
      session_id: state.selectedChatSessionId || "",
      actor: "web_ui",
    }),
  });
  await applyAdvancedChatResult(result, text);
}

async function handleVoiceChatStream(rawMessage, options = {}) {
  const text = String(rawMessage || "").trim();
  if (!text) return;
  const detected = classifyAdvancedIntent(text);
  const selectedIntent = state.selectedChatIntent || detected.intent || "chat";
  const confirmSave = selectedIntent === "teach" ? !!el.chatConfirmSave?.checked : false;
  let confirmSensitive = false;
  if (selectedIntent === "goal") {
    confirmSensitive = window.confirm(`Run this goal from voice transcript?\n\n${text}`);
    if (!confirmSensitive) {
      setCliOutput("Voice goal run canceled.");
      if (state.voice.continuousMode) {
        await pauseContinualVoiceChat("Continual mode paused: goal execution requires explicit confirmation.");
      }
      state.voice.generating = false;
      syncVoiceUiState();
      return;
    }
  }

  const turnId = String(options?.turnId || state.voice.activeTurnId || nextVoiceTurnId());
  state.voice.activeTurnId = turnId;
  state.voice.ttsMode = "none";
  state.voice.generating = true;
  transitionVoiceTurn("respond_start");
  state.voice.partialAssistant = "";
  state.voice.ttsFallbackWarned = false;
  setVoiceAssistantPreview("");
  syncVoiceUiState();

  let finalResult = null;
  let streamError = "";
  let streamAborted = false;
  const streamController = new AbortController();
  state.voice.streamAbortController = streamController;
  try {
    await streamJsonSse(
      "/api/voice/chat/stream",
      {
        message: text,
        intent: selectedIntent,
        confirm_save: confirmSave,
        parent_teaching_mode: (!!el.parentTeachingMode?.checked) || state.parentTeachingMode,
        session_id: state.selectedChatSessionId || "",
        actor: "web_voice",
        confirm_sensitive: confirmSensitive,
        text_only_mode: !!state.voice.textOnlyMode,
        mute: !!state.voice.muted,
        voice_style: state.voice.style,
        voice_rate: state.voice.rate,
        turn_id: turnId,
      },
      async ({ event, data }) => {
        if (turnId !== state.voice.activeTurnId) return;
        if (data?.turn_id && String(data.turn_id) !== String(turnId)) return;
        if (event === "confirmation_required") {
          throw new Error(String(data?.message || "Confirmation is required."));
        }
        if (event === "assistant_partial") {
          const chunk = String(data?.chunk || "").trim();
          const assembled = String(data?.assembled || "").trim();
          const synthesisError = String(data?.error || "").trim();
          if (synthesisError && !state.voice.ttsFallbackWarned) {
            state.voice.ttsFallbackWarned = true;
            setCliOutput(`Local TTS error: ${synthesisError}. Falling back to browser speech synthesis.`);
            showToast("Local TTS unavailable, using browser speech.");
          }
          if (assembled) {
            state.voice.partialAssistant = assembled;
            setVoiceAssistantPreview(assembled);
          }
          if (chunk && !state.voice.textOnlyMode && !state.voice.muted) {
            const audioBase64 = String(data?.audio_base64 || "").trim();
            const mimeType = String(data?.mime_type || "audio/wav").trim();
            const hasAudio = !!audioBase64;
            if (state.voice.ttsMode === "none") {
              state.voice.ttsMode = hasAudio ? "backend" : "browser";
            }
            if (synthesisError && state.voice.ttsMode === "backend") {
              state.voice.ttsMode = "browser";
              clearVoiceAudioQueue(true);
            }
            if (state.voice.ttsMode === "backend") {
              if (hasAudio) enqueueVoiceAudioChunk(audioBase64, mimeType);
            } else if (state.voice.ttsMode === "browser") {
              speakVoiceChunkBrowser(chunk);
            }
          }
          return;
        }
        if (event === "assistant_final") {
          finalResult = data?.result || null;
          const assistantText = String(data?.assistant_text || "").trim();
          if (assistantText) {
            state.voice.partialAssistant = assistantText;
            setVoiceAssistantPreview(assistantText);
          }
          if (data?.crisis_support) {
            setVoiceCrisisOverlay(true);
          }
          return;
        }
        if (event === "error") {
          throw new Error(String(data?.error || "Voice stream failed."));
        }
      },
      { signal: streamController.signal }
    );
  } catch (err) {
    if (err?.name === "AbortError") {
      streamAborted = true;
    } else {
      streamError = err?.message || "Voice stream failed.";
    }
  } finally {
    if (state.voice.streamAbortController === streamController) {
      state.voice.streamAbortController = null;
    }
    state.voice.generating = false;
    transitionVoiceTurn("complete");
    if (state.voice.vadActive) {
      transitionVoiceTurn("arm");
    }
    syncVoiceUiState();
  }

  if (streamAborted) {
    return;
  }
  if (streamError) {
    setCliOutput(streamError);
    pushChatMessage("system", streamError);
    setVoiceAssistantPreview("");
    if (state.voice.continuousMode && !state.voice.continuousPaused) {
      if (/confirmation is required/i.test(streamError)) {
        await pauseContinualVoiceChat("Continual mode paused: confirmation is required before continuing.");
      } else {
        scheduleContinualRearm("stream_error");
      }
    }
    return;
  }
  if (!finalResult) {
    const fallback = "Voice stream ended without final response payload.";
    setCliOutput(fallback);
    pushChatMessage("system", fallback);
    if (state.voice.continuousMode && !state.voice.continuousPaused) {
      scheduleContinualRearm("missing_final");
    }
    return;
  }
  await applyAdvancedChatResult(finalResult, text);
  if (state.voice.continuousMode && !state.voice.continuousPaused) {
    const responseStatus = String(finalResult?.response?.status || "").trim().toLowerCase();
    if (responseStatus === "overwrite_confirmation_required") {
      await pauseContinualVoiceChat("Continual mode paused: overwrite confirmation required in UI.");
      return;
    }
    scheduleContinualRearm("reply_complete");
  }
}

async function transcribeVoiceBlob(blob) {
  const turnId = state.voice.activeTurnId || nextVoiceTurnId();
  state.voice.activeTurnId = turnId;
  state.voice.generating = true;
  transitionVoiceTurn("transcribe_start");
  syncVoiceUiState();
  const form = new FormData();
  form.append("audio", blob, `voice_${Date.now()}.webm`);
  form.append("actor", "web_voice");
  if (state.selectedChatSessionId) {
    form.append("session_id", state.selectedChatSessionId);
  }
  const controller = new AbortController();
  state.voice.transcribeAbortController = controller;
  try {
    const result = await apiMultipart("/api/voice/transcribe", form, { signal: controller.signal });
    const transcript = String(result?.text || "").trim();
    if (turnId !== state.voice.activeTurnId) {
      return;
    }
    setVoiceTranscriptPreview(transcript);
    if (!transcript) {
      throw new Error("No transcript text was returned.");
    }
    if (state.voice.continuousMode && matchesVoiceStopPhrase(transcript)) {
      await pauseContinualVoiceChat("Continual voice chat stopped by phrase.");
      stopContinualVoiceChat("Continual voice chat stopped by phrase.");
      return;
    }
    if (el.memoryChatInput) {
      el.memoryChatInput.value = transcript;
    }
    updateIntentPreview();
    await handleVoiceChatStream(transcript, { turnId });
  } finally {
    if (state.voice.transcribeAbortController === controller) {
      state.voice.transcribeAbortController = null;
    }
    state.voice.generating = false;
    if (state.voice.turnState === "transcribing") {
      transitionVoiceTurn("complete");
      if (state.voice.vadActive) {
        transitionVoiceTurn("arm");
      }
    }
    syncVoiceUiState();
  }
}

async function submitMemoryChat() {
  const raw = (el.memoryChatInput?.value || "").trim();
  if (!raw) {
    setCliOutput("Enter a question, a fact, or an explicit /goal|/ask|/teach command.");
    return;
  }
  if (el.memoryChatInput) {
    el.memoryChatInput.value = "";
  }
  updateIntentPreview();

  if (state.advancedChatMode) {
    await handleAdvancedChat(raw);
    return;
  }

  const request = inferChatRequest(raw);
  if (!request || !request.payload) {
    setCliOutput("Unsupported command. Use /goal, /ask, /teach, or plain natural input.");
    return;
  }
  pushChatMessage("user", raw, { session_id: state.selectedChatSessionId });
  if (request.mode === "ask") return handleMemoryAsk(request.payload);
  if (request.mode === "teach") return handleMemoryTeach(request.payload, false);
  if (request.mode === "goal") return handleGoalCommand(request);
  setCliOutput("Unsupported command. Use /goal, /ask, /teach, or plain natural input.");
}

function walkthroughSteps() {
  return [
    {
      tab: "dashboard",
      title: "Dashboard",
      text: "Start here for status, progress, and growth. Check the version stamp in the header and the demo badge when fixture mode is enabled.",
      highlight: "#tab-dashboard .dashboard-top-grid",
    },
    {
      tab: "cli",
      title: "Memory & Chat",
      text: "This is memory-first chat. We prefilled an Ask prompt. Send it to see citation chips and Memory Insight references.",
      highlight: "#memoryChatInput",
      onEnter: () => {
        setAdvancedIntent("ask");
        if (el.memoryChatInput) {
          el.memoryChatInput.value = "Who is your father?";
        }
        updateIntentPreview();
      },
    },
    {
      tab: "cli",
      title: "Confirmation Gating",
      text: "Teach writes are confirmation-gated. We prefilled a Teach prompt; keep Confirm Teach save off to preview before storing.",
      highlight: "#chatConfirmSave",
      onEnter: () => {
        setAdvancedIntent("teach");
        if (el.chatConfirmSave) {
          el.chatConfirmSave.checked = false;
        }
        if (el.memoryChatInput) {
          el.memoryChatInput.value = "Always value patience.";
        }
        updateIntentPreview();
      },
    },
    {
      tab: "approvals",
      title: "Approvals Queue",
      text: "High-risk changes can require typed confirmation. Use exact text like `approve <run_id>` when required, then review audit entries.",
      highlight: "#approvalList",
    },
    {
      tab: "runs",
      title: "Runs Replay/Compare",
      text: "Inspect Run Health Summary, then use replay controls to step iterations and compare where regressions started.",
      highlight: "#replayPanel",
      onEnter: async () => {
        if (state.runViewerMode === "import" && state.selectedImportedBundleId) {
          await loadImportedBundle(state.selectedImportedBundleId);
          return;
        }
        if (!state.selectedRunId && state.runs.length) {
          state.selectedRunId = String(state.runs[0].id || "");
        }
        if (state.selectedRunId) {
          await loadRun(state.selectedRunId);
        }
      },
    },
    {
      tab: "logs",
      title: "Logs",
      text: "Logs include info/warn/error with search and level filters so newcomers can inspect system behavior quickly.",
      highlight: "#logsView",
    },
    {
      tab: "settings",
      title: "Settings",
      text: "Calibrate personality sliders, model roles, and demo controls. Settings never bypass safety constraints.",
      highlight: "#settingsInfo",
    },
  ];
}

function clearWalkthroughHighlight() {
  if (!state.walkthrough.highlightedSelector) return;
  const node = document.querySelector(state.walkthrough.highlightedSelector);
  if (node) {
    node.classList.remove("walkthrough-highlight");
  }
  state.walkthrough.highlightedSelector = "";
}

function applyWalkthroughHighlight(selector) {
  clearWalkthroughHighlight();
  const clean = String(selector || "").trim();
  if (!clean) return;
  const node = document.querySelector(clean);
  if (!node) return;
  node.classList.add("walkthrough-highlight");
  state.walkthrough.highlightedSelector = clean;
  try {
    node.scrollIntoView({ behavior: state.reducedMotion ? "auto" : "smooth", block: "center", inline: "nearest" });
  } catch (_) {}
}

async function renderWalkthroughStep() {
  const steps = walkthroughSteps();
  const maxIndex = Math.max(0, steps.length - 1);
  const idx = Math.max(0, Math.min(state.walkthrough.stepIndex, maxIndex));
  state.walkthrough.stepIndex = idx;
  const step = steps[idx];
  if (!step) return;

  activateTab(step.tab || "dashboard");
  if (typeof step.onEnter === "function") {
    await step.onEnter();
  }
  applyWalkthroughHighlight(step.highlight || "");

  if (el.walkthroughStepCounter) {
    el.walkthroughStepCounter.textContent = `Step ${idx + 1} / ${steps.length}`;
  }
  if (el.walkthroughTitle) {
    el.walkthroughTitle.textContent = step.title || "Guided Walkthrough";
  }
  if (el.walkthroughText) {
    el.walkthroughText.textContent = step.text || "";
  }
  if (el.walkthroughBackBtn) {
    el.walkthroughBackBtn.disabled = idx <= 0;
  }
  if (el.walkthroughNextBtn) {
    el.walkthroughNextBtn.textContent = idx >= maxIndex ? "Finish" : "Next";
  }
}

function closeWalkthrough(markDismissed = false) {
  state.walkthrough.active = false;
  if (el.walkthroughOverlay) {
    el.walkthroughOverlay.classList.add("hidden");
  }
  if (markDismissed) {
    localStorage.setItem(WALKTHROUGH_DISMISSED_KEY, "1");
  }
  clearWalkthroughHighlight();
}

async function openWalkthrough(stepIndex = 0) {
  state.walkthrough.active = true;
  state.walkthrough.stepIndex = Math.max(0, Number(stepIndex) || 0);
  if (el.walkthroughOverlay) {
    el.walkthroughOverlay.classList.remove("hidden");
  }
  await renderWalkthroughStep();
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
  el.startWalkthroughBtn?.addEventListener("click", async () => {
    localStorage.removeItem(WALKTHROUGH_DISMISSED_KEY);
    await openWalkthrough(0);
  });
  el.walkthroughCloseBtn?.addEventListener("click", () => closeWalkthrough(true));
  el.walkthroughBackBtn?.addEventListener("click", async () => {
    if (!state.walkthrough.active) return;
    state.walkthrough.stepIndex = Math.max(0, state.walkthrough.stepIndex - 1);
    await renderWalkthroughStep();
  });
  el.walkthroughNextBtn?.addEventListener("click", async () => {
    if (!state.walkthrough.active) return;
    const maxIndex = Math.max(0, walkthroughSteps().length - 1);
    if (state.walkthrough.stepIndex >= maxIndex) {
      closeWalkthrough(true);
      return;
    }
    state.walkthrough.stepIndex += 1;
    await renderWalkthroughStep();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.walkthrough.active) {
      closeWalkthrough(true);
    }
  });

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
      state.runViewerMode = "live";
      state.runReadOnlyView = false;
      state.selectedImportedBundleId = "";
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

  el.importBundleBtn?.addEventListener("click", async () => {
    const file = el.bundleImportFile?.files?.[0];
    if (!file) {
      setMessage("Choose a .zip run bundle first.");
      return;
    }
    const form = new FormData();
    form.append("bundle", file, file.name || "bundle.zip");
    form.append("actor", "web_ui");
    try {
      const result = await apiMultipart("/api/bundles/import", form);
      showToast(`Imported bundle: ${result.run_id || "-"}`);
      if (el.bundleImportFile) {
        el.bundleImportFile.value = "";
      }
      await refreshImportedBundles();
      if (result.import_id) {
        state.selectedImportedBundleId = String(result.import_id);
        state.runViewerMode = "import";
        state.runReadOnlyView = true;
        await loadImportedBundle(state.selectedImportedBundleId);
        renderImportedBundles();
      }
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.loadDiffBtn.addEventListener("click", async () => {
    const runId = el.diffRunId.value.trim();
    if (!runId) return setMessage("Enter run ID.");
    state.runViewerMode = "live";
    state.runReadOnlyView = false;
    state.selectedImportedBundleId = "";
    state.selectedRunId = runId;
    localStorage.setItem("dcc_selected_run", runId);
    setupRunStream(runId);
    await loadRun(runId);
  });

  el.refreshLogsBtn.addEventListener("click", () => refreshLogs().catch((e) => setMessage(e.message)));
  el.growthRefreshBtn?.addEventListener("click", () => refreshGrowth().catch((e) => setMessage(e.message)));
  el.legacyRefreshBtn?.addEventListener("click", () => refreshLegacyArchive().catch((e) => setMessage(e.message)));
  el.selfImproveAutoBtn?.addEventListener("click", async () => {
    try {
      const result = await api("/api/self_improvements/autonomous_cycle", {
        method: "POST",
        body: JSON.stringify({ trigger: "manual", actor: "david_autonomous" }),
      });
      const status = String(result?.status || "unknown");
      if (status === "proposed") {
        showToast(`Autonomous proposal drafted: ${result?.proposal_id || "-"}`);
      } else {
        showToast(`Autonomous cycle: ${status}`);
      }
      await refreshSelfImprovements();
      await refreshGrowth().catch(() => {});
      await refreshStatus().catch(() => {});
    } catch (err) {
      setMessage(err.message);
    }
  });
  el.selfImproveRefreshBtn?.addEventListener("click", () => refreshSelfImprovements().catch((e) => setMessage(e.message)));
  el.logsSearch.addEventListener("input", () => renderLogs(state.logs || {}));
  el.logsLevelFilter.addEventListener("change", () => renderLogs(state.logs || {}));

  el.loadDemoDataBtn?.addEventListener("click", async () => {
    try {
      try {
        await api("/api/demo/load", {
          method: "POST",
          body: JSON.stringify({ confirm_overwrite: false, actor: "web_ui" }),
        });
      } catch (err) {
        const requiresConfirmation = !!err?.response?.requires_confirmation;
        if (!requiresConfirmation) {
          throw err;
        }
        const approved = window.confirm(
          "Live data already exists. Replace runs/memory/conversations with deterministic demo fixtures?"
        );
        if (!approved) return;
        await api("/api/demo/load", {
          method: "POST",
          body: JSON.stringify({ confirm_overwrite: true, actor: "web_ui" }),
        });
      }
      showToast("Demo fixtures loaded.");
      await Promise.all([
        refreshSettings().catch(() => {}),
        refreshStatus().catch(() => {}),
        refreshRuns().catch(() => {}),
        refreshImportedBundles().catch(() => {}),
        refreshApprovals().catch(() => {}),
        refreshMemory().catch(() => {}),
        refreshTelemetry().catch(() => {}),
        refreshLogs().catch(() => {}),
        refreshWorkspaceTargets().catch(() => {}),
      ]);
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.resetDemoDataBtn?.addEventListener("click", async () => {
    const approved = window.confirm("Reset demo data to the baseline fixtures?");
    if (!approved) return;
    try {
      await api("/api/demo/reset", {
        method: "POST",
        body: JSON.stringify({ actor: "web_ui" }),
      });
      showToast("Demo fixtures reset.");
      await Promise.all([
        refreshSettings().catch(() => {}),
        refreshStatus().catch(() => {}),
        refreshRuns().catch(() => {}),
        refreshImportedBundles().catch(() => {}),
        refreshApprovals().catch(() => {}),
        refreshMemory().catch(() => {}),
        refreshTelemetry().catch(() => {}),
        refreshLogs().catch(() => {}),
        refreshWorkspaceTargets().catch(() => {}),
      ]);
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.saveSettingsBtn.addEventListener("click", async () => {
    try {
      const payload = {
        safe_mode: el.settingSafeMode.value === "true",
        rate_limit_seconds: Number(el.settingRateLimit.value || 0),
        max_iterations_override: Number(el.settingMaxIterations.value || 0),
        risky_large_edit_bytes: Number(el.settingLargeEdit.value || 50000),
        risky_multi_file_threshold: Number(el.settingMultiFile.value || 4),
        run_preview_default: !!el.settingPreviewDefault.checked,
        companion_mode: el.settingCompanionMode ? !!el.settingCompanionMode.checked : true,
        memory_insight_mode: el.settingMemoryInsightMode ? !!el.settingMemoryInsightMode.checked : true,
        parent_teaching_mode: el.settingParentTeachingMode ? !!el.settingParentTeachingMode.checked : false,
        autonomous_self_improvement_mode: el.settingAutonomousSelfImproveMode
          ? !!el.settingAutonomousSelfImproveMode.checked
          : true,
        demo_mode: el.settingDemoMode ? !!el.settingDemoMode.checked : false,
        upload_vision_mode: el.settingUploadVisionMode ? !!el.settingUploadVisionMode.checked : false,
        upload_vision_model: String(el.settingUploadVisionModel?.value || "").trim(),
        voice_mode_enabled: el.settingVoiceModeEnabled ? !!el.settingVoiceModeEnabled.checked : false,
        voice_text_only_mode: el.settingVoiceTextOnlyMode ? !!el.settingVoiceTextOnlyMode.checked : false,
        voice_input_mode: String(el.settingVoiceInputMode?.value || "manual").trim().toLowerCase() || "manual",
        voice_continuous_mode: el.settingVoiceContinuousMode ? !!el.settingVoiceContinuousMode.checked : false,
        voice_post_reply_delay_ms: clampVoicePostReplyDelay(el.settingVoicePostReplyDelayMs?.value, 450),
        voice_stop_phrases: parseVoiceStopPhrases(el.settingVoiceStopPhrases?.value || ""),
        voice_vad_threshold: clampVoiceVadThreshold(el.settingVoiceVadThreshold?.value, 0.035),
        voice_vad_silence_ms: clampVoiceVadSilence(el.settingVoiceVadSilenceMs?.value, 900),
        voice_vad_min_speech_ms: clampVoiceVadMinSpeech(el.settingVoiceVadMinSpeechMs?.value, 300),
        vad_threshold: clampVoiceVadThreshold(el.settingVoiceVadThreshold?.value, 0.035),
        vad_silence_ms: clampVoiceVadSilence(el.settingVoiceVadSilenceMs?.value, 900),
        vad_min_speech_ms: clampVoiceVadMinSpeech(el.settingVoiceVadMinSpeechMs?.value, 300),
        voice_style: String(el.settingVoiceStyle?.value || "warm").trim().toLowerCase() || "warm",
        voice_rate: clampVoiceRate(el.settingVoiceRate?.value, 100),
        voice_stt_engine: String(el.settingVoiceSttEngine?.value || "none").trim().toLowerCase() || "none",
        voice_stt_model: String(el.settingVoiceSttModel?.value || "base").trim() || "base",
        voice_stt_language: String(el.settingVoiceSttLanguage?.value || "en").trim().toLowerCase() || "en",
        voice_stt_command: String(el.settingVoiceSttCommand?.value || "whisper").trim() || "whisper",
        voice_whisper_cpp_command: String(el.settingVoiceWhisperCppCommand?.value || "whisper-cli").trim() || "whisper-cli",
        voice_whisper_cpp_model_path: String(el.settingVoiceWhisperCppModelPath?.value || "").trim(),
        voice_tts_engine: String(el.settingVoiceTtsEngine?.value || "browser").trim().toLowerCase() || "browser",
        voice_tts_command: String(el.settingVoiceTtsCommand?.value || "piper").trim() || "piper",
        voice_tts_model_path: String(el.settingVoiceTtsModelPath?.value || "").trim(),
        voice_chunk_chars: Math.max(80, Math.min(400, Number(el.settingVoiceChunkChars?.value || 180))),
        personality_warmth: clampPercent(el.settingPersonalityWarmth?.value, 55),
        personality_verbosity: clampPercent(el.settingPersonalityVerbosity?.value, 55),
        personality_curiosity: clampPercent(el.settingPersonalityCuriosity?.value, 50),
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

  [el.settingPersonalityWarmth, el.settingPersonalityVerbosity, el.settingPersonalityCuriosity].forEach((node) => {
    node?.addEventListener("input", () => renderPersonalityCalibrationLabels());
    node?.addEventListener("change", () => renderPersonalityCalibrationLabels());
  });
  el.settingVoiceRate?.addEventListener("input", () => renderVoiceRateLabel());
  el.settingVoiceRate?.addEventListener("change", () => renderVoiceRateLabel());
  el.settingVoiceVadThreshold?.addEventListener("input", () => {
    state.voice.vadThreshold = clampVoiceVadThreshold(el.settingVoiceVadThreshold?.value, 0.035);
    renderVoiceVadLabel();
    renderVoiceModeHint();
  });
  el.settingVoiceVadThreshold?.addEventListener("change", () => {
    state.voice.vadThreshold = clampVoiceVadThreshold(el.settingVoiceVadThreshold?.value, 0.035);
    renderVoiceVadLabel();
    renderVoiceModeHint();
  });
  el.settingVoiceVadSilenceMs?.addEventListener("change", () => {
    state.voice.vadSilenceMs = clampVoiceVadSilence(el.settingVoiceVadSilenceMs?.value, 900);
    renderVoiceModeHint();
  });
  el.settingVoiceVadMinSpeechMs?.addEventListener("change", () => {
    state.voice.vadMinSpeechMs = clampVoiceVadMinSpeech(el.settingVoiceVadMinSpeechMs?.value, 300);
    renderVoiceModeHint();
  });
  el.settingVoiceModeEnabled?.addEventListener("change", () => {
    state.voice.enabled = !!el.settingVoiceModeEnabled?.checked;
    if (!state.voice.enabled) {
      state.voice.continuousMode = false;
      state.voice.continuousPaused = false;
      clearVoiceRearmTimer();
      if (el.voiceContinuousMode) el.voiceContinuousMode.checked = false;
      if (el.settingVoiceContinuousMode) el.settingVoiceContinuousMode.checked = false;
      abortVoiceStream();
      abortVoiceTranscription();
      abortBrowserSpeechRecognition();
      stopVoiceVad({ submit: false }).catch(() => {});
      stopVoiceListening({ submit: false, keepStream: false }).catch(() => {});
      clearVoiceAudioQueue(true);
      state.voice.generating = false;
      setVoiceTurnState("idle");
      setVoiceAssistantPreview("");
      setVoiceTranscriptPreview("");
      setVoiceCrisisOverlay(false);
    }
    syncVoiceUiState();
  });
  el.settingVoiceContinuousMode?.addEventListener("change", async () => {
    const enabled = !!el.settingVoiceContinuousMode?.checked;
    state.voice.continuousMode = enabled;
    state.voice.continuousPaused = false;
    if (el.voiceContinuousMode) {
      el.voiceContinuousMode.checked = enabled;
    }
    if (enabled && state.voice.inputMode !== "vad") {
      setVoiceInputMode("vad");
    }
    if (enabled && state.voice.enabled) {
      await resumeContinualVoiceChat().catch((err) => setCliOutput(err?.message || "Unable to start continual mode."));
    } else if (!enabled) {
      clearVoiceRearmTimer();
      stopVoiceVad({ submit: false }).catch(() => {});
      syncVoiceUiState();
    }
    renderVoiceModeHint();
  });
  el.settingVoiceInputMode?.addEventListener("change", () => {
    setVoiceInputMode(el.settingVoiceInputMode?.value || "manual", { syncSetting: false });
  });
  el.settingVoicePostReplyDelayMs?.addEventListener("change", () => {
    state.voice.postReplyDelayMs = clampVoicePostReplyDelay(el.settingVoicePostReplyDelayMs?.value, 450);
  });
  el.settingVoiceStopPhrases?.addEventListener("change", () => {
    const raw = String(el.settingVoiceStopPhrases?.value || "").trim();
    const normalized = parseVoiceStopPhrases(raw);
    state.voice.stopPhrases = normalized;
    if (el.settingVoiceStopPhrases) {
      el.settingVoiceStopPhrases.value = voiceStopPhrasesDisplay(normalized);
    }
    renderVoiceModeHint();
  });
  el.settingVoiceStopPhrasesResetBtn?.addEventListener("click", async () => {
    try {
      const defaults = ["stop listening", "end chat", "bye david"];
      const data = await api("/api/settings", {
        method: "POST",
        body: JSON.stringify({ voice_stop_phrases: defaults }),
      });
      renderSettings(data);
      showToast("Stop phrases reset to defaults.");
    } catch (err) {
      setMessage(err?.message || "Failed to reset stop phrases.");
    }
  });
  el.settingVoiceTextOnlyMode?.addEventListener("change", () => {
    state.voice.textOnlyMode = !!el.settingVoiceTextOnlyMode?.checked;
    if (el.voiceTextOnlyMode) {
      el.voiceTextOnlyMode.checked = !!state.voice.textOnlyMode;
    }
    syncVoiceUiState();
  });
  el.settingVoiceStyle?.addEventListener("change", () => {
    state.voice.style = String(el.settingVoiceStyle?.value || "warm").trim().toLowerCase() || "warm";
    if (!["warm", "balanced", "clear"].includes(state.voice.style)) {
      state.voice.style = "warm";
    }
  });
  el.settingUploadVisionMode?.addEventListener("change", () => {
    if (el.uploadVisionMode) {
      el.uploadVisionMode.checked = !!el.settingUploadVisionMode?.checked;
    }
  });
  el.settingUploadVisionModel?.addEventListener("change", () => {
    if (!el.uploadVisionModel) return;
    el.uploadVisionModel.value = String(el.settingUploadVisionModel?.value || "");
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
  el.memoryChatInput?.addEventListener("input", () => updateIntentPreview());

  el.voiceModePttBtn?.addEventListener("click", () => setVoiceInputMode("manual"));
  el.voiceModeVadBtn?.addEventListener("click", () => setVoiceInputMode("vad"));

  el.voiceStartBtn?.addEventListener("click", async () => {
    try {
      if (state.voice.continuousMode) {
        if (state.voice.continuousPaused) {
          await resumeContinualVoiceChat();
          return;
        }
        if (!state.voice.vadActive) {
          await resumeContinualVoiceChat();
        }
        return;
      }
      if (state.voice.inputMode === "vad") {
        if (state.voice.vadActive) return;
        await startVoiceVad();
        return;
      }
      if (state.voice.listening) {
        await stopVoiceListening({ submit: true, keepStream: false });
        return;
      }
      await startVoiceListening();
    } catch (err) {
      setCliOutput(err?.message || "Voice start failed.");
    }
  });

  el.voiceStopBtn?.addEventListener("click", async () => {
    try {
      if (state.voice.continuousMode) {
        await cancelVoiceTurn({ disarmAuto: true, reason: "Continual conversation ended by user." });
        stopContinualVoiceChat("Continual conversation ended.");
        return;
      }
      if (state.voice.inputMode === "vad") {
        await cancelVoiceTurn({ disarmAuto: true, reason: "Voice stopped by user." });
        return;
      }
      await cancelVoiceTurn({ disarmAuto: false, reason: "Voice turn canceled." });
    } catch (err) {
      setCliOutput(err?.message || "Voice stop failed.");
    }
  });
  el.voiceMuteBtn?.addEventListener("click", () => {
    state.voice.muted = !state.voice.muted;
    if (state.voice.muted) {
      clearVoiceAudioQueue(true);
    }
    syncVoiceUiState();
  });
  el.voiceContinuousMode?.addEventListener("change", async () => {
    const enabled = !!el.voiceContinuousMode?.checked;
    state.voice.continuousMode = enabled;
    state.voice.continuousPaused = false;
    if (el.settingVoiceContinuousMode) {
      el.settingVoiceContinuousMode.checked = enabled;
    }
    if (!enabled) {
      clearVoiceRearmTimer();
      await stopVoiceVad({ submit: false }).catch(() => {});
      syncVoiceUiState();
      return;
    }
    if (state.voice.inputMode !== "vad") {
      setVoiceInputMode("vad");
    }
    await resumeContinualVoiceChat().catch((err) => setCliOutput(err?.message || "Unable to start continual mode."));
  });
  el.voicePauseBtn?.addEventListener("click", async () => {
    try {
      await pauseContinualVoiceChat("Continual conversation paused.");
    } catch (err) {
      setCliOutput(err?.message || "Unable to pause continual mode.");
    }
  });
  el.voiceResumeBtn?.addEventListener("click", async () => {
    try {
      await resumeContinualVoiceChat();
    } catch (err) {
      setCliOutput(err?.message || "Unable to resume continual mode.");
    }
  });
  el.voiceEndConversationBtn?.addEventListener("click", async () => {
    try {
      await cancelVoiceTurn({ disarmAuto: true, reason: "Continual conversation ended by user." });
      stopContinualVoiceChat("Continual conversation ended.");
    } catch (err) {
      setCliOutput(err?.message || "Unable to end continual mode.");
    }
  });
  el.voiceTextOnlyMode?.addEventListener("change", () => {
    state.voice.textOnlyMode = !!el.voiceTextOnlyMode?.checked;
    if (state.voice.textOnlyMode) {
      clearVoiceAudioQueue(true);
    }
    syncVoiceUiState();
  });
  el.voiceDiagnosticsRunBtn?.addEventListener("click", () => {
    runVoiceDiagnostics().catch((err) => setCliOutput(err?.message || "Voice diagnostics failed."));
  });
  el.voiceDiagnosticsCopyBtn?.addEventListener("click", async () => {
    if (!el.voiceDiagnosticsSteps) return;
    const text = String(el.voiceDiagnosticsSteps.value || "").trim();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast("Troubleshooting steps copied.");
    } catch (_) {
      setCliOutput("Copy failed. Select and copy the steps manually.");
    }
  });

  el.memoryConfirmTeachBtn?.addEventListener("click", async () => {
    try {
      if (state.pendingOverwriteId) {
        await confirmPendingOverwrite("approve");
        showToast("Memory overwrite confirmed.");
        return;
      }
      const pending = state.pendingTeachMessage;
      if (!pending) {
        setCliOutput("No pending conflicting teach message.");
        return;
      }
      await handleMemoryTeach(pending, true);
      showToast("Conflicting teach confirmed.");
    } catch (err) {
      setCliOutput(err.message);
      pushChatMessage("system", err.message);
    }
  });

  el.memoryClearHistoryBtn?.addEventListener("click", async () => {
    const sessionId = String(state.selectedChatSessionId || "").trim();
    const prompt = sessionId
      ? `Clear this conversation (${sessionId})? This cannot be undone.`
      : "Clear all conversations? This cannot be undone.";
    if (!window.confirm(prompt)) return;
    try {
      const result = await api("/api/memory/conversations/clear", {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId, actor: "web_ui" }),
      });
      if (sessionId) {
        state.chatMessages = state.chatMessages.filter((row) => String(row?.session_id || "") !== sessionId);
      } else {
        state.chatMessages = [];
      }
      state.selectedChatSessionId = "";
      localStorage.removeItem("dcc_chat_session_id");
      await refreshMemory();
      renderChatHistory();
      const removedCount = Number(result?.removed_count || 0);
      showToast(removedCount > 0 ? `Cleared ${removedCount} messages.` : "No messages were removed.");
    } catch (err) {
      setCliOutput(err.message);
      pushChatMessage("system", err.message);
    }
  });

  el.memoryChatRefreshBtn?.addEventListener("click", () => {
    refreshMemory().catch((err) => setCliOutput(err.message));
  });

  el.uploadAnalyzeBtn?.addEventListener("click", async () => {
    try {
      await analyzeUploadFromPicker();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.uploadRefreshBtn?.addEventListener("click", async () => {
    try {
      await refreshUploads({ keepSelection: true });
      showToast("Uploads refreshed.");
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.uploadAskBtn?.addEventListener("click", async () => {
    try {
      await askSelectedUploadQuestion();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.uploadAskInput?.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    try {
      await askSelectedUploadQuestion();
    } catch (err) {
      setMessage(err.message);
    }
  });

  el.memoryChatSearch?.addEventListener("input", () => {
    renderMemoryChatFacts();
    renderMemoryValuesPanel();
    renderMemoryConversationsPanel();
    renderMemoryLessonsPanel();
    renderMemoryReflectionsPanel();
  });

  el.memoryPanelFactsBtn?.addEventListener("click", () => setMemoryPanelTab("facts"));
  el.memoryPanelValuesBtn?.addEventListener("click", () => setMemoryPanelTab("values"));
  el.memoryPanelConversationsBtn?.addEventListener("click", () => setMemoryPanelTab("conversations"));
  el.memoryPanelLessonsBtn?.addEventListener("click", () => setMemoryPanelTab("lessons"));
  el.memoryPanelReflectionsBtn?.addEventListener("click", () => setMemoryPanelTab("reflections"));

  el.advancedChatToggle?.addEventListener("change", () => {
    state.advancedChatMode = !!el.advancedChatToggle.checked;
    showToast(state.advancedChatMode ? "Advanced Chat enabled." : "Advanced Chat disabled.");
  });
  el.parentTeachingMode?.addEventListener("change", () => {
    state.parentTeachingMode = !!el.parentTeachingMode.checked;
  });
  el.chatIntentAskBtn?.addEventListener("click", () => setAdvancedIntent("ask"));
  el.chatIntentTeachBtn?.addEventListener("click", () => setAdvancedIntent("teach"));
  el.chatIntentGoalBtn?.addEventListener("click", () => setAdvancedIntent("goal"));
  el.chatIntentChatBtn?.addEventListener("click", () => setAdvancedIntent("chat"));

  el.chatNewSessionBtn?.addEventListener("click", async () => {
    state.selectedChatSessionId = "";
    localStorage.removeItem("dcc_chat_session_id");
    await refreshMemory().catch(() => {});
    renderChatHistory();
    showToast("Started new chat session.");
  });

  el.chatSessionsList?.addEventListener("click", async (event) => {
    const button = event.target?.closest?.("button[data-chat-session]");
    if (!button) return;
    const sid = String(button.getAttribute("data-chat-session") || "").trim();
    if (!sid) return;
    state.selectedChatSessionId = sid;
    localStorage.setItem("dcc_chat_session_id", sid);
    await refreshMemory().catch(() => {});
    renderChatHistory();
  });

  el.memoryChatHistory?.addEventListener("click", async (event) => {
    const pinBtn = event.target?.closest?.("button[data-chat-pin]");
    if (pinBtn) {
      const messageId = pinBtn.getAttribute("data-chat-pin");
      togglePinnedMessage(messageId);
      return;
    }

    const chipBtn = event.target?.closest?.("button[data-chat-chip]");
    if (!chipBtn) return;
    const chip = String(chipBtn.getAttribute("data-chat-chip") || "");
    const sourceText = String(chipBtn.getAttribute("data-chat-text") || "").trim();
    if (chip === "save-memory") {
      setAdvancedIntent("teach");
      if (el.chatConfirmSave) el.chatConfirmSave.checked = true;
      if (el.memoryChatInput) {
        el.memoryChatInput.value = sourceText;
        el.memoryChatInput.focus();
      }
      updateIntentPreview();
      return;
    }
    if (chip === "ask-followup") {
      setAdvancedIntent("ask");
      if (el.memoryChatInput) {
        el.memoryChatInput.value = `Can you clarify this: ${sourceText}`;
        el.memoryChatInput.focus();
      }
      updateIntentPreview();
      return;
    }
    if (chip === "teach-refine") {
      setAdvancedIntent("teach");
      if (el.chatConfirmSave) el.chatConfirmSave.checked = true;
      if (el.memoryChatInput) {
        el.memoryChatInput.value = `Refinement: ${sourceText}`;
        el.memoryChatInput.focus();
      }
      updateIntentPreview();
      return;
    }
    if (chip === "mark-legacy") {
      const messageId = String(chipBtn.getAttribute("data-chat-id") || "").trim();
      const sessionId = String(chipBtn.getAttribute("data-chat-session") || "").trim();
      const kind = String(chipBtn.getAttribute("data-chat-kind") || "chat").trim();
      try {
        await markLegacyMoment({
          source_type: "conversation",
          source_id: messageId,
          summary: summarizeText(sourceText, 180),
          details: sourceText,
          metadata: {
            session_id: sessionId,
            kind,
          },
        });
      } catch (err) {
        setMessage(err.message);
      }
    }
  });

  el.replayPrevBtn.addEventListener("click", async () => {
    if (state.runViewerMode === "import") {
      if (!state.selectedImportedBundleId) return;
      await loadReplay(state.selectedImportedBundleId, Math.max(1, state.selectedIteration - 1), "import");
      return;
    }
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, Math.max(1, state.selectedIteration - 1), "live");
  });

  el.replayNextBtn.addEventListener("click", async () => {
    if (state.runViewerMode === "import") {
      if (!state.selectedImportedBundleId) return;
      await loadReplay(state.selectedImportedBundleId, state.selectedIteration + 1, "import");
      return;
    }
    if (!state.selectedRunId) return;
    await loadReplay(state.selectedRunId, state.selectedIteration + 1, "live");
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

  window.addEventListener("beforeunload", () => {
    abortVoiceStream();
    abortVoiceTranscription();
    stopVoiceVad({ submit: false }).catch(() => {});
    stopVoiceListening({ submit: false }).catch(() => {});
    clearVoiceAudioQueue(true);
    cleanupVoiceAudioResources();
    stopVoiceWaveform();
  });
}

async function bootstrap() {
  applyTheme(state.theme, false);
  applyBackgroundPreference();
  setStreamState("polling fallback");
  setChatMode("auto");
  setAdvancedIntent(state.selectedChatIntent || "chat");
  state.advancedChatMode = el.advancedChatToggle ? !!el.advancedChatToggle.checked : true;
  setMemoryPanelTab(state.memoryPanelTab || "facts");
  updateIntentPreview();
  renderChatHistory();
  renderRunHealthSummary({}, false);
  initHeroParticles();
  setVoiceTranscriptPreview("");
  setVoiceAssistantPreview("");
  setVoiceCrisisOverlay(false);
  state.voice.rate = clampVoiceRate(state.voice.rate, 100);
  renderVoiceRateLabel();
  syncVoiceUiState();
  stopVoiceWaveform();

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

  await safeRefresh("models", refreshModelOptions);
  await Promise.all([
    safeRefresh("status", refreshStatus),
    safeRefresh("approvals", refreshApprovals),
    safeRefresh("runs", refreshRuns),
    safeRefresh("imported bundles", refreshImportedBundles),
    safeRefresh("uploads", refreshUploads),
    safeRefresh("memory", refreshMemory),
    safeRefresh("growth", refreshGrowth),
    safeRefresh("legacy archive", refreshLegacyArchive),
    safeRefresh("self improvements", refreshSelfImprovements),
    safeRefresh("telemetry", refreshTelemetry),
    safeRefresh("logs", refreshLogs),
    safeRefresh("workspace", refreshWorkspaceTargets),
  ]);
  await safeRefresh("settings", refreshSettings);
  renderWorkspaceTargetHint();
  if (state.selectedRunId) {
    setupRunStream(state.selectedRunId);
    await safeRefresh("run details", async () => loadRun(state.selectedRunId));
  }

  const walkthroughDismissed = localStorage.getItem(WALKTHROUGH_DISMISSED_KEY) === "1";
  const demoActive = !!(state.status?.demo_mode || state.settings?.demo_mode);
  if (demoActive && !walkthroughDismissed) {
    setTimeout(() => {
      openWalkthrough(0).catch(() => {});
    }, 350);
  }

  setupSSE();
  setInterval(async () => {
    if (!state.streams.connected) {
      setStreamState("polling fallback");
      await Promise.all([
        safeRefresh("status", refreshStatus, { silent: true }),
        safeRefresh("runs", refreshRuns, { silent: true }),
        safeRefresh("imported bundles", refreshImportedBundles, { silent: true }),
        safeRefresh("uploads", refreshUploads, { silent: true }),
        safeRefresh("approvals", refreshApprovals, { silent: true }),
        safeRefresh("legacy archive", refreshLegacyArchive, { silent: true }),
        safeRefresh("self improvements", refreshSelfImprovements, { silent: true }),
        safeRefresh("logs", refreshLogs, { silent: true }),
      ]);
      setupSSE();
    }
  }, STREAM_RETRY_MS);

  setInterval(() => refreshMemory().catch(() => {}), 6000);
  setInterval(() => refreshUploads({ keepSelection: true }).catch(() => {}), 6500);
  setInterval(() => refreshGrowth().catch(() => {}), 7000);
  setInterval(() => refreshLegacyArchive().catch(() => {}), 8000);
  setInterval(() => refreshSelfImprovements().catch(() => {}), 9000);
  setInterval(() => refreshTelemetry().catch(() => {}), 5000);
}

bootstrap();
