"""Admin endpoints binding a route name (used in RoutePolicy.routes) to an outbound HTTPS SMS
provider configuration, so dispatch can reach a distinct provider per named route."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin import require_admin, require_admin_recent_2fa
from .database import get_db
from .models import ProviderRoute
from .schemas import TtbsWebhookInfoOut
from .security import decrypt_secret, encrypt_secret
from .services import ttbs_webhook_url as _ttbs_webhook_url

router = APIRouter(prefix="/v1/admin/provider-routes", tags=["provider-routes"])


class HttpsProviderRouteCreate(BaseModel):
    route_name: str = Field(description="Must match a route string used in RoutePolicy.routes, e.g. 'https-primary'.")
    endpoint: str
    method: str = Field(default="POST", pattern="^(GET|POST)$")
    auth_style: str = Field(default="none", pattern="^(none|header|query|bearer)$")
    auth_key_name: str | None = None
    auth_value: str | None = Field(default=None, description="API key/token; stored encrypted, never returned by GET.")
    param_mapping: dict[str, str] = Field(default_factory=dict, description="Maps Textzi's logical fields (to/from/content) to the provider's actual field names.")


class TtbsProviderRouteCreate(BaseModel):
    route_name: str = Field(description="Must match a route string used in RoutePolicy.routes, e.g. 'ttbs-primary'.")
    endpoint: str = Field(default="https://ttbssmsgw.tatatel.co.in/campaignService/campaigns/qs", description="TTBS HTTP Query String submission URL.")
    user: str = Field(description="Textzi's own TTBS account username -- one shared credential used for every send, platform or customer, since the agreement is between Textzi and Tata (not per-customer).")
    pswd: str = Field(description="Textzi's own TTBS account password; stored encrypted, never returned by GET.")

    @field_validator("endpoint")
    @classmethod
    def _require_https(cls, value: str) -> str:
        # user/pswd travel as query-string params on every single send -- an http:// endpoint
        # (typo, or a copy-pasted sandbox URL) would put the platform's shared TTBS credentials
        # on the wire in plaintext on every message. Reject it outright rather than accept a
        # config that leaks credentials.
        if not value.lower().startswith("https://"):
            raise ValueError("TTBS endpoint must use https:// -- credentials travel in the query string on every send")
        return value


def _public_config(config: dict) -> dict:
    return {k: v for k, v in config.items() if not k.endswith("_encrypted")}


@router.get("", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def list_provider_routes(db: Session = Depends(get_db)):
    rows = db.scalars(select(ProviderRoute)).all()
    return [{"route_name": r.route_name, "provider_type": r.provider_type, "config": _public_config(r.config)} for r in rows]


@router.post("", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_provider_route(payload: HttpsProviderRouteCreate, db: Session = Depends(get_db)):
    if db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == payload.route_name)):
        raise HTTPException(status_code=409, detail=f"route_name '{payload.route_name}' is already provisioned")
    config = {
        "endpoint": payload.endpoint,
        "method": payload.method,
        "auth_style": payload.auth_style,
        "auth_key_name": payload.auth_key_name,
        "param_mapping": payload.param_mapping,
    }
    if payload.auth_value:
        config["auth_value_encrypted"] = encrypt_secret(payload.auth_value)
    row = ProviderRoute(route_name=payload.route_name, provider_type="https", config=config)
    db.add(row)
    db.commit()
    return {"route_name": row.route_name, "provider_type": row.provider_type, "config": _public_config(config)}


@router.post("/ttbs", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def create_ttbs_provider_route(payload: TtbsProviderRouteCreate, db: Session = Depends(get_db)):
    """Tata Tele Business Services SMSGW route. One route = one Textzi<->TTBS account (our own
    agreement, shared across every customer's messages) -- PE_ID/Template_ID are NOT configured
    here, since those vary per send (platform's own DLT identity vs. the sending customer's own
    registered DLT identity) and are resolved per-message at dispatch time instead.

    Auto-generates a webhook auth token and returns the full DR callback URL to register with
    Tata -- this is the only time the token is ever returned; like the password, it's encrypted
    at rest and never echoed back by GET."""
    if db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == payload.route_name)):
        raise HTTPException(status_code=409, detail=f"route_name '{payload.route_name}' is already provisioned")
    webhook_secret = secrets.token_urlsafe(24)
    config = {
        "endpoint": payload.endpoint,
        "user": payload.user,
        "pswd_encrypted": encrypt_secret(payload.pswd),
        "webhook_secret_encrypted": encrypt_secret(webhook_secret),
    }
    row = ProviderRoute(route_name=payload.route_name, provider_type="ttbs", config=config)
    db.add(row)
    db.commit()
    return {
        "route_name": row.route_name,
        "provider_type": row.provider_type,
        "config": _public_config(config),
        "webhook_url": _ttbs_webhook_url(db, webhook_secret),
    }


@router.get("/{route_name}/webhook-url", response_model=TtbsWebhookInfoOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def get_ttbs_webhook_url(route_name: str, db: Session = Depends(get_db)):
    """Re-fetch the DR callback URL for an existing TTBS route -- unlike the account password,
    this is safe to re-show on demand (worst case if leaked: someone can spoof fake delivery
    reports for this route, not touch the Tata account itself), and admins legitimately need to
    keep giving it to Tata during onboarding/renewal."""
    row = db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == route_name, ProviderRoute.provider_type == "ttbs"))
    if not row:
        raise HTTPException(status_code=404, detail=f"TTBS route_name '{route_name}' not found")
    secret_encrypted = row.config.get("webhook_secret_encrypted")
    if not secret_encrypted:
        return TtbsWebhookInfoOut(webhook_url=None, configured=False)
    webhook_url = _ttbs_webhook_url(db, decrypt_secret(secret_encrypted))
    return TtbsWebhookInfoOut(webhook_url=webhook_url, configured=webhook_url is not None)


@router.post("/{route_name}/regenerate-webhook-secret", response_model=TtbsWebhookInfoOut, dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def regenerate_ttbs_webhook_secret(route_name: str, db: Session = Depends(get_db)):
    """Generates (or rotates) the DR webhook token for a TTBS route -- for routes created before
    this webhook feature existed (no token yet), or to rotate an existing one without having to
    re-enter the TTBS account password. Re-register the returned URL with Tata afterward -- the
    old URL stops being accepted the moment this runs."""
    row = db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == route_name, ProviderRoute.provider_type == "ttbs"))
    if not row:
        raise HTTPException(status_code=404, detail=f"TTBS route_name '{route_name}' not found")
    webhook_secret = secrets.token_urlsafe(24)
    row.config = {**row.config, "webhook_secret_encrypted": encrypt_secret(webhook_secret)}
    db.commit()
    webhook_url = _ttbs_webhook_url(db, webhook_secret)
    return TtbsWebhookInfoOut(webhook_url=webhook_url, configured=webhook_url is not None)


@router.delete("/{route_name}", dependencies=[Depends(require_admin), Depends(require_admin_recent_2fa)])
def remove_provider_route(route_name: str, db: Session = Depends(get_db)):
    row = db.scalar(select(ProviderRoute).where(ProviderRoute.route_name == route_name))
    if not row:
        raise HTTPException(status_code=404, detail=f"route_name '{route_name}' not found")
    db.delete(row)
    db.commit()
    return {"route_name": route_name, "removed": True}
