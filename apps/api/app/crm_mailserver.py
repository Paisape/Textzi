"""Provisioning Textzi-hosted CRM mailboxes on Textzi's own self-hosted Stalwart Mail Server
(local dev: the "stalwart" docker-compose service; production mail.textzi.in is a separate later
deploy, not built yet -- see the plan doc's Chapter 13/14).

Deliberately its own module, same one-directional-isolation convention as every other channel
module: never imported by dispatch.py/waba_dispatch.py, doesn't import them either. crm_email.py
imports this module (one direction only) to provision a mailbox; everything else in crm_email.py
(send/poll/test) is untouched and already works against any SMTP/IMAP server, Stalwart included.

Talks to Stalwart's JMAP-based admin API (urn:stalwart:jmap capability, method names prefixed
"x:") over HTTP Basic auth using the one platform-wide service-account credential resolved via
services.get_platform_stalwart_settings (DB-backed, admin-UI-editable, falls back to the .env
Settings.stalwart_admin_* fields until an admin configures it -- same convention as
PlatformSmtpSettings/PlatformWabaSettings). No tenant/client ever calls this API directly or holds
these credentials -- Community Edition has no native tenant isolation (confirmed in Chapter 13),
so Textzi's own backend is the only caller and the only thing that knows which mailbox belongs to
which entity.

Exact request/response shapes below were confirmed by hand against a running local instance, not
just docs (docs and even some doc-summary tools disagreed with each other and with the real
behavior on a few details -- e.g. Domain/Account object creation uses "x:Domain/set"/"x:Account/set",
not "Principal/set" as the object-reference page's method-name convention might suggest; a new
User account's password can only be set via a *second* call using the JMAP array-index patch path
"credentials/0", not by including a "credentials" array/object on create or in a plain keyed-map
update -- every other shape returns "invalidPatch")."""
import logging
import secrets

import requests
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import EmailAccount, Entity
from .security import encrypt_secret
from .services import get_platform_stalwart_settings

logger = logging.getLogger("textzi.crm_mailserver")

_JMAP_USING = ["urn:ietf:params:jmap:core", "urn:stalwart:jmap"]


def _jmap_call(db: Session, method_calls: list[list]) -> list:
    admin_url, admin_user, admin_password, _ = get_platform_stalwart_settings(db)
    response = requests.post(
        f"{admin_url}/jmap/",
        auth=(admin_user, admin_password),
        json={"using": _JMAP_USING, "methodCalls": method_calls},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["methodResponses"]


def _ensure_domain(db: Session, domain_name: str) -> str:
    """Finds or creates the Domain object for domain_name, returns its id. Called once per
    provisioning request rather than once at startup, since a fresh Stalwart instance starts with
    no domains at all and this keeps provisioning self-contained/idempotent."""
    responses = _jmap_call(db, [["x:Domain/query", {"filter": {"name": domain_name}}, "0"]])
    ids = responses[0][1].get("ids", [])
    if ids:
        return ids[0]
    responses = _jmap_call(db, [["x:Domain/set", {"create": {"d1": {
        "name": domain_name,
        "certificateManagement": {"@type": "Manual"},
        "dkimManagement": {"@type": "Automatic"},
        "dnsManagement": {"@type": "Manual"},
        "subAddressing": {"@type": "Enabled"},
    }}}, "0"]])
    result = responses[0][1]
    if result.get("notCreated"):
        raise RuntimeError(f"Could not create Stalwart domain {domain_name!r}: {result['notCreated']}")
    return result["created"]["d1"]["id"]


def username_available(db: Session, username: str) -> bool:
    return db.scalar(select(EmailAccount).where(EmailAccount.stalwart_username == username)) is None


def provision_mailbox(db: Session, entity: Entity, username: str) -> EmailAccount:
    """Creates username@<stalwart_mail_domain> on Stalwart and an EmailAccount row pointing at it.
    Two Stalwart calls, not one -- x:Account/set's "create" rejects any shape of a "credentials"
    field (confirmed empirically), so the account is created bare first, then a second
    x:Account/set "update" call sets the password via the "credentials/0" array-index patch path,
    the only shape that was found to actually work."""
    if not username_available(db, username):
        raise HTTPException(status_code=409, detail=f"Mailbox username '{username}' is already taken")

    _, _, _, mail_domain = get_platform_stalwart_settings(db)
    domain_id = _ensure_domain(db, mail_domain)

    create_responses = _jmap_call(db, [["x:Account/set", {"create": {"u1": {
        "@type": "User",
        "name": username,
        "domainId": domain_id,
        "memberGroupIds": {},
        "roles": {"@type": "User"},
        "permissions": {"@type": "Inherit"},
        "quotas": {},
        "aliases": {},
        "encryptionAtRest": {"@type": "Disabled"},
    }}}, "0"]])
    create_result = create_responses[0][1]
    if create_result.get("notCreated"):
        raise RuntimeError(f"Could not create Stalwart mailbox {username!r}: {create_result['notCreated']}")
    account_id = create_result["created"]["u1"]["id"]

    password = secrets.token_urlsafe(18)
    update_responses = _jmap_call(db, [["x:Account/set", {"update": {account_id: {
        "credentials/0": {"@type": "Password", "secret": password},
    }}}, "0"]])
    update_result = update_responses[0][1]
    if update_result.get("notUpdated"):
        raise RuntimeError(f"Could not set password on Stalwart mailbox {username!r}: {update_result['notUpdated']}")

    email_address = f"{username}@{mail_domain}"
    encrypted_password = encrypt_secret(password)
    account = db.scalar(select(EmailAccount).where(EmailAccount.entity_id == entity.id))
    if not account:
        account = EmailAccount(entity_id=entity.id)
        db.add(account)
    account.provider = "stalwart"
    account.stalwart_username = username
    account.from_name = None
    account.from_email = email_address
    # Only port 465 (implicit TLS) is confirmed reachable on a fresh Stalwart instance in local
    # dev -- 587/STARTTLS was refused in the hands-on verification pass. smtp_use_tls=False is
    # what crm_email.py's send_email/_test_smtp read as "use SMTP_SSL", not "no encryption".
    account.smtp_host = "stalwart"
    account.smtp_port = 465
    account.smtp_username = email_address
    account.smtp_password_encrypted = encrypted_password
    account.smtp_use_tls = False
    account.imap_host = "stalwart"
    account.imap_port = 993
    account.imap_username = email_address
    account.imap_password_encrypted = encrypted_password
    account.imap_use_ssl = True
    # No test-connection round-trip needed before marking this connected, unlike BYO -- Textzi
    # just created this mailbox on its own server with its own generated credentials, both ends
    # are already known-good.
    account.status = "connected"
    account.last_error = None
    return account
