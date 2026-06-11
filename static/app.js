// PulsePipe — Chat UI with heal-loop visibility

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const btnSend = document.getElementById("btn-send");
const btnReset = document.getElementById("btn-reset");
const pipelineStatusEl = document.getElementById("pipeline-status");
const incidentLogEl = document.getElementById("incident-log");
const healBanner = document.getElementById("heal-banner");
const healBannerText = document.getElementById("heal-banner-text");

const USER_ID = "user_" + Math.random().toString(36).slice(2, 10);

const pipelines = new Map();
const incidents = [];

// ── SSE: subscribe to heal-loop events ──────────────────────────
function connectHealStream() {
  const source = new EventSource("/api/heal/stream");

  source.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }

    if (event.type === "heal_start") {
      showHealBanner(`Repairing ${event.connection_id} (${event.event_type})...`);
      appendHealMessage(`Pipeline repair triggered for **${event.connection_id}** — event: ${event.event_type}`);
      updatePipelineStatus(event.connection_id, "healing");

    } else if (event.type === "tool_call") {
      appendToolCall(event.name, event.args, true);
      trackPipeline(event.name, event.args);

    } else if (event.type === "text") {
      appendHealMessage(event.content);

    } else if (event.type === "heal_end") {
      hideHealBanner();
      appendHealMessage(`Repair complete for **${event.connection_id}**`);
      updatePipelineStatus(event.connection_id, "success");
      loadIncidents();

    } else if (event.type === "heal_error") {
      hideHealBanner();
      appendHealMessage(`Repair failed for **${event.connection_id}**: ${event.error}`);
      updatePipelineStatus(event.connection_id, "error");
      loadIncidents();
    }
  };

  source.onerror = () => {
    source.close();
    setTimeout(connectHealStream, 5000);
  };
}

connectHealStream();

// ── Heal banner ─────────────────────────────────────────────────
function showHealBanner(text) {
  healBannerText.textContent = text;
  healBanner.classList.remove("hidden");
}

function hideHealBanner() {
  healBanner.classList.add("hidden");
}

// ── Send message ────────────────────────────────────────────────
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  appendMessage("user", text);
  input.value = "";
  setLoading(true);

  const typingEl = appendTyping();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, message: text }),
    });

    typingEl.remove();

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let assistantBubble = null;
    let assistantText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const lines = decoder.decode(value, { stream: true }).split("\n");
      for (const line of lines) {
        if (!line.trim()) continue;
        let chunk;
        try { chunk = JSON.parse(line); } catch { continue; }

        if (chunk.type === "tool_call") {
          appendToolCall(chunk.name, chunk.args, false);
          trackPipeline(chunk.name, chunk.args);
        } else if (chunk.type === "text") {
          assistantText += chunk.content;
          if (!assistantBubble) {
            assistantBubble = appendMessage("assistant", assistantText);
          } else {
            assistantBubble.querySelector(".message-content").innerHTML =
              formatMarkdown(assistantText);
          }
        }
      }
    }
  } catch (err) {
    typingEl.remove();
    appendMessage("assistant", "Connection error — please try again.");
    console.error(err);
  }

  setLoading(false);
});

// ── Reset session ───────────────────────────────────────────────
btnReset.addEventListener("click", async () => {
  await fetch("/api/sessions/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID }),
  });
  messagesEl.innerHTML = "";
  pipelines.clear();
  incidents.length = 0;
  renderPipelines();
  renderIncidents();
  appendMessage(
    "assistant",
    "Session reset. Describe the data you need!"
  );
});

// ── DOM helpers ─────────────────────────────────────────────────
function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `message ${role}`;
  div.innerHTML = `<div class="message-content">${formatMarkdown(text)}</div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function appendHealMessage(text) {
  const div = document.createElement("div");
  div.className = "message heal";
  div.innerHTML = `
    <div class="message-content">
      <div class="message-label">Auto-Repair</div>
      ${formatMarkdown(text)}
    </div>`;
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function appendToolCall(name, args, isHeal) {
  const div = document.createElement("div");
  div.className = `tool-call${isHeal ? " heal-tool" : ""}`;
  const argsStr = Object.entries(args || {})
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" ")
    .slice(0, 120);
  div.innerHTML = `
    <span class="tool-icon">&#9881;</span>
    <span class="tool-name">${escapeHtml(name)}</span>
    <span class="tool-args">${escapeHtml(argsStr)}</span>
  `;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function appendTyping() {
  const div = document.createElement("div");
  div.className = "typing";
  div.innerHTML = "<span></span><span></span><span></span>";
  messagesEl.appendChild(div);
  scrollToBottom();
  return div;
}

function setLoading(on) {
  btnSend.disabled = on;
  input.disabled = on;
  if (!on) input.focus();
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ── Pipeline tracker ────────────────────────────────────────────
function trackPipeline(toolName, args) {
  if (toolName === "create_connection" || toolName === "create_connect_card") {
    const id = args.connector_id || args.service || "pipeline";
    pipelines.set(id, { name: args.service || id, status: "syncing" });
  } else if (toolName === "sync_connection") {
    const id = args.connector_id || "pipeline";
    if (pipelines.has(id)) pipelines.get(id).status = "syncing";
  } else if (toolName === "query_destination" || toolName === "verify_post_heal") {
    for (const [, p] of pipelines) {
      if (p.status === "syncing") p.status = "success";
    }
  } else if (toolName === "resync_tables" || toolName === "modify_connection") {
    const id = args.connector_id || "pipeline";
    if (pipelines.has(id)) pipelines.get(id).status = "healing";
  }
  renderPipelines();
}

function updatePipelineStatus(connectionId, status) {
  if (pipelines.has(connectionId)) {
    pipelines.get(connectionId).status = status;
  } else {
    pipelines.set(connectionId, { name: connectionId, status });
  }
  renderPipelines();
}

function renderPipelines() {
  if (pipelines.size === 0) {
    pipelineStatusEl.innerHTML = '<div class="status-empty">No active pipelines</div>';
    return;
  }
  pipelineStatusEl.innerHTML = "";
  for (const [, p] of pipelines) {
    const div = document.createElement("div");
    div.className = "status-item";
    div.innerHTML = `
      <span class="status-dot ${p.status}"></span>
      <span>${escapeHtml(p.name)}</span>
    `;
    pipelineStatusEl.appendChild(div);
  }
}

// ── Incident log ────────────────────────────────────────────────
async function loadIncidents() {
  try {
    const res = await fetch("/api/incidents");
    const data = await res.json();
    incidents.length = 0;
    incidents.push(...data);
    renderIncidents();
  } catch { /* ignore */ }
}

function renderIncidents() {
  if (incidents.length === 0) {
    incidentLogEl.innerHTML = '<div class="status-empty">No incidents</div>';
    return;
  }
  incidentLogEl.innerHTML = "";
  // Show most recent first, max 10
  const recent = incidents.slice(-10).reverse();
  for (const inc of recent) {
    const div = document.createElement("div");
    div.className = `incident-item ${inc.outcome || ""}`;
    div.innerHTML = `
      <span class="incident-id">${escapeHtml(inc.id)}</span>
      <span class="incident-type">${escapeHtml(inc.failure_type)}</span>
      <span class="incident-outcome">${escapeHtml(inc.outcome)}
        ${inc.time_to_recovery_seconds != null ? ` &middot; ${inc.time_to_recovery_seconds}s` : ""}
      </span>
    `;
    incidentLogEl.appendChild(div);
  }
}

// Load incidents on startup
loadIncidents();

// ── Formatting ──────────────────────────────────────────────────
function formatMarkdown(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
