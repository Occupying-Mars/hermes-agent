const invoke = window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke || null;

const state = {
  sessions: [],
  toolsets: [],
  models: [],
  config: null,
  openTabs: [],
  activeSessionId: null,
  isSending: false,
  mode: "chat",
  observation: null,
  observationPending: "",
  desktopContext: {
    enabled: false,
    snapshot: null,
    error: "",
    loading: false,
    request: null,
  },
};

const els = {
  sessionsList: document.getElementById("sessions-list"),
  sessionTabs: document.getElementById("session-tabs"),
  chatEmpty: document.getElementById("chat-empty"),
  chatView: document.getElementById("chat-view"),
  sessionTitle: document.getElementById("session-title"),
  sessionMeta: document.getElementById("session-meta"),
  sessionDetails: document.getElementById("session-details"),
  toolsetsView: document.getElementById("toolsets-view"),
  toolsView: document.getElementById("tools-view"),
  messages: document.getElementById("messages"),
  composer: document.getElementById("composer"),
  messageInput: document.getElementById("message-input"),
  shareContextToggle: document.getElementById("share-context-toggle"),
  refreshContextButton: document.getElementById("refresh-context-button"),
  contextStatus: document.getElementById("context-status"),
  contextPreview: document.getElementById("context-preview"),
  refreshButton: document.getElementById("refresh-button"),
  settingsToggle: document.getElementById("settings-toggle"),
  settingsPanel: document.getElementById("settings-panel"),
  configMeta: document.getElementById("config-meta"),
  configEditor: document.getElementById("config-editor"),
  saveConfigButton: document.getElementById("save-config-button"),
  toggleInspectorButton: document.getElementById("toggle-inspector-button"),
  toggleSettingsButton: document.getElementById("toggle-settings-button"),
  newSessionButton: document.getElementById("new-session-button"),
  newSessionDialog: document.getElementById("new-session-dialog"),
  closeDialogButton: document.getElementById("close-dialog-button"),
  newSessionForm: document.getElementById("new-session-form"),
  newTitle: document.getElementById("new-title"),
  newCwd: document.getElementById("new-cwd"),
  newModel: document.getElementById("new-model"),
  newMaxTurns: document.getElementById("new-max-turns"),
  toolsetOptions: document.getElementById("toolset-options"),
  sessionFilter: document.getElementById("session-filter"),
  renameSessionButton: document.getElementById("rename-session-button"),
  deleteSessionButton: document.getElementById("delete-session-button"),
  sendButton: document.getElementById("send-button"),
  inspector: document.getElementById("inspector"),
  workspaceTitle: document.getElementById("workspace-title"),
  modelSelect: document.getElementById("model-select"),
  messagePill: document.getElementById("message-pill"),
  chatModelBadge: document.getElementById("chat-model-badge"),
  chatMessagesBadge: document.getElementById("chat-messages-badge"),
  chatModeButton: document.getElementById("chat-mode-button"),
  observeModeButton: document.getElementById("observe-mode-button"),
  observationView: document.getElementById("observation-view"),
  observationForm: document.getElementById("observation-form"),
  observationGoal: document.getElementById("observation-goal"),
  observationHeroState: document.getElementById("observation-hero-state"),
  observationHeroCopy: document.getElementById("observation-hero-copy"),
  observationModelLabel: document.getElementById("observation-model-label"),
  observationSessionLabel: document.getElementById("observation-session-label"),
  observationLastEvent: document.getElementById("observation-last-event"),
  observationFeedback: document.getElementById("observation-feedback"),
  observationStartButton: document.getElementById("observation-start-button"),
  observationStopButton: document.getElementById("observation-stop-button"),
  observationCheckButton: document.getElementById("observation-check-button"),
  observationGuidance: document.getElementById("observation-guidance"),
  observationTargetSession: document.getElementById("observation-target-session"),
  observationAutoIntervene: document.getElementById("observation-auto-intervene"),
  observationSaveSettingsButton: document.getElementById("observation-save-settings-button"),
  observationStatusPill: document.getElementById("observation-status-pill"),
  observationSummary: document.getElementById("observation-summary"),
  observationActivity: document.getElementById("observation-activity"),
  observationStats: document.getElementById("observation-stats"),
  observationTopApps: document.getElementById("observation-top-apps"),
  observationRecentText: document.getElementById("observation-recent-text"),
  observationEvents: document.getElementById("observation-events"),
  observationAnomalies: document.getElementById("observation-anomalies"),
  observationActions: document.getElementById("observation-actions"),
  desktopActionsView: document.getElementById("desktop-actions-view"),
};

function ensureTauri() {
  if (!invoke) {
    throw new Error("tauri invoke bridge not found");
  }
}

function activeSession() {
  return state.openTabs.find((tab) => tab.session?.id === state.activeSessionId) || null;
}

function relativeTime(ts) {
  if (!ts) return "unknown";
  const deltaMs = Date.now() - Number(ts) * 1000;
  const deltaMin = Math.round(deltaMs / 60000);
  if (deltaMin < 1) return "just now";
  if (deltaMin < 60) return `${deltaMin}m ago`;
  const deltaHours = Math.round(deltaMin / 60);
  if (deltaHours < 24) return `${deltaHours}h ago`;
  const deltaDays = Math.round(deltaHours / 24);
  return `${deltaDays}d ago`;
}

function messageTimestamp(ts) {
  if (!ts) return "";
  try {
    return new Date(Number(ts) * 1000).toLocaleString();
  } catch {
    return "";
  }
}

function shorten(value, limit = 160) {
  const text = String(value || "").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 3).trimEnd()}...`;
}

function contextIsFresh(snapshot, maxAgeMs = 15000) {
  if (!snapshot?.captured_at) return false;
  return Date.now() - Number(snapshot.captured_at) * 1000 < maxAgeMs;
}

function normalizeSessionSummary(item) {
  return {
    id: item.id,
    title: item.title || "",
    preview: item.preview || "",
    source: item.source || "",
    started_at: item.started_at,
    last_active: item.last_active,
    metadata: item.metadata || {},
  };
}

function normalizeObservation(data) {
  return {
    running: Boolean(data?.running),
    goal: data?.goal || "",
    started_at: data?.started_at || null,
    last_check_at: data?.last_check_at || null,
    active_window: data?.active_window || "",
    error: data?.error || "",
    model: data?.model || "moonshotai/kimi-k2",
    session_id: data?.session_id || "",
    log_path: data?.log_path || "",
    screenshots_dir: data?.screenshots_dir || "",
    last_saved_at: data?.last_saved_at || null,
    latest_result: data?.latest_result || null,
    current_activity: data?.current_activity || null,
    activities: Array.isArray(data?.activities) ? data.activities : [],
    stats: data?.stats || {},
    top_apps: Array.isArray(data?.top_apps) ? data.top_apps : [],
    top_windows: Array.isArray(data?.top_windows) ? data.top_windows : [],
    recent_text_captures: Array.isArray(data?.recent_text_captures) ? data.recent_text_captures : [],
    timeline_count: Number(data?.timeline_count || 0),
    events: Array.isArray(data?.events) ? data.events : [],
    guidance: data?.guidance || "",
    target_session_id: data?.target_session_id || "",
    target_session_title: data?.target_session_title || "",
    auto_intervene: data?.auto_intervene !== false,
    anomalies: Array.isArray(data?.anomalies) ? data.anomalies : [],
    recent_actions: Array.isArray(data?.recent_actions) ? data.recent_actions : [],
  };
}

function renderSessions() {
  const query = els.sessionFilter.value.trim().toLowerCase();
  const filtered = state.sessions.filter((session) => {
    if (!query) return true;
    return [session.title, session.preview, session.id, session.metadata?.cwd]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });

  els.sessionsList.innerHTML = "";
  filtered.forEach((session) => {
    const card = document.createElement("button");
    card.className = `session-card ${session.id === state.activeSessionId ? "active" : ""}`;
    card.type = "button";
    card.innerHTML = `
      <h3>${escapeHtml(session.title || session.preview || "untitled session")}</h3>
      <p>${escapeHtml(session.preview || session.metadata?.cwd || "empty session")}</p>
      <div class="session-foot">
        <span>${escapeHtml(session.source || "desktop")}</span>
        <span>${escapeHtml(relativeTime(session.last_active || session.started_at))}</span>
      </div>
    `;
    card.addEventListener("click", () => openSession(session.id));
    els.sessionsList.appendChild(card);
  });
}

function renderTabs() {
  els.sessionTabs.innerHTML = "";
  state.openTabs.forEach((tab) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `tab ${tab.session?.id === state.activeSessionId ? "active" : ""}`;
    button.textContent = tab.session?.title || tab.summary?.title || tab.session?.id || "session";
    button.addEventListener("click", () => setActiveSession(tab.session.id));
    els.sessionTabs.appendChild(button);
  });
}

function renderActiveSession() {
  const tab = activeSession();
  const hasSession = Boolean(tab);
  els.chatEmpty.classList.toggle("hidden", hasSession);
  els.chatView.classList.toggle("hidden", !hasSession);
  if (!tab) {
    els.messages.innerHTML = "";
    els.sessionDetails.innerHTML = "";
    els.toolsetsView.innerHTML = "";
    els.toolsView.innerHTML = "";
    els.desktopActionsView.innerHTML = "";
    els.workspaceTitle.textContent = "autoclys workspace";
    els.modelSelect.value = "";
    els.messagePill.textContent = "0 messages";
    els.chatMessagesBadge.textContent = "0 messages";
    els.chatModelBadge.textContent = "model";
    renderDesktopContext();
    renderMode();
    return;
  }

  const title = tab.session.title || tab.summary?.title || "untitled session";
  const meta = tab.metadata || {};
  els.sessionTitle.textContent = title;
  els.sessionMeta.textContent = `${meta.model || "default model"} · ${meta.cwd || "."}`;
  els.workspaceTitle.textContent = title;
  els.modelSelect.value = meta.model || "";
  els.messagePill.textContent = `${(tab.messages || []).length} messages`;
  els.chatMessagesBadge.textContent = `${(tab.messages || []).length} messages`;
  els.chatModelBadge.textContent = meta.model || "default model";

  els.messages.innerHTML = "";
  (tab.messages || []).forEach((message) => {
    const role = message.role || "assistant";
    const article = document.createElement("article");
    article.className = `message ${role}`;
    const timestamp = escapeHtml(messageTimestamp(message.timestamp));
    const content = escapeHtml(message.content || "");

    if (role === "user") {
      article.innerHTML = `
        <div class="message-user-content">
          <div class="message-head">
            <span>user</span>
            <span>${timestamp}</span>
          </div>
          <div class="message-body">${content}</div>
        </div>
      `;
    } else if (role === "tool") {
      article.innerHTML = `
        <div class="message-head">
          <span>tool</span>
          <span>${timestamp}</span>
        </div>
        <div class="message-tool-content">${content}</div>
      `;
    } else {
      article.innerHTML = `
        <div class="message-head">
          <span>${escapeHtml(role)}</span>
          <span>${timestamp}</span>
        </div>
        <div class="message-assistant-content">${content}</div>
      `;
    }
    els.messages.appendChild(article);
  });
  
  if (state.isSending) {
    const loader = document.createElement("article");
    loader.className = "message assistant";
    loader.innerHTML = `
      <div class="message-head">
        <span>assistant</span>
      </div>
      <div class="message-assistant-content typing-indicator">
        <span class="dot">.</span><span class="dot">.</span><span class="dot">.</span>
      </div>
    `;
    els.messages.appendChild(loader);
  }

  els.messages.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });

  els.sessionDetails.innerHTML = "";
  [
    ["id", tab.session.id],
    ["title", title],
    ["model", meta.model || ""],
    ["cwd", meta.cwd || ""],
    ["toolsets", (meta.toolsets || []).join(", ")],
    ["messages", String((tab.messages || []).length)],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "detail-row";
    row.innerHTML = `<span>${escapeHtml(label)}</span><code>${escapeHtml(value || "")}</code>`;
    els.sessionDetails.appendChild(row);
  });

  els.toolsetsView.innerHTML = "";
  (meta.toolsets || []).forEach((name) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.textContent = name;
    els.toolsetsView.appendChild(chip);
  });

  els.toolsView.innerHTML = "";
  (tab.resolved_tools || []).forEach((name) => {
    const chip = document.createElement("div");
    chip.className = "chip tool";
    chip.textContent = name;
    els.toolsView.appendChild(chip);
  });

  const desktopActions = tab.desktop_actions || [];
  els.desktopActionsView.innerHTML = desktopActions.length
    ? desktopActions
        .map((item) => `
          <article class="observation-event">
            <div class="observation-event-head">
              <strong>${escapeHtml(item.title || item.kind || "action")}</strong>
              <span>${escapeHtml(item.status || "")}</span>
            </div>
            <p>${escapeHtml(shorten([item.objective, item.why, item.detail].filter(Boolean).join(" | "), 220))}</p>
          </article>
        `)
        .join("")
    : '<div class="chat-empty-subtitle">no desktop actions yet.</div>';

  renderDesktopContext();
  renderMode();
}

function verdictLabel(value) {
  if (value === true) return "distracted";
  if (value === false) return "focused";
  return "unknown";
}

function setMode(mode) {
  state.mode = mode === "observe" ? "observe" : "chat";
  renderMode();
}

function renderMode() {
  const observe = state.mode === "observe";
  els.chatModeButton.classList.toggle("active", !observe);
  els.observeModeButton.classList.toggle("active", observe);
  els.observationView.classList.toggle("hidden", !observe);
  els.chatEmpty.classList.toggle("hidden", observe || Boolean(activeSession()));
  els.chatView.classList.toggle("hidden", observe || !activeSession());
  els.renameSessionButton.classList.toggle("hidden", observe);
  els.deleteSessionButton.classList.toggle("hidden", observe);
  els.toggleInspectorButton.classList.toggle("hidden", observe);
  if (observe) {
    const observeState = state.observationPending ? `${state.observationPending}...` : state.observation?.running ? "running" : state.observation?.error ? "error" : "idle";
    els.inspector.classList.add("hidden");
    els.workspaceTitle.textContent = "autoclys observer";
    els.sessionTitle.textContent = state.observation?.goal || "observation";
    els.sessionMeta.textContent = `observer ${observeState}`;
    els.sessionMeta.classList.remove("hidden");
    els.messagePill.textContent = state.observationPending ? `${state.observationPending}...` : state.observation?.running ? "observer live" : state.observation?.error ? "observer error" : "observer idle";
    els.chatModelBadge.textContent = state.observation?.model || "moonshotai/kimi-k2";
    els.chatMessagesBadge.textContent = `${state.observation?.events?.length || 0} events`;
    renderObservation();
    return;
  }
  els.toggleInspectorButton.classList.remove("hidden");
  if (!activeSession()) {
    els.workspaceTitle.textContent = "autoclys workspace";
    els.sessionTitle.textContent = "session";
    els.sessionMeta.textContent = "";
    els.sessionMeta.classList.add("hidden");
    els.messagePill.textContent = "0 messages";
    els.chatModelBadge.textContent = "model";
    els.chatMessagesBadge.textContent = "0 messages";
  }
}

function setObservationError(message) {
  state.observationPending = "";
  state.observation = normalizeObservation({
    ...(state.observation || {}),
    error: message || "unknown error",
  });
  renderObservation();
  renderMode();
}

function renderObservation() {
  const observation = state.observation || normalizeObservation(null);
  state.observation = observation;
  const pending = state.observationPending;
  const isStarting = pending === "start";
  const isStopping = pending === "stop";
  const isChecking = pending === "check";
  const hasError = Boolean(observation.error || observation.latest_result?.error);
  const heroState = isStarting ? "starting" : isStopping ? "stopping" : isChecking ? "checking" : observation.running ? "running" : hasError ? "error" : "idle";
  const lastEvent = observation.events?.[0]?.kind || "waiting";
  const feedback = isStarting
    ? "starting observer. waiting for the backend to begin the capture loop..."
    : isStopping
      ? "stopping observer and flushing the current log..."
      : isChecking
        ? "running an immediate distraction check now..."
        : hasError
          ? (observation.error || observation.latest_result?.error || "observer hit an error")
          : observation.running
            ? "observer is live. window changes, typing bursts, and text chunks will appear below."
            : "idle. press start to begin observing your foreground window.";

  if (document.activeElement !== els.observationGoal || observation.running) {
    els.observationGoal.value = observation.goal || els.observationGoal.value || "";
  }

  els.observationStatusPill.textContent = heroState;
  els.observationStatusPill.className = `chat-header-badge observation-status ${heroState}`;
  els.observationHeroState.textContent = heroState;
  els.observationHeroState.className = `observation-hero-state ${heroState}`;
  els.observationHeroCopy.textContent = observation.running
    ? "autoclys is actively watching the foreground window and asking hermes to judge distraction using kimi."
    : "press start once, then keep working. this panel will tell you immediately if the observer is starting, running, stopping, or failing.";
  els.observationModelLabel.textContent = observation.model || "moonshotai/kimi-k2";
  els.observationSessionLabel.textContent = observation.session_id || "not started";
  els.observationLastEvent.textContent = lastEvent.replaceAll("_", " ");
  els.observationFeedback.textContent = feedback;
  els.observationFeedback.className = `observation-feedback ${heroState}`;
  els.observationStartButton.textContent = isStarting ? "starting..." : observation.running ? "restart" : "start";
  els.observationStopButton.textContent = isStopping ? "stopping..." : "stop";
  els.observationCheckButton.textContent = isChecking ? "checking..." : "check now";
  els.observationGoal.disabled = isStarting || isStopping;
  if (document.activeElement !== els.observationGuidance) {
    els.observationGuidance.value = observation.guidance || "";
  }
  els.observationAutoIntervene.checked = observation.auto_intervene !== false;
  els.observationStartButton.disabled = isStarting || isStopping;
  els.observationStopButton.disabled = isStarting || isStopping || !observation.running;
  els.observationCheckButton.disabled = isStarting || isStopping || isChecking || !observation.running;
  els.observationSaveSettingsButton.disabled = isStarting || isStopping;

  if (document.activeElement !== els.observationTargetSession) {
    const sessionOptionsList = ['<option value="">auto-create intervention thread</option>']
      .concat(
        state.sessions.map((session) => {
          const label = session.title || session.preview || session.id;
          return `<option value="${escapeHtml(session.id)}">${escapeHtml(label)}</option>`;
        })
      );
    if (observation.target_session_id && !state.sessions.find((session) => session.id === observation.target_session_id)) {
      sessionOptionsList.push(
        `<option value="${escapeHtml(observation.target_session_id)}">${escapeHtml(observation.target_session_title || observation.target_session_id)}</option>`
      );
    }
    const sessionOptions = sessionOptionsList.join("");
    els.observationTargetSession.innerHTML = sessionOptions;
    els.observationTargetSession.value = observation.target_session_id || "";
  }

  const latest = observation.latest_result || {};
  const summaryRows = [
    ["goal", observation.goal || "-"],
    ["target", observation.target_session_title || observation.target_session_id || "auto-create"],
    ["model", observation.model || "moonshotai/kimi-k2"],
    ["session", observation.session_id || "-"],
    ["state", heroState],
    ["active window", observation.active_window || latest.window_title || "-"],
    ["last check", observation.last_check_at ? relativeTime(observation.last_check_at) : "never"],
    ["last save", observation.last_saved_at ? relativeTime(observation.last_saved_at) : "never"],
    ["verdict", verdictLabel(latest.is_distracted)],
    ["error", observation.error || latest.error || "-"],
  ];
  els.observationSummary.innerHTML = summaryRows
    .map(([label, value]) => `<div class="detail-row"><span>${escapeHtml(label)}</span><code>${escapeHtml(value || "")}</code></div>`)
    .join("");

  const activity = observation.current_activity;
  if (!activity) {
    els.observationActivity.innerHTML = '<div class="detail-row"><span>status</span><code>no active activity yet</code></div>';
  } else {
    const activityRows = [
      ["window", activity.window_title || "-"],
      ["app", activity.app_name || "-"],
      ["category", activity.category || "-"],
      ["domain", activity.domain || "-"],
      ["duration", activity.duration_ms ? `${Math.round(activity.duration_ms / 1000)}s` : "-"],
      ["keystrokes", String(activity.keystroke_count || 0)],
      ["input events", String(activity.input_events || 0)],
      ["latest text", activity.text_inputs?.[activity.text_inputs.length - 1]?.text || "-"],
      ["recent keys", (activity.keystrokes || []).slice(-12).map((item) => item.key).join(" ") || "-"],
    ];
    els.observationActivity.innerHTML = activityRows
      .map(([label, value]) => `<div class="detail-row"><span>${escapeHtml(label)}</span><code>${escapeHtml(String(value || ""))}</code></div>`)
      .join("");
  }

  const stats = observation.stats || {};
  const statRows = [
    ["log file", observation.log_path ? shorten(observation.log_path, 48) : "-"],
    ["screenshots", observation.screenshots_dir ? shorten(observation.screenshots_dir, 48) : "-"],
    ["apps tracked", String(stats.app_count || 0)],
    ["windows tracked", String(stats.window_count || 0)],
    ["time tracked", stats.total_time_seconds ? `${Math.round(stats.total_time_seconds)}s` : "0s"],
    ["keystrokes", String(stats.total_keystrokes || 0)],
    ["chars typed", String(stats.total_characters_typed || 0)],
    ["timeline", String(observation.timeline_count || 0)],
  ];
  els.observationStats.innerHTML = statRows
    .map(([label, value]) => `<div class="detail-row"><span>${escapeHtml(label)}</span><code>${escapeHtml(String(value || ""))}</code></div>`)
    .join("");

  const topApps = observation.top_apps || [];
  els.observationTopApps.innerHTML = topApps.length
    ? topApps
        .map((item) => {
          const meta = [item.category, `${Math.round(Number(item.seconds || 0))}s`].filter(Boolean).join(" · ");
          return `
            <article class="observation-list-item">
              <strong>${escapeHtml(item.app_name || "app")}</strong>
              <span>${escapeHtml(meta || "-")}</span>
            </article>
          `;
        })
        .join("")
    : '<div class="chat-empty-subtitle">no app rollups yet.</div>';

  const recentText = observation.recent_text_captures || [];
  els.observationRecentText.innerHTML = recentText.length
    ? recentText
        .slice()
        .reverse()
        .map((item) => {
          return `
            <article class="observation-event">
              <div class="observation-event-head">
                <strong>${escapeHtml(item.window || "text")}</strong>
                <span>${escapeHtml(item.timestamp || "")}</span>
              </div>
              <p>${escapeHtml(shorten(item.text || "", 220))}</p>
            </article>
          `;
        })
        .join("")
    : '<div class="chat-empty-subtitle">no captured text yet.</div>';

  const events = observation.events.slice(0, 40);
  els.observationEvents.innerHTML = events.length
    ? events
        .map((event) => {
          const detail = event.text || event.key || event.window_title || event.message || event.app_name || event.previous_window || "";
          return `
            <article class="observation-event">
              <div class="observation-event-head">
                <strong>${escapeHtml(event.kind || "event")}</strong>
                <span>${escapeHtml(relativeTime(event.timestamp))}</span>
              </div>
              <p>${escapeHtml(shorten(detail || JSON.stringify(event), 220))}</p>
            </article>
          `;
        })
        .join("")
    : '<div class="chat-empty-subtitle">no observer events yet.</div>';

  const anomalies = observation.anomalies || [];
  els.observationAnomalies.innerHTML = anomalies.length
    ? anomalies
        .map((item) => `
          <article class="observation-event">
            <div class="observation-event-head">
              <strong>${escapeHtml(item.summary || item.reason || "anomaly")}</strong>
              <span>${escapeHtml(relativeTime(item.timestamp))}</span>
            </div>
            <p>${escapeHtml(shorten([item.window_title, item.app_name, item.text_chunk].filter(Boolean).join(" | "), 220))}</p>
          </article>
        `)
        .join("")
    : '<div class="chat-empty-subtitle">no forwarded anomalies yet.</div>';

  const actions = observation.recent_actions || [];
  els.observationActions.innerHTML = actions.length
    ? actions
        .map((item) => `
          <article class="observation-event">
            <div class="observation-event-head">
              <strong>${escapeHtml(item.title || item.kind || "action")}</strong>
              <span>${escapeHtml(item.status || "")}</span>
            </div>
            <p>${escapeHtml(shorten([item.objective, item.why, item.detail].filter(Boolean).join(" | "), 220))}</p>
          </article>
        `)
        .join("")
    : '<div class="chat-empty-subtitle">the main agent has not acted yet.</div>';
}

function renderToolsetOptions() {
  els.toolsetOptions.innerHTML = "";
  state.toolsets.forEach((toolset) => {
    const label = document.createElement("label");
    label.className = "toolset-option";
    label.innerHTML = `
      <input type="checkbox" value="${escapeHtml(toolset.name)}" />
      <div>
        <strong>${escapeHtml(toolset.name)}</strong>
        <div class="muted small">${escapeHtml(toolset.description || "")}</div>
      </div>
    `;
    els.toolsetOptions.appendChild(label);
  });
}

function renderModels() {
  const options = [`<option value="">default model</option>`]
    .concat(state.models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`))
    .join("");
  els.newModel.innerHTML = options;
  els.modelSelect.innerHTML = options;
}

function renderConfig() {
  if (!state.config) return;
  els.configMeta.textContent = `${state.config.path} · env: ${state.config.env_path}`;
  els.configEditor.value = state.config.config_text || "";
}

function renderDesktopContext() {
  const draft = els.messageInput.value.trim();
  const { enabled, snapshot, error, loading } = state.desktopContext;

  els.shareContextToggle.checked = enabled;
  els.refreshContextButton.disabled = !enabled || loading;

  if (!enabled) {
    els.contextStatus.textContent = "off";
    els.contextPreview.innerHTML = `
      <div class="context-preview-row">
        <span>privacy</span>
        <p>share the foreground app, window title, and browser tab title only when you opt in.</p>
      </div>
    `;
    return;
  }

  if (loading) {
    els.contextStatus.textContent = "capturing...";
  } else if (snapshot?.captured_at) {
    els.contextStatus.textContent = `captured ${relativeTime(snapshot.captured_at)}`;
  } else if (error) {
    els.contextStatus.textContent = "unavailable";
  } else {
    els.contextStatus.textContent = "ready";
  }

  const rows = [];
  if (snapshot?.active_app) {
    rows.push(`
      <div class="context-preview-row">
        <span>active app</span>
        <code>${escapeHtml(snapshot.active_app)}</code>
      </div>
    `);
  }
  if (snapshot?.window_title) {
    rows.push(`
      <div class="context-preview-row">
        <span>window</span>
        <code>${escapeHtml(shorten(snapshot.window_title, 220))}</code>
      </div>
    `);
  }
  if (snapshot?.browser_tab?.title || snapshot?.browser_tab?.browser || snapshot?.browser_tab?.domain) {
    const parts = [
      snapshot.browser_tab.browser,
      snapshot.browser_tab.title,
      snapshot.browser_tab.domain && `(${snapshot.browser_tab.domain})`,
    ].filter(Boolean);
    rows.push(`
      <div class="context-preview-row">
        <span>browser tab</span>
        <code>${escapeHtml(shorten(parts.join(" | "), 220))}</code>
      </div>
    `);
  }
  if (draft) {
    rows.push(`
      <div class="context-preview-row">
        <span>current draft</span>
        <code>${escapeHtml(shorten(draft, 240))}</code>
      </div>
    `);
  }
  if (error) {
    rows.push(`
      <div class="context-preview-row">
        <span>status</span>
        <p>${escapeHtml(error)}</p>
      </div>
    `);
  }
  if (!rows.length) {
    rows.push(`
      <div class="context-preview-row">
        <span>status</span>
        <p>no active context captured yet. press refresh.</p>
      </div>
    `);
  }

  els.contextPreview.innerHTML = rows.join("");
}

async function refreshDesktopContext({ force = false, silent = false } = {}) {
  ensureTauri();
  if (!state.desktopContext.enabled && !force) {
    return null;
  }
  if (state.desktopContext.request) {
    return state.desktopContext.request;
  }
  if (!force && contextIsFresh(state.desktopContext.snapshot)) {
    return state.desktopContext.snapshot;
  }

  state.desktopContext.loading = true;
  if (!silent) {
    state.desktopContext.error = "";
  }
  renderDesktopContext();

  state.desktopContext.request = invoke("get_desktop_context")
    .then((snapshot) => {
      state.desktopContext.snapshot = snapshot || null;
      state.desktopContext.error = snapshot?.error || "";
      return state.desktopContext.snapshot;
    })
    .catch((error) => {
      state.desktopContext.error = error?.message || String(error);
      if (!silent) {
        console.error(error);
      }
      return null;
    })
    .finally(() => {
      state.desktopContext.loading = false;
      state.desktopContext.request = null;
      renderDesktopContext();
    });

  return state.desktopContext.request;
}

async function buildContextPayload(message) {
  if (!state.desktopContext.enabled) {
    return null;
  }

  let snapshot = state.desktopContext.snapshot;
  if (!contextIsFresh(snapshot)) {
    snapshot = await refreshDesktopContext({ force: true, silent: true });
  }
  if (!snapshot) {
    return null;
  }

  return {
    active_app: snapshot.active_app || null,
    window_title: snapshot.window_title || null,
    browser_tab: snapshot.browser_tab || null,
    draft_text: message,
    captured_at: snapshot.captured_at || null,
  };
}

function setActiveSession(sessionId) {
  state.activeSessionId = sessionId;
  renderSessions();
  renderTabs();
  renderActiveSession();
}

function upsertSummary(summary) {
  const normalized = normalizeSessionSummary(summary);
  const existing = state.sessions.findIndex((item) => item.id === normalized.id);
  if (existing === -1) {
    state.sessions.unshift(normalized);
  } else {
    state.sessions[existing] = { ...state.sessions[existing], ...normalized };
  }
}

async function openSession(sessionId) {
  ensureTauri();
  const result = await invoke("get_session", { sessionId });
  const session = result.session;
  const summary = normalizeSessionSummary({
    ...session,
    preview: result.messages?.find((message) => message.role === "user")?.content || "",
    metadata: result.metadata,
  });
  upsertSummary(summary);

  const existing = state.openTabs.findIndex((tab) => tab.session?.id === sessionId);
  const nextTab = {
    summary,
    session,
    metadata: result.metadata,
    messages: result.messages || [],
    resolved_tools: result.resolved_tools || [],
    desktop_actions: result.desktop_actions || [],
    desktop_anomalies: result.desktop_anomalies || [],
  };
  if (existing === -1) {
    state.openTabs.push(nextTab);
  } else {
    state.openTabs[existing] = nextTab;
  }
  setActiveSession(sessionId);
}

async function bootstrap() {
  ensureTauri();
  const data = await invoke("bootstrap");
  state.sessions = (data.sessions || []).map(normalizeSessionSummary);
  state.toolsets = data.toolsets || [];
  state.models = data.models || [];
  state.config = data.config || null;
  renderSessions();
  renderToolsetOptions();
  renderModels();
  renderConfig();
  state.observation = normalizeObservation(data.observation);
  renderDesktopContext();
  renderObservation();
  renderMode();
}

async function fetchObservationState({ silent = false } = {}) {
  ensureTauri();
  try {
    const data = await invoke("get_observation_state");
    const nextObservation = normalizeObservation(data.observation);
    if (state.observationPending === "start" && !nextObservation.running && !nextObservation.error) {
      state.observation = nextObservation;
    } else if (state.observationPending === "stop" && nextObservation.running) {
      state.observation = nextObservation;
    } else if (state.observationPending === "check" && nextObservation.running && !nextObservation.last_check_at) {
      state.observation = nextObservation;
    } else {
      state.observationPending = "";
      state.observation = nextObservation;
    }
    renderObservation();
    renderMode();
    if (nextObservation.target_session_id && !state.sessions.find((item) => item.id === nextObservation.target_session_id)) {
      refreshSessions().catch(() => {});
    }
    return state.observation;
  } catch (error) {
    if (!silent) {
      console.error(error);
    }
    throw error;
  }
}

async function refreshSessions() {
  ensureTauri();
  const data = await invoke("list_sessions");
  state.sessions = (data.sessions || []).map(normalizeSessionSummary);
  renderSessions();
}

async function handleCreateSession(event) {
  event.preventDefault();
  ensureTauri();
  const selectedToolsets = Array.from(
    els.toolsetOptions.querySelectorAll("input:checked")
  ).map((input) => input.value);

  const payload = {
    title: els.newTitle.value.trim() || null,
    cwd: els.newCwd.value.trim() || null,
    model: els.newModel.value || null,
    max_turns: els.newMaxTurns.value ? Number(els.newMaxTurns.value) : null,
    toolsets: selectedToolsets.length ? selectedToolsets : null,
  };

  const created = await invoke("create_session", { payload });
  els.newSessionDialog.close();
  els.newSessionForm.reset();
  upsertSummary({
    ...created.session,
    preview: "",
    metadata: created.metadata,
  });
  await openSession(created.session.id);
  renderSessions();
}

async function handleSendMessage(event) {
  event.preventDefault();
  const tab = activeSession();
  if (!tab) return;
  const message = els.messageInput.value.trim();
  if (!message) return;

  state.isSending = true;
  const optimisticMessage = {
    role: "user",
    content: message,
    timestamp: Math.floor(Date.now() / 1000),
  };
  const existing = state.openTabs.findIndex((item) => item.session.id === tab.session.id);
  if (existing !== -1) {
    state.openTabs[existing] = {
      ...state.openTabs[existing],
      messages: [...(state.openTabs[existing].messages || []), optimisticMessage],
    };
  }
  upsertSummary({
    ...tab.session,
    preview: message,
    metadata: tab.metadata,
  });
  els.messageInput.value = "";
  renderSessions();
  renderActiveSession();
  els.sendButton.disabled = true;
  try {
    const contextSnapshot = await buildContextPayload(message);
    const result = await invoke("send_message", {
      payload: {
        session_id: tab.session.id,
        message,
        context_snapshot: contextSnapshot,
      },
    });
    upsertSummary({
      ...result.session,
      preview: message,
      metadata: result.metadata,
    });
    if (existing !== -1) {
      state.openTabs[existing] = {
        ...state.openTabs[existing],
        session: result.session,
        metadata: result.metadata,
        messages: result.messages,
        resolved_tools: result.resolved_tools,
        desktop_actions: result.desktop_actions || [],
        desktop_anomalies: result.desktop_anomalies || [],
      };
    }
    renderSessions();
    renderActiveSession();
  } catch (error) {
    if (existing !== -1) {
      state.openTabs[existing] = {
        ...state.openTabs[existing],
        messages: tab.messages,
      };
    }
    els.messageInput.value = message;
    renderActiveSession();
    throw error;
  } finally {
    els.sendButton.disabled = false;
    state.isSending = false;
    renderActiveSession();
  }
}

function handleComposerKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  els.composer.requestSubmit();
}

function handleContextToggle() {
  state.desktopContext.enabled = els.shareContextToggle.checked;
  state.desktopContext.error = "";
  renderDesktopContext();
  if (state.desktopContext.enabled) {
    refreshDesktopContext({ force: true }).catch((error) => {
      console.error(error);
    });
  }
}

async function handleRenameSession() {
  const tab = activeSession();
  if (!tab) return;
  const title = window.prompt("new session title", tab.session.title || "");
  if (!title) return;
  const result = await invoke("rename_session", {
    payload: { session_id: tab.session.id, title },
  });
  upsertSummary({
    ...result.session,
    preview: tab.summary?.preview || "",
    metadata: result.metadata,
  });
  await openSession(tab.session.id);
}

async function handleDeleteSession() {
  const tab = activeSession();
  if (!tab) return;
  const confirmed = window.confirm(`delete session ${tab.session.id}?`);
  if (!confirmed) return;
  await invoke("delete_session", { sessionId: tab.session.id });
  state.openTabs = state.openTabs.filter((item) => item.session.id !== tab.session.id);
  state.sessions = state.sessions.filter((item) => item.id !== tab.session.id);
  state.activeSessionId = state.openTabs[0]?.session?.id || null;
  renderSessions();
  renderTabs();
  renderActiveSession();
}

async function handleObservationStart(event) {
  event?.preventDefault?.();
  const goal = els.observationGoal.value.trim() || state.observation?.goal || "study";
  els.observationGoal.value = goal;
  state.observationPending = "start";
  state.observation = normalizeObservation({
    ...(state.observation || {}),
    goal,
    error: "",
    model: state.observation?.model || "moonshotai/kimi-k2",
  });
  setMode("observe");
  renderObservation();
  try {
    ensureTauri();
    await handleObservationSettingsSave();
    const data = await invoke("start_observation", { payload: { goal } });
    state.observationPending = "";
    state.observation = normalizeObservation(data.observation);
    setMode("observe");
  } catch (error) {
    console.error(error);
    state.observationPending = "";
    setObservationError(error?.message || String(error));
  }
}

async function handleObservationStop(event) {
  event?.preventDefault?.();
  state.observationPending = "stop";
  renderObservation();
  try {
    ensureTauri();
    const data = await invoke("stop_observation");
    state.observationPending = "";
    state.observation = normalizeObservation(data.observation);
    renderObservation();
    renderMode();
  } catch (error) {
    console.error(error);
    state.observationPending = "";
    setObservationError(error?.message || String(error));
  }
}

async function handleObservationCheck(event) {
  event?.preventDefault?.();
  state.observationPending = "check";
  renderObservation();
  try {
    ensureTauri();
    const data = await invoke("check_observation_now");
    state.observationPending = "";
    state.observation = normalizeObservation(data.observation);
    renderObservation();
    renderMode();
  } catch (error) {
    console.error(error);
    state.observationPending = "";
    setObservationError(error?.message || String(error));
  }
}

async function handleObservationSettingsSave() {
  ensureTauri();
  const result = await invoke("update_observation_settings", {
    payload: {
      guidance: els.observationGuidance.value.trim(),
      target_session_id: els.observationTargetSession.value || null,
      auto_intervene: els.observationAutoIntervene.checked,
    },
  });
  state.observation = normalizeObservation(result.observation);
  renderObservation();
  renderMode();
}

async function handleSaveConfig() {
  ensureTauri();
  const result = await invoke("save_config", {
    payload: { config_text: els.configEditor.value },
  });
  state.config = result.config;
  renderConfig();
}

async function handleModelChange() {
  const tab = activeSession();
  if (!tab) {
    return;
  }
  const result = await invoke("update_session_settings", {
    payload: {
      session_id: tab.session.id,
      model: els.modelSelect.value || null,
    },
  });
  const existing = state.openTabs.findIndex((item) => item.session.id === tab.session.id);
  state.openTabs[existing] = {
    ...state.openTabs[existing],
    session: result.session,
    metadata: result.metadata,
    messages: result.messages,
    resolved_tools: result.resolved_tools,
    desktop_actions: result.desktop_actions || [],
    desktop_anomalies: result.desktop_anomalies || [],
  };
  upsertSummary({
    ...result.session,
    preview: tab.summary?.preview || "",
    metadata: result.metadata,
  });
  renderSessions();
  renderActiveSession();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function wireEvents() {
  els.refreshButton.addEventListener("click", refreshSessions);
  els.chatModeButton.addEventListener("click", () => setMode("chat"));
  els.observeModeButton.addEventListener("click", () => setMode("observe"));
  els.settingsToggle.addEventListener("click", () => {
    els.settingsPanel.classList.toggle("hidden");
  });
  els.toggleSettingsButton.addEventListener("click", () => {
    els.settingsPanel.classList.toggle("hidden");
  });
  els.toggleInspectorButton.addEventListener("click", () => {
    els.inspector.classList.toggle("hidden");
  });
  els.newSessionButton.addEventListener("click", () => els.newSessionDialog.showModal());
  els.closeDialogButton.addEventListener("click", () => els.newSessionDialog.close());
  els.newSessionForm.addEventListener("submit", handleCreateSession);
  els.composer.addEventListener("submit", handleSendMessage);
  els.messageInput.addEventListener("keydown", handleComposerKeydown);
  els.messageInput.addEventListener("input", renderDesktopContext);
  els.shareContextToggle.addEventListener("change", handleContextToggle);
  els.refreshContextButton.addEventListener("click", () => {
    refreshDesktopContext({ force: true }).catch((error) => {
      console.error(error);
    });
  });
  els.sessionFilter.addEventListener("input", renderSessions);
  els.renameSessionButton.addEventListener("click", handleRenameSession);
  els.deleteSessionButton.addEventListener("click", handleDeleteSession);
  els.saveConfigButton.addEventListener("click", handleSaveConfig);
  els.modelSelect.addEventListener("change", handleModelChange);
  els.observationForm.addEventListener("submit", handleObservationStart);
  els.observationStartButton.addEventListener("click", handleObservationStart);
  els.observationStopButton.addEventListener("click", handleObservationStop);
  els.observationCheckButton.addEventListener("click", handleObservationCheck);
  els.observationSaveSettingsButton.addEventListener("click", () => {
    handleObservationSettingsSave().catch((error) => console.error(error));
  });
}

async function main() {
  wireEvents();
  window.setInterval(() => {
    if (!document.hidden && state.desktopContext.enabled) {
      refreshDesktopContext({ silent: true }).catch(() => {});
    }
  }, 15000);
  window.setInterval(() => {
    if (!document.hidden) {
      fetchObservationState({ silent: true }).catch(() => {});
    }
  }, 500);
  window.setInterval(() => {
    if (!document.hidden && activeSession() && !state.isSending) {
      openSession(state.activeSessionId).catch(() => {});
    }
  }, 2000);
  try {
    await bootstrap();
  } catch (error) {
    console.error(error);
    els.chatEmpty.innerHTML = `
      <h2>desktop app could not start</h2>
      <p>${escapeHtml(error?.message || String(error))}</p>
      <p>make sure the repo has a working <code>.venv</code> because the app uses it to launch hermes.</p>
    `;
  }
}

main();
