"""Post-login onboarding: organisation -> lightweight KYC -> first entity -> automatic wallet.
Full KYC (document upload, approval workflow) is a separate, larger feature and out of scope here
-- this captures the same fields as a self-declared profile, activated immediately."""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import Entity, Organization, Status, User, WabaWallet, Wallet
from .schemas import CompanyProfileOut, CompanyProfileUpdateResponse, OrganizationOnboardRequest, OrganizationOnboardResponse
from .services import GST_STATE_CODES, save_upload

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


@router.post("/organization", response_model=OrganizationOnboardResponse)
def onboard_organization(payload: OrganizationOnboardRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.organization_id:
        raise HTTPException(status_code=409, detail="Account is already onboarded to an organization")
    # A GSTIN's own prefix is authoritative for GST state (services.state_code_from_gstin) --
    # state_code is only required, and only ever used, when there's no GSTIN to derive it from.
    if not payload.gstin and not payload.state_code:
        raise HTTPException(status_code=422, detail="Select a state, or provide a GSTIN")
    if payload.state_code and payload.state_code not in GST_STATE_CODES:
        raise HTTPException(status_code=422, detail="Select a valid state")

    org = Organization(
        name=payload.organization_name, gstin=payload.gstin, pan=payload.pan, industry=payload.industry, address=payload.address,
        state_code=payload.state_code if not payload.gstin else None,
        contact_person_name=payload.contact_person_name, contact_email=payload.contact_email, contact_mobile=payload.contact_mobile,
    )
    db.add(org)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An organization with this name already exists")

    entity = Entity(organization_id=org.id, name=payload.entity_name or payload.organization_name, status=Status.active)
    db.add(entity)
    db.flush()

    db.add(Wallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))
    db.add(WabaWallet(entity_id=entity.id, prepaid_balance=0, credit_limit=0, credit_used=0))

    user.organization_id = org.id
    db.commit()

    return OrganizationOnboardResponse(organization_id=org.id, entity_id=entity.id)


def _require_own_organization(user: User, db: Session) -> Organization:
    if not user.organization_id:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding first")
    org = db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(status_code=422, detail="Complete organisation onboarding first")
    return org


@router.get("/company-profile", response_model=CompanyProfileOut)
def get_company_profile(user: User = Depends(require_user), db: Session = Depends(get_db)):
    org = _require_own_organization(user, db)
    return CompanyProfileOut(
        organization_id=org.id, company_name=org.name, pan=org.pan, gstin=org.gstin, state_code=org.state_code, address=org.address,
        contact_email=org.contact_email, contact_mobile=org.contact_mobile,
        gst_certificate_uploaded=bool(org.gst_certificate_path), profile_completed=bool(org.profile_completed_at),
    )


@router.put("/company-profile", response_model=CompanyProfileUpdateResponse)
def update_company_profile(
    company_name: str = Form(min_length=2, max_length=160),
    pan: str = Form(min_length=10, max_length=10),
    # gstin stays optional, same as OrganizationOnboardRequest -- not every business is
    # GST-registered. A certificate is only required when a gstin is actually being declared.
    gstin: str | None = Form(default=None),
    # Required whenever gstin is blank -- a GSTIN's own prefix is authoritative for GST state
    # (services.state_code_from_gstin) when one is given, so this is ignored in that case.
    state_code: str | None = Form(default=None),
    address: str = Form(min_length=1, max_length=300),
    contact_email: str = Form(...),
    contact_mobile: str = Form(pattern=r"^[1-9][0-9]{9,14}$"),
    gst_certificate: UploadFile | None = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    org = _require_own_organization(user, db)
    if not PAN_PATTERN.match(pan.strip().upper()):
        raise HTTPException(status_code=422, detail="Enter a valid PAN (e.g. ABCDE1234F)")
    gstin = (gstin or "").strip().upper() or None
    if gstin and len(gstin) != 15:
        raise HTTPException(status_code=422, detail="GSTIN must be exactly 15 characters")
    if gstin and not org.gst_certificate_path and not gst_certificate:
        raise HTTPException(status_code=422, detail="Upload your GST certificate, or leave the GSTIN field blank if you're not GST-registered")
    state_code = (state_code or "").strip().upper() or None
    if not gstin and not state_code:
        raise HTTPException(status_code=422, detail="Select a state, or provide a GSTIN")
    if state_code and state_code not in GST_STATE_CODES:
        raise HTTPException(status_code=422, detail="Select a valid state")

    org.name = company_name.strip()
    org.pan = pan.strip().upper()
    org.gstin = gstin
    org.state_code = state_code if not gstin else None
    org.address = address.strip()
    org.contact_email = contact_email.strip()
    org.contact_mobile = contact_mobile.strip()
    if gst_certificate:
        stored_path, _ = save_upload(gst_certificate, f"company-profile/{org.id}")
        org.gst_certificate_path = stored_path
    if not org.profile_completed_at:
        org.profile_completed_at = datetime.now(timezone.utc)
    db.commit()
    return CompanyProfileUpdateResponse(profile_completed=True)
