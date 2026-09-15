"""Microsoft Graph API client for the CRM Email channel's "Connect Microsoft 365" option --
OAuth2 authorization-code flow, token refresh, mail send, and change-notification subscription
management. Plain SMTP/IMAP is not offered for Microsoft 365: Microsoft permanently disabled
Basic Authentication for Exchange Online in October 2022, tenant-wide, with no admin override --
Graph's OAuth2 API is the only way any code can send/receive mail through an M365 mailbox, for
every tenant, not a design choice made here.

Deliberately its own module, mirroring waba_meta.py's isolation (never imported by dispatch.py/
providers.py/webhooks.py or waba_dispatch.py/waba_meta.py/waba_webhooks.py) -- crm_email.py
imports this one-directionally for the one shared concern (writing into the same
Contact/Conversation/ConversationMessage tables the BYO SMTP/IMAP path already uses), the same
pattern as every other CRM-to-channel touchpoint in this codebase.

Every endpoint here is documented against Microsoft's own current Graph API docs
(learn.microsoft.com/graph), not guessed -- OAuth2 v2.0 endpoint, /me/sendMail, /me/messages,
/subscriptions (change notifications). Not yet live-verified against a real Azure App
Registration/real M365 mailbox at the time this module was written -- flagged inline wherever a
detail (e.g. subscription lifetime, exact webhook validation handshake shape) is taken from docs
rather than confirmed live, same honesty convention as waba_meta.py's own header comment."""
import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger("textzi.crm_email_graph")

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

# Delegated scopes requested at authorize time -- kept to exactly what this feature needs
# (read/write/send the signed-in user's own mailbox, plus offline_access for the refresh token)
# regardless of what's registered on the Azure App Registration itself; Microsoft only actually
# grants what the admin consented to, so requesting less here is always safe.
GRAPH_SCOPES = "offline_access Mail.ReadWrite Mail.Send User.Read"

# Graph's own documented maximum subscription lifetime for /me/messages is 4230 minutes (~2.94
# days) -- renewed well before that by the scheduled job in crm_email.py, same margin-of-safety
# convention as this codebase's other expiry-tracked credentials (API keys, TOTP).
MAX_SUBSCRIPTION_MINUTES = 4230


class GraphApiError(Exception):
    def __init__(self, message: str, response_body: dict | None = None):
        super().__init__(message)
        self.response_body = response_body


def _authority(tenant_id: str | None) -> str:
    # "common" (not a specific tenant_id) is the standard choice for a multi-tenant-capable app
    # registration -- it lets any organizational OR personal Microsoft account complete the
    # login, with the actual tenant resolved from the signed-in user, not from this URL. Using
    # the admin's own tenant_id here would incorrectly restrict every customer to that one tenant.
    return f"https://login.microsoftonline.com/{tenant_id or 'common'}"


def build_authorize_url(client_id: str, tenant_id: str | None, redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": GRAPH_SCOPES,
        "state": state,
    }
    return f"{_authority(tenant_id)}/oauth2/v2.0/authorize?{urlencode(params)}"


def _token_request(tenant_id: str | None, data: dict) -> dict:
    try:
        response = requests.post(f"{_authority(tenant_id)}/oauth2/v2.0/token", data=data, timeout=15)
    except requests.exceptions.RequestException as exc:
        raise GraphApiError(f"Could not reach Microsoft's login endpoint: {exc}") from exc
    body = response.json() if response.content else {}
    if response.status_code >= 400 or "error" in body:
        raise GraphApiError(body.get("error_description", f"Microsoft returned HTTP {response.status_code}"), response_body=body)
    return body


def exchange_code_for_tokens(client_id: str, client_secret: str, tenant_id: str | None, redirect_uri: str, code: str) -> dict:
    """Returns the full token response dict -- caller pulls access_token/refresh_token/expires_in
    (seconds) out of it. Microsoft's own refresh tokens for this permission set don't expire on a
    fixed schedule (only on 90 days of total inactivity or explicit revocation), so this is a
    genuinely long-lived credential once obtained, not something needing re-consent per session."""
    return _token_request(tenant_id, {
        "client_id": client_id, "client_secret": client_secret, "grant_type": "authorization_code",
        "code": code, "redirect_uri": redirect_uri, "scope": GRAPH_SCOPES,
    })


def refresh_access_token(client_id: str, client_secret: str, tenant_id: str | None, refresh_token: str) -> dict:
    return _token_request(tenant_id, {
        "client_id": client_id, "client_secret": client_secret, "grant_type": "refresh_token",
        "refresh_token": refresh_token, "scope": GRAPH_SCOPES,
    })


def _request(method: str, path: str, access_token: str, json_body: dict | None = None, params: dict | None = None) -> dict:
    try:
        response = requests.request(
            method, f"{GRAPH_API_BASE}/{path}", headers={"Authorization": f"Bearer {access_token}"},
            json=json_body, params=params, timeout=20,
        )
    except requests.exceptions.RequestException as exc:
        raise GraphApiError(f"Could not reach Microsoft Graph: {exc}") from exc
    if response.status_code == 204 or not response.content:
        return {}
    body = response.json()
    if response.status_code >= 400:
        raise GraphApiError(body.get("error", {}).get("message", f"Graph returned HTTP {response.status_code}"), response_body=body)
    return body


def fetch_me(access_token: str) -> dict:
    """Confirms the token works and returns the signed-in user's own mail/displayName -- used
    right after the OAuth callback to populate EmailAccount.from_email/from_name without asking
    the customer to type their own address."""
    return _request("GET", "me", access_token, params={"$select": "mail,userPrincipalName,displayName"})


def send_mail(access_token: str, subject: str, html_body: str, to_addresses: list[str], cc_addresses: list[str] | None = None, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    """POST /me/sendMail -- sends as the signed-in user, no separate SMTP round-trip. Graph
    returns 202 Accepted with an empty body on success (no message-id back synchronously); the
    sent copy lands in the mailbox's own Sent Items, which this integration doesn't separately
    mirror into ConversationMessage (crm_email.py records the outbound message itself, same as
    the BYO SMTP path already does)."""
    import base64
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to_addresses],
    }
    if cc_addresses:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc_addresses]
    if attachments:
        message["attachments"] = [
            {"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": content_type, "contentBytes": base64.b64encode(content).decode("ascii")}
            for name, content, content_type in attachments
        ]
    _request("POST", "me/sendMail", access_token, json_body={"message": message, "saveToSentItems": True})


def list_recent_inbox_messages(access_token: str, since: datetime) -> list[dict]:
    """Inbox messages received since `since` -- the poll-fallback path's own query (crm_email.py's
    _poll_one_graph_account), used both for a mailbox with no working push subscription and as a
    safety net for one that has one (a missed webhook delivery is real and documented, not
    hypothetical)."""
    since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = _request(
        "GET", "me/mailFolders('Inbox')/messages", access_token,
        params={"$filter": f"receivedDateTime ge {since_str}", "$select": "id,subject,from,body,receivedDateTime,bodyPreview", "$top": "50"},
    )
    return result.get("value", [])


def fetch_message(access_token: str, message_id: str) -> dict:
    """One message by id -- used when a change-notification webhook fires (the notification
    payload only carries the message's resource id, not its content; a follow-up GET is Graph's
    own documented, required shape for this, not something this codebase chose to add)."""
    return _request("GET", f"me/messages/{message_id}", access_token, params={"$select": "subject,from,toRecipients,body,receivedDateTime,bodyPreview"})


def create_subscription(access_token: str, notification_url: str, client_state: str) -> dict:
    """Subscribes to new-mail change notifications on the Inbox folder. Graph's own real, current
    behavior (per docs) is to immediately POST a validation request to notification_url with a
    validationToken query parameter that must be echoed back as plain text within 10 seconds --
    the webhook receiver (waba_webhooks.py's own GET-handshake precedent, adapted for Graph's
    POST-based version) must already be live and reachable before this call succeeds. Returns the
    subscription dict including its id and expirationDateTime."""
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return _request("POST", "subscriptions", access_token, json_body={
        "changeType": "created",
        "notificationUrl": notification_url,
        "resource": "me/mailFolders('Inbox')/messages",
        "expirationDateTime": expires_at,
        "clientState": client_state,
    })


def renew_subscription(access_token: str, subscription_id: str) -> dict:
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=MAX_SUBSCRIPTION_MINUTES)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return _request("PATCH", f"subscriptions/{subscription_id}", access_token, json_body={"expirationDateTime": expires_at})


def delete_subscription(access_token: str, subscription_id: str) -> None:
    _request("DELETE", f"subscriptions/{subscription_id}", access_token)
