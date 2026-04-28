const state = {
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

async function loadTasks() {
  const data = await api("/api/tasks");
  nodes.taskList.innerHTML = "";
  if (!data.tasks.length) {
    renderEmpty(nodes.taskList, "No sessions");
    return;
  }
  data.tasks.forEach((task) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-row";
    button.innerHTML = `
      <strong>${escapeHtml(task.inputs.ticker || task.skill_name)}</strong>
      <span class="status-${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
      <span>${escapeHtml(task.id.slice(0, 8))}</span>
    `;
    button.addEventListener("click", () => openTask(task.id));
    nodes.taskList.appendChild(button);
  });
}

async function openTask(taskId) {
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
  renderChatMessages(task.messages || []);
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
    loadTasks();
    await loadTaskResult(taskId);
    const task = await api(`/api/tasks/${taskId}`);
    appendCompletionSummary(task);
  });
}

async function loadTaskResult(taskId) {
  const task = await api(`/api/tasks/${taskId}`);
  setStatus(task.status);
  renderTaskResult(task);
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
  await loadTasks();
  await openTask(task.id);
}

async function sendChat(event) {
  event.preventDefault();
  const message = nodes.chatMessage.value.trim();
  if (!message) {
    return;
  }

  renderChatMessages([{ role: "user", content: message }]);
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
    body: JSON.stringify({ message }),
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
      if (event.event === "chat-token") {
        content += event.data.content || "";
        updateChatMessage(row, { role: "assistant", content });
      }
    }
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
nodes.refreshTasks.addEventListener("click", loadTasks);

renderEmpty(nodes.chatLog, "Start with a research request");
renderEmpty(nodes.taskList, "No sessions");
renderEmpty(nodes.skillList, "No skills");
renderEmpty(nodes.timeline, "No events");
renderEmpty(nodes.evidenceList, "No evidence");
renderJson({});

loadSkills();
loadModelConfig();
loadTasks();
