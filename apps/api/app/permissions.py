"""Real capability enforcement, beyond the binary ADMIN_ROLES check. The capability data itself
(ROLE_CAPABILITIES, capabilities_for, has_capability) lives in services.py, which auth.py also
depends on for its own /v1/auth/permissions endpoint -- kept out of this module to avoid a
require_user <-> permissions import cycle, since this module needs require_user for the FastAPI
dependency below."""
from fastapi import Depends, HTTPException

from .auth import require_user
from .models import User
from .services import has_capability


def require_capability(capability: str):
    def dependency(user: User = Depends(require_user)) -> User:
        if not has_capability(user.role, capability):
            raise HTTPException(status_code=403, detail=f"Your role does not have the '{capability}' permission")
        return user
    return dependency


def require_channel_scope(channel: str):
    """The real security boundary behind a teammate's channel_scope (set at invite time,
    team.py) -- applied once per router via APIRouter(..., dependencies=[Depends(...)]) so every
    route in that channel's module is covered without touching each endpoint individually.
    channel_scope=None means full access (the account owner, or a teammate never restricted), so
    this only ever blocks a teammate whose scope names a *different* channel than this router."""
    return require_channel_scope_any([channel])


def require_channel_scope_any(channels: list[str]):
    """Same idea as require_channel_scope, but for a module genuinely shared by more than one
    channel -- waba_inbox.py owns the Conversation/Task/ticket tables that both the plain
    WhatsApp inbox AND CRM's Tickets/Email/Helpdesk pages call directly, so it can't be gated to
    a single channel without locking CRM-scoped teammates out of Tickets."""
    def dependency(user: User = Depends(require_user)) -> User:
        if user.channel_scope and user.channel_scope not in channels:
            raise HTTPException(status_code=403, detail=f"Your account does not have access to the {'/'.join(channels)} channel")
        return user
    return dependency
