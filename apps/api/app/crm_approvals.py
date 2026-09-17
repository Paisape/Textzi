"""Generalized internal approval requests -- a requester picks one or more people per stage
(sequential: stage 2 only opens once stage 1 approves), attachable to a Deal/Quote/SalesInvoice at
creation time or raised standalone with no linked record at all. Purely internal: nothing here is
ever surfaced on a customer-facing page (public quote link, WhatsApp send, invoice PDF) -- keeping
it out of every customer-facing serializer is the whole mechanism, no separate "hide from
customer" flag needed.

Deliberately its own module rather than folded into crm.py/crm_quotes.py -- it reads/writes Deal,
Quote, and SalesInvoice rows for the record_label resolution, so it would create an awkward
circular-import shape living inside any one of those. crm.py/crm_quotes.py stay untouched by this
file; this one just reads their tables directly (all in the same CRM data domain, no cross-channel
isolation concern the way WABA/SMS have)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import ApprovalActivity, ApprovalDocument, ApprovalRequest, ApprovalStage, Contact, Conversation, CrmContact, Deal, Entity, Quote, SalesInvoice, User
from .permissions import require_channel_scope
from .schemas import (
    ApprovalActionRequest, ApprovalActivityOut, ApprovalDocumentOut, ApprovalRequestCreateRequest, ApprovalRequestOut, ApprovalStageOut,
)
from .services import DomainError, channel_active, notify_user as _notify_user_row, resolve_user_entity, save_upload
from .waba_realtime import publish_notification

router = APIRouter(prefix="/v1/crm/approvals", tags=["crm-approvals"], dependencies=[Depends(require_channel_scope("crm"))])


def notify_user(db: Session, entity_id: str, user_id: str, notif_type: str, title: str, body: str, link: str | None = None):
    notification = _notify_user_row(db, entity_id, user_id, notif_type, title, body, link)
    publish_notification(entity_id, user_id, notification.id, notif_type, title, body, link)
    return notification


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use internal approvals")


def _log_activity(db: Session, approval_request_id: str, user_id: str | None, kind: str, detail: str) -> None:
    db.add(ApprovalActivity(approval_request_id=approval_request_id, user_id=user_id, kind=kind, detail=detail))


def _record_label(db: Session, record_type: str | None, record_id: str | None) -> str | None:
    if not record_type or not record_id:
        return None
    if record_type == "deal":
        deal = db.get(Deal, record_id)
        if not deal:
            return None
        contact = db.get(CrmContact, deal.contact_id)
        return f"Deal · {deal.name or (contact.name if contact else 'Unknown')}"
    if record_type == "quote":
        quote = db.get(Quote, record_id)
        return f"Quote · {quote.quote_number or '(draft)'}" if quote else None
    if record_type == "sales_invoice":
        invoice = db.get(SalesInvoice, record_id)
        return f"Invoice · {invoice.invoice_number or '(draft)'}" if invoice else None
    if record_type == "ticket":
        conversation = db.get(Conversation, record_id)
        if not conversation:
            return None
        contact = db.get(Contact, conversation.contact_id)
        return f"Ticket {conversation.ticket_number or '(unnumbered)'} · {contact.name if contact else 'Unknown'}"
    return None


def _stage_out(db: Session, stage: ApprovalStage, users: dict[str, User]) -> ApprovalStageOut:
    return ApprovalStageOut(
        id=stage.id, position=stage.position, approver_user_ids=stage.approver_user_ids or [],
        approver_names=[users[uid].full_name for uid in (stage.approver_user_ids or []) if uid in users],
        status=stage.status, approved_by_user_id=stage.approved_by_user_id,
        approved_by_name=users[stage.approved_by_user_id].full_name if stage.approved_by_user_id in users else None,
        approved_at=stage.approved_at.isoformat() if stage.approved_at else None, comment=stage.comment,
    )


def _request_out(db: Session, request: ApprovalRequest) -> ApprovalRequestOut:
    stages = db.scalars(select(ApprovalStage).where(ApprovalStage.approval_request_id == request.id).order_by(ApprovalStage.position)).all()
    documents = db.scalars(select(ApprovalDocument).where(ApprovalDocument.approval_request_id == request.id).order_by(ApprovalDocument.created_at)).all()
    activity_rows = db.scalars(select(ApprovalActivity).where(ApprovalActivity.approval_request_id == request.id).order_by(ApprovalActivity.created_at)).all()

    user_ids: set[str] = {request.requested_by_user_id}
    for stage in stages:
        user_ids.update(stage.approver_user_ids or [])
        if stage.approved_by_user_id:
            user_ids.add(stage.approved_by_user_id)
    for doc in documents:
        if doc.uploaded_by_user_id:
            user_ids.add(doc.uploaded_by_user_id)
    for a in activity_rows:
        if a.user_id:
            user_ids.add(a.user_id)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()}
    requester = users.get(request.requested_by_user_id)

    document_outs = [
        ApprovalDocumentOut(
            id=d.id, version_group_id=d.version_group_id, version_number=d.version_number, filename=d.filename,
            content_type=d.content_type, size=d.size, uploaded_by_user_id=d.uploaded_by_user_id,
            uploaded_by_name=users[d.uploaded_by_user_id].full_name if d.uploaded_by_user_id in users else None,
            created_at=d.created_at.isoformat(),
        )
        for d in documents
    ]
    activity_outs = [
        ApprovalActivityOut(
            id=a.id, user_id=a.user_id, user_name=users[a.user_id].full_name if a.user_id in users else None,
            kind=a.kind, detail=a.detail, created_at=a.created_at.isoformat(),
        )
        for a in activity_rows
    ]

    return ApprovalRequestOut(
        id=request.id, record_type=request.record_type, record_id=request.record_id,
        record_label=_record_label(db, request.record_type, request.record_id),
        title=request.title, description=request.description,
        requested_by_user_id=request.requested_by_user_id, requested_by_name=requester.full_name if requester else None,
        status=request.status, stages=[_stage_out(db, s, users) for s in stages],
        documents=document_outs, activity=activity_outs,
        created_at=request.created_at.isoformat(), resolved_at=request.resolved_at.isoformat() if request.resolved_at else None,
    )


@router.get("", response_model=list[ApprovalRequestOut])
def list_approval_requests(
    record_type: str | None = None, record_id: str | None = None, status: str | None = None,
    pending_my_action: bool = False, user: User = Depends(require_user), db: Session = Depends(get_db),
):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(ApprovalRequest).where(ApprovalRequest.entity_id == entity.id)
    if record_type:
        query = query.where(ApprovalRequest.record_type == record_type)
    if record_id:
        query = query.where(ApprovalRequest.record_id == record_id)
    if status:
        query = query.where(ApprovalRequest.status == status)
    requests = db.scalars(query.order_by(ApprovalRequest.created_at.desc())).all()
    out = [_request_out(db, r) for r in requests]
    if pending_my_action:
        # The stage currently actionable is whichever one is "pending" (its turn has come) --
        # "waiting" stages further down the chain aren't this user's concern yet. Also requires
        # the request's own status still be "pending" -- a cancelled request can leave its current
        # stage sitting at "pending" forever (cancel never touches stage rows), so the stage check
        # alone isn't enough; confirmed live as a real bug before this check was added.
        out = [
            r for r in out
            if r.status == "pending" and any(s.status == "pending" and user.id in s.approver_user_ids for s in r.stages)
        ]
    return out


@router.get("/{request_id}", response_model=ApprovalRequestOut)
def get_approval_request(request_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = db.get(ApprovalRequest, request_id)
    if not request or request.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return _request_out(db, request)


@router.post("", response_model=ApprovalRequestOut)
def create_approval_request(payload: ApprovalRequestCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    # "policy" is a pure category tag for a standalone request (an internal policy/board approval
    # with nothing to link to) -- it never has a real backing row, unlike deal/quote/sales_invoice/
    # ticket, which always do. Only those four require a record_id.
    if payload.record_type in ("deal", "quote", "sales_invoice", "ticket") and not payload.record_id:
        raise HTTPException(status_code=422, detail="record_id is required when record_type is set")
    if payload.record_id and not _record_label(db, payload.record_type, payload.record_id):
        raise HTTPException(status_code=404, detail="Linked record not found")

    all_approver_ids = {uid for stage in payload.stages for uid in stage.approver_user_ids}
    approvers = {u.id: u for u in db.scalars(select(User).where(User.id.in_(all_approver_ids))).all()}
    for uid in all_approver_ids:
        if uid not in approvers or approvers[uid].organization_id != user.organization_id:
            raise HTTPException(status_code=422, detail="Every approver must belong to your organization")

    request = ApprovalRequest(
        entity_id=entity.id, record_type=payload.record_type, record_id=payload.record_id,
        title=payload.title.strip(), description=payload.description, requested_by_user_id=user.id,
    )
    db.add(request)
    db.flush()
    for i, stage_payload in enumerate(payload.stages):
        db.add(ApprovalStage(
            approval_request_id=request.id, position=i, approver_user_ids=stage_payload.approver_user_ids,
            status="pending" if i == 0 else "waiting",
        ))
    _log_activity(db, request.id, user.id, "created", f"{user.full_name} raised this request ({len(payload.stages)} stage{'s' if len(payload.stages) != 1 else ''})")
    db.commit()
    db.refresh(request)

    first_stage_approvers = payload.stages[0].approver_user_ids
    for uid in first_stage_approvers:
        if uid != user.id:
            notify_user(db, entity.id, uid, "approval_requested", "Approval requested", f"{user.full_name} requested your approval: {request.title}", "/crm-approvals")
    return _request_out(db, request)


@router.post("/{request_id}/cancel", response_model=ApprovalRequestOut)
def cancel_approval_request(request_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = db.get(ApprovalRequest, request_id)
    if not request or request.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.requested_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the requester can cancel this")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Only a pending request can be cancelled")
    request.status = "cancelled"
    request.resolved_at = datetime.now(timezone.utc)
    _log_activity(db, request.id, user.id, "cancelled", f"{user.full_name} cancelled this request")
    db.commit()
    db.refresh(request)
    return _request_out(db, request)


def _act_on_stage(db: Session, request: ApprovalRequest, user: User, entity_id: str, approve: bool, comment: str | None) -> None:
    # Row-locked: two approvers on the same stage acting at the same instant must not both think
    # they're the one resolving it -- same reasoning as crm_quotes.approve_quote's own locking.
    stage = db.scalar(
        select(ApprovalStage).where(ApprovalStage.approval_request_id == request.id, ApprovalStage.status == "pending").with_for_update(),
    )
    if not stage:
        raise HTTPException(status_code=409, detail="This request has no stage currently awaiting action")
    if user.id not in (stage.approver_user_ids or []):
        raise HTTPException(status_code=403, detail="You're not an approver on this stage")
    stage.status = "approved" if approve else "rejected"
    stage.approved_by_user_id = user.id
    stage.approved_at = datetime.now(timezone.utc)
    stage.comment = comment

    action_word = "approved" if approve else "rejected"
    detail = f"{user.full_name} {action_word} stage {stage.position + 1}"
    if comment:
        detail += f' -- "{comment}"'
    _log_activity(db, request.id, user.id, f"stage_{action_word}", detail)

    if not approve:
        request.status = "rejected"
        request.resolved_at = datetime.now(timezone.utc)
        if request.requested_by_user_id != user.id:
            notify_user(db, entity_id, request.requested_by_user_id, "approval_rejected", "Approval rejected", f"{user.full_name} rejected: {request.title}", "/crm-approvals")
        return

    next_stage = db.scalar(
        select(ApprovalStage).where(ApprovalStage.approval_request_id == request.id, ApprovalStage.position == stage.position + 1),
    )
    if next_stage:
        next_stage.status = "pending"
        db.flush()
        for uid in next_stage.approver_user_ids or []:
            if uid != user.id:
                notify_user(db, entity_id, uid, "approval_requested", "Approval requested", f"{request.title} needs your sign-off", "/crm-approvals")
    else:
        request.status = "approved"
        request.resolved_at = datetime.now(timezone.utc)
        if request.requested_by_user_id != user.id:
            notify_user(db, entity_id, request.requested_by_user_id, "approval_approved", "Approval granted", f"{request.title} was fully approved", "/crm-approvals")


@router.post("/{request_id}/approve", response_model=ApprovalRequestOut)
def approve_stage(request_id: str, payload: ApprovalActionRequest = ApprovalActionRequest(), user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = db.get(ApprovalRequest, request_id)
    if not request or request.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="This request is no longer pending")
    _act_on_stage(db, request, user, entity.id, approve=True, comment=payload.comment)
    db.commit()
    db.refresh(request)
    return _request_out(db, request)


@router.post("/{request_id}/reject", response_model=ApprovalRequestOut)
def reject_stage(request_id: str, payload: ApprovalActionRequest = ApprovalActionRequest(), user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = db.get(ApprovalRequest, request_id)
    if not request or request.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="This request is no longer pending")
    _act_on_stage(db, request, user, entity.id, approve=False, comment=payload.comment)
    db.commit()
    db.refresh(request)
    return _request_out(db, request)


def _get_owned_request(db: Session, entity_id: str, request_id: str) -> ApprovalRequest:
    request = db.get(ApprovalRequest, request_id)
    if not request or request.entity_id != entity_id:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return request


@router.post("/{request_id}/documents", response_model=ApprovalDocumentOut)
def upload_approval_document(
    request_id: str, file: UploadFile = File(...), version_group_id: str | None = None,
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """A fresh document (no version_group_id given) starts its own version-1 group. Passing an
    existing version_group_id (from a prior upload's own response) instead adds the next revision
    of that same document -- e.g. re-uploading a policy draft after a reviewer's requested edits,
    with the full revision history kept, not overwritten."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = _get_owned_request(db, entity.id, request_id)
    stored_path, content = save_upload(file, "crm_approval_documents")

    if version_group_id:
        existing = db.scalars(
            select(ApprovalDocument).where(ApprovalDocument.approval_request_id == request_id, ApprovalDocument.version_group_id == version_group_id),
        ).all()
        if not existing:
            raise HTTPException(status_code=404, detail="No document with this version_group_id on this request")
        version_number = max(d.version_number for d in existing) + 1
    else:
        version_group_id = str(uuid.uuid4())
        version_number = 1

    document = ApprovalDocument(
        approval_request_id=request_id, version_group_id=version_group_id, version_number=version_number,
        filename=file.filename or "document", stored_path=stored_path, content_type=file.content_type or "application/octet-stream",
        size=len(content), uploaded_by_user_id=user.id,
    )
    db.add(document)
    kind = "document_revised" if version_number > 1 else "document_attached"
    detail = f"{user.full_name} " + (f"uploaded revision {version_number} of {document.filename}" if version_number > 1 else f"attached {document.filename}")
    _log_activity(db, request.id, user.id, kind, detail)
    db.commit()
    db.refresh(document)
    users = {user.id: user}
    return ApprovalDocumentOut(
        id=document.id, version_group_id=document.version_group_id, version_number=document.version_number,
        filename=document.filename, content_type=document.content_type, size=document.size,
        uploaded_by_user_id=document.uploaded_by_user_id, uploaded_by_name=users[document.uploaded_by_user_id].full_name,
        created_at=document.created_at.isoformat(),
    )


@router.get("/{request_id}/documents/{document_id}/download")
def download_approval_document(request_id: str, document_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    _get_owned_request(db, entity.id, request_id)
    document = db.get(ApprovalDocument, document_id)
    if not document or document.approval_request_id != request_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(document.stored_path, media_type=document.content_type, filename=document.filename)


@router.delete("/{request_id}/documents/{document_id}")
def delete_approval_document(request_id: str, document_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Removing a document doesn't remove its earlier revisions -- only the one row -- so deleting
    a mistaken re-upload never destroys the version history around it."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    request = _get_owned_request(db, entity.id, request_id)
    document = db.get(ApprovalDocument, document_id)
    if not document or document.approval_request_id != request_id:
        raise HTTPException(status_code=404, detail="Document not found")
    _log_activity(db, request.id, user.id, "document_removed", f"{user.full_name} removed {document.filename} (revision {document.version_number})")
    db.delete(document)
    db.commit()
    return {"deleted": True}
