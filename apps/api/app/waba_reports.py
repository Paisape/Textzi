"""Reporting for the WhatsApp channel -- conversation volume, per-agent activity, label
distribution, SLA breaches, CSAT. Read-only aggregation over the shared inbox tables; deliberately
its own module (kept out of the already-large waba_inbox.py) but still just a consumer of the
shared Contact/Conversation/ConversationMessage tables, same as every other inbox-adjacent
module."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import ConversationLabel, ConversationMessage, CsatResponse, Conversation, Label, User
from .schemas import ReportAgentRow, ReportLabelRow, ReportVolumePoint, WabaReportsOut
from .services import DomainError, resolve_user_entity

router = APIRouter(prefix="/v1/waba/reports", tags=["waba-reports"])


@router.get("", response_model=WabaReportsOut)
def get_reports(days: int = 30, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    conversation_ids = db.scalars(select(Conversation.id).where(Conversation.entity_id == entity.id)).all()
    if not conversation_ids:
        return WabaReportsOut(volume=[], agents=[], labels=[], total_conversations=0, open_conversations=0, resolved_conversations=0, sla_breached_count=0, avg_csat=None, csat_response_count=0)

    # --- Volume: per-day inbound/outbound counts ---
    volume_rows = db.execute(
        select(func.date(ConversationMessage.created_at), ConversationMessage.direction, func.count())
        .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.created_at >= since, ConversationMessage.is_private.is_(False))
        .group_by(func.date(ConversationMessage.created_at), ConversationMessage.direction),
    ).all()
    by_date: dict[str, dict[str, int]] = {}
    for date_val, direction, count in volume_rows:
        key = date_val.isoformat() if hasattr(date_val, "isoformat") else str(date_val)
        by_date.setdefault(key, {"inbound": 0, "outbound": 0})[direction] = count
    volume = [ReportVolumePoint(date=d, inbound=v.get("inbound", 0), outbound=v.get("outbound", 0)) for d, v in sorted(by_date.items())]

    # --- Per-agent: messages sent, conversations currently resolved & assigned to them ---
    sent_rows = db.execute(
        select(ConversationMessage.sent_by_user_id, func.count())
        .where(ConversationMessage.conversation_id.in_(conversation_ids), ConversationMessage.direction == "outbound", ConversationMessage.sent_by_user_id.isnot(None), ConversationMessage.created_at >= since)
        .group_by(ConversationMessage.sent_by_user_id),
    ).all()
    resolved_rows = db.execute(
        select(Conversation.assigned_user_id, func.count())
        .where(Conversation.id.in_(conversation_ids), Conversation.status == "resolved", Conversation.assigned_user_id.isnot(None))
        .group_by(Conversation.assigned_user_id),
    ).all()
    resolved_by_user = dict(resolved_rows)
    agent_ids = {row[0] for row in sent_rows} | set(resolved_by_user.keys())
    agents_by_id = {u.id: u for u in db.scalars(select(User).where(User.id.in_(agent_ids))).all()} if agent_ids else {}
    sent_by_user = dict(sent_rows)
    agents = [
        ReportAgentRow(user_id=uid, full_name=agents_by_id[uid].full_name, messages_sent=sent_by_user.get(uid, 0), conversations_resolved=resolved_by_user.get(uid, 0), avg_first_response_minutes=None)
        for uid in agent_ids if uid in agents_by_id
    ]

    # --- Labels ---
    label_rows = db.execute(
        select(Label.id, Label.name, Label.color, func.count(ConversationLabel.conversation_id))
        .join(ConversationLabel, ConversationLabel.label_id == Label.id)
        .where(Label.entity_id == entity.id, ConversationLabel.conversation_id.in_(conversation_ids))
        .group_by(Label.id, Label.name, Label.color),
    ).all()
    labels = [ReportLabelRow(label_id=lid, name=name, color=color, conversation_count=count) for lid, name, color, count in label_rows]

    # --- Overview ---
    total = len(conversation_ids)
    open_count = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.id.in_(conversation_ids), Conversation.status != "resolved")) or 0
    resolved_count = total - open_count
    sla_breached = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.id.in_(conversation_ids), Conversation.sla_breached.is_(True))) or 0
    csat_rows = db.scalars(select(CsatResponse).where(CsatResponse.entity_id == entity.id, CsatResponse.rating.isnot(None))).all()
    avg_csat = round(sum(r.rating for r in csat_rows) / len(csat_rows), 2) if csat_rows else None

    return WabaReportsOut(
        volume=volume, agents=agents, labels=labels, total_conversations=total, open_conversations=open_count,
        resolved_conversations=resolved_count, sla_breached_count=sla_breached, avg_csat=avg_csat, csat_response_count=len(csat_rows),
    )
