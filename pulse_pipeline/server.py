"""FastAPI server — chat API, Fivetran webhook receiver, and static UI."""

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

# Mapping: user_id -> session_id (for simplicity, one session per user)
_user_sessions: dict[str, str] = {}

# SSE subscribers — browsers listening for heal-loop events
_event_subscribers: set[asyncio.Queue] = set()


def _broadcast(event: dict) -> None:
    """Push an event to every connected SSE client (drop if a queue is full)."""
    for queue in _event_subscribers:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

app = FastAPI(title="PulsePipe", version="0.1.0")

# Serve static frontend
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_or_create_session(user_id: str) -> str:
    """Return existing session ID or create a new one."""
    if user_id in _user_sessions:
        return _user_sessions[user_id]

    session = await session_service.create_session(
        app_name="pulse_pipeline",
        user_id=user_id,
    )
    _user_sessions[user_id] = session.id
    return session.id


async def _run_agent(user_id: str, message: str):
    """Send a message to the agent and yield text chunks."""
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
            # Tool call events — surface to UI for transparency
            if part.function_call:
                yield {
                    "type": "tool_call",
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args) if part.function_call.args else {},
                }
            elif part.function_response:
                yield {
                    "type": "tool_result",
                    "name": part.function_response.name,
                    "result": _safe_serialize(part.function_response.response),
                }
            elif part.text:
                yield {"type": "text", "content": part.text}


def _safe_serialize(obj) -> str:
    """Best-effort JSON serialization for tool results."""
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
    """Non-streaming chat endpoint — returns the full response at once."""
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

    return {
        "response": "".join(texts),
        "tool_calls": tool_calls,
    }


@app.post("/api/webhook/fivetran")
async def fivetran_webhook(request: Request):
    """Receive Fivetran webhook events and feed them into the heal loop."""
    payload = await request.json()
    logger.info("Webhook received: %s", json.dumps(payload, default=str)[:500])

    event_type = payload.get("event", "unknown")
    connection_id = payload.get("connector_id") or payload.get("data", {}).get("connector_id", "unknown")

    # Build a system-style message so the agent recognizes it as a webhook
    webhook_message = (
        f"[WEBHOOK EVENT] Fivetran event received.\n"
        f"Event type: {event_type}\n"
        f"Connection ID: {connection_id}\n"
        f"Payload: {json.dumps(payload, default=str)[:1000]}\n\n"
        f"Please diagnose and fix this issue following the Heal loop protocol."
    )

    # Run in background — don't block the webhook response
    asyncio.create_task(_heal_in_background(connection_id, webhook_message))

    return {"status": "accepted", "connection_id": connection_id}


async def _heal_in_background(connection_id: str, message: str):
    """Run the heal loop in the background and broadcast progress to the UI."""
    user_id = f"webhook_{connection_id}"
    _broadcast({"type": "heal_start", "connection_id": connection_id})
    try:
        texts = []
        async for chunk in _run_agent(user_id, message):
            # Surface every heal step (tool calls + agent narration) to the UI
            _broadcast({**chunk, "heal": True, "connection_id": connection_id})
            if chunk["type"] == "text":
                texts.append(chunk["content"])
        logger.info("Heal loop completed for %s: %s", connection_id, "".join(texts)[:500])
        _broadcast({"type": "heal_complete", "connection_id": connection_id, "ok": True})
    except Exception:
        logger.exception("Heal loop failed for %s", connection_id)
        _broadcast({"type": "heal_complete", "connection_id": connection_id, "ok": False})


@app.get("/api/events")
async def events():
    """SSE stream — pushes heal-loop events to the browser in real time."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _event_subscribers.add(queue)

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _event_subscribers.discard(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/sessions/reset")
async def reset_session(request: Request):
    """Reset a user's session to start fresh."""
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
