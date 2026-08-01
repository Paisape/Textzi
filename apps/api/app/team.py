"""Sub-user invites: an existing organization member invites a teammate by email; accepting the
invite creates a new User whose organization_id is inherited directly from the invitation,
skipping org onboarding entirely (the router guard in the frontend only forces onboarding when
organization_id is null)."""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import _create_session, require_user
from .config import settings
from .database import get_db
from .email_service import render_email, send_email
from .models import Invitation, User, UserRole, UserStatus
from .permissions import require_capability
from .schemas import AcceptInviteRequest, TeamInviteRequest, TeamInviteResponse, TeamMemberOut, TokenResponse
from .security import create_access_token, hash_api_key, hash_password
from .services import log_activity

router = APIRouter(prefix="/v1/team", tags=["team"])

INVITE_TTL_HOURS = 72

# Only these internal, capability-limited roles can be granted through a self-service invite --
# never an admin-tier role (super_admin/operator_admin), never one of the internal-only roles
# that fall through to every capability by default (see services.capabilities_for's
# ALL_CAPABILITIES fallback), and never enterprise_customer itself: that's the org's own owner
# role, so letting an existing member "invite" another one would mint a second account owner
# inside the same organization rather than a scoped teammate.
INVITABLE_ROLES = {UserRole.sub_user, UserRole.finance_user, UserRole.marketing_user, UserRole.read_only_user}


@router.post("/invite", response_model=TeamInviteResponse)
def invite_teammate(payload: TeamInviteRequest, request: Request, user: User = Depends(require_capability("team:invite")), db: Session = Depends(get_db)):
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding before inviting teammates")
    if payload.role not in INVITABLE_ROLES:
        raise HTTPException(status_code=422, detail="That role cannot be granted through a team invite")
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=user.organization_id, email=payload.email, invited_by_user_id=user.id,
        token_hash=hash_api_key(token), role=payload.role.value,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS),
    )
    db.add(invitation)
    log_activity(db, user.organization_id, "team_invite_sent", f"Invited {payload.email} as {payload.role.value.replace('_', ' ')}.", user_id=user.id, actor_email=user.email, request=request)
    db.commit()

    accept_url = f"{settings.web_origin}/accept-invite?token={token}"
    send_email(
        db,
        to=payload.email,
        subject=f"{user.full_name} invited you to join their Textzi team",
        html_body=render_email(
            "You've been invited to Textzi",
            f"<p>{user.full_name} invited you to join their organization on Textzi as {payload.role.value.replace('_', ' ').title()}.</p>"
            f"<p>Click below to set up your account. This invite expires in {INVITE_TTL_HOURS} hours.</p>",
            cta_label="Accept Invite",
            cta_url=accept_url,
        ),
    )
    return TeamInviteResponse(invitation_id=invitation.id, email=invitation.email, dev_invite_token=token if settings.environment == "development" else None)


@router.get("/members", response_model=list[TeamMemberOut])
def list_team_members(user: User = Depends(require_capability("team:view")), db: Session = Depends(get_db)):
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding first")
    members = db.scalars(select(User).where(User.organization_id == user.organization_id).order_by(User.created_at.asc())).all()
    return [TeamMemberOut(id=m.id, email=m.email, full_name=m.full_name, role=m.role, status=m.status) for m in members]


@router.post("/accept-invite", response_model=TokenResponse)
def accept_invite(payload: AcceptInviteRequest, request: Request, db: Session = Depends(get_db)):
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_api_key(payload.token)))
    if not invitation or invitation.status != "pending":
        raise HTTPException(status_code=422, detail="This invite link is invalid or has already been used")
    if invitation.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="This invite link has expired")
    if db.scalar(select(User).where(User.email == invitation.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = User(
        email=invitation.email, password_hash=hash_password(payload.password), full_name=payload.full_name,
        mobile=payload.mobile, organization_id=invitation.organization_id, role=invitation.role, status=UserStatus.active,
        email_verified=True,
    )
    db.add(user)
    invitation.status = "accepted"
    try:
        db.commit()
    except IntegrityError:
        # A same-email register() slipped in between the check above and this commit -- the
        # invitation itself is still "pending" (its own status update rolled back too), so the
        # invitee can simply retry accept-invite once that conflict is resolved.
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    # Logged only once the User row is actually committed -- user.id is a Python-side default
    # that isn't populated until flush, and this event should never survive a rolled-back invite.
    log_activity(db, invitation.organization_id, "team_member_joined", f"{invitation.email} joined the team as {invitation.role.replace('_', ' ')}.", user_id=user.id, actor_email=invitation.email, request=request)
    sid = _create_session(db, user.id, request)
    db.commit()
    return TokenResponse(access_token=create_access_token(subject=user.id, extra_claims={"sid": sid}), mfa_required=False)
