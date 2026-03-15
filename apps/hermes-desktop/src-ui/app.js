const invoke = window.__TAURI__?.core?.invoke || window.__TAURI_INTERNALS__?.invoke || null;

const state = {
  sessions: [],
  toolsets: [],
  models: [],
  config: null,
  openTabs: [],
  activeSessionId: null,
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
  els.workspaceTitle.textContent = "autoclys workspace";
  els.modelSelect.value = "";
  els.messagePill.textContent = "0 messages";
  els.chatMessagesBadge.textContent = "0 messages";
  els.chatModelBadge.textContent = "model";
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
  els.messages.lastElementChild?.scrollIntoView({ block: "end" });

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
    const result = await invoke("send_message", {
      payload: {
        session_id: tab.session.id,
        message,
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
  }
}

function handleComposerKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  els.composer.requestSubmit();
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
  els.sessionFilter.addEventListener("input", renderSessions);
  els.renameSessionButton.addEventListener("click", handleRenameSession);
  els.deleteSessionButton.addEventListener("click", handleDeleteSession);
  els.saveConfigButton.addEventListener("click", handleSaveConfig);
  els.modelSelect.addEventListener("change", handleModelChange);
}

async function main() {
  wireEvents();
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
