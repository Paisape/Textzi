"""Live connection for an anonymous website visitor's browser tab -- the visitor-facing
counterpart to waba_realtime.py's agent-facing socket. No JWT (there's no account): auth is the
widget_key (identifies the entity) plus an Origin-header check against
WebchatWidgetSettings.allowed_origins, since a WebSocket handshake isn't covered by the app's
regular CORSMiddleware the way a normal HTTP request is (confirmed via research -- browsers don't
apply the fetch/XHR CORS model to WS connections at all). Publishes onto a per-visitor Redis
channel (not the shared per-entity one waba_realtime.py uses) so a visitor only ever receives
events addressed to them, never another visitor's or another channel's traffic; the agent-inbox
side still sees new webchat messages via the existing per-entity channel, since
webchat_public.py's send_visitor_message already publishes there too (see waba_realtime.publish_event
reuse). Deliberately its own module, same isolation principle as every other channel module."""
import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import WebchatWidgetSettings
from .waba_realtime import publish_event

logger = logging.getLogger("textzi.webchat")

router = APIRouter(tags=["webchat-realtime"])


def _visitor_channel(visitor_id: str) -> str:
    return f"webchat:visitor:{visitor_id}"


def publish_to_visitor(visitor_id: str, event: dict) -> None:
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        client.publish(_visitor_channel(visitor_id), json.dumps(event))
    except Exception:
        logger.warning("webchat realtime: could not publish event for visitor_id=%s", visitor_id, exc_info=True)


@router.websocket("/v1/public/webchat/{widget_key}/ws")
async def webchat_visitor_websocket(websocket: WebSocket, widget_key: str, visitor_id: str = ""):
    if not visitor_id:
        await websocket.close(code=4422)
        return

    db = SessionLocal()
    try:
        settings_row = db.scalar(select(WebchatWidgetSettings).where(WebchatWidgetSettings.widget_key == widget_key))
        if not settings_row or not settings_row.enabled:
            await websocket.close(code=4404)
            return
        origin = websocket.headers.get("origin")
        if not settings_row.allowed_origins or origin not in settings_row.allowed_origins:
            await websocket.close(code=4403)
            return
        entity_id = settings_row.entity_id
    finally:
        db.close()

    await websocket.accept()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=5)
    pubsub = redis_client.pubsub()
    channel = _visitor_channel(visitor_id)
    await pubsub.subscribe(channel)

    async def _forward() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    forward_task = asyncio.create_task(_forward())
    try:
        while True:
            # The widget sends a "typing" ping while the visitor is composing -- republished to
            # the entity's own agent-inbox channel so an agent viewing this conversation sees a
            # live "visitor is typing..." indicator, same shape as waba_realtime.py's own presence
            # re-broadcast for agent-side "viewing" pings.
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if data.get("type") == "typing":
                publish_event(entity_id, {"type": "webchat_typing", "visitor_id": visitor_id})
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis_client.aclose()
