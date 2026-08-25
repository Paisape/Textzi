"""Read-only sync of a connected entity's Meta Commerce Manager catalog into WabaCatalogItem, so
the agent inbox can offer a real product picker instead of requiring an agent to already know a
product's retailer_id. Deliberately its own module, not folded into waba.py/waba_dispatch.py --
same "one file per distinct integration surface" convention as crm_quotes.py/crm_public.py."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import require_user
from .database import SessionLocal, get_db
from .models import User, WabaCatalogItem, WabaConnection
from .permissions import require_channel_scope
from .schemas import WabaCatalogItemOut
from .security import decrypt_secret
from .services import DomainError, resolve_user_entity
from .waba_meta import MetaApiError, get_catalog_products

logger = logging.getLogger("textzi.waba")

router = APIRouter(prefix="/v1/waba/catalog", tags=["waba"], dependencies=[Depends(require_channel_scope("waba"))])


def sync_catalog(db: Session, entity_id: str, catalog_id: str, access_token: str) -> int:
    """Fetches the current product list from Meta and replaces this entity's WabaCatalogItem rows
    wholesale (delete-then-insert, not a diff/upsert) -- catalogs at this scale (capped at 100
    items per get_catalog_products' own single-page limit) make a full replace simpler and safer
    than tracking per-product staleness, and it's exactly what "sync" should mean here: the local
    mirror matches Meta's current state, full stop. Returns the number of items synced."""
    products = get_catalog_products(catalog_id, access_token)
    db.execute(delete(WabaCatalogItem).where(WabaCatalogItem.entity_id == entity_id))
    for product in products:
        retailer_id = product.get("retailer_id")
        if not retailer_id:
            continue
        db.add(WabaCatalogItem(
            entity_id=entity_id, product_retailer_id=retailer_id, name=product.get("name") or retailer_id,
            image_url=product.get("image_url"), price=product.get("price"), currency=product.get("currency"),
            availability=product.get("availability"),
        ))
    db.commit()
    return len(products)


def sync_all_catalogs() -> None:
    """The scheduled runner (main.py's lifespan, hourly) -- syncs every connected entity that has
    a catalog_id set. Owns its own DB session since it runs outside any request context, same
    shape as crm_email.poll_all_email_inboxes."""
    db = SessionLocal()
    try:
        connections = db.scalars(select(WabaConnection).where(WabaConnection.status == "connected", WabaConnection.catalog_id.is_not(None))).all()
        for connection in connections:
            try:
                access_token = decrypt_secret(connection.access_token_encrypted)
                sync_catalog(db, connection.entity_id, connection.catalog_id, access_token)
            except Exception:
                logger.warning("catalog_sync: sync failed for entity %s", connection.entity_id, exc_info=True)
    finally:
        db.close()


@router.get("", response_model=list[WabaCatalogItemOut])
def list_catalog_items(q: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Backs the agent-inbox product picker -- `q` filters by name/retailer_id substring so an
    agent can type-to-search rather than scroll a flat list."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    query = select(WabaCatalogItem).where(WabaCatalogItem.entity_id == entity.id)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(WabaCatalogItem.name.ilike(like) | WabaCatalogItem.product_retailer_id.ilike(like))
    items = db.scalars(query.order_by(WabaCatalogItem.name).limit(200)).all()
    return [
        WabaCatalogItemOut(
            id=item.id, product_retailer_id=item.product_retailer_id, name=item.name, image_url=item.image_url,
            price=item.price, currency=item.currency, availability=item.availability,
            last_synced_at=item.last_synced_at.isoformat(),
        )
        for item in items
    ]


@router.post("/sync")
def sync_now(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Manual "Sync now" button -- immediate feedback after first connecting a catalog rather than
    waiting for the next hourly job run."""
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number first")
    if not connection.catalog_id:
        raise HTTPException(status_code=422, detail="Add your Meta catalog id in Manage WhatsApp before syncing")
    access_token = decrypt_secret(connection.access_token_encrypted)
    try:
        count = sync_catalog(db, entity.id, connection.catalog_id, access_token)
    except MetaApiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"synced": count}
