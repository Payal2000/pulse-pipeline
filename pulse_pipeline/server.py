"""FastAPI server — chat API, Fivetran webhook receiver, SSE heal stream, and static UI."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agent import root_agent
from .config import settings
from .tools import get_incident_log

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ADK runner + session service
# ---------------------------------------------------------------------------
session_service = InMemorySessionService()
runner = Runner(
    agent=root_agent,
    app_name="pulse_pipeline",
    session_service=session_service,
)

# Mapping: user_id -> session_id (one session per user)
_user_sessions: dict[str, str] = {}

# SSE subscribers for heal-loop visibility
# Each connected client gets a queue; heal events are broadcast to all
_heal_subscribers: list[asyncio.Queue] = []

app = FastAPI(title="PulsePipe", version="0.1.0")

# Serve static frontend
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_or_create_session(user_id: str) -> str:
    if user_id in _user_sessions:
        return _user_sessions[user_id]

    session = await session_service.create_session(
        app_name="pulse_pipeline",
        user_id=user_id,
    )
    _user_sessions[user_id] = session.id
    return session.id


async def _broadcast_heal_event(event: dict):
    """Push a heal event to all connected SSE clients."""
    dead: list[asyncio.Queue] = []
    for q in _heal_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _heal_subscribers.remove(q)


async def _run_agent(user_id: str, message: str, broadcast_heal: bool = False):
    """Send a message to the agent and yield event chunks."""
    session_id = await _get_or_create_session(user_id)

    content = types.Content(
        role="user",
        parts=[types.Part(text=message)],
    )

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue

        for part in event.content.parts:
            if part.function_call:
                chunk = {
                    "type": "tool_call",
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args) if part.function_call.args else {},
                }
                yield chunk
                if broadcast_heal:
                    await _broadcast_heal_event(chunk)

            elif part.function_response:
                chunk = {
                    "type": "tool_result",
                    "name": part.function_response.name,
                    "result": _safe_serialize(part.function_response.response),
                }
                yield chunk
                if broadcast_heal:
                    await _broadcast_heal_event(chunk)

            elif part.text:
                chunk = {"type": "text", "content": part.text}
                yield chunk
                if broadcast_heal:
                    await _broadcast_heal_event(chunk)


def _safe_serialize(obj) -> str:
    try:
        return json.dumps(obj, default=str)[:2000]
    except Exception:
        return str(obj)[:2000]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text()


@app.post("/api/chat")
async def chat(request: Request):
    """Stream agent response as newline-delimited JSON (NDJSON)."""
    body = await request.json()
    user_id = body.get("user_id", "default")
    message = body.get("message", "")

    if not message:
        return {"error": "message is required"}

    async def event_stream():
        async for chunk in _run_agent(user_id, message):
            yield json.dumps(chunk) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.post("/api/chat/sync")
async def chat_sync(request: Request):
    """Non-streaming chat — returns the full response at once."""
    body = await request.json()
    user_id = body.get("user_id", "default")
    message = body.get("message", "")

    if not message:
        return {"error": "message is required"}

    texts: list[str] = []
    tool_calls: list[dict] = []

    async for chunk in _run_agent(user_id, message):
        if chunk["type"] == "text":
            texts.append(chunk["content"])
        elif chunk["type"] == "tool_call":
            tool_calls.append(chunk)

    return {"response": "".join(texts), "tool_calls": tool_calls}


@app.post("/api/webhook/fivetran")
async def fivetran_webhook(request: Request):
    """Receive Fivetran webhook events and feed them into the repair loop.

    All repair actions are broadcast to connected SSE clients so the
    heal loop is visible in the chat UI in real time.
    """
    payload = await request.json()
    logger.info("Webhook received: %s", json.dumps(payload, default=str)[:500])

    event_type = payload.get("event", "unknown")
    connection_id = (
        payload.get("connector_id")
        or payload.get("data", {}).get("connector_id", "unknown")
    )

    # Notify all SSE clients that a webhook arrived
    await _broadcast_heal_event({
        "type": "heal_start",
        "connection_id": connection_id,
        "event_type": event_type,
    })

    webhook_message = (
        f"[WEBHOOK EVENT] Fivetran event received.\n"
        f"Event type: {event_type}\n"
        f"Connection ID: {connection_id}\n"
        f"Payload: {json.dumps(payload, default=str)[:1000]}\n\n"
        f"Please diagnose and fix this issue following the Repair loop protocol."
    )

    asyncio.create_task(_heal_in_background(connection_id, webhook_message))

    return {"status": "accepted", "connection_id": connection_id}


async def _heal_in_background(connection_id: str, message: str):
    """Run the repair loop in the background, broadcasting events to the UI."""
    user_id = f"webhook_{connection_id}"
    try:
        texts = []
        async for chunk in _run_agent(user_id, message, broadcast_heal=True):
            if chunk["type"] == "text":
                texts.append(chunk["content"])

        await _broadcast_heal_event({
            "type": "heal_end",
            "connection_id": connection_id,
            "summary": "".join(texts)[:500],
        })
        logger.info("Repair completed for %s", connection_id)

    except Exception:
        logger.exception("Repair loop failed for %s", connection_id)
        await _broadcast_heal_event({
            "type": "heal_error",
            "connection_id": connection_id,
            "error": "Repair loop encountered an unexpected error.",
        })


@app.get("/api/heal/stream")
async def heal_stream():
    """SSE endpoint — clients subscribe to real-time heal-loop events.

    The frontend connects to this on page load.  When a webhook triggers
    a repair, every step (tool calls, reasoning, outcome) is pushed here
    so the user watches the agent heal the pipeline live.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _heal_subscribers.append(queue)

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _heal_subscribers:
                _heal_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/incidents")
async def incidents():
    """Return the incident audit log."""
    return get_incident_log()


@app.post("/api/sessions/reset")
async def reset_session(request: Request):
    body = await request.json()
    user_id = body.get("user_id", "default")
    _user_sessions.pop(user_id, None)
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "pulse_pipeline"}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main():
    uvicorn.run(
        "pulse_pipeline.server:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
