"""Customer-facing testimonial submission -- a logged-in user shares a quote about their own
experience, which sits as "pending" until an admin approves it (see admin.py's
list_testimonials/update_testimonial_status). Never shown publicly until approved; see
public.py's list_public_testimonials for the only endpoint that's actually unauthenticated."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .models import Testimonial, User
from .schemas import TestimonialOut, TestimonialSubmitRequest

router = APIRouter(prefix="/v1/testimonials", tags=["testimonials"])


@router.post("", response_model=TestimonialOut)
def submit_testimonial(payload: TestimonialSubmitRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = Testimonial(
        organization_id=user.organization_id,
        submitted_by_user_id=user.id,
        author_name=payload.author_name,
        author_role=payload.author_role,
        quote=payload.quote,
        status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return TestimonialOut(id=row.id, author_name=row.author_name, author_role=row.author_role, quote=row.quote, status=row.status, created_at=row.created_at.isoformat())


@router.get("/mine", response_model=list[TestimonialOut])
def list_my_testimonials(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Testimonial).where(Testimonial.submitted_by_user_id == user.id).order_by(Testimonial.created_at.desc())).all()
    return [TestimonialOut(id=r.id, author_name=r.author_name, author_role=r.author_role, quote=r.quote, status=r.status, created_at=r.created_at.isoformat()) for r in rows]
