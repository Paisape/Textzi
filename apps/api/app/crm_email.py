"""Email as a CRM channel -- bring-your-own SMTP/IMAP, one mailbox per entity. Textzi never
operates this infrastructure or bills per message (unlike SMS/WhatsApp), so it's gated the same
way quotes/sequences are: a CRM-plan capability (_require_crm), not a separately billed channel.

Deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (SMS) or waba_dispatch.py/waba_meta.py/waba_webhooks.py (WhatsApp) -- it writes to the
same shared Contact/Conversation/ConversationMessage tables those already use (channel="email"),
since those tables were designed from the start to be channel-agnostic (Contact's own docstring:
"WhatsApp today (identified by wa_id), email accounts later (identified by email address
instead)"), not by importing WhatsApp's module code."""
import imaplib
import logging
import mimetypes
import smtplib
from datetime import datetime, timezone
from email import encoders, message_from_bytes
from email.header import decode_header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .crm_quotes import _get_pdf_bytes
from .database import SessionLocal, get_db
from .models import Contact, Conversation, ConversationMessage, EmailAccount, Entity, Quote, User
from .permissions import require_channel_scope, require_page_scope_for
from .schemas import EmailAccountOut, EmailAccountTestResult, EmailAccountUpdateRequest, EmailSendRequest
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, channel_active, resolve_user_entity

logger = logging.getLogger("textzi.crm_email")

router = APIRouter(prefix="/v1/crm/email", tags=["crm-email"], dependencies=[Depends(require_channel_scope("crm")), Depends(require_page_scope_for("crm-email"))])


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use the Email channel")


def _account_out(account: EmailAccount | None) -> EmailAccountOut:
    if not account:
        return EmailAccountOut(connected=False)
    return EmailAccountOut(
        connected=True, from_name=account.from_name, from_email=account.from_email,
        smtp_host=account.smtp_host, smtp_port=account.smtp_port, smtp_username=account.smtp_username,
        smtp_use_tls=account.smtp_use_tls, imap_host=account.imap_host, imap_port=account.imap_port,
        imap_username=account.imap_username, imap_use_ssl=account.imap_use_ssl, status=account.status,
        last_error=account.last_error,
        last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
    )


@router.get("/account", response_model=EmailAccountOut)
def get_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    return _account_out(account)


@router.put("/account", response_model=EmailAccountOut)
def save_email_account(payload: EmailAccountUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        account = EmailAccount(
            entity_id=entity.id, from_email=payload.from_email, smtp_host=payload.smtp_host,
            smtp_username=payload.smtp_username, smtp_password_encrypted="", imap_host=payload.imap_host,
            imap_username=payload.imap_username, imap_password_encrypted="",
        )
        db.add(account)
    account.from_name = payload.from_name
    account.from_email = payload.from_email
    account.smtp_host = payload.smtp_host
    account.smtp_port = payload.smtp_port
    account.smtp_username = payload.smtp_username
    account.smtp_password_encrypted = encrypt_secret(payload.smtp_password)
    account.smtp_use_tls = payload.smtp_use_tls
    account.imap_host = payload.imap_host
    account.imap_port = payload.imap_port
    account.imap_username = payload.imap_username
    account.imap_password_encrypted = encrypt_secret(payload.imap_password)
    account.imap_use_ssl = payload.imap_use_ssl
    account.status = "unverified"
    account.last_error = None
    db.commit()
    db.refresh(account)
    return _account_out(account)


@router.delete("/account")
def disconnect_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Removes this entity's connected mailbox so a different one can be connected instead."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        raise HTTPException(status_code=404, detail="No email account connected")
    db.delete(account)
    db.commit()
    return {"disconnected": True}


def _test_smtp(account: EmailAccount) -> str | None:
    try:
        password = decrypt_secret(account.smtp_password_encrypted)
        if account.smtp_use_tls:
            server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=15)
        server.login(account.smtp_username, password)
        server.quit()
        return None
    except Exception as exc:
        return f"SMTP: {exc}"


def _test_imap(account: EmailAccount) -> str | None:
    try:
        password = decrypt_secret(account.imap_password_encrypted)
        conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port, timeout=15) if account.imap_use_ssl \
            else imaplib.IMAP4(account.imap_host, account.imap_port, timeout=15)
        conn.login(account.imap_username, password)
        conn.logout()
        return None
    except Exception as exc:
        return f"IMAP: {exc}"


@router.post("/account/test", response_model=EmailAccountTestResult)
def test_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        raise HTTPException(status_code=404, detail="No email account configured yet")
    error = _test_smtp(account) or _test_imap(account)
    account.status = "error" if error else "connected"
    account.last_error = error
    db.commit()
    return EmailAccountTestResult(ok=error is None, error=error)


def _find_or_create_contact(db: Session, entity_id: str, email_address: str, display_name: str | None) -> Contact:
    contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.email == email_address))
    if contact:
        return contact
    contact = Contact(entity_id=entity_id, email=email_address, name=display_name)
    db.add(contact)
    # A manual send racing the scheduled inbound poll (or two overlapping polls) for the same
    # brand-new email address can both pass the SELECT above before either commits --
    # uq_contacts_entity_email is the real guarantee; re-fetch on the loser instead of crashing.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        contact = db.scalar(select(Contact).where(Contact.entity_id == entity_id, Contact.email == email_address))
        if not contact:
            raise
    return contact


def _find_or_create_conversation(db: Session, entity_id: str, contact_id: str) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "email"),
    )
    if conversation:
        return conversation
    conversation = Conversation(entity_id=entity_id, contact_id=contact_id, channel="email")
    db.add(conversation)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        conversation = db.scalar(
            select(Conversation).where(Conversation.entity_id == entity_id, Conversation.contact_id == contact_id, Conversation.channel == "email"),
        )
        if not conversation:
            raise
    return conversation


@router.post("/send")
def send_email(
    contact_id: str | None = Form(default=None),
    to_email: str | None = Form(default=None),
    to_name: str | None = Form(default=None),
    subject: str = Form(...),
    body: str = Form(...),
    cc: str = Form(default=""),
    quote_id: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    """Body is HTML (the compose/reply box is a rich-text editor) -- sent as text/html directly,
    and re-displayed as HTML in our own thread view (inbound mail stays plain text, see
    _extract_body, so only our own outbound messages are ever HTML -- no rendering ambiguity).

    Multipart, not a JSON body, so the composer can attach files fresh at send time without first
    saving them anywhere -- a plain file picker, no dependency on the contact already having a
    CrmContact/Attachment record. quote_id attaches a Quote's generated PDF the same way waba's
    "send via WhatsApp" action does, just as an email attachment instead of a WhatsApp document."""
    try:
        payload = EmailSendRequest(
            contact_id=contact_id, to_email=to_email, to_name=to_name, subject=subject, body=body,
            cc=[c.strip() for c in cc.split(",") if c.strip()], quote_id=quote_id,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account or account.status != "connected":
        raise HTTPException(status_code=422, detail="Connect and verify an email account before sending")
    if payload.contact_id:
        contact = db.get(Contact, payload.contact_id)
        if not contact or contact.entity_id != entity.id or not contact.email:
            raise HTTPException(status_code=404, detail="Contact not found or has no email address")
    elif payload.to_email:
        contact = _find_or_create_contact(db, entity.id, payload.to_email, payload.to_name)
    else:
        raise HTTPException(status_code=422, detail="Provide either contact_id or to_email")

    attachments: list[tuple[str, bytes, str]] = []
    for upload in files:
        if not upload.filename:
            continue
        attachments.append((upload.filename, upload.file.read(), upload.content_type or mimetypes.guess_type(upload.filename)[0] or "application/octet-stream"))
    if payload.quote_id:
        quote = db.get(Quote, payload.quote_id)
        if not quote or quote.entity_id != entity.id:
            raise HTTPException(status_code=404, detail="Quote not found")
        attachments.append((f"{quote.quote_number or quote.id}.pdf", _get_pdf_bytes(db, quote), "application/pdf"))

    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(payload.body, "html"))
    else:
        msg = MIMEText(payload.body, "html")
    msg["Subject"] = payload.subject
    msg["From"] = f"{account.from_name} <{account.from_email}>" if account.from_name else account.from_email
    msg["To"] = contact.email
    if payload.cc:
        msg["Cc"] = ", ".join(payload.cc)
    for filename, content, content_type in attachments:
        maintype, _, subtype = content_type.partition("/")
        if maintype == "image":
            part = MIMEImage(content, _subtype=subtype or "octet-stream")
        else:
            part = MIMEText("", _subtype="octet-stream")
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Type", content_type)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    try:
        password = decrypt_secret(account.smtp_password_encrypted)
        if account.smtp_use_tls:
            server = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=15)
        server.login(account.smtp_username, password)
        server.sendmail(account.from_email, [contact.email, *payload.cc], msg.as_string())
        server.quit()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this email: {exc}") from exc

    conversation = _find_or_create_conversation(db, entity.id, contact.id)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.add(ConversationMessage(
        conversation_id=conversation.id, direction="outbound", message_type="email",
        body=payload.body, payload={"subject": payload.subject, "to": contact.email, "cc": payload.cc, "attachments": [a[0] for a in attachments]},
        sent_by_user_id=user.id,
    ))
    db.commit()
    return {"sent": True, "conversation_id": conversation.id}


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part for part, enc in parts)


def _extract_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
        return ""
    charset = msg.get_content_charset() or "utf-8"
    payload = msg.get_payload(decode=True)
    return payload.decode(charset, errors="replace") if payload else ""


def _poll_one_account(db: Session, account: EmailAccount) -> None:
    password = decrypt_secret(account.imap_password_encrypted)
    conn = imaplib.IMAP4_SSL(account.imap_host, account.imap_port, timeout=30) if account.imap_use_ssl \
        else imaplib.IMAP4(account.imap_host, account.imap_port, timeout=30)
    try:
        conn.login(account.imap_username, password)
        conn.select("INBOX")
        _, data = conn.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = conn.fetch(num, "(RFC822)")
            raw = msg_data[0][1]
            msg = message_from_bytes(raw)
            from_name, from_email = parseaddr(_decode(msg.get("From")))
            if not from_email:
                continue
            contact = _find_or_create_contact(db, account.entity_id, from_email, from_name or None)
            conversation = _find_or_create_conversation(db, account.entity_id, contact.id)
            conversation.last_message_at = datetime.now(timezone.utc)
            db.add(ConversationMessage(
                conversation_id=conversation.id, direction="inbound", message_type="email",
                body=_extract_body(msg), payload={"subject": _decode(msg.get("Subject"))},
            ))
        account.last_synced_at = datetime.now(timezone.utc)
        account.status = "connected"
        account.last_error = None
        db.commit()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def poll_all_email_inboxes() -> None:
    """The scheduled runner (main.py's lifespan, every 10 minutes) -- polls every connected
    EmailAccount's inbox for unseen messages. Owns its own DB session since it runs outside any
    request context, same shape as crm_sequences.run_due_steps."""
    db = SessionLocal()
    try:
        accounts = db.scalars(select(EmailAccount).where(EmailAccount.status == "connected")).all()
        for account in accounts:
            try:
                _poll_one_account(db, account)
            except Exception:
                logger.warning("crm_email: poll failed for account %s", account.id, exc_info=True)
                account.status = "error"
                account.last_error = "Poll failed -- check credentials"
                db.commit()
    finally:
        db.close()
