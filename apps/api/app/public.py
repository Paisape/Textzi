"""Unauthenticated endpoints backing the public marketing site (src/pages/index.vue) --
Contact form submission and the admin-curated public Pricing section. No require_user
anywhere in this file; that's intentional, not an oversight."""
from datetime import datetime, timezone
from html import escape

import jwt
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .email_service import render_email, send_email
from .models import ContactMessage, PageView, RateCard, Testimonial, VisitorSession
from .schemas import ContactRequest, ContactResponse, PublicApiBaseUrlOut, PublicCompanyInfoOut, PublicRateCardOut, PublicTestimonialOut, PublicTurnstileConfigOut, RateCardSlabOut, TrackVisitRequest, TrackVisitResponse
from .security import decode_access_token
from .services import client_ip, get_platform_company_info, get_platform_turnstile_settings, parse_user_agent, rate_card_slabs
from .turnstile import require_turnstile

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


@router.get("/turnstile-config", response_model=PublicTurnstileConfigOut)
def get_public_turnstile_config(db: Session = Depends(get_db)):
    """The sitekey isn't a secret -- it's shipped to every visitor's browser regardless -- so
    TurnstileWidget.vue fetches it here at runtime instead of it being baked into the JS bundle at
    build time, letting an admin change it from Platform Settings > Turnstile Setting without a
    frontend rebuild/redeploy."""
    site_key, _ = get_platform_turnstile_settings(db)
    return PublicTurnstileConfigOut(site_key=site_key)


@router.post("/contact", response_model=ContactResponse)
def submit_contact(payload: ContactRequest, request: Request, db: Session = Depends(get_db)):
    require_turnstile(payload.turnstile_token, request, db)
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


@router.get("/testimonials", response_model=list[PublicTestimonialOut])
def list_public_testimonials(db: Session = Depends(get_db)):
    """Only ever admin-approved testimonials -- a customer's own pending/rejected submission is
    never visible here, only to themselves (GET /v1/testimonials/mine) and to admins."""
    rows = db.scalars(
        select(Testimonial).where(Testimonial.status == "approved").order_by(Testimonial.reviewed_at.desc()).limit(12),
    ).all()
    return [PublicTestimonialOut(author_name=r.author_name, author_role=r.author_role, quote=r.quote) for r in rows]


@router.post("/track", response_model=TrackVisitResponse)
def track_visit(payload: TrackVisitRequest, request: Request, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One row per page view, grouped into a VisitorSession the frontend identifies by an opaque
    id it generates and stores itself (localStorage, first-party to the frontend's own origin) --
    not a cookie, since the API and frontend sit on different subdomains (api.textzi.in vs
    textzi.in) and this app's CORS policy deliberately runs with allow_credentials=False, which a
    cross-origin cookie wouldn't reliably round-trip through anyway. No name/email/mobile/
    cross-site history captured here, matching Privacy Policy Section 1/7. country comes from
    Cloudflare's own CF-IPCountry header (already in front of this deployment), not a GeoIP
    database. If the caller happens to already be logged in (Authorization header present and
    valid), the session is linked to that user_id -- best-effort, a missing/invalid/expired token
    here is never an error, since most visits to this endpoint are genuinely anonymous."""
    session = db.get(VisitorSession, payload.session_id) if payload.session_id else None
    if not session:
        browser, os_name, device_type = parse_user_agent(request.headers.get("User-Agent"))
        session = VisitorSession(
            ip_address=client_ip(request),
            country=request.headers.get("CF-IPCountry"),
            browser=browser,
            os=os_name,
            device_type=device_type,
            first_referrer=(payload.referrer or request.headers.get("Referer") or "")[:500] or None,
        )
        db.add(session)
        db.flush()
    else:
        session.last_seen = datetime.now(timezone.utc)

    if not session.user_id and authorization and authorization.startswith("Bearer "):
        try:
            claims = decode_access_token(authorization.removeprefix("Bearer ").strip())
            session.user_id = claims.get("sub")
        except jwt.PyJWTError:
            pass

    db.add(PageView(
        session_id=session.id,
        path=payload.path[:500],
        referrer=(payload.referrer or "")[:500] or None,
        viewport_width=payload.viewport_width,
        viewport_height=payload.viewport_height,
    ))
    db.commit()
    return TrackVisitResponse(session_id=session.id)
