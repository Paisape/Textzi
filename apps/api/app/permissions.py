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
