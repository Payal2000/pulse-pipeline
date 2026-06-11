// PulsePipe — Chat UI

const messagesEl = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const btnSend = document.getElementById("btn-send");
const btnReset = document.getElementById("btn-reset");
const pipelineStatusEl = document.getElementById("pipeline-status");

const USER_ID = "user_" + Math.random().toString(36).slice(2, 10);

// Track active pipelines for sidebar
const pipelines = new Map();

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
          appendToolCall(chunk.name, chunk.args);
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

// ── Heal-loop live events (SSE) ─────────────────────────────────
// The heal loop runs server-side from Fivetran webhooks; this stream
// makes it visible in the chat in real time.
let healBubble = null;
let healText = "";

const eventSource = new EventSource("/api/events");
eventSource.onmessage = (e) => {
  let event;
  try { event = JSON.parse(e.data); } catch { return; }

  if (event.type === "heal_start") {
    healBubble = null;
    healText = "";
    appendHealBanner(`Pipeline issue detected (${event.connection_id}) — agent is investigating…`);
    setPipelineStatus(event.connection_id, "healing");
  } else if (event.type === "tool_call" && event.heal) {
    appendToolCall(event.name, event.args);
    trackPipeline(event.name, event.args);
  } else if (event.type === "text" && event.heal) {
    healText += event.content;
    if (!healBubble) {
      healBubble = appendMessage("assistant heal", healText);
    } else {
      healBubble.querySelector(".message-content").innerHTML = formatMarkdown(healText);
    }
  } else if (event.type === "heal_complete") {
    setPipelineStatus(event.connection_id, event.ok ? "success" : "error");
    appendHealBanner(
      event.ok
        ? `Self-heal complete for ${event.connection_id} ✓`
        : `Self-heal could not finish for ${event.connection_id} — see report above`
    );
  }
};

function appendHealBanner(text) {
  const div = document.createElement("div");
  div.className = "heal-banner";
  div.innerHTML = `<span class="heal-icon">&#128295;</span> ${escapeHtml(text)}`;
  messagesEl.appendChild(div);
  scrollToBottom();
}

function setPipelineStatus(id, status) {
  if (!pipelines.has(id)) pipelines.set(id, { name: id, status });
  else pipelines.get(id).status = status;
  renderPipelines();
}

// ── Reset session ───────────────────────────────────────────────
btnReset.addEventListener("click", async () => {
  await fetch("/api/sessions/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: USER_ID }),
  });
  messagesEl.innerHTML = "";
  pipelines.clear();
  renderPipelines();
  appendMessage(
    "assistant",
    "Session reset. Tell me what data you need!"
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

function appendToolCall(name, args) {
  const div = document.createElement("div");
  div.className = "tool-call";
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
  } else if (toolName === "query_destination") {
    // If we're querying, a sync likely succeeded
    for (const [, p] of pipelines) {
      if (p.status === "syncing") p.status = "success";
    }
  } else if (toolName === "reload_connection_schema_config" || toolName === "resync_tables") {
    const id = args.connector_id || "pipeline";
    if (pipelines.has(id)) pipelines.get(id).status = "healing";
  }
  renderPipelines();
}

function renderPipelines() {
  if (pipelines.size === 0) {
    pipelineStatusEl.innerHTML = '<div class="status-empty">No active pipelines</div>';
    return;
  }
  pipelineStatusEl.innerHTML = "";
  for (const [id, p] of pipelines) {
    const div = document.createElement("div");
    div.className = "status-item";
    div.innerHTML = `
      <span class="status-dot ${p.status}"></span>
      <span>${escapeHtml(p.name)}</span>
    `;
    pipelineStatusEl.appendChild(div);
  }
}

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
