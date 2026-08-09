"""Cloudflare Turnstile server-side verification (siteverify) for the unauthenticated,
bot-facing endpoints that embed the widget on the frontend: register/login/forgot-password
(auth.py) and the public contact form (public.py). Browser never talks to siteverify directly --
only this module, called from inside the existing request handler, does."""
import logging

import requests
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .services import client_ip, get_platform_turnstile_settings

logger = logging.getLogger("textzi.turnstile")

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _turnstile_ok(token: str | None, request: Request, db: Session) -> bool:
    _, secret = get_platform_turnstile_settings(db)
    if secret is None:
        if settings.environment == "development":
            return True
        # Same posture as the four secrets config.py enforces at import time -- an unconfigured
        # secret outside development must fail closed, not silently accept every submission.
        logger.error("Turnstile secret is not configured (Platform Settings > Turnstile Setting, or TURNSTILE_SECRET) outside development; rejecting request")
        return False
    if not token:
        return False
    try:
        response = requests.post(
            SITEVERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": client_ip(request)},
            timeout=10,
        )
        # Deliberately not response.raise_for_status() -- Cloudflare answers a malformed/wrong
        # secret or token with HTTP 400, not 200, but still returns the same structured
        # {"success": false, ...} body either way, which the check below already handles
        # correctly. Only an actual network failure or non-JSON body should hit the except below.
        result = response.json()
    except Exception:
        # Network error or a non-JSON body from siteverify -- fail closed rather than let an
        # outage on Cloudflare's end silently disable bot protection on every form.
        logger.exception("turnstile siteverify request failed")
        return False
    return result.get("success") is True


def require_turnstile(token: str | None, request: Request, db: Session) -> None:
    if not _turnstile_ok(token, request, db):
        raise HTTPException(status_code=403, detail="Verification failed. Please try again.")
