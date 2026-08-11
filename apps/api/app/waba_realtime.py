"""Live updates for the shared inbox UI -- one WebSocket per connected browser tab, fed by Redis
pub/sub so every API process/replica sees the same events regardless of which one handled the
HTTP request that triggered them (same reasoning services._redis() already applies to rate
limiting: an in-process-only channel would miss events published by a sibling worker). Publishing
is fire-and-forget -- a missed live update just leaves the inbox stale until the next reload
(the database row is always the source of truth), so a Redis blip must never affect the request
that triggered the publish. Deliberately its own module, never importing from or importing into
dispatch.py/providers.py/webhooks.py (the SMS-specific pipeline)."""
import asyncio
import json
import logging

import jwt
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import ConversationMessage, User, UserSession, UserStatus
from .security import decode_access_token
from .services import DomainError, resolve_user_entity

logger = logging.getLogger("textzi.waba")

router = APIRouter(tags=["waba-realtime"])


def _channel(entity_id: str) -> str:
    return f"waba:entity:{entity_id}"


def message_payload(message: ConversationMessage) -> dict:
    return {
        "id": message.id, "conversation_id": message.conversation_id, "direction": message.direction,
        "is_private": message.is_private, "message_type": message.message_type, "body": message.body,
        "media_url": message.media_url, "status": message.status, "sent_by_user_id": message.sent_by_user_id,
        "created_at": message.created_at.isoformat(),
    }


def publish_event(entity_id: str, event: dict) -> None:
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        client.publish(_channel(entity_id), json.dumps(event))
    except Exception:
        logger.warning("waba realtime: could not publish event for entity_id=%s", entity_id, exc_info=True)


def authenticate_query_token(db: Session, token: str) -> User | None:
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    if claims.get("purpose") == "mfa":
        return None
    user = db.get(User, claims.get("sub"))
    if not user or user.status != UserStatus.active:
        return None
    sid = claims.get("sid")
    if sid:
        session = db.get(UserSession, sid)
        if not session or session.revoked_at:
            return None
    return user


@router.websocket("/v1/waba/ws")
async def waba_websocket(websocket: WebSocket, token: str = ""):
    """Browsers' native WebSocket API can't set an Authorization header, so the access token
    travels as a query param instead -- the one exception to this codebase's usual Bearer-header
    convention (auth.require_user), same tradeoff every app with a token-per-header auth model
    and a WebSocket feature makes."""
    db = SessionLocal()
    try:
        user = authenticate_query_token(db, token)
        if not user:
            await websocket.close(code=4401)
            return
        try:
            entity = resolve_user_entity(db, user)
        except DomainError:
            await websocket.close(code=4422)
            return
    finally:
        db.close()

    await websocket.accept()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=5)
    pubsub = redis_client.pubsub()
    channel = _channel(entity.id)
    await pubsub.subscribe(channel)

    async def _forward() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    forward_task = asyncio.create_task(_forward())
    try:
        while True:
            # The only thing the frontend ever sends is a "viewing" ping when an agent opens a
            # conversation -- collision detection (see inbox.vue), re-broadcast to every other tab
            # on this entity (including the sender's own other tabs) via the same Redis channel
            # events flow through the other direction. Anything else received is ignored rather
            # than closing the connection, so a stray/future message shape doesn't kill the socket.
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if data.get("type") == "viewing" and data.get("conversation_id"):
                publish_event(entity.id, {"type": "presence", "conversation_id": data["conversation_id"], "user_id": user.id, "user_name": user.full_name})
    except WebSocketDisconnect:
        pass
    finally:
        forward_task.cancel()
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis_client.aclose()
