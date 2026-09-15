"""Email as a CRM channel -- two connection providers share this one module and one EmailAccount
row shape (see EmailAccount's own docstring, models.py): bring-your-own SMTP/IMAP ("byo"), and
OAuth2-connected Microsoft 365/Outlook via Graph ("microsoft_graph", crm_email_graph.py). Textzi
never operates this infrastructure or bills per message (unlike SMS/WhatsApp), so it's gated the
same way quotes/sequences are: a CRM-plan capability (_require_crm), not a separately billed
channel.

Deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (SMS) or waba_dispatch.py/waba_meta.py/waba_webhooks.py (WhatsApp) -- it writes to the
same shared Contact/Conversation/ConversationMessage tables those already use (channel="email"),
since those tables were designed from the start to be channel-agnostic (Contact's own docstring:
"WhatsApp today (identified by wa_id), email accounts later (identified by email address
instead)"), not by importing WhatsApp's module code. It does import crm_email_graph.py
one-directionally (that module never imports this one back), same pattern as every other
CRM-to-channel touchpoint."""
import imaplib
import logging
import mimetypes
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email import encoders, message_from_bytes
from email.header import decode_header
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import crm_email_graph
from .auth import require_user
from .crm_email_graph import GraphApiError
from .crm_quotes import _get_pdf_bytes
from .database import SessionLocal, get_db
from .models import Contact, Conversation, ConversationMessage, EmailAccount, Entity, Quote, User
from .permissions import require_channel_scope, require_page_scope_for, require_plan_feature
from .schemas import (
    EmailAccountOut, EmailAccountTestResult, EmailAccountUpdateRequest, EmailSendRequest,
    EmailSignatureUpdateRequest, MicrosoftAuthorizeUrlOut, MicrosoftOAuthCallbackRequest,
    UserEmailSignatureOut,
)
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, channel_active, get_platform_microsoft_settings, microsoft_graph_redirect_uri, microsoft_graph_webhook_url, resolve_user_entity, sanitize_email_html

logger = logging.getLogger("textzi.crm_email")

router = APIRouter(prefix="/v1/crm/email", tags=["crm-email"], dependencies=[Depends(require_channel_scope("crm")), Depends(require_page_scope_for("crm-email")), Depends(require_plan_feature("crm", "crm-email"))])
# Graph's OAuth callback and webhook receiver are unauthenticated by necessity (Microsoft's own
# redirect/webhook calls carry no Textzi session) -- a separate router, no _require_crm/auth
# dependencies, matching crm_public.py's own "structurally excluded, not a bypass flag" posture.
public_router = APIRouter(tags=["crm-email"])


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
        connected=True, provider=account.provider, from_name=account.from_name, from_email=account.from_email,
        smtp_host=account.smtp_host, smtp_port=account.smtp_port, smtp_username=account.smtp_username,
        smtp_use_tls=account.smtp_use_tls, imap_host=account.imap_host, imap_port=account.imap_port,
        imap_username=account.imap_username, imap_use_ssl=account.imap_use_ssl, status=account.status,
        last_error=account.last_error,
        last_synced_at=account.last_synced_at.isoformat() if account.last_synced_at else None,
        signature_html=account.signature_html,
    )


@router.get("/account", response_model=EmailAccountOut)
def get_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    return _account_out(account)


@router.put("/account", response_model=EmailAccountOut)
def save_email_account(payload: EmailAccountUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """BYO SMTP/IMAP path -- always (re)creates the account as provider="byo", replacing any
    previous Microsoft Graph connection cleanly (a connect-then-reconnect-differently flow is
    expected to just work, not require an explicit "disconnect first" step)."""
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
    account.provider = "byo"
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
    # Clear any leftover Graph state from a previous connection -- a disconnected Graph
    # subscription left pointing at this row would otherwise keep firing webhook notifications
    # for a mailbox this row no longer represents.
    account.ms_access_token_encrypted = None
    account.ms_refresh_token_encrypted = None
    account.ms_token_expires_at = None
    account.ms_subscription_id = None
    account.ms_subscription_expires_at = None
    account.status = "unverified"
    account.last_error = None
    db.commit()
    db.refresh(account)
    return _account_out(account)


@router.put("/account/signature", response_model=EmailAccountOut)
def save_email_signature(payload: EmailSignatureUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The org-wide DEFAULT signature -- used for any teammate who hasn't set their own personal
    one (see save_my_signature below). Kept as its own endpoint, separate from save_email_account,
    so it isn't wiped by a reconnect and so it's usable regardless of provider (byo or
    microsoft_graph). Any teammate with access to this settings page can set the org default;
    setting your own personal one below always takes priority for your own sends."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        raise HTTPException(status_code=422, detail="Connect an email account first")
    account.signature_html = payload.signature_html.strip() or None
    db.commit()
    db.refresh(account)
    return _account_out(account)


@router.get("/my-signature", response_model=UserEmailSignatureOut)
def get_my_email_signature(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """This user's own personal signature -- one mailbox (EmailAccount) is shared org-wide, but
    each teammate sending from it wants their own name/title, not the same shared block. Stored on
    User, not EmailAccount, since it belongs to the person, not the connected mailbox."""
    return UserEmailSignatureOut(signature_html=user.email_signature_html)


@router.put("/my-signature", response_model=UserEmailSignatureOut)
def save_my_email_signature(payload: EmailSignatureUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    user.email_signature_html = payload.signature_html.strip() or None
    db.commit()
    return UserEmailSignatureOut(signature_html=user.email_signature_html)


@router.delete("/account")
def disconnect_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Removes this entity's connected mailbox so a different one can be connected instead. For a
    Graph-connected account, best-effort deletes the active change-notification subscription
    first (Microsoft's own subscriptions otherwise just expire naturally on their own within
    MAX_SUBSCRIPTION_MINUTES, but tidying up immediately is cheap and avoids Graph holding an
    active subscription against a token this row is about to stop tracking)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        raise HTTPException(status_code=404, detail="No email account connected")
    if account.provider == "microsoft_graph" and account.ms_subscription_id:
        try:
            token = _ensure_graph_access_token(db, account)
            crm_email_graph.delete_subscription(token, account.ms_subscription_id)
        except (DomainError, GraphApiError):
            logger.warning("crm_email: could not delete Graph subscription for account %s on disconnect", account.id, exc_info=True)
    db.delete(account)
    db.commit()
    return {"disconnected": True}


# --- Microsoft Graph OAuth2 connect flow -------------------------------------------------------

def _require_graph_configured(db: Session) -> tuple[str, str, str | None]:
    client_id, tenant_id, client_secret = get_platform_microsoft_settings(db)
    if not client_id or not client_secret:
        raise HTTPException(status_code=422, detail="Microsoft 365 connection is not configured on this platform yet")
    return client_id, client_secret, tenant_id


@router.get("/microsoft/authorize-url", response_model=MicrosoftAuthorizeUrlOut)
def get_microsoft_authorize_url(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The frontend redirects the whole browser tab to this URL (not a popup -- Microsoft's own
    login flow, including MFA prompts, doesn't reliably complete inside a small popup window the
    way Meta's embedded-signup does). state carries the calling user's own id so the callback
    (unauthenticated, since it's Microsoft redirecting back, not an API call carrying our JWT)
    knows which entity to attach the resulting tokens to, and is checked against a fresh
    random value stored server-side (CSRF protection on the callback -- a state value forged by
    anyone other than this exact request would not match)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    client_id, _client_secret, tenant_id = _require_graph_configured(db)
    redirect_uri = microsoft_graph_redirect_uri(db)
    if not redirect_uri:
        raise HTTPException(status_code=422, detail="Configure Company > Public API base URL first")
    state = f"{entity.id}:{secrets.token_urlsafe(24)}"
    # Stashed on the (about-to-be-replaced-or-created) EmailAccount row itself rather than a
    # separate table -- one in-flight connect attempt per entity is the only real case, and the
    # callback below re-validates state against exactly this value before trusting the code.
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        account = EmailAccount(entity_id=entity.id, provider="microsoft_graph", from_email="", status="unverified")
        db.add(account)
    account.last_error = f"__pending_oauth_state__:{state}"
    db.commit()
    return MicrosoftAuthorizeUrlOut(authorize_url=crm_email_graph.build_authorize_url(client_id, tenant_id, redirect_uri, state))


@router.post("/microsoft/callback", response_model=EmailAccountOut)
def microsoft_oauth_callback(payload: MicrosoftOAuthCallbackRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Called by the frontend landing page after Microsoft redirects back with ?code=&state= --
    the frontend itself is what's redirected to (not this API directly), and it POSTs the code
    here authenticated as the logged-in user, which is what actually ties the new mailbox to the
    right entity (state is checked as a defense-in-depth CSRF guard, not the sole binding)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    client_id, client_secret, tenant_id = _require_graph_configured(db)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    expected_state = account.last_error[len("__pending_oauth_state__:"):] if account and account.last_error and account.last_error.startswith("__pending_oauth_state__:") else None
    if not account or expected_state != payload.state:
        raise HTTPException(status_code=422, detail="This connection attempt has expired or is invalid -- try connecting again")
    redirect_uri = microsoft_graph_redirect_uri(db)
    if not redirect_uri:
        raise HTTPException(status_code=422, detail="Configure Company > Public API base URL first")

    try:
        tokens = crm_email_graph.exchange_code_for_tokens(client_id, client_secret, tenant_id, redirect_uri, payload.code)
    except GraphApiError as exc:
        raise HTTPException(status_code=422, detail=f"Microsoft rejected this connection: {exc}") from exc

    account.provider = "microsoft_graph"
    account.ms_access_token_encrypted = encrypt_secret(tokens["access_token"])
    account.ms_refresh_token_encrypted = encrypt_secret(tokens["refresh_token"])
    account.ms_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    account.last_error = None

    try:
        me = crm_email_graph.fetch_me(tokens["access_token"])
        account.from_email = me.get("mail") or me.get("userPrincipalName") or account.from_email
        account.from_name = me.get("displayName") or account.from_name
    except GraphApiError:
        logger.warning("crm_email: could not fetch /me after Graph connect for entity %s", entity.id, exc_info=True)

    webhook_url = microsoft_graph_webhook_url(db)
    if webhook_url:
        try:
            client_state = secrets.token_urlsafe(24)
            subscription = crm_email_graph.create_subscription(tokens["access_token"], webhook_url, client_state)
            account.ms_subscription_id = subscription["id"]
            account.ms_subscription_expires_at = datetime.fromisoformat(subscription["expirationDateTime"].replace("Z", "+00:00"))
            account.status = "connected"
        except GraphApiError as exc:
            # A local/no-public-URL deployment (or a real webhook-side problem) shouldn't block
            # the connection itself -- the account is still usable for sending; the scheduled
            # poll-as-fallback (see poll_all_email_inboxes below) picks up new mail regardless of
            # whether the live-push subscription exists.
            logger.warning("crm_email: could not create Graph subscription for entity %s: %s", entity.id, exc, exc_info=True)
            account.status = "connected"
            account.last_error = f"Connected, but real-time updates are unavailable: {exc}"
    else:
        account.status = "connected"

    db.commit()
    db.refresh(account)
    return _account_out(account)


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


def _ensure_graph_access_token(db: Session, account: EmailAccount) -> str:
    """Returns a live access token, silently refreshing first if the cached one has expired (or
    is within a minute of expiring -- avoids a real request racing an about-to-expire token).
    Raises DomainError (not GraphApiError) on a refresh failure -- callers already catch
    DomainError from every other part of this module's send path, and a caller not expecting a
    connected account to suddenly need re-auth (refresh tokens are revoked if a user changes
    their Microsoft password, disables the app, etc.) should surface that the same way any other
    "this account needs attention" failure does."""
    if account.ms_token_expires_at and account.ms_token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=1):
        return decrypt_secret(account.ms_access_token_encrypted)
    client_id, tenant_id, client_secret = get_platform_microsoft_settings(db)
    if not client_id or not client_secret:
        raise DomainError("Microsoft 365 connection is not configured on this platform")
    try:
        tokens = crm_email_graph.refresh_access_token(client_id, client_secret, tenant_id, decrypt_secret(account.ms_refresh_token_encrypted))
    except GraphApiError as exc:
        account.status = "error"
        account.last_error = f"Microsoft 365 re-authorization needed: {exc}"
        db.commit()
        raise DomainError(f"This Microsoft 365 connection needs to be reconnected: {exc}") from exc
    account.ms_access_token_encrypted = encrypt_secret(tokens["access_token"])
    # Microsoft may or may not rotate the refresh token on a given refresh call -- only overwrite
    # it when a new one is actually returned, otherwise the still-valid existing one is kept.
    if tokens.get("refresh_token"):
        account.ms_refresh_token_encrypted = encrypt_secret(tokens["refresh_token"])
    account.ms_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
    db.commit()
    return tokens["access_token"]


@router.post("/account/test", response_model=EmailAccountTestResult)
def test_email_account(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        raise HTTPException(status_code=404, detail="No email account configured yet")
    if account.provider == "microsoft_graph":
        try:
            _ensure_graph_access_token(db, account)
            error = None
        except DomainError as exc:
            error = str(exc)
    else:
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

    if account.provider == "microsoft_graph":
        try:
            token = _ensure_graph_access_token(db, account)
            crm_email_graph.send_mail(token, payload.subject, payload.body, [contact.email], payload.cc or None, attachments or None)
        except (DomainError, GraphApiError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not send this email: {exc}") from exc
    else:
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
        body=payload.body, payload={"subject": payload.subject, "to": contact.email, "cc": payload.cc, "attachments": [a[0] for a in attachments], "is_html": True},
        sent_by_user_id=user.id,
    ))
    db.commit()
    return {"sent": True, "conversation_id": conversation.id}


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part for part, enc in parts)


def _extract_body(msg) -> tuple[str, bool]:
    """Returns (body, is_html). Prefers a real text/plain part (most mail clients send both);
    falls back to the text/html part -- sanitized, since this is untrusted content from an
    external sender, same threat model as a webchat visitor's own input -- for an HTML-only
    email that has no plain-text alternative at all (increasingly common; plenty of real mail
    sent by services/marketing tools skips the plain-text part entirely, and previously this
    returned an empty body for every one of those)."""
    if msg.is_multipart():
        html_part = None
        for part in msg.walk():
            if part.get("Content-Disposition"):
                continue
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace"), False
            if part.get_content_type() == "text/html" and html_part is None:
                html_part = part
        if html_part is not None:
            charset = html_part.get_content_charset() or "utf-8"
            raw_html = html_part.get_payload(decode=True).decode(charset, errors="replace")
            return sanitize_email_html(raw_html), True
        return "", False
    charset = msg.get_content_charset() or "utf-8"
    payload = msg.get_payload(decode=True)
    text = payload.decode(charset, errors="replace") if payload else ""
    if msg.get_content_type() == "text/html":
        return sanitize_email_html(text), True
    return text, False


def _poll_one_imap_account(db: Session, account: EmailAccount) -> None:
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
            body_text, is_html = _extract_body(msg)
            db.add(ConversationMessage(
                conversation_id=conversation.id, direction="inbound", message_type="email",
                body=body_text, payload={"subject": _decode(msg.get("Subject")), "is_html": is_html},
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


def _record_inbound_graph_message(db: Session, account: EmailAccount, message: dict) -> None:
    """Turns one fetched Graph message dict (crm_email_graph.fetch_message's return shape) into
    the same Contact/Conversation/ConversationMessage rows the IMAP path produces -- shared
    end-state regardless of which provider delivered the message, since inbox.vue's rendering is
    already channel-generic, not provider-aware. Graph's own default bodyType is HTML (confirmed
    live -- a real fetched message's body.content was a full <html><head>... document, not
    plain text), so unlike IMAP's _extract_body this is unconditionally HTML, sanitized the same
    way (untrusted content from an external sender)."""
    from_field = (message.get("from") or {}).get("emailAddress") or {}
    from_email = from_field.get("address")
    if not from_email:
        return
    contact = _find_or_create_contact(db, account.entity_id, from_email, from_field.get("name"))
    conversation = _find_or_create_conversation(db, account.entity_id, contact.id)
    conversation.last_message_at = datetime.now(timezone.utc)
    body_field = message.get("body") or {}
    raw_content = body_field.get("content") or message.get("bodyPreview") or ""
    is_html = (body_field.get("contentType") or "html").lower() == "html"
    body_content = sanitize_email_html(raw_content) if is_html else raw_content
    db.add(ConversationMessage(
        conversation_id=conversation.id, direction="inbound", message_type="email",
        body=body_content, payload={"subject": message.get("subject") or "", "is_html": is_html},
    ))


def _poll_one_graph_account(db: Session, account: EmailAccount) -> None:
    """Fallback path for a Graph-connected mailbox with no live webhook subscription (a local/
    no-public-URL deployment, or a subscription that silently failed to create/renew) -- lists
    Inbox messages received since the last successful sync instead of relying purely on push
    notifications, same 10-minute cadence as the IMAP poll job. A mailbox WITH a working
    subscription still gets this as a safety net (a missed/dropped webhook delivery is a real,
    documented possibility Microsoft itself warns about), just redundantly rather than as the
    only mechanism."""
    token = _ensure_graph_access_token(db, account)
    since = account.last_synced_at or (datetime.now(timezone.utc) - timedelta(minutes=15))
    messages = crm_email_graph.list_recent_inbox_messages(token, since)
    for message in messages:
        _record_inbound_graph_message(db, account, message)
    account.last_synced_at = datetime.now(timezone.utc)
    account.status = "connected"
    account.last_error = None
    db.commit()


def poll_all_email_inboxes() -> None:
    """The scheduled runner (main.py's lifespan, every 10 minutes) -- polls every connected
    EmailAccount's inbox for unseen/recent messages, BYO via IMAP and Microsoft Graph via its own
    REST query, so a Graph mailbox still gets new mail even where the push-webhook subscription
    couldn't be created (no public URL) or silently missed a delivery. Owns its own DB session
    since it runs outside any request context, same shape as crm_sequences.run_due_steps."""
    db = SessionLocal()
    try:
        accounts = db.scalars(select(EmailAccount).where(EmailAccount.status == "connected")).all()
        for account in accounts:
            try:
                if account.provider == "microsoft_graph":
                    _poll_one_graph_account(db, account)
                else:
                    _poll_one_imap_account(db, account)
            except Exception:
                logger.warning("crm_email: poll failed for account %s", account.id, exc_info=True)
                account.status = "error"
                account.last_error = "Poll failed -- check credentials"
                db.commit()
    finally:
        db.close()


def renew_graph_subscriptions() -> None:
    """Scheduled runner (main.py's lifespan, daily is plenty given the ~3-day real lifetime) --
    renews every Graph-connected account's active subscription well before it expires. A renewal
    failure (e.g. the refresh token itself was revoked) is logged and leaves that one account
    relying on the poll-fallback above rather than failing the whole run for every other account."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) + timedelta(hours=12)
        accounts = db.scalars(
            select(EmailAccount).where(EmailAccount.provider == "microsoft_graph", EmailAccount.status == "connected", EmailAccount.ms_subscription_id.is_not(None), EmailAccount.ms_subscription_expires_at < cutoff),
        ).all()
        for account in accounts:
            try:
                token = _ensure_graph_access_token(db, account)
                renewed = crm_email_graph.renew_subscription(token, account.ms_subscription_id)
                account.ms_subscription_expires_at = datetime.fromisoformat(renewed["expirationDateTime"].replace("Z", "+00:00"))
                db.commit()
            except (DomainError, GraphApiError):
                logger.warning("crm_email: could not renew Graph subscription for account %s", account.id, exc_info=True)
    finally:
        db.close()


# --- Microsoft Graph webhook receiver (unauthenticated -- Microsoft calls this directly) -------

@public_router.post("/v1/webhooks/microsoft-graph")
async def microsoft_graph_webhook(request: Request, validationToken: str | None = None):
    """Two real, distinct shapes per Microsoft's own current docs: (1) the validation handshake,
    sent immediately after create_subscription/renew_subscription and again periodically --
    identified by the validationToken query parameter, which must be echoed back as
    text/plain within 10 seconds, no body processing; (2) a real change notification, a JSON body
    listing one or more {subscriptionId, resource, clientState} entries with no message content
    of its own -- each requires the separate fetch_message follow-up call to get anything useful,
    which is Graph's own documented shape, not something this code chose to make harder than
    necessary. Every notification is looked up by subscriptionId against EmailAccount, so a
    request for an unknown/already-disconnected subscription is silently ignored (204), not an
    error -- Graph itself doesn't reliably stop calling a deleted subscription's URL instantly."""
    if validationToken is not None:
        return PlainTextResponse(validationToken, status_code=200)

    body = await request.json()
    db = SessionLocal()
    try:
        for notification in body.get("value", []):
            subscription_id = notification.get("subscriptionId")
            resource = notification.get("resource", "")
            if not subscription_id or "/messages/" not in resource:
                continue
            message_id = resource.rsplit("/messages/", 1)[-1]
            account = db.scalar(select(EmailAccount).where(EmailAccount.ms_subscription_id == subscription_id))
            if not account:
                continue
            try:
                token = _ensure_graph_access_token(db, account)
                message = crm_email_graph.fetch_message(token, message_id)
                _record_inbound_graph_message(db, account, message)
                account.last_synced_at = datetime.now(timezone.utc)
                db.commit()
            except (DomainError, GraphApiError):
                logger.warning("crm_email: could not process Graph webhook notification for account %s", account.id, exc_info=True)
    finally:
        db.close()
    return {"received": True}
