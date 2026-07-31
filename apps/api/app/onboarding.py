"""Post-login onboarding: organisation -> lightweight KYC -> first entity -> automatic wallet.
Full KYC (document upload, approval workflow) is a separate, larger feature and out of scope here
-- this captures the same fields as a self-declared profile, activated immediately."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import Entity, Organization, Status, User, WabaWallet, Wallet
from .schemas import OrganizationOnboardRequest, OrganizationOnboardResponse

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


@router.post("/organization", response_model=OrganizationOnboardResponse)
def onboard_organization(payload: OrganizationOnboardRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.organization_id:
        raise HTTPException(status_code=409, detail="Account is already onboarded to an organization")

    org = Organization(name=payload.organization_name, gstin=payload.gstin, pan=payload.pan, industry=payload.industry, address=payload.address)
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
