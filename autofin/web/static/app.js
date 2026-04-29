const state = {
  activeSessionId: null,
  activeTaskId: null,
  eventSource: null,
  inlineEventKeys: new Set(),
  summaryAppended: false,
};

const nodes = {
  form: document.querySelector("#task-form"),
  chatForm: document.querySelector("#chat-form"),
  chatMessage: document.querySelector("#chat-message"),
  chatLog: document.querySelector("#chat-log"),
  ticker: document.querySelector("#ticker"),
  filingType: document.querySelector("#filing-type"),
  objective: document.querySelector("#objective"),
  runtimeStatus: document.querySelector("#runtime-status"),
  activeTaskId: document.querySelector("#active-task-id"),
  sessionMemory: document.querySelector("#session-memory"),
  timeline: document.querySelector("#timeline"),
  taskList: document.querySelector("#task-list"),
  skillList: document.querySelector("#skill-list"),
  modelConfigForm: document.querySelector("#model-config-form"),
  modelConfigState: document.querySelector("#model-config-state"),
  modelProvider: document.querySelector("#model-provider"),
  modelName: document.querySelector("#model-name"),
  modelBaseUrl: document.querySelector("#model-base-url"),
  modelApiKey: document.querySelector("#model-api-key"),
  modelTemperature: document.querySelector("#model-temperature"),
  resultJson: document.querySelector("#result-json"),
  evidenceList: document.querySelector("#evidence-list"),
  refreshTasks: document.querySelector("#refresh-tasks"),
  newSession: document.querySelector("#new-session"),
  clearSessions: document.querySelector("#clear-sessions"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setStatus(status) {
  nodes.runtimeStatus.textContent = status;
  nodes.runtimeStatus.className = `status-badge status-${status.toLowerCase()}`;
}

function renderJson(value) {
  nodes.resultJson.textContent = JSON.stringify(value || {}, null, 2);
}

function renderEmpty(container, text) {
  container.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty";
  empty.textContent = text;
  container.appendChild(empty);
}

async function loadSkills() {
  const data = await api("/api/skills");
  nodes.skillList.innerHTML = "";
  data.skills.forEach((skill) => {
    const row = document.createElement("div");
    row.className = "skill-row";
    row.innerHTML = `
      <strong>${escapeHtml(skill.name)}</strong>
      <span>${escapeHtml(skill.description)}</span>
      <span>${escapeHtml(JSON.stringify(skill.permissions))}</span>
    `;
    nodes.skillList.appendChild(row);
  });
}

async function loadModelConfig() {
  const data = await api("/api/settings/model");
  renderModelConfig(data.model_api);
}

function renderModelConfig(config) {
  nodes.modelProvider.value = config.provider || "openai-compatible";
  nodes.modelName.value = config.model || "";
  nodes.modelBaseUrl.value = config.base_url || "";
  nodes.modelApiKey.value = "";
  nodes.modelApiKey.placeholder = config.api_key_configured
    ? `Configured: ${config.api_key_preview}`
    : "Leave blank to keep existing key";
  nodes.modelTemperature.value = config.temperature ?? 0.2;
  nodes.modelConfigState.textContent = config.api_key_configured ? "Ready" : "Unset";
  nodes.modelConfigState.className = `config-state ${config.api_key_configured ? "config-ready" : ""}`;
}

async function saveModelConfig(event) {
  event.preventDefault();
  const payload = {
    provider: nodes.modelProvider.value,
    model: nodes.modelName.value.trim(),
    base_url: nodes.modelBaseUrl.value.trim(),
    api_key: nodes.modelApiKey.value.trim(),
    temperature: Number(nodes.modelTemperature.value || 0.2),
  };
  const data = await api("/api/settings/model", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderModelConfig(data.model_api);
}

async function loadSessions() {
  const data = await api("/api/sessions");
  nodes.taskList.innerHTML = "";
  if (!data.sessions.length) {
    renderEmpty(nodes.taskList, "No sessions");
    return;
  }
  if (!state.activeSessionId) {
    state.activeSessionId = data.sessions[0].id;
  }
  data.sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = `task-row ${session.id === state.activeSessionId ? "active" : ""}`;
    row.innerHTML = `
      <button type="button" class="session-open-button">
        <strong>${escapeHtml(session.title || "New session")}</strong>
        <span>${escapeHtml(session.working_entities?.last_intent || "conversation")}</span>
        <span>${escapeHtml(session.id.slice(0, 12))}</span>
      </button>
      <span class="session-row-actions">
        <button type="button" data-delete-session="${escapeHtml(session.id)}" title="Delete session">Delete</button>
      </span>
    `;
    row.querySelector(".session-open-button").addEventListener("click", () => openSession(session.id));
    const deleteButton = row.querySelector("[data-delete-session]");
    deleteButton.addEventListener("click", (event) => deleteSession(event, session.id, session.title));
    nodes.taskList.appendChild(row);
  });
  if (state.activeSessionId) {
    await openSession(state.activeSessionId);
  }
}

async function newSession() {
  const data = await api("/api/sessions", { method: "POST", body: JSON.stringify({}) });
  state.activeSessionId = data.session.id;
  state.activeTaskId = null;
  nodes.activeTaskId.textContent = "No active task";
  nodes.timeline.innerHTML = "";
  renderJson({});
  renderEmpty(nodes.evidenceList, "No evidence");
  renderSessionMemory(data.session);
  renderChatMessages([]);
  await loadSessions();
}

async function deleteSession(event, sessionId, title) {
  event.stopPropagation();
  const confirmed = window.confirm(`Delete session "${title || sessionId}"? This removes its local conversation memory and transcript.`);
  if (!confirmed) {
    return;
  }
  const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  state.activeSessionId = data.active_session?.id || null;
  await loadSessions();
  if (state.activeSessionId) {
    await openSession(state.activeSessionId);
  }
}

async function clearSessions() {
  const confirmed = window.confirm("Delete all local sessions? This removes all conversation memory and transcripts.");
  if (!confirmed) {
    return;
  }
  const data = await api("/api/sessions", { method: "DELETE" });
  state.activeSessionId = data.active_session?.id || null;
  state.activeTaskId = null;
  nodes.activeTaskId.textContent = "No active task";
  nodes.timeline.innerHTML = "";
  renderJson({});
  renderEmpty(nodes.evidenceList, "No evidence");
  await loadSessions();
}

async function openSession(sessionId) {
  state.activeSessionId = sessionId;
  const data = await api(`/api/sessions/${sessionId}`);
  renderChatMessages(data.session.messages || []);
  if (data.session.active_task_id) {
    nodes.activeTaskId.textContent = data.session.active_task_id;
    state.activeTaskId = data.session.active_task_id;
    try {
      await loadTaskResult(data.session.active_task_id);
    } catch (error) {
      renderMissingTask(data.session.active_task_id, error, data.session);
    }
  } else {
    state.activeTaskId = null;
    nodes.activeTaskId.textContent = "No active task";
    renderJson({});
    renderEmpty(nodes.evidenceList, "No evidence");
  }
  renderSessionMemory(data.session);
  nodes.taskList.querySelectorAll(".task-row").forEach((row) => row.classList.remove("active"));
  await loadSessionsHeaderOnly();
}

async function loadSessionsHeaderOnly() {
  const data = await api("/api/sessions");
  nodes.taskList.innerHTML = "";
  data.sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = `task-row ${session.id === state.activeSessionId ? "active" : ""}`;
    row.innerHTML = `
      <button type="button" class="session-open-button">
        <strong>${escapeHtml(session.title || "New session")}</strong>
        <span>${escapeHtml(session.working_entities?.last_intent || "conversation")}</span>
        <span>${escapeHtml(session.id.slice(0, 12))}</span>
      </button>
      <span class="session-row-actions">
        <button type="button" data-delete-session="${escapeHtml(session.id)}" title="Delete session">Delete</button>
      </span>
    `;
    row.querySelector(".session-open-button").addEventListener("click", () => openSession(session.id));
    const deleteButton = row.querySelector("[data-delete-session]");
    deleteButton.addEventListener("click", (event) => deleteSession(event, session.id, session.title));
    nodes.taskList.appendChild(row);
  });
}

async function openTask(taskId, options = {}) {
  if (state.eventSource) {
    state.eventSource.close();
  }
  state.activeTaskId = taskId;
  state.inlineEventKeys = new Set();
  state.summaryAppended = false;
  nodes.activeTaskId.textContent = taskId;
  nodes.timeline.innerHTML = "";

  const task = await api(`/api/tasks/${taskId}`);
  setStatus(task.status);
  if (!options.preserveChat) {
    renderChatMessages(task.messages || []);
  }
  renderTaskResult(task);

  const source = new EventSource(`/api/tasks/${taskId}/events`);
  state.eventSource = source;
  source.addEventListener("task-event", (message) => {
    const event = JSON.parse(message.data);
    appendTimelineEvent(event);
    appendInlineEvent(event);
    loadTaskResult(taskId);
  });
  source.addEventListener("task-closed", async (message) => {
    const event = JSON.parse(message.data);
    setStatus(event.status);
    source.close();
    await loadTaskResult(taskId);
    if (state.activeSessionId) {
      await refreshActiveSessionMemory();
    }
    await loadSessionsHeaderOnly();
    const task = await api(`/api/tasks/${taskId}`);
    appendCompletionSummary(task);
  });
}

async function loadTaskResult(taskId) {
  const task = await api(`/api/tasks/${taskId}`);
  setStatus(task.status);
  renderTaskResult(task);
}

function renderMissingTask(taskId, error, session = null) {
  const taskSummary = (session?.task_summaries || []).find((task) => task.task_id === taskId);
  setStatus("Missing");
  renderJson({
    status: "missing",
    task_id: taskId,
    note: "This session references a task that is not available in the current runtime.",
    recovered_from_session_memory: taskSummary || null,
    next_step: taskSummary ? "Re-run the research task to restore full events and evidence." : undefined,
    error: error.message,
  });
  renderEmpty(
    nodes.evidenceList,
    taskSummary
      ? "Full evidence is unavailable for this older task; the session memory still has its summary."
      : "Task result is unavailable",
  );
}

function renderTaskResult(task) {
  renderJson(task.result || { status: task.status, error: task.error });
  const evidence = task.result?.result?.evidence || [];
  nodes.evidenceList.innerHTML = "";
  if (!evidence.length) {
    renderEmpty(nodes.evidenceList, "No evidence");
    return;
  }
  evidence.forEach((item) => {
    const row = document.createElement("div");
    row.className = "evidence-row";
    row.innerHTML = `
      <strong>${escapeHtml(item.source || item.kind || "evidence")}</strong>
      <span>${escapeHtml(item.note || JSON.stringify(item))}</span>
    `;
    nodes.evidenceList.appendChild(row);
  });
}

async function refreshActiveSessionMemory() {
  if (!state.activeSessionId) {
    renderEmpty(nodes.sessionMemory, "No session memory");
    return;
  }
  const data = await api(`/api/sessions/${state.activeSessionId}`);
  renderSessionMemory(data.session);
}

function renderSessionMemory(session) {
  if (!session) {
    renderEmpty(nodes.sessionMemory, "No session memory");
    return;
  }

  const entities = session.working_entities || {};
  const pending = session.pending_action;
  const taskSummaries = session.task_summaries || [];

  const entityRows = Object.entries(entities).map(
    ([key, value]) => `
      <div class="memory-row">
        <span>${escapeHtml(key)}</span>
        <strong>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</strong>
      </div>
    `,
  );

  const pendingHtml = pending
    ? `
      <div class="memory-block">
        <div class="memory-title">Pending</div>
        <pre>${escapeHtml(JSON.stringify(pending, null, 2))}</pre>
      </div>
    `
    : "";

  const taskHtml = taskSummaries.length
    ? `
      <div class="memory-block">
        <div class="memory-title">Recent Tasks</div>
        ${taskSummaries
          .slice()
          .reverse()
          .map(
            (task) => `
              <div class="memory-task">
                <strong>${escapeHtml(task.ticker || task.skill_name || "task")}</strong>
                <span>${escapeHtml([task.filing_type, `${task.evidence_count || 0} evidence`].filter(Boolean).join(" · "))}</span>
                <small>${escapeHtml(task.summary || task.task_id || "")}</small>
              </div>
            `,
          )
          .join("")}
      </div>
    `
    : "";

  nodes.sessionMemory.innerHTML = `
    <div class="memory-block">
      <div class="memory-title">Session</div>
      <div class="memory-row">
        <span>ID</span>
        <strong>${escapeHtml((session.id || "").slice(0, 12))}</strong>
      </div>
      <div class="memory-row">
        <span>Messages</span>
        <strong>${escapeHtml(session.message_count || 0)}</strong>
      </div>
      ${
        session.active_task_id
          ? `<div class="memory-row"><span>Active task</span><strong>${escapeHtml(session.active_task_id.slice(0, 8))}</strong></div>`
          : ""
      }
    </div>
    ${
      entityRows.length
        ? `<div class="memory-block"><div class="memory-title">Working Entities</div>${entityRows.join("")}</div>`
        : `<div class="empty compact-empty">No working entities</div>`
    }
    ${pendingHtml}
    ${taskHtml}
  `;
}

function renderChatMessages(messages) {
  nodes.chatLog.innerHTML = "";
  if (!messages.length) {
    renderEmpty(nodes.chatLog, "Start with a research request");
    return;
  }
  messages.forEach((message) => appendChatMessage(message));
}

function appendChatMessage(message) {
  const row = document.createElement("div");
  row.className = `chat-message chat-${message.role}`;
  row.innerHTML = `
    <div class="chat-role">${escapeHtml(message.role)}</div>
    <div class="chat-content">${escapeHtml(message.content)}</div>
  `;
  nodes.chatLog.appendChild(row);
  nodes.chatLog.scrollTop = nodes.chatLog.scrollHeight;
  return row;
}

function updateChatMessage(row, message) {
  row.className = `chat-message chat-${message.role}`;
  row.innerHTML = `
    <div class="chat-role">${escapeHtml(message.role)}</div>
    <div class="chat-content">${escapeHtml(message.content)}</div>
  `;
  nodes.chatLog.scrollTop = nodes.chatLog.scrollHeight;
}

function appendInlineEvent(event) {
  const key = `${event.index}-${event.event_type}`;
  if (state.inlineEventKeys.has(key)) {
    return;
  }
  state.inlineEventKeys.add(key);

  const row = document.createElement("div");
  row.className = `chat-event event-${event.event_type}`;
  row.innerHTML = renderEventCard(event);
  nodes.chatLog.appendChild(row);
  nodes.chatLog.scrollTop = nodes.chatLog.scrollHeight;
}

function renderEventCard(event) {
  if (event.event_type.startsWith("tool_call_")) {
    const payload = event.payload || {};
    const isCompleted = event.event_type === "tool_call_completed";
    const summary = isCompleted
      ? `${payload.tool || "tool"} · ${payload.status || "completed"} · ${payload.evidence_count || 0} evidence`
      : `${payload.tool || "tool"} · permissions requested`;
    return `
      <details class="event-card tool-card" ${isCompleted ? "" : "open"}>
        <summary>
          <span class="event-dot"></span>
          <span>
            <strong>${escapeHtml(event.message)}</strong>
            <small>${escapeHtml(summary)}</small>
          </span>
        </summary>
        ${renderPayloadSections(payload)}
      </details>
    `;
  }

  return `
    <details class="event-card" open>
      <summary>
        <span class="event-dot"></span>
        <span>
          <strong>${escapeHtml(event.message)}</strong>
          <small>${escapeHtml(formatEventType(event.event_type))}</small>
        </span>
      </summary>
      <pre>${escapeHtml(JSON.stringify(event.payload || {}, null, 2))}</pre>
    </details>
  `;
}

function renderPayloadSections(payload) {
  const sections = [];
  if (payload.inputs) {
    sections.push(payloadSection("Inputs", payload.inputs));
  }
  if (payload.permissions) {
    sections.push(payloadSection("Permissions", payload.permissions));
  }
  if (payload.trace_id) {
    sections.push(payloadSection("Trace", { trace_id: payload.trace_id }));
  }
  if (payload.evidence) {
    sections.push(payloadSection("Evidence", payload.evidence));
  }
  if (!sections.length) {
    sections.push(payloadSection("Payload", payload));
  }
  return sections.join("");
}

function payloadSection(title, value) {
  return `
    <div class="payload-section">
      <div class="payload-title">${escapeHtml(title)}</div>
      <pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>
    </div>
  `;
}

function appendCompletionSummary(task) {
  if (state.summaryAppended || !task?.result) {
    return;
  }
  state.summaryAppended = true;
  const result = task.result.result?.data || {};
  const warnings = task.result.result?.warnings || [];
  appendChatMessage({
    role: "assistant",
    content: [
      `已完成 ${result.ticker || task.inputs.ticker} 的 ${result.filing_type || task.inputs.filing_type} 研究任务。`,
      result.summary || "",
      warnings.length ? `Warnings: ${warnings.join("; ")}` : "",
    ]
      .filter(Boolean)
      .join("\n\n"),
  });
}

function appendTimelineEvent(event) {
  const item = document.createElement("li");
  item.className = "timeline-item";
  const time = new Date(event.timestamp).toLocaleTimeString();
  item.innerHTML = `
    <span class="timeline-time">${escapeHtml(time)}</span>
    <div>
      <div class="timeline-title">${escapeHtml(event.message)}</div>
      <div class="timeline-payload">${escapeHtml(JSON.stringify(event.payload, null, 2))}</div>
    </div>
  `;
  nodes.timeline.appendChild(item);
}

function formatEventType(eventType) {
  return eventType.replaceAll("_", " ");
}

async function createTask(event) {
  event.preventDefault();
  setStatus("Queued");
  const payload = {
    objective: nodes.objective.value.trim() || "Analyze SEC filing",
    skill_name: "sec_filing_analysis",
    ticker: nodes.ticker.value.trim(),
    filing_type: nodes.filingType.value,
  };
  const task = await api("/api/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadSessions();
  await openTask(task.id);
}

async function sendChat(event) {
  event.preventDefault();
  const message = nodes.chatMessage.value.trim();
  if (!message) {
    return;
  }

  if (nodes.chatLog.querySelector(".empty")) {
    nodes.chatLog.innerHTML = "";
  }
  appendChatMessage({ role: "user", content: message });
  const pendingRow = appendChatMessage({ role: "assistant", content: "" });
  nodes.chatMessage.value = "";
  setStatus("Queued");

  try {
    await streamChatReply(message, pendingRow);
    setStatus("Idle");
  } catch (error) {
    updateChatMessage(pendingRow, {
      role: "assistant",
      content: `请求失败：${error.message}`,
    });
    setStatus("Idle");
  }
}

async function streamChatReply(message, row) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: state.activeSessionId }),
  });
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let content = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const event = parseSSE(rawEvent);
      if (event.event === "chat-meta") {
        if (event.data.session_id) {
          state.activeSessionId = event.data.session_id;
        }
        if (event.data.session) {
          renderSessionMemory(event.data.session);
        }
        appendRouteCard(event.data, message);
        loadSessionsHeaderOnly();
      }
      if (event.event === "chat-token") {
        content += event.data.content || "";
        updateChatMessage(row, { role: "assistant", content });
      }
    }
  }
}

function appendRouteCard(meta, message) {
  const routed = meta.routed_intent || {};
  const policy = meta.policy_decision || {};
  const actionCard = meta.action_card;
  const row = document.createElement("div");
  row.className = "chat-event";

  const confidence = typeof routed.confidence === "number" ? routed.confidence.toFixed(2) : "n/a";
  const fields = [
    routed.ticker ? `Ticker: ${routed.ticker}` : "",
    routed.filing_type ? `Filing: ${routed.filing_type}` : "",
    routed.focus?.length ? `Focus: ${routed.focus.join(", ")}` : "",
    routed.missing_fields?.length ? `Missing: ${routed.missing_fields.join(", ")}` : "",
  ].filter(Boolean);

  row.innerHTML = `
    <div class="route-card">
      <div class="route-card-header">
        <span class="intent-chip">${escapeHtml(routed.intent || "unknown")} · ${escapeHtml(confidence)}</span>
        <span class="policy-action">${escapeHtml(policy.action || "route")}</span>
      </div>
      ${fields.length ? `<div class="route-fields">${fields.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>` : ""}
      ${actionCard ? renderRunResearchCard(actionCard) : ""}
    </div>
  `;

  const button = row.querySelector("[data-run-research]");
  if (button) {
    button.addEventListener("click", () => runResearch(message, button));
  }
  nodes.chatLog.appendChild(row);
  nodes.chatLog.scrollTop = nodes.chatLog.scrollHeight;
}

function renderRunResearchCard(actionCard) {
  const focus = actionCard.focus?.length ? actionCard.focus.join(", ") : "general filing analysis";
  return `
    <div class="run-card">
      <div>
        <strong>${escapeHtml(actionCard.title || "Run research")}</strong>
        <span>${escapeHtml(actionCard.skill_name || "sec_filing_analysis")} · ${escapeHtml(focus)}</span>
      </div>
      <button type="button" data-run-research>Run Research</button>
    </div>
  `;
}

async function runResearch(message, button) {
  button.disabled = true;
  button.textContent = "Running";
  setStatus("Queued");
  try {
    const payload = await api("/api/research/run", {
      method: "POST",
      body: JSON.stringify({ message, session_id: state.activeSessionId }),
    });
    if (payload.session_id) {
      state.activeSessionId = payload.session_id;
    }
    if (!payload.task) {
      appendChatMessage(payload.assistant_message || { role: "assistant", content: "这个请求还不能执行。" });
      setStatus("Idle");
      return;
    }
    appendChatMessage(payload.assistant_message);
    if (payload.session) {
      renderSessionMemory(payload.session);
    }
    await loadSessions();
    await openTask(payload.task.id, { preserveChat: true });
  } catch (error) {
    button.disabled = false;
    button.textContent = "Run Research";
    appendChatMessage({ role: "assistant", content: `启动研究失败：${error.message}` });
    setStatus("Idle");
  }
}

function parseSSE(rawEvent) {
  const lines = rawEvent.split("\n");
  const eventType = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() || "message";
  const dataLine = lines.find((line) => line.startsWith("data:"))?.slice(5).trim() || "{}";
  return { event: eventType, data: JSON.parse(dataLine) };
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

if (nodes.form) {
  nodes.form.addEventListener("submit", createTask);
}
nodes.modelConfigForm.addEventListener("submit", saveModelConfig);
nodes.chatForm.addEventListener("submit", sendChat);
nodes.refreshTasks.addEventListener("click", loadSessions);
nodes.newSession.addEventListener("click", newSession);
nodes.clearSessions.addEventListener("click", clearSessions);

renderEmpty(nodes.chatLog, "Start with a research request");
renderEmpty(nodes.taskList, "No sessions");
renderEmpty(nodes.skillList, "No skills");
renderEmpty(nodes.timeline, "No events");
renderEmpty(nodes.evidenceList, "No evidence");
renderEmpty(nodes.sessionMemory, "No session memory");
renderJson({});

loadSkills();
loadModelConfig();
loadSessions();
