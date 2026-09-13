"""WooCommerce twin of catalog_shopify.py -- pulls a connected self-hosted store's products and
pushes them into the entity's Meta Commerce Catalog. Same one-directional shape and same reasons
for it (WabaCatalogItem is a read-only Meta mirror, see its own docstring); see catalog_shopify.py
for the fuller architectural explanation, not repeated here."""
import logging
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException
from requests.auth import HTTPBasicAuth
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import User, WabaConnection, WooCommerceConnection
from .permissions import require_channel_scope
from .schemas import WooCommerceConnectionOut, WooCommerceConnectRequest
from .security import decrypt_secret, encrypt_secret
from .services import DomainError, resolve_user_entity
from .waba_meta import MetaApiError, push_catalog_batch

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/woocommerce", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])

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
        return WooCommerceConnectionOut(connected=False, store_url=None, status=None, last_sync_status=None, last_sync_error=None, last_synced_at=None, products_synced=0)
    return WooCommerceConnectionOut(
        connected=True, store_url=connection.store_url, status=connection.status,
        last_sync_status=connection.last_sync_status, last_sync_error=connection.last_sync_error,
        last_synced_at=connection.last_synced_at.isoformat() if connection.last_synced_at else None,
        products_synced=connection.products_synced,
    )


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
    db.delete(connection)
    db.commit()
    return {"disconnected": True}
