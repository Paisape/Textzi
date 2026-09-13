"""Pulls a connected Shopify store's products and pushes them into the entity's Meta Commerce
Catalog, so they become sendable over WhatsApp Commerce -- WabaCatalogItem is a read-only mirror
of Meta's own catalog (see its own docstring), so this never writes there directly; the existing
hourly catalog_sync.py pull picks up whatever lands in Meta afterward, same as any other Meta-side
catalog change. Deliberately its own module, not folded into catalog_sync.py -- same "one file per
distinct integration surface" convention as crm_quotes.py/crm_public.py/waba_meta.py.

Also imports a real Shopify order into CRM as a Deal the moment it's placed -- a genuinely
different direction from the catalog sync above (Shopify -> CRM, not Shopify -> Meta), via a
webhook Shopify calls, not a poll. This module is architecturally WABA-side (its own router lives
under /v1/waba/shopify, same as the rest of it), so per the standing one-directional isolation
rule it must NOT import crm.py -- Deal/CrmContact are shared, neutral model classes (like WabaOrder
already is for the WhatsApp-cart-order case), and the small find-or-create-contact logic below is
its own local copy of crm._resolve_or_create_contact's dedup shape, not an import of it."""
import hmac
import logging
import secrets
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import CrmContact, Deal, ImportedStoreOrder, ShopifyConnection, User, WabaConnection
from .permissions import require_channel_scope
from .schemas import ShopifyConnectionOut, ShopifyConnectRequest
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, get_platform_company_info, resolve_user_entity
from .waba_meta import MetaApiError, push_catalog_batch

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/shopify", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])
# The order-import webhook itself is unauthenticated (Shopify calls it directly, no user session)
# -- kept on its own router with no require_channel_scope dependency, same structural exclusion
# already used for waba_webhooks.py/crm_public.py, rather than a bypass flag on the router above.
public_router = APIRouter(prefix="/v1/webhooks/shopify", tags=["waba"])

REQUEST_TIMEOUT_SECONDS = 20
# Shopify returns up to 250 products per page; capped here (not paginated) since a periodic full
# resync at this scale is simpler and safer than tracking per-product staleness across pages --
# same "full replace, not diff" reasoning catalog_sync.py's own docstring already applies to the
# Meta-side pull, just one level upstream of it. A store with more than this many active products
# would need real cursor pagination, not attempted here since no customer has hit this yet.
MAX_PRODUCTS_PER_SYNC = 250


class ShopifyApiError(Exception):
    pass


def _shop_domain_only(raw: str) -> str:
    """Accepts either a bare "example.myshopify.com" or a pasted full URL and normalizes to just
    the domain -- the same tolerant-input handling this codebase already applies elsewhere (e.g.
    IFSC/GSTIN fields trimming whitespace/case) rather than rejecting a technically-valid paste."""
    domain = raw.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return domain.split("/")[0]


def _fetch_products(shop_domain: str, access_token: str) -> list[dict]:
    url = f"https://{shop_domain}/admin/api/2024-01/products.json"
    try:
        response = requests.get(
            url, headers={"X-Shopify-Access-Token": access_token}, params={"limit": MAX_PRODUCTS_PER_SYNC, "status": "active"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise ShopifyApiError(f"Could not reach this Shopify store: timed out after {REQUEST_TIMEOUT_SECONDS}s.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise ShopifyApiError(f"Could not reach this Shopify store at '{shop_domain}' -- check the domain is correct.") from exc
    except requests.exceptions.RequestException as exc:
        # Anything else (a malformed URL, an unsupported redirect, etc.) -- str(exc) on these is
        # usually readable on its own, unlike ConnectionError/Timeout's own str() which embeds a
        # raw urllib3 connection-pool repr (object memory address and all) meant for a stack
        # trace, not an end user.
        raise ShopifyApiError(f"Could not reach this Shopify store: {exc}") from exc
    if response.status_code == 401:
        raise ShopifyApiError("Shopify rejected this access token -- it may have been revoked. Reconnect with a fresh one.")
    if not response.ok:
        raise ShopifyApiError(f"Shopify returned HTTP {response.status_code}: {response.text[:300]}")
    return response.json().get("products", [])


def _to_meta_item(product: dict) -> dict | None:
    """Shapes one Shopify product into the {id, title, ...} dict push_catalog_batch expects.
    Uses the FIRST variant's price/sku -- a product with real per-variant pricing (size/color
    options at different prices) only gets its base variant represented, same simplification
    every "sync a store catalog into a single flat product list" integration makes; a genuine
    per-variant catalog would need one Meta product per variant, not attempted here since it's a
    much larger scope than what was asked for. Skips a product with no variants/price entirely
    rather than pushing a malformed item Meta would reject."""
    variants = product.get("variants") or []
    if not variants or not variants[0].get("price"):
        return None
    variant = variants[0]
    images = product.get("images") or []
    item = {
        "id": f"shopify-{product['id']}",
        "title": (product.get("title") or "")[:100],
        "description": (product.get("body_html") or product.get("title") or "")[:5000],
        "price": f"{variant['price']} INR",
        "availability": "in stock" if (variant.get("inventory_quantity") or 0) > 0 else "out of stock",
        "condition": "new",
        "brand": product.get("vendor") or "Unbranded",
        "link": f"https://{product.get('shop_domain', '')}/products/{product.get('handle', '')}",
    }
    if images:
        item["image_link"] = images[0].get("src")
    return item


def sync_shopify_catalog(db: Session, connection: ShopifyConnection, waba_connection: WabaConnection) -> int:
    """Fetches this store's products and pushes them into the entity's Meta catalog. Returns the
    count actually pushed. Raises ShopifyApiError/MetaApiError on failure -- callers (the manual
    "Sync now" endpoint and the scheduled runner below) each decide how to surface that."""
    access_token = decrypt_secret(connection.access_token_encrypted)
    products = _fetch_products(connection.shop_domain, access_token)
    for product in products:
        product["shop_domain"] = connection.shop_domain
    items = [item for item in (_to_meta_item(p) for p in products) if item]
    if not items:
        return 0
    meta_access_token = decrypt_secret(waba_connection.access_token_encrypted)
    push_catalog_batch(waba_connection.catalog_id, meta_access_token, items)
    return len(items)


def sync_all_shopify_connections() -> None:
    """The scheduled runner (main.py's lifespan) -- syncs every connected Shopify store whose
    entity also has a WABA catalog_id set (no catalog to push into otherwise). Owns its own DB
    session, same shape as catalog_sync.sync_all_catalogs/crm_email.poll_all_email_inboxes."""
    db = SessionLocal()
    try:
        connections = db.query(ShopifyConnection).filter(ShopifyConnection.status == "connected").all()
        for connection in connections:
            waba_connection = db.get(WabaConnection, connection.entity_id)
            if not waba_connection or not waba_connection.catalog_id:
                continue
            try:
                count = sync_shopify_catalog(db, connection, waba_connection)
                connection.last_sync_status = "success"
                connection.last_sync_error = None
                connection.products_synced = count
            except (ShopifyApiError, MetaApiError) as exc:
                connection.last_sync_status = "failed"
                connection.last_sync_error = str(exc)[:500]
                logger.warning("shopify catalog sync failed for entity %s: %s", connection.entity_id, exc)
            connection.last_synced_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _connection_out(connection: ShopifyConnection | None) -> ShopifyConnectionOut:
    if not connection:
        return ShopifyConnectionOut(
            connected=False, shop_domain=None, status=None, last_sync_status=None, last_sync_error=None,
            last_synced_at=None, products_synced=0, order_import_active=False, orders_imported=0,
        )
    return ShopifyConnectionOut(
        connected=True, shop_domain=connection.shop_domain, status=connection.status,
        last_sync_status=connection.last_sync_status, last_sync_error=connection.last_sync_error,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        products_synced=connection.products_synced, order_import_active=bool(connection.order_webhook_id),
        orders_imported=connection.orders_imported,
    )


def _register_order_webhook(db: Session, entity_id: str, shop_domain: str, access_token: str) -> tuple[str, str] | None:
    """Registers a Shopify orders/create webhook pointed at this entity's own callback URL.
    Returns (webhook_id, secret) on success, or None if the platform's own public_api_base_url
    isn't configured yet (order import silently stays off in that case, same "degrade gracefully,
    don't crash the connect flow" behavior as ttbs_webhook_url's own None-when-unconfigured case)
    -- catalog sync itself, which doesn't need a public callback URL, still works either way.

    Confirmed via Shopify's own webhook docs: X-Shopify-Hmac-SHA256 is computed with the app's own
    API *client secret* -- a value that only exists for an installed/public app, not for the
    private-app Admin API access token this integration authenticates with (ShopifyConnection's
    own docstring explains why: one merchant's own store, not a public app listing). So real
    per-request HMAC verification the way waba_webhooks.py does for Meta isn't available here.
    The random secret generated below is instead embedded directly in the callback URL path (see
    the receiver) -- a legitimate, commonly used fallback when the platform's real signing key
    isn't one the integrator can possess, not a weaker copy of the HMAC approach."""
    base_url = get_platform_company_info(db).public_api_base_url
    if not base_url:
        return None
    secret = secrets.token_urlsafe(32)
    callback_url = f"{base_url.rstrip('/')}/v1/webhooks/shopify/{entity_id}/{secret}/orders"
    try:
        response = requests.post(
            f"https://{shop_domain}/admin/api/2024-01/webhooks.json",
            headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"},
            json={"webhook": {"topic": "orders/create", "address": callback_url, "format": "json"}},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise ShopifyApiError(f"Connected, but could not register the order-import webhook: {exc}") from exc
    if not response.ok:
        raise ShopifyApiError(f"Connected, but Shopify rejected the order-import webhook registration: HTTP {response.status_code}: {response.text[:300]}")
    webhook_id = str(response.json()["webhook"]["id"])
    return webhook_id, secret


def _deregister_order_webhook(shop_domain: str, access_token: str, webhook_id: str) -> None:
    try:
        requests.delete(
            f"https://{shop_domain}/admin/api/2024-01/webhooks/{webhook_id}.json",
            headers={"X-Shopify-Access-Token": access_token}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("could not deregister Shopify order webhook %s: %s", webhook_id, exc)


@router.get("/connection", response_model=ShopifyConnectionOut)
def get_shopify_connection(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    return _connection_out(db.get(ShopifyConnection, entity.id))


@router.post("/connect", response_model=ShopifyConnectionOut)
def connect_shopify(payload: ShopifyConnectRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    shop_domain = _shop_domain_only(payload.shop_domain)
    # Verify the credentials actually work before saving them -- same "test before storing"
    # discipline as crm_email.py's SMTP/IMAP connect flow, so a typo'd token doesn't sit silently
    # broken until the next scheduled sync fails hours later with no immediate feedback.
    try:
        _fetch_products(shop_domain, payload.access_token)
    except ShopifyApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(ShopifyConnection, entity.id)
    if not connection:
        connection = ShopifyConnection(entity_id=entity.id)
        db.add(connection)
    connection.shop_domain = shop_domain
    connection.access_token_encrypted = encrypt_secret(payload.access_token)
    connection.status = "connected"
    db.commit(); db.refresh(connection)

    # Best-effort: a merchant who hasn't set Public API base URL yet (or whose webhook
    # registration call itself fails) still gets a working catalog-sync connection -- order import
    # just doesn't turn on until that's fixed and this endpoint (or a future "retry webhook"
    # action) runs again, rather than failing the whole connect flow over a secondary feature.
    try:
        registered = _register_order_webhook(db, entity.id, shop_domain, payload.access_token)
        if registered:
            connection.order_webhook_id, secret = registered
            connection.webhook_secret_encrypted = encrypt_secret(secret)
            db.commit(); db.refresh(connection)
    except ShopifyApiError as exc:
        logger.warning("Shopify order-webhook registration failed for entity %s: %s", entity.id, exc)
    return _connection_out(connection)


@router.post("/sync-now", response_model=ShopifyConnectionOut)
def sync_shopify_now(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    connection = db.get(ShopifyConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a Shopify store first.")
    waba_connection = db.get(WabaConnection, entity.id)
    if not waba_connection or not waba_connection.catalog_id:
        raise HTTPException(status_code=422, detail="Connect WhatsApp and set a Meta Commerce Catalog id first (Channels > WhatsApp > Connect).")
    try:
        count = sync_shopify_catalog(db, connection, waba_connection)
        connection.last_sync_status = "success"
        connection.last_sync_error = None
        connection.products_synced = count
    except (ShopifyApiError, MetaApiError) as exc:
        connection.last_sync_status = "failed"
        connection.last_sync_error = str(exc)[:500]
    connection.last_synced_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(connection)
    return _connection_out(connection)


@router.delete("/connection")
def disconnect_shopify(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    connection = db.get(ShopifyConnection, entity.id)
    if not connection:
        raise HTTPException(status_code=404, detail="No Shopify connection to remove.")
    if connection.order_webhook_id:
        _deregister_order_webhook(connection.shop_domain, decrypt_secret(connection.access_token_encrypted), connection.order_webhook_id)
    db.delete(connection)
    db.commit()
    return {"disconnected": True}


# --- Order import (Shopify orders/create webhook -> a Deal) -------------------------------------

def _find_or_create_order_contact(db: Session, entity_id: str, name: str | None, phone: str | None, email: str | None) -> CrmContact:
    """Local copy of crm._resolve_or_create_contact's find-or-create-by-phone/email shape -- not
    an import of it, since this module is WABA-side and must not import crm.py (the standing
    one-directional isolation rule; see this file's own top-of-module docstring)."""
    existing = None
    if phone:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.phone == phone))
    if not existing and email:
        existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.email == email))
    if existing:
        return existing
    contact = CrmContact(entity_id=entity_id, name=(name or phone or email or "Unknown").strip(), phone=phone, email=email, source="manual")
    db.add(contact)
    try:
        db.flush()
    except IntegrityError:
        # Same concurrent-first-order race crm._resolve_or_create_contact already guards against
        # (uq_crm_contacts_entity_phone/email) -- re-fetch the row the other request just created.
        db.rollback()
        if phone:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.phone == phone))
        if not existing and email:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.email == email))
        if existing:
            return existing
        raise
    return contact


@public_router.post("/{entity_id}/{secret}/orders")
async def receive_shopify_order_webhook(entity_id: str, secret: str, request: Request, db: Session = Depends(get_db)):
    """Shopify's own orders/create delivery -- see _register_order_webhook's docstring for why
    this is verified via a URL-embedded shared secret rather than X-Shopify-Hmac-SHA256 (that
    header is signed with an app client secret this private-app integration never has). Shopify
    retries on anything but a 2xx (documented up to 19 times over 48h), so this must be safe to
    call twice for the same order -- ImportedStoreOrder is the real dedup guard, not any property
    of the created Deal itself."""
    connection = db.get(ShopifyConnection, entity_id)
    if not connection or not connection.webhook_secret_encrypted or not hmac.compare_digest(secret, decrypt_secret(connection.webhook_secret_encrypted)):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    try:
        payload = await request.json()
    except ValueError:
        return {"status": "ignored", "reason": "invalid_json"}

    external_order_id = str(payload.get("id") or "")
    if not external_order_id:
        return {"status": "ignored", "reason": "no order id in payload"}
    already_imported = db.scalar(select(ImportedStoreOrder.id).where(
        ImportedStoreOrder.entity_id == entity_id, ImportedStoreOrder.platform == "shopify", ImportedStoreOrder.external_order_id == external_order_id,
    ))
    if already_imported:
        return {"status": "ok", "reason": "already imported"}

    customer = payload.get("customer") or {}
    contact_name = " ".join(filter(None, [customer.get("first_name"), customer.get("last_name")])) or None
    contact_phone = payload.get("phone") or customer.get("phone")
    contact_email = payload.get("email") or customer.get("email")
    contact = _find_or_create_order_contact(db, entity_id, contact_name, contact_phone, contact_email)

    order_number = payload.get("name") or payload.get("order_number") or external_order_id
    total = float(payload.get("total_price") or 0)
    deal = Deal(
        entity_id=entity_id, contact_id=contact.id, name=f"Shopify order {order_number}",
        source="shopify_order", value=total, status="won",
        notes=f"Imported from Shopify order {order_number} ({len(payload.get('line_items') or [])} line item(s)).",
    )
    db.add(deal)
    db.flush()
    db.add(ImportedStoreOrder(entity_id=entity_id, platform="shopify", external_order_id=external_order_id, deal_id=deal.id))
    connection.orders_imported = (connection.orders_imported or 0) + 1
    db.commit()
    return {"status": "ok", "deal_id": deal.id}
