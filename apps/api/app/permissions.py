"""Real capability enforcement, beyond the binary ADMIN_ROLES check. The capability data itself
(ROLE_CAPABILITIES, capabilities_for, has_capability) lives in services.py, which auth.py also
depends on for its own /v1/auth/permissions endpoint -- kept out of this module to avoid a
require_user <-> permissions import cycle, since this module needs require_user for the FastAPI
dependency below."""
from fastapi import Depends, HTTPException, Request

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


# Maps a /v1/crm/{prefix} URL segment to the frontend route name page_scope actually stores (see
# navigation/vertical/index.ts's CRM_NAV_ITEMS) -- a teammate's page_scope only ever lists CRM page
# names since that's the only channel page_scope has ever been offered for at invite time (team.vue).
# Endpoints with no clear single-page owner (search, notifications, web-form, saved-views) are left
# unmapped and fall through unrestricted -- narrowing those would block legitimate cross-page use
# (e.g. global search) for no real security gain, since they don't expose one resource's full data.
_CRM_PATH_TO_PAGE = {
    "leads": "crm-leads", "deals": "crm-deals", "contacts": "crm-contacts", "customers": "crm-customers",
    "companies": "crm-companies", "tasks": "crm-tasks", "quotes": "crm-quotes", "pipelines": "crm-pipelines",
    "reports": "crm-reports", "settings": "channels-crm", "custom-fields": "channels-crm",
    "scoring-rules": "crm-automation", "territories": "crm-automation", "sales-targets": "crm-automation",
}


def require_page_scope():
    """The finer-grained half of a teammate's access (models.py's User.page_scope docstring) --
    channel_scope (require_channel_scope above) is the hard boundary; this narrows further within
    CRM to just the pages an owner picked at invite time. Applied once on crm.py's router, same
    shape as require_channel_scope, so it covers every CRM endpoint without per-route annotation.
    page_scope=None means every CRM page (today's default, and every account before this existed)."""
    def dependency(request: Request, user: User = Depends(require_user)) -> User:
        if not user.page_scope:
            return user
        segment = request.url.path.removeprefix("/v1/crm/").split("/", 1)[0]
        page = _CRM_PATH_TO_PAGE.get(segment)
        if page and page not in user.page_scope:
            raise HTTPException(status_code=403, detail="Your account does not have access to this CRM page")
        return user
    return dependency


def require_page_scope_for(page: str):
    """Fixed-page variant of require_page_scope, for a module whose whole router already maps to
    one frontend page (crm_email.py -> crm-email, crm_quotes.py -> crm-quotes, crm_sequences.py ->
    crm-automation, crm_documents.py -> channels-crm's Document Templates tab) -- no URL parsing
    needed since every route in that router belongs to the same page."""
    def dependency(user: User = Depends(require_user)) -> User:
        if user.page_scope and page not in user.page_scope:
            raise HTTPException(status_code=403, detail="Your account does not have access to this CRM page")
        return user
    return dependency
