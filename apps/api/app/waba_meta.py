"""Direct Meta Graph API client for WhatsApp Embedded Signup -- Textzi talks to Meta directly as
a Tech Provider (no Chatwoot in this codebase; see the WABA plan's own reasoning for why that
integration was replaced with a native one). Every call here is documented against Meta's own
developer docs (developers.facebook.com/docs/whatsapp/embedded-signup, business-messaging docs),
fetched directly during this work -- not guessed. Two specific things are flagged inline as
NOT YET LIVE-VERIFIED, since that requires a real Meta Tech Provider app (the user's own
prerequisite, same category as Razorpay live keys) which doesn't exist yet in this environment:
whether `redirect_uri` is required on the code-exchange call for the embedded-signup (config_id)
flow specifically (classic OAuth redirect flows require it; the popup-based embedded-signup flow
may not, since there's no actual redirect happening), and whether /register (with a PIN) is
needed at all for a number that already completed embedded signup, or if Meta handles that
automatically as part of the signup flow itself. Both are called defensively (register failure is
logged, not fatal to the connect flow) until that can be confirmed against a real account."""
import logging

import requests

logger = logging.getLogger("textzi.waba")

GRAPH_API_VERSION = "v23.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class MetaApiError(Exception):
    def __init__(self, message: str, response_body: dict | None = None):
        super().__init__(message)
        self.response_body = response_body


def _get(path: str, params: dict) -> dict:
    try:
        response = requests.get(f"{GRAPH_API_BASE}/{path}", params=params, timeout=15)
    except requests.exceptions.RequestException as exc:
        # A connection-level failure (timeout, DNS, reset) raises here, not via an HTTP status --
        # callers (waba.py's "best-effort" register/fetch steps) only ever catch MetaApiError, so
        # leaving this as a raw RequestException would 500 the whole /connect request even though
        # the token exchange and webhook subscription already succeeded and are about to be lost.
        raise MetaApiError(f"Could not reach Meta's Graph API: {exc}") from exc
    return _parse(response)


def _post(path: str, access_token: str, json_body: dict | None = None) -> dict:
    try:
        response = requests.post(f"{GRAPH_API_BASE}/{path}", headers={"Authorization": f"Bearer {access_token}"}, json=json_body or {}, timeout=15)
    except requests.exceptions.RequestException as exc:
        raise MetaApiError(f"Could not reach Meta's Graph API: {exc}") from exc
    return _parse(response)


def _post_multipart(path: str, access_token: str, data: dict, files: dict) -> dict:
    try:
        response = requests.post(f"{GRAPH_API_BASE}/{path}", headers={"Authorization": f"Bearer {access_token}"}, data=data, files=files, timeout=30)
    except requests.exceptions.RequestException as exc:
        raise MetaApiError(f"Could not reach Meta's Graph API: {exc}") from exc
    return _parse(response)


def _parse(response: requests.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        raise MetaApiError(f"Meta API returned a non-JSON response (HTTP {response.status_code})")
    if response.status_code >= 400:
        error = body.get("error", {}) if isinstance(body, dict) else {}
        raise MetaApiError(error.get("message") or f"Meta API error (HTTP {response.status_code})", response_body=body)
    return body


def exchange_code_for_token(app_id: str, app_secret: str, code: str) -> str:
    """The embedded-signup popup hands the frontend a short-lived (30-second TTL, per Meta's own
    docs) authorization code -- this exchanges it server-side for an access token. Never called
    from the browser: app_secret must never leave this backend."""
    body = _get("oauth/access_token", {"client_id": app_id, "client_secret": app_secret, "code": code})
    token = body.get("access_token")
    if not token:
        raise MetaApiError("Meta did not return an access_token for this code", response_body=body)
    return token


def subscribe_app_to_waba(waba_id: str, access_token: str) -> None:
    """Required so Meta actually sends Textzi webhook events (incoming messages, delivery
    status) for this customer's WhatsApp Business Account -- without this, the connection is
    established but Textzi never hears about anything happening on it. Explicitly checks the
    `success` field rather than just the HTTP status -- Meta's own API (like Cloudflare's
    Turnstile siteverify, already handled the same way elsewhere in this codebase) can answer
    HTTP 200 with a body indicating failure, which a status-code-only check would silently miss."""
    body = _post(f"{waba_id}/subscribed_apps", access_token)
    if body.get("success") is not True:
        raise MetaApiError("Meta did not confirm the webhook subscription", response_body=body)


def register_phone_number(phone_number_id: str, access_token: str, pin: str) -> None:
    """Registers the number for Cloud API messaging. See this module's own docstring -- not yet
    confirmed live whether this is required after embedded signup or already handled by it;
    called defensively, failure here doesn't roll back the connection itself (caller decides)."""
    body = _post(f"{phone_number_id}/register", access_token, {"messaging_product": "whatsapp", "pin": pin})
    if body.get("success") is not True:
        raise MetaApiError("Meta did not confirm the phone number registration", response_body=body)


def fetch_phone_number_details(phone_number_id: str, access_token: str) -> dict:
    """Returns Meta's own record for this phone number -- includes display_phone_number and
    verified_name when available, used to show the customer a human-readable confirmation of
    which number actually got connected rather than just an opaque ID."""
    return _get(phone_number_id, {"access_token": access_token, "fields": "display_phone_number,verified_name"})


def send_text_message(phone_number_id: str, access_token: str, to: str, body: str) -> str:
    """Sends a free-form text message via the Cloud API and returns Meta's own message id
    (wamid), which the caller persists on the ConversationMessage row so later delivery-status
    webhooks (which key off that same id) can update it. Free-form text only works inside Meta's
    24-hour customer-service window -- outside it Meta rejects the send (error body, not a
    connection failure), which callers surface via MetaApiError like every other Meta error here."""
    response = _post(
        f"{phone_number_id}/messages",
        access_token,
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": body},
        },
    )
    messages = response.get("messages")
    if not messages or not messages[0].get("id"):
        raise MetaApiError("Meta did not return a message id for this send", response_body=response)
    return messages[0]["id"]


def _extract_wamid(response: dict) -> str:
    messages = response.get("messages")
    if not messages or not messages[0].get("id"):
        raise MetaApiError("Meta did not return a message id for this send", response_body=response)
    return messages[0]["id"]


def send_location_message(phone_number_id: str, access_token: str, to: str, latitude: float, longitude: float, name: str | None = None, address: str | None = None) -> str:
    location: dict = {"latitude": latitude, "longitude": longitude}
    if name:
        location["name"] = name
    if address:
        location["address"] = address
    response = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "location", "location": location})
    return _extract_wamid(response)


def send_contact_message(phone_number_id: str, access_token: str, to: str, contacts: list[dict]) -> str:
    """`contacts` is Meta's own contacts-array shape verbatim (each entry: name{formatted_name,...},
    phones[], emails[], etc, per Meta's Contacts Messages reference) -- passed through as-is
    rather than remodeled, since the frontend composer builds this same shape directly."""
    response = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "contacts", "contacts": contacts})
    return _extract_wamid(response)


def send_interactive_button_message(phone_number_id: str, access_token: str, to: str, body_text: str, buttons: list[dict]) -> str:
    """`buttons` is up to 3 {id, title} dicts -- Meta's own hard cap, enforced by the caller
    (waba_dispatch) before this ever gets called, since Meta's own rejection error for a 4th
    button is not a useful thing to surface to an agent after the fact."""
    interactive = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]},
    }
    response = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive", "interactive": interactive})
    return _extract_wamid(response)


def send_interactive_list_message(phone_number_id: str, access_token: str, to: str, body_text: str, button_label: str, sections: list[dict]) -> str:
    """`sections` is Meta's own [{title, rows: [{id, title, description}]}] shape -- up to 10 rows
    total across all sections, Meta's own hard cap."""
    interactive = {
        "type": "list",
        "body": {"text": body_text},
        "action": {"button": button_label, "sections": sections},
    }
    response = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive", "interactive": interactive})
    return _extract_wamid(response)


def send_reaction_message(phone_number_id: str, access_token: str, to: str, reacted_to_wamid: str, emoji: str) -> str:
    """An empty string emoji removes a previously-sent reaction -- Meta's own convention, not a
    separate "remove reaction" call."""
    response = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "reaction", "reaction": {"message_id": reacted_to_wamid, "emoji": emoji}})
    return _extract_wamid(response)


def fetch_business_profile(phone_number_id: str, access_token: str) -> dict:
    fields = "about,address,description,email,profile_picture_url,websites,vertical"
    body = _get(f"{phone_number_id}/whatsapp_business_profile", {"access_token": access_token, "fields": fields})
    data = body.get("data") or []
    return data[0] if data else {}


def update_business_profile(phone_number_id: str, access_token: str, profile: dict) -> None:
    """`profile` holds only the fields being changed -- Meta only requires messaging_product plus
    whichever of about/address/description/email/vertical/websites the caller is actually
    updating; omitted fields are left untouched on Meta's side, not cleared."""
    body = _post(f"{phone_number_id}/whatsapp_business_profile", access_token, {"messaging_product": "whatsapp", **profile})
    if body.get("success") is not True:
        raise MetaApiError("Meta did not confirm the business profile update", response_body=body)


def fetch_phone_number_status(phone_number_id: str, access_token: str) -> dict:
    """quality_rating (GREEN/YELLOW/RED/UNKNOWN/NA) and throughput (current messaging tier) --
    separate from fetch_phone_number_details since that one is called on every /connect and
    doesn't need these; this is only called on an explicit "refresh status" action."""
    return _get(phone_number_id, {"access_token": access_token, "fields": "quality_rating,throughput"})


def create_message_template(
    waba_id: str, access_token: str, name: str, category: str, language: str, body_text: str,
    example_params: list[str] | None = None, header_text: str | None = None, footer_text: str | None = None,
    buttons: list[dict] | None = None,
) -> dict:
    """Submits a new template for Meta's review -- it comes back PENDING, not immediately usable;
    the existing list_message_templates() call is how a caller later sees it move to APPROVED (or
    REJECTED). Supports a TEXT header, footer, and buttons (quick-reply/URL/phone-number) per
    Meta's real component model -- media headers (IMAGE/VIDEO/DOCUMENT) need a separate
    resumable-upload flow for the example media handle, not added here."""
    components: list[dict] = []
    if header_text:
        components.append({"type": "HEADER", "format": "TEXT", "text": header_text})
    body_component: dict = {"type": "BODY", "text": body_text}
    if example_params:
        body_component["example"] = {"body_text": [example_params]}
    components.append(body_component)
    if footer_text:
        components.append({"type": "FOOTER", "text": footer_text})
    if buttons:
        components.append({"type": "BUTTONS", "buttons": buttons})
    response = _post(f"{waba_id}/message_templates", access_token, {"name": name, "category": category, "language": language, "components": components})
    if not response.get("id"):
        raise MetaApiError("Meta did not confirm the template submission", response_body=response)
    return response


def delete_message_template(waba_id: str, access_token: str, name: str) -> None:
    response = requests.delete(f"{GRAPH_API_BASE}/{waba_id}/message_templates", headers={"Authorization": f"Bearer {access_token}"}, params={"name": name}, timeout=15)
    body = _parse(response)
    if body.get("success") is not True:
        raise MetaApiError("Meta did not confirm the template deletion", response_body=body)


def upload_media(phone_number_id: str, access_token: str, content: bytes, filename: str, mime_type: str) -> str:
    """Meta requires media to be uploaded to its own servers first (returns an opaque media id)
    before it can be referenced in a send -- unlike a text body, you can't just inline the bytes
    in the /messages call itself."""
    response = _post_multipart(
        f"{phone_number_id}/media", access_token,
        data={"messaging_product": "whatsapp"},
        files={"file": (filename, content, mime_type)},
    )
    media_id = response.get("id")
    if not media_id:
        raise MetaApiError("Meta did not return a media id for this upload", response_body=response)
    return media_id


def send_media_message(phone_number_id: str, access_token: str, to: str, media_type: str, media_id: str, caption: str | None = None) -> str:
    """media_type is one of image/video/audio/document/sticker, matching both Meta's own message
    `type` field and this codebase's ConversationMessage.message_type. Audio and sticker messages
    don't support a caption (Meta's API), so it's only attached for image/video/document."""
    payload: dict = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": media_type, media_type: {"id": media_id}}
    if caption and media_type not in ("audio", "sticker"):
        payload[media_type]["caption"] = caption
    response = _post(f"{phone_number_id}/messages", access_token, payload)
    messages = response.get("messages")
    if not messages or not messages[0].get("id"):
        raise MetaApiError("Meta did not return a message id for this send", response_body=response)
    return messages[0]["id"]


def fetch_media_url(media_id: str, access_token: str) -> tuple[str, str]:
    """Returns (download_url, mime_type). The URL is short-lived (per Meta's docs) and itself
    requires the same Bearer token to actually download from -- callers must fetch and persist
    the bytes immediately, not store this URL for later."""
    body = _get(media_id, {"access_token": access_token, "fields": "url,mime_type"})
    url = body.get("url")
    if not url:
        raise MetaApiError("Meta did not return a download URL for this media", response_body=body)
    return url, body.get("mime_type", "application/octet-stream")


def download_media_bytes(url: str, access_token: str) -> bytes:
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
    except requests.exceptions.RequestException as exc:
        raise MetaApiError(f"Could not download media from Meta: {exc}") from exc
    if response.status_code >= 400:
        raise MetaApiError(f"Meta returned HTTP {response.status_code} downloading media")
    return response.content


def send_read_receipt(phone_number_id: str, access_token: str, message_id: str) -> None:
    """Tells Meta to show the customer the blue double-check mark on this specific inbound
    message -- best-effort by every caller (a failure here must never block an agent from simply
    viewing a conversation), so this raises MetaApiError like everything else and leaves the
    catching to the caller."""
    body = _post(f"{phone_number_id}/messages", access_token, {"messaging_product": "whatsapp", "status": "read", "message_id": message_id})
    if body.get("success") is not True:
        raise MetaApiError("Meta did not confirm the read receipt", response_body=body)


def list_message_templates(waba_id: str, access_token: str) -> list[dict]:
    """Only APPROVED templates are usable for a real send -- Meta returns every template
    regardless of review status, so callers filter on `status` themselves (kept here rather than
    filtered in this function so the admin-facing template list can still show pending/rejected
    ones for visibility)."""
    body = _get(f"{waba_id}/message_templates", {"access_token": access_token, "fields": "name,status,language,category,components", "limit": 100})
    return body.get("data", [])


def send_template_message(phone_number_id: str, access_token: str, to: str, template_name: str, language_code: str, body_params: list[str]) -> str:
    """body_params fills the template's {{1}}, {{2}}, ... placeholders in order -- Meta doesn't
    accept named variables, only positional ones matched to the template's own approved body."""
    components = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]}] if body_params else []
    response = _post(
        f"{phone_number_id}/messages", access_token,
        {
            "messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": {"name": template_name, "language": {"code": language_code}, "components": components},
        },
    )
    messages = response.get("messages")
    if not messages or not messages[0].get("id"):
        raise MetaApiError("Meta did not return a message id for this send", response_body=response)
    return messages[0]["id"]
