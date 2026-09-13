"""Pulls a connected Shopify store's products and pushes them into the entity's Meta Commerce
Catalog, so they become sendable over WhatsApp Commerce -- WabaCatalogItem is a read-only mirror
of Meta's own catalog (see its own docstring), so this never writes there directly; the existing
hourly catalog_sync.py pull picks up whatever lands in Meta afterward, same as any other Meta-side
catalog change. Deliberately its own module, not folded into catalog_sync.py -- same "one file per
distinct integration surface" convention as crm_quotes.py/crm_public.py/waba_meta.py."""
import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import ShopifyConnection, User, WabaConnection
from .permissions import require_channel_scope
from .schemas import ShopifyConnectionOut, ShopifyConnectRequest
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, resolve_user_entity
from .waba_meta import MetaApiError, push_catalog_batch

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/shopify", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])

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
    except requests.exceptions.RequestException as exc:
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
        return ShopifyConnectionOut(connected=False, shop_domain=None, status=None, last_sync_status=None, last_sync_error=None, last_synced_at=None, products_synced=0)
    return ShopifyConnectionOut(
        connected=True, shop_domain=connection.shop_domain, status=connection.status,
        last_sync_status=connection.last_sync_status, last_sync_error=connection.last_sync_error,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        products_synced=connection.products_synced,
    )


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
    db.delete(connection)
    db.commit()
    return {"disconnected": True}
