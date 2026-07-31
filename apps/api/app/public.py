"""Unauthenticated endpoints backing the public marketing site (src/pages/index.vue) --
Contact form submission and the admin-curated public Pricing section. No require_user
anywhere in this file; that's intentional, not an oversight."""
from html import escape

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .email_service import render_email, send_email
from .models import ContactMessage, RateCard
from .schemas import ContactRequest, ContactResponse, PublicApiBaseUrlOut, PublicCompanyInfoOut, PublicRateCardOut, RateCardSlabOut
from .services import get_platform_company_info, rate_card_slabs

router = APIRouter(prefix="/v1/public", tags=["public"])


@router.get("/api-base-url", response_model=PublicApiBaseUrlOut)
def get_public_api_base_url(db: Session = Depends(get_db)):
    """Not a secret -- it's the very URL a developer needs to call the SMS API at all, shown on
    the in-app API docs page (channels-sms.vue's API Docs tab). Falls back the same way
    get_platform_company_info always does when unset."""
    return PublicApiBaseUrlOut(api_base_url=get_platform_company_info(db).public_api_base_url)


@router.get("/company-info", response_model=PublicCompanyInfoOut)
def get_public_company_info(db: Session = Depends(get_db)):
    """Name/address/phone/support email for the marketing site's footer -- all admin-editable
    from Platform Settings > General Setting, not hardcoded, so the footer never drifts out of
    date with what's actually configured. Never includes GSTIN/state (accounting-only fields with
    no reason to be public)."""
    info = get_platform_company_info(db)
    return PublicCompanyInfoOut(
        company_name=info.company_name, company_address=info.company_address,
        company_phone=info.company_phone, support_email=info.support_email,
    )


@router.post("/contact", response_model=ContactResponse)
def submit_contact(payload: ContactRequest, db: Session = Depends(get_db)):
    row = ContactMessage(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        company=payload.company,
        message=payload.message,
    )
    db.add(row)
    db.flush()

    # Every field here is unauthenticated, attacker-controlled input landing in an HTML email in
    # the support inbox -- escape it, or a crafted "message"/"name" becomes a phishing link,
    # tracking pixel, or spoofed content rendered by whatever staff member's mail client opens it.
    body = (
        f"<p><strong>Name:</strong> {escape(payload.name)}</p>"
        f"<p><strong>Email:</strong> {escape(payload.email)}</p>"
        f"<p><strong>Phone:</strong> {escape(payload.phone) if payload.phone else '—'}</p>"
        f"<p><strong>Company:</strong> {escape(payload.company) if payload.company else '—'}</p>"
        f"<p><strong>Message:</strong></p><p>{escape(payload.message).replace(chr(10), '<br>')}</p>"
    )
    # Strip CR/LF before this lands in an email header -- payload.name is otherwise unrestricted
    # free text, and a raw newline in a header value is the classic email-header-injection
    # primitive (smuggling in extra headers like a Bcc into the raw message).
    safe_name = payload.name.replace("\r", " ").replace("\n", " ")
    result = send_email(
        db,
        to=get_platform_company_info(db).support_email,
        subject=f"New contact form submission from {safe_name}",
        html_body=render_email("New Contact Form Submission", body),
    )
    row.email_sent = result.accepted
    db.commit()

    # Best-effort confirmation to the person who submitted the form -- their own submission
    # already succeeded (the row above is committed) regardless of whether this send works, so
    # its result isn't tracked on the row the way the internal notification's is.
    send_email(
        db,
        to=payload.email,
        subject="We've received your message — Textzi",
        html_body=render_email(
            f"Thanks for reaching out, {escape(payload.name)}",
            f"<p>Dear {escape(payload.name)},</p>"
            f"<p>Thanks for contacting us. Our team will connect with you within 48 hours.</p>"
            f"<p>For your reference, here's a copy of what you sent us:</p>"
            f"<p style=\"margin:16px 0; padding:12px 16px; background:#f4f4f5; border-radius:6px; color:#3a3a3a;\">"
            f"{escape(payload.message).replace(chr(10), '<br>')}</p>",
        ),
    )

    return ContactResponse(message="Thanks for reaching out — our team will get back to you shortly.")


@router.get("/rate-cards", response_model=list[PublicRateCardOut])
def list_public_rate_cards(db: Session = Depends(get_db)):
    """Rate cards an admin has explicitly flagged for the public landing page's Pricing
    section -- which cards appear (and under which channel) is entirely admin-controlled via
    RateCard.show_on_public_pricing; nothing here is illustrative/hardcoded."""
    cards = db.scalars(
        select(RateCard).where(RateCard.show_on_public_pricing == True).order_by(RateCard.channel, RateCard.created_at),  # noqa: E712
    ).all()
    result = []
    for card in cards:
        slabs = rate_card_slabs(db, card.id)
        result.append(PublicRateCardOut(
            name=card.name,
            channel=card.channel,
            public_tagline=card.public_tagline,
            min_recharge_amount=float(card.min_recharge_amount),
            slabs=[RateCardSlabOut(id=s.id, min_amount=float(s.min_amount), max_amount=float(s.max_amount) if s.max_amount is not None else None, price_per_sms=float(s.price_per_sms)) for s in slabs],
        ))
    return result
