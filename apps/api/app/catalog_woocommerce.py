"""WooCommerce twin of catalog_shopify.py -- pulls a connected self-hosted store's products and
pushes them into the entity's Meta Commerce Catalog. Same one-directional shape and same reasons
for it (WabaCatalogItem is a read-only Meta mirror, see its own docstring); see catalog_shopify.py
for the fuller architectural explanation, not repeated here.

Also imports a real WooCommerce order into CRM as a Deal via a webhook, same Shopify -> CRM
direction and same WABA-side-module-must-not-import-crm.py isolation reasoning as
catalog_shopify.py's own order-import addition -- see that file's module docstring for the fuller
explanation. Unlike Shopify (whose webhook HMAC key is an app client secret this integration never
has), WooCommerce's REST API lets the caller set an arbitrary secret at webhook-creation time, so
this one verifies a real X-WC-Webhook-Signature (base64 HMAC-SHA256), not a URL-embedded token."""
import base64
import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from requests.auth import HTTPBasicAuth
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import CrmContact, Deal, ImportedStoreOrder, User, WabaConnection, WooCommerceConnection
from .permissions import require_channel_scope
from .schemas import WooCommerceConnectionOut, WooCommerceConnectRequest
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, get_platform_company_info, resolve_user_entity
from .waba_meta import MetaApiError, push_catalog_batch

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/woocommerce", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])
# Unauthenticated -- WooCommerce calls this directly, no user session. Same structural exclusion
# (a separate router, not a bypass flag) already used for waba_webhooks.py/crm_public.py.
public_router = APIRouter(prefix="/v1/webhooks/woocommerce", tags=["waba"])

REQUEST_TIMEOUT_SECONDS = 20
MAX_PRODUCTS_PER_SYNC = 250  # same "full replace at this scale, no real pagination" reasoning as catalog_shopify.py


class WooCommerceApiError(Exception):
    pass


def _store_url_only(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    return url


def _fetch_products(store_url: str, consumer_key: str, consumer_secret: str) -> list[dict]:
    url = f"{store_url}/wp-json/wc/v3/products"
    try:
        response = requests.get(
            url, auth=HTTPBasicAuth(consumer_key, consumer_secret),
            params={"per_page": MAX_PRODUCTS_PER_SYNC, "status": "publish"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout as exc:
        raise WooCommerceApiError(f"Could not reach this WooCommerce store: timed out after {REQUEST_TIMEOUT_SECONDS}s.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise WooCommerceApiError(f"Could not reach this WooCommerce store at '{store_url}' -- check the URL is correct.") from exc
    except requests.exceptions.RequestException as exc:
        raise WooCommerceApiError(f"Could not reach this WooCommerce store: {exc}") from exc
    if response.status_code == 401:
        raise WooCommerceApiError("WooCommerce rejected these API keys -- they may have been revoked. Reconnect with fresh ones.")
    if not response.ok:
        raise WooCommerceApiError(f"WooCommerce returned HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def _to_meta_item(product: dict) -> dict | None:
    price = product.get("price") or product.get("regular_price")
    if not price:
        return None
    images = product.get("images") or []
    item = {
        "id": f"woo-{product['id']}",
        "title": (product.get("name") or "")[:100],
        "description": (product.get("short_description") or product.get("description") or product.get("name") or "")[:5000],
        "price": f"{price} INR",
        "availability": "in stock" if product.get("stock_status") == "instock" else "out of stock",
        "condition": "new",
        "brand": "Unbranded",
        "link": product.get("permalink") or "",
    }
    if images:
        item["image_link"] = images[0].get("src")
    return item


def sync_woocommerce_catalog(db: Session, connection: WooCommerceConnection, waba_connection: WabaConnection) -> int:
    consumer_key = decrypt_secret(connection.consumer_key_encrypted)
    consumer_secret = decrypt_secret(connection.consumer_secret_encrypted)
    products = _fetch_products(connection.store_url, consumer_key, consumer_secret)
    items = [item for item in (_to_meta_item(p) for p in products) if item]
    if not items:
        return 0
    meta_access_token = decrypt_secret(waba_connection.access_token_encrypted)
    push_catalog_batch(waba_connection.catalog_id, meta_access_token, items)
    return len(items)


def sync_all_woocommerce_connections() -> None:
    db = SessionLocal()
    try:
        connections = db.query(WooCommerceConnection).filter(WooCommerceConnection.status == "connected").all()
        for connection in connections:
            waba_connection = db.get(WabaConnection, connection.entity_id)
            if not waba_connection or not waba_connection.catalog_id:
                continue
            try:
                count = sync_woocommerce_catalog(db, connection, waba_connection)
                connection.last_sync_status = "success"
                connection.last_sync_error = None
                connection.products_synced = count
            except (WooCommerceApiError, MetaApiError) as exc:
                connection.last_sync_status = "failed"
                connection.last_sync_error = str(exc)[:500]
                logger.warning("woocommerce catalog sync failed for entity %s: %s", connection.entity_id, exc)
            connection.last_synced_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _resolve_entity(db: Session, user: User):
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _connection_out(connection: WooCommerceConnection | None) -> WooCommerceConnectionOut:
    if not connection:
        return WooCommerceConnectionOut(
            connected=False, store_url=None, status=None, last_sync_status=None, last_sync_error=None,
            last_synced_at=None, products_synced=0, order_import_active=False, orders_imported=0,
        )
    return WooCommerceConnectionOut(
        connected=True, store_url=connection.store_url, status=connection.status,
        last_sync_status=connection.last_sync_status, last_sync_error=connection.last_sync_error,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        products_synced=connection.products_synced, order_import_active=bool(connection.order_webhook_id),
        orders_imported=connection.orders_imported,
    )


def _register_order_webhook(db: Session, entity_id: str, store_url: str, consumer_key: str, consumer_secret: str) -> tuple[str, str] | None:
    """Registers a WooCommerce order.created webhook with a freshly generated secret WooCommerce
    will sign every delivery with (X-WC-Webhook-Signature) -- unlike Shopify, WooCommerce's REST
    API lets the caller set this secret directly, so real per-request HMAC verification is
    possible here (see the receiver). Returns (webhook_id, secret), or None if public_api_base_url
    isn't configured yet -- catalog sync still works either way, same degrade-gracefully shape as
    catalog_shopify.py's identical helper."""
    base_url = get_platform_company_info(db).public_api_base_url
    if not base_url:
        return None
    secret = secrets.token_urlsafe(32)
    callback_url = f"{base_url.rstrip('/')}/v1/webhooks/woocommerce/{entity_id}/orders"
    try:
        response = requests.post(
            f"{store_url}/wp-json/wc/v3/webhooks", auth=HTTPBasicAuth(consumer_key, consumer_secret),
            json={"name": "Textzi order import", "topic": "order.created", "delivery_url": callback_url, "secret": secret},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise WooCommerceApiError(f"Connected, but could not register the order-import webhook: {exc}") from exc
    if not response.ok:
        raise WooCommerceApiError(f"Connected, but WooCommerce rejected the order-import webhook registration: HTTP {response.status_code}: {response.text[:300]}")
    webhook_id = str(response.json()["id"])
    return webhook_id, secret


def _deregister_order_webhook(store_url: str, consumer_key: str, consumer_secret: str, webhook_id: str) -> None:
    try:
        requests.delete(
            f"{store_url}/wp-json/wc/v3/webhooks/{webhook_id}", auth=HTTPBasicAuth(consumer_key, consumer_secret),
            params={"force": "true"}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        logger.warning("could not deregister WooCommerce order webhook %s: %s", webhook_id, exc)


@router.get("/connection", response_model=WooCommerceConnectionOut)
def get_woocommerce_connection(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    return _connection_out(db.get(WooCommerceConnection, entity.id))


@router.post("/connect", response_model=WooCommerceConnectionOut)
def connect_woocommerce(payload: WooCommerceConnectRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    store_url = _store_url_only(payload.store_url)
    try:
        _fetch_products(store_url, payload.consumer_key, payload.consumer_secret)
    except WooCommerceApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WooCommerceConnection, entity.id)
    if not connection:
        connection = WooCommerceConnection(entity_id=entity.id)
        db.add(connection)
    connection.store_url = store_url
    connection.consumer_key_encrypted = encrypt_secret(payload.consumer_key)
    connection.consumer_secret_encrypted = encrypt_secret(payload.consumer_secret)
    connection.status = "connected"
    db.commit(); db.refresh(connection)

    # Best-effort, same reasoning as catalog_shopify.py's identical block -- catalog sync itself
    # still works even if the webhook registration fails or Public API base URL isn't set yet.
    try:
        registered = _register_order_webhook(db, entity.id, store_url, payload.consumer_key, payload.consumer_secret)
        if registered:
            connection.order_webhook_id, secret = registered
            connection.webhook_secret_encrypted = encrypt_secret(secret)
            db.commit(); db.refresh(connection)
    except WooCommerceApiError as exc:
        logger.warning("WooCommerce order-webhook registration failed for entity %s: %s", entity.id, exc)
    return _connection_out(connection)


@router.post("/sync-now", response_model=WooCommerceConnectionOut)
def sync_woocommerce_now(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    connection = db.get(WooCommerceConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WooCommerce store first.")
    waba_connection = db.get(WabaConnection, entity.id)
    if not waba_connection or not waba_connection.catalog_id:
        raise HTTPException(status_code=422, detail="Connect WhatsApp and set a Meta Commerce Catalog id first (Channels > WhatsApp > Connect).")
    try:
        count = sync_woocommerce_catalog(db, connection, waba_connection)
        connection.last_sync_status = "success"
        connection.last_sync_error = None
        connection.products_synced = count
    except (WooCommerceApiError, MetaApiError) as exc:
        connection.last_sync_status = "failed"
        connection.last_sync_error = str(exc)[:500]
    connection.last_synced_at = datetime.now(timezone.utc)
    db.commit(); db.refresh(connection)
    return _connection_out(connection)


@router.delete("/connection")
def disconnect_woocommerce(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    connection = db.get(WooCommerceConnection, entity.id)
    if not connection:
        raise HTTPException(status_code=404, detail="No WooCommerce connection to remove.")
    if connection.order_webhook_id:
        _deregister_order_webhook(
            connection.store_url, decrypt_secret(connection.consumer_key_encrypted),
            decrypt_secret(connection.consumer_secret_encrypted), connection.order_webhook_id,
        )
    db.delete(connection)
    db.commit()
    return {"disconnected": True}


# --- Order import (WooCommerce order.created webhook -> a Deal) ---------------------------------

def _find_or_create_order_contact(db: Session, entity_id: str, name: str | None, phone: str | None, email: str | None) -> CrmContact:
    """Local copy of crm._resolve_or_create_contact's find-or-create-by-phone/email shape -- see
    catalog_shopify.py's identical helper for why this isn't an import of it."""
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
        db.rollback()
        if phone:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.phone == phone))
        if not existing and email:
            existing = db.scalar(select(CrmContact).where(CrmContact.entity_id == entity_id, CrmContact.email == email))
        if existing:
            return existing
        raise
    return contact


@public_router.post("/{entity_id}/orders")
async def receive_woocommerce_order_webhook(entity_id: str, request: Request, db: Session = Depends(get_db), x_wc_webhook_signature: str | None = Header(default=None)):
    """WooCommerce's own order.created delivery, HMAC-verified for real (unlike Shopify's version
    of this receiver) since WooCommerce lets the caller set its own webhook secret at registration
    time. Retries on non-2xx per WooCommerce's own webhook delivery/retry behavior, so this must be
    idempotent -- ImportedStoreOrder is the dedup guard, same as the Shopify receiver."""
    connection = db.get(WooCommerceConnection, entity_id)
    if not connection or not connection.webhook_secret_encrypted:
        raise HTTPException(status_code=403, detail="No order-import webhook configured for this entity")
    raw_body = await request.body()
    secret = decrypt_secret(connection.webhook_secret_encrypted)
    expected_signature = base64.b64encode(hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()).decode()
    if not x_wc_webhook_signature or not hmac.compare_digest(x_wc_webhook_signature, expected_signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except ValueError:
        return {"status": "ignored", "reason": "invalid_json"}

    # WooCommerce sends an empty {} body as a one-time ping when a webhook is first created --
    # confirmed via their own docs; nothing to import yet, and there's no order id to key on.
    external_order_id = str(payload.get("id") or "")
    if not external_order_id:
        return {"status": "ok", "reason": "no order id (likely the webhook's own creation ping)"}
    already_imported = db.scalar(select(ImportedStoreOrder.id).where(
        ImportedStoreOrder.entity_id == entity_id, ImportedStoreOrder.platform == "woocommerce", ImportedStoreOrder.external_order_id == external_order_id,
    ))
    if already_imported:
        return {"status": "ok", "reason": "already imported"}

    billing = payload.get("billing") or {}
    contact_name = " ".join(filter(None, [billing.get("first_name"), billing.get("last_name")])) or None
    contact_phone = billing.get("phone")
    contact_email = billing.get("email")
    contact = _find_or_create_order_contact(db, entity_id, contact_name, contact_phone, contact_email)

    order_number = payload.get("number") or external_order_id
    total = float(payload.get("total") or 0)
    deal = Deal(
        entity_id=entity_id, contact_id=contact.id, name=f"WooCommerce order #{order_number}",
        source="woocommerce_order", value=total, status="won",
        notes=f"Imported from WooCommerce order #{order_number} ({len(payload.get('line_items') or [])} line item(s)).",
    )
    db.add(deal)
    db.flush()
    db.add(ImportedStoreOrder(entity_id=entity_id, platform="woocommerce", external_order_id=external_order_id, deal_id=deal.id))
    connection.orders_imported = (connection.orders_imported or 0) + 1
    db.commit()
    return {"status": "ok", "deal_id": deal.id}
