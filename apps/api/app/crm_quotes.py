"""GST-aware proforma quotes tied to a CRM Deal -- deliberately not an IRN-registered e-invoice
(mandatory only above Rs 5 crore turnover, past this product's SME target), so this is a plain
PDF-generation + optional WhatsApp-send feature, not an Invoice Registration Portal integration.
"Convert to invoice" reuses the existing SMS-billing Invoice pipeline (invoicing.py) as-is,
including its already-working Zoho Books sync -- a quote becomes exactly the same Invoice row
type Textzi's own billing uses, not a parallel CRM invoice table.

Deliberately its own module, never importing from or importing into dispatch.py/providers.py/
webhooks.py (SMS) or waba_meta.py/waba_webhooks.py (WhatsApp's inbound pipeline) -- it does import
waba_dispatch.send_whatsapp_media for the one-directional "send this quote via WhatsApp" action,
same pattern as every other CRM-to-channel touchpoint this session (crm_campaigns, etc.)."""
import os
from datetime import datetime, timezone

from fpdf import FPDF
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .auth import require_user
from .config import settings
from .database import get_db
from .invoicing import _safe_text
from .models import (
    BundleItem, Company, CrmContact, CrmSettings, Deal, DiscountRule, Entity, Organization, PriceList, PriceListEntry,
    Product, Quote, SalesInvoice, User, WabaConnection,
)
from .permissions import require_channel_scope, require_page_scope_for, require_plan_feature
from .schemas import (
    BundleItemOut, DiscountRuleCreateRequest, DiscountRuleOut, DiscountRuleUpdateRequest, PriceListCreateRequest,
    PriceListEntryOut, PriceListEntrySetRequest, PriceListOut, PriceListUpdateRequest, ProductCreateRequest, ProductOut,
    ProductUpdateRequest, QuoteCreateRequest, QuoteLineItem, QuoteLineItemsUpdateRequest, QuoteOut, SalesInvoiceOut,
)
from .services import DomainError, channel_active, get_gst_rate, notify_user, resolve_user_entity, state_code_from_gstin

router = APIRouter(prefix="/v1/crm/quotes", tags=["crm-quotes"], dependencies=[Depends(require_channel_scope("crm")), Depends(require_page_scope_for("crm-quotes")), Depends(require_plan_feature("crm", "crm-quotes"))])


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_crm(db: Session, entity_id: str) -> None:
    if not channel_active(db, entity_id, "crm"):
        raise HTTPException(status_code=422, detail="Upgrade to the CRM plan to use quotes")


# --- Products (CPQ price list) -----------------------------------------------------------------

def _product_out(db: Session, product: Product) -> ProductOut:
    bundle_items: list[BundleItemOut] = []
    if product.is_bundle:
        items = db.scalars(select(BundleItem).where(BundleItem.bundle_product_id == product.id)).all()
        components = {c.id: c for c in db.scalars(select(Product).where(Product.id.in_([i.component_product_id for i in items]))).all()} if items else {}
        bundle_items = [
            BundleItemOut(id=i.id, component_product_id=i.component_product_id, component_name=components[i.component_product_id].name if i.component_product_id in components else "Unknown", quantity=float(i.quantity))
            for i in items
        ]
    return ProductOut(
        id=product.id, name=product.name, sku=product.sku, hsn_code=product.hsn_code,
        unit_price=float(product.unit_price), tax_rate=float(product.tax_rate) if product.tax_rate is not None else None,
        category=product.category, description=product.description, is_bundle=product.is_bundle,
        bundle_items=bundle_items, active=product.active,
    )


def _set_bundle_items(db: Session, entity_id: str, bundle_product_id: str, items: list) -> None:
    db.execute(text("DELETE FROM bundle_items WHERE bundle_product_id = :id"), {"id": bundle_product_id})
    if not items:
        return
    component_ids = [i.component_product_id for i in items]
    components = {c.id: c for c in db.scalars(select(Product).where(Product.entity_id == entity_id, Product.id.in_(component_ids))).all()}
    missing = set(component_ids) - set(components)
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown component product id(s): {', '.join(sorted(missing))}")
    if bundle_product_id in component_ids:
        raise HTTPException(status_code=422, detail="A bundle cannot contain itself")
    nested = [components[cid].name for cid in component_ids if components[cid].is_bundle]
    if nested:
        raise HTTPException(status_code=422, detail=f"A bundle's components must not themselves be bundles: {', '.join(nested)}")
    for item in items:
        db.add(BundleItem(bundle_product_id=bundle_product_id, component_product_id=item.component_product_id, quantity=item.quantity))


@router.get("/products", response_model=list[ProductOut])
def list_products(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    products = db.scalars(select(Product).where(Product.entity_id == entity.id).order_by(Product.name)).all()
    return [_product_out(db, p) for p in products]


@router.post("/products", response_model=ProductOut)
def create_product(payload: ProductCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    if payload.is_bundle and not payload.bundle_items:
        raise HTTPException(status_code=422, detail="A bundle needs at least one component product")
    product = Product(
        entity_id=entity.id, name=payload.name.strip(), sku=payload.sku, hsn_code=payload.hsn_code,
        unit_price=payload.unit_price, tax_rate=payload.tax_rate, category=payload.category,
        description=payload.description, is_bundle=payload.is_bundle, active=payload.active,
    )
    db.add(product)
    db.flush()  # assigns product.id, needed by _set_bundle_items before the row is committed
    if payload.is_bundle:
        _set_bundle_items(db, entity.id, product.id, payload.bundle_items)
    db.commit()
    db.refresh(product)
    return _product_out(db, product)


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: str, payload: ProductUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    product = db.get(Product, product_id)
    if not product or product.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Product not found")
    if "name" in payload.model_fields_set and payload.name:
        product.name = payload.name.strip()
    if "sku" in payload.model_fields_set:
        product.sku = payload.sku
    if "hsn_code" in payload.model_fields_set and payload.hsn_code is not None:
        product.hsn_code = payload.hsn_code
    if "unit_price" in payload.model_fields_set and payload.unit_price is not None:
        product.unit_price = payload.unit_price
    if "tax_rate" in payload.model_fields_set:
        product.tax_rate = payload.tax_rate
    if "category" in payload.model_fields_set:
        product.category = payload.category
    if "description" in payload.model_fields_set:
        product.description = payload.description
    if "bundle_items" in payload.model_fields_set and payload.bundle_items is not None:
        if not product.is_bundle:
            raise HTTPException(status_code=422, detail="Only a bundle product has components -- set is_bundle at creation time")
        _set_bundle_items(db, entity.id, product.id, payload.bundle_items)
    if "active" in payload.model_fields_set and payload.active is not None:
        product.active = payload.active
    db.commit()
    db.refresh(product)
    return _product_out(db, product)


@router.delete("/products/{product_id}")
def delete_product(product_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    product = db.get(Product, product_id)
    if not product or product.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Product not found")
    referenced_as_component = db.scalar(select(BundleItem.id).where(BundleItem.component_product_id == product_id))
    if referenced_as_component:
        raise HTTPException(status_code=409, detail="This product is a component of a bundle -- remove it from that bundle first")
    db.execute(text("DELETE FROM bundle_items WHERE bundle_product_id = :id"), {"id": product_id})
    db.execute(text("DELETE FROM price_list_entries WHERE product_id = :id"), {"id": product_id})
    db.delete(product)
    db.commit()
    return {"deleted": True}


# --- Discount rules (quantity-threshold, per-product or catalog-wide) ---------------------------

def _discount_rule_out(rule: DiscountRule) -> DiscountRuleOut:
    return DiscountRuleOut(
        id=rule.id, product_id=rule.product_id, name=rule.name,
        min_quantity=float(rule.min_quantity), discount_percent=float(rule.discount_percent), active=rule.active,
    )


@router.get("/discount-rules", response_model=list[DiscountRuleOut])
def list_discount_rules(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rules = db.scalars(select(DiscountRule).where(DiscountRule.entity_id == entity.id).order_by(DiscountRule.min_quantity)).all()
    return [_discount_rule_out(r) for r in rules]


@router.post("/discount-rules", response_model=DiscountRuleOut)
def create_discount_rule(payload: DiscountRuleCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    if payload.product_id:
        product = db.get(Product, payload.product_id)
        if not product or product.entity_id != entity.id:
            raise HTTPException(status_code=404, detail="Product not found")
    rule = DiscountRule(
        entity_id=entity.id, product_id=payload.product_id, name=payload.name.strip(),
        min_quantity=payload.min_quantity, discount_percent=payload.discount_percent, active=payload.active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _discount_rule_out(rule)


@router.patch("/discount-rules/{rule_id}", response_model=DiscountRuleOut)
def update_discount_rule(rule_id: str, payload: DiscountRuleUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(DiscountRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Discount rule not found")
    if "name" in payload.model_fields_set and payload.name:
        rule.name = payload.name.strip()
    if "min_quantity" in payload.model_fields_set and payload.min_quantity is not None:
        rule.min_quantity = payload.min_quantity
    if "discount_percent" in payload.model_fields_set and payload.discount_percent is not None:
        rule.discount_percent = payload.discount_percent
    if "active" in payload.model_fields_set and payload.active is not None:
        rule.active = payload.active
    db.commit()
    db.refresh(rule)
    return _discount_rule_out(rule)


@router.delete("/discount-rules/{rule_id}")
def delete_discount_rule(rule_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    rule = db.get(DiscountRule, rule_id)
    if not rule or rule.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Discount rule not found")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


# --- Price lists (per-company override pricing) -------------------------------------------------

def _price_list_out(price_list: PriceList) -> PriceListOut:
    return PriceListOut(id=price_list.id, name=price_list.name, active=price_list.active)


@router.get("/price-lists", response_model=list[PriceListOut])
def list_price_lists(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    lists = db.scalars(select(PriceList).where(PriceList.entity_id == entity.id).order_by(PriceList.name)).all()
    return [_price_list_out(pl) for pl in lists]


@router.post("/price-lists", response_model=PriceListOut)
def create_price_list(payload: PriceListCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    price_list = PriceList(entity_id=entity.id, name=payload.name.strip(), active=payload.active)
    db.add(price_list)
    db.commit()
    db.refresh(price_list)
    return _price_list_out(price_list)


@router.patch("/price-lists/{price_list_id}", response_model=PriceListOut)
def update_price_list(price_list_id: str, payload: PriceListUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    price_list = db.get(PriceList, price_list_id)
    if not price_list or price_list.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Price list not found")
    if "name" in payload.model_fields_set and payload.name:
        price_list.name = payload.name.strip()
    if "active" in payload.model_fields_set and payload.active is not None:
        price_list.active = payload.active
    db.commit()
    db.refresh(price_list)
    return _price_list_out(price_list)


@router.delete("/price-lists/{price_list_id}")
def delete_price_list(price_list_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    price_list = db.get(PriceList, price_list_id)
    if not price_list or price_list.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Price list not found")
    in_use = db.scalar(select(Company.id).where(Company.price_list_id == price_list_id))
    if in_use:
        raise HTTPException(status_code=409, detail="This price list is assigned to a company -- unassign it first")
    db.execute(text("DELETE FROM price_list_entries WHERE price_list_id = :id"), {"id": price_list_id})
    db.delete(price_list)
    db.commit()
    return {"deleted": True}


def _price_list_entry_out(db: Session, entry: PriceListEntry) -> PriceListEntryOut:
    product = db.get(Product, entry.product_id)
    return PriceListEntryOut(id=entry.id, product_id=entry.product_id, product_name=product.name if product else "Unknown", unit_price=float(entry.unit_price))


@router.get("/price-lists/{price_list_id}/entries", response_model=list[PriceListEntryOut])
def list_price_list_entries(price_list_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    price_list = db.get(PriceList, price_list_id)
    if not price_list or price_list.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Price list not found")
    entries = db.scalars(select(PriceListEntry).where(PriceListEntry.price_list_id == price_list_id)).all()
    return [_price_list_entry_out(db, e) for e in entries]


@router.put("/price-lists/{price_list_id}/entries", response_model=PriceListEntryOut)
def set_price_list_entry(price_list_id: str, payload: PriceListEntrySetRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Upserts one product's override price -- a price list only needs entries for the products
    it actually overrides, so this is set-one-at-a-time, not a bulk replace."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    price_list = db.get(PriceList, price_list_id)
    if not price_list or price_list.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Price list not found")
    product = db.get(Product, payload.product_id)
    if not product or product.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Product not found")
    entry = db.scalar(select(PriceListEntry).where(PriceListEntry.price_list_id == price_list_id, PriceListEntry.product_id == payload.product_id))
    if entry:
        entry.unit_price = payload.unit_price
    else:
        entry = PriceListEntry(price_list_id=price_list_id, product_id=payload.product_id, unit_price=payload.unit_price)
        db.add(entry)
    db.commit()
    db.refresh(entry)
    return _price_list_entry_out(db, entry)


@router.delete("/price-lists/{price_list_id}/entries/{entry_id}")
def delete_price_list_entry(price_list_id: str, entry_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    entry = db.get(PriceListEntry, entry_id)
    if not entry or entry.price_list_id != price_list_id:
        raise HTTPException(status_code=404, detail="Price list entry not found")
    price_list = db.get(PriceList, price_list_id)
    if not price_list or price_list.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Price list not found")
    db.delete(entry)
    db.commit()
    return {"deleted": True}


# --- Line item pricing (discount rules, price lists, bundle expansion) --------------------------

def _best_discount_percent(db: Session, entity_id: str, product_id: str | None, quantity: float) -> float:
    """Picks the single best-matching active rule for this line: the highest min_quantity that's
    still <= quantity, preferring a product-specific rule over a catalog-wide one (product_id is
    null) at the same min_quantity. No stacking -- exactly one rule ever applies per line."""
    rules = db.scalars(select(DiscountRule).where(DiscountRule.entity_id == entity_id, DiscountRule.active.is_(True), DiscountRule.min_quantity <= quantity)).all()
    candidates = [r for r in rules if r.product_id == product_id] or [r for r in rules if r.product_id is None]
    if not candidates:
        return 0.0
    best = max(candidates, key=lambda r: float(r.min_quantity))
    return float(best.discount_percent)


def _price_list_price(db: Session, price_list_id: str | None, product_id: str) -> float | None:
    if not price_list_id:
        return None
    entry = db.scalar(select(PriceListEntry).where(PriceListEntry.price_list_id == price_list_id, PriceListEntry.product_id == product_id))
    return float(entry.unit_price) if entry else None


def _deal_price_list_id(db: Session, deal: Deal) -> str | None:
    contact = db.get(CrmContact, deal.contact_id) if deal.contact_id else None
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    return company.price_list_id if company else None


def _expand_bundle(db: Session, price_list_id: str | None, item: QuoteLineItem) -> list[QuoteLineItem]:
    """A bundle line item becomes one real line per component, quantity multiplied through, each
    priced independently (price-list override applies per component, same as a standalone sale of
    that product) -- the bundle Product row itself never appears as a priced line, only its
    components do, so the quote's own tax/discount math (which operates per real line item) needs
    no bundle-specific branch anywhere else."""
    bundle_items = db.scalars(select(BundleItem).where(BundleItem.bundle_product_id == item.product_id)).all()
    expanded = []
    for bi in bundle_items:
        component = db.get(Product, bi.component_product_id)
        if not component:
            continue
        unit_price = _price_list_price(db, price_list_id, component.id)
        if unit_price is None:
            unit_price = float(component.unit_price)
        expanded.append(QuoteLineItem(
            description=f"{component.name} (from {item.description})", hsn_code=component.hsn_code,
            quantity=item.quantity * float(bi.quantity), unit_price=unit_price, product_id=component.id,
            tax_rate=float(component.tax_rate) if component.tax_rate is not None else None,
        ))
    return expanded


def _apply_line_item_defaults(db: Session, entity_id: str, items: list[QuoteLineItem], price_list_id: str | None = None) -> list[dict]:
    """Fills in tax_rate/discount_percent for each line at add/edit time from the referenced
    Product and any matching DiscountRule -- a caller can still override either explicitly (both
    fields already came through validated on the request), this only fills gaps left as None/0.
    A line referencing a bundle Product is expanded into one real line per component first (see
    _expand_bundle) before any of that per-line logic runs. price_list_id (the deal's own company's
    assigned list, if any) overrides a resolved product's unit_price when an entry exists."""
    expanded_items: list[QuoteLineItem] = []
    for item in items:
        product = db.get(Product, item.product_id) if item.product_id else None
        if product and product.is_bundle:
            expanded_items.extend(_expand_bundle(db, price_list_id, item))
        else:
            expanded_items.append(item)

    result = []
    for item in expanded_items:
        data = item.model_dump()
        product = db.get(Product, item.product_id) if item.product_id else None
        if data.get("tax_rate") is None and product and product.tax_rate is not None:
            data["tax_rate"] = float(product.tax_rate)
        if product and price_list_id:
            override = _price_list_price(db, price_list_id, product.id)
            if override is not None:
                data["unit_price"] = override
        if not data.get("discount_percent"):
            data["discount_percent"] = _best_discount_percent(db, entity_id, item.product_id, item.quantity)
        result.append(data)
    return result


def _compute_totals(db: Session, line_items: list, entity_state: str | None, company_state: str | None) -> dict:
    """Shared by Quote and SalesInvoice -- both snapshot the same line_items shape
    (description/hsn_code/quantity/unit_price/tax_rate/discount_percent), so the tax math needs
    only one implementation."""
    subtotal = 0.0
    discount_total = 0.0
    gst = 0.0
    default_rate = get_gst_rate(db)
    for item in line_items:
        line_amount = item["quantity"] * item["unit_price"]
        discount = line_amount * (item.get("discount_percent") or 0) / 100
        taxable = line_amount - discount
        rate = item.get("tax_rate")
        rate = default_rate if rate is None else rate
        subtotal += line_amount
        discount_total += discount
        gst += taxable * rate
    same_state = bool(entity_state and company_state and entity_state == company_state) or not company_state
    cgst = gst / 2 if same_state else 0
    sgst = gst / 2 if same_state else 0
    igst = gst if not same_state else 0
    return {
        "subtotal": round(subtotal, 2), "discount_total": round(discount_total, 2),
        "cgst": round(cgst, 2), "sgst": round(sgst, 2), "igst": round(igst, 2),
        "total": round(subtotal - discount_total + gst, 2),
    }


def _quote_out(db: Session, quote: Quote) -> QuoteOut:
    deal = db.get(Deal, quote.deal_id)
    contact = db.get(CrmContact, deal.contact_id) if deal else None
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    entity = db.get(Entity, quote.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity else None
    entity_state = (organization.state_code or state_code_from_gstin(organization.gstin)) if organization else None
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(db, quote.line_items, entity_state, company_state)
    settings_row = db.get(CrmSettings, quote.entity_id)
    approvers_required = (settings_row.quote_approver_user_ids or []) if settings_row else []
    return QuoteOut(
        id=quote.id, deal_id=quote.deal_id, quote_number=quote.quote_number, line_items=quote.line_items, status=quote.status,
        subtotal=totals["subtotal"], discount_total=totals["discount_total"],
        cgst=totals["cgst"], sgst=totals["sgst"], igst=totals["igst"], total=totals["total"],
        has_pdf=bool(quote.pdf_path), approval_status=quote.approval_status, approvals=quote.approvals or [],
        approvers_required=approvers_required, converted_invoice_id=quote.converted_invoice_id,
        created_at=quote.created_at.isoformat(), sent_at=quote.sent_at.isoformat() if quote.sent_at else None,
        signed_by_name=quote.signed_by_name, signed_at=quote.signed_at.isoformat() if quote.signed_at else None,
    )


def _render_line_items_pdf(doc_label: str, doc_number: str | None, line_items: list, contact: CrmContact, company: Company | None, organization, totals: dict, tax_invoice: bool = False) -> bytes:
    """Shared by Quote (doc_label="Quote", tax_invoice=False) and SalesInvoice
    (doc_label="TAX INVOICE", tax_invoice=True) -- both a proforma and a real tax invoice are the
    same header/party/item-table/totals layout; a real invoice additionally gets a signatory
    block, since (unlike a quote) it's the actual document a client uses for their own accounting."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _safe_text(organization.name if organization else doc_label), ln=True)
    pdf.set_font("Helvetica", "", 10)
    if organization and organization.gstin:
        pdf.cell(0, 6, _safe_text(f"GSTIN: {organization.gstin}"), ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, _safe_text(f"{doc_label} {doc_number or '(draft)'}"), ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _safe_text(f"To: {company.name if company else (contact.name or contact.phone or 'Customer')}"), ln=True)
    if company and company.gstin:
        pdf.cell(0, 6, _safe_text(f"GSTIN: {company.gstin}"), ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(80, 8, "Description", border=1)
    pdf.cell(25, 8, "HSN", border=1)
    pdf.cell(25, 8, "Qty", border=1)
    pdf.cell(30, 8, "Unit Price", border=1)
    pdf.cell(30, 8, "Amount", border=1, ln=True)
    pdf.set_font("Helvetica", "", 10)
    for item in line_items:
        amount = item["quantity"] * item["unit_price"]
        pdf.cell(80, 8, _safe_text(item["description"])[:40], border=1)
        pdf.cell(25, 8, _safe_text(item.get("hsn_code", "")), border=1)
        pdf.cell(25, 8, str(item["quantity"]), border=1)
        pdf.cell(30, 8, f"{item['unit_price']:.2f}", border=1)
        pdf.cell(30, 8, f"{amount:.2f}", border=1, ln=True)

    pdf.ln(4)
    pdf.cell(160, 7, "Subtotal", align="R")
    pdf.cell(30, 7, f"{totals['subtotal']:.2f}", ln=True)
    if totals["discount_total"]:
        pdf.cell(160, 7, "Discount", align="R")
        pdf.cell(30, 7, f"-{totals['discount_total']:.2f}", ln=True)
    # No fixed "(9%)"/"(18%)" label -- line items can each carry their own tax_rate override
    # (per-product GST varies by HSN code), so the total is a sum across possibly-mixed rates.
    if totals["cgst"]:
        pdf.cell(160, 7, "CGST", align="R")
        pdf.cell(30, 7, f"{totals['cgst']:.2f}", ln=True)
        pdf.cell(160, 7, "SGST", align="R")
        pdf.cell(30, 7, f"{totals['sgst']:.2f}", ln=True)
    if totals["igst"]:
        pdf.cell(160, 7, "IGST", align="R")
        pdf.cell(30, 7, f"{totals['igst']:.2f}", ln=True)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(160, 8, "Total", align="R")
    pdf.cell(30, 8, f"{totals['total']:.2f}", ln=True)

    if tax_invoice:
        pdf.ln(14)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(0, 4.5, "This is a system-generated tax invoice and does not require a physical signature. Subject to reconciliation.")
        pdf.ln(12)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _safe_text(f"For {organization.name}" if organization else ""), align="R", ln=True)
        pdf.cell(0, 5, "Authorized Signatory", align="R", ln=True)

    return bytes(pdf.output())


@router.get("", response_model=list[QuoteOut])
def list_quotes(deal_id: str | None = None, pending_my_approval: bool = False, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(Quote).where(Quote.entity_id == entity.id)
    if deal_id:
        query = query.where(Quote.deal_id == deal_id)
    if pending_my_approval:
        query = query.where(Quote.approval_status == "pending")
    quotes = db.scalars(query.order_by(Quote.created_at.desc())).all()
    if pending_my_approval:
        settings_row = db.get(CrmSettings, entity.id)
        approvers_required = (settings_row.quote_approver_user_ids or []) if settings_row else []
        quotes = [
            q for q in quotes
            if (not approvers_required or user.id in approvers_required)
            and user.id not in {a["user_id"] for a in (q.approvals or [])}
        ]
    return [_quote_out(db, q) for q in quotes]


@router.post("", response_model=QuoteOut)
def create_quote(payload: QuoteCreateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    deal = db.scalar(select(Deal).where(Deal.id == payload.deal_id, Deal.entity_id == entity.id))
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    price_list_id = _deal_price_list_id(db, deal)
    quote = Quote(entity_id=entity.id, deal_id=deal.id, line_items=_apply_line_item_defaults(db, entity.id, payload.line_items, price_list_id), created_by_user_id=user.id)
    db.add(quote)
    db.commit()
    db.refresh(quote)

    # Approval workflow -- if this quote's total exceeds CrmSettings.quote_approval_threshold,
    # it can't be sent until approved (see send_quote below).
    settings_row = db.get(CrmSettings, entity.id)
    if settings_row and settings_row.quote_approval_threshold:
        out = _quote_out(db, quote)
        if out.total > float(settings_row.quote_approval_threshold):
            quote.approval_status = "pending"
            db.commit()
            db.refresh(quote)
            approvers = settings_row.quote_approver_user_ids or []
            for approver_id in approvers:
                notify_user(db, entity.id, approver_id, "quote_pending_approval", "Quote awaiting your approval", f"Quote {quote.quote_number or quote.id} needs your sign-off", "/crm-quotes")
    return _quote_out(db, quote)


@router.patch("/{quote_id}", response_model=QuoteOut)
def update_quote_line_items(quote_id: str, payload: QuoteLineItemsUpdateRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.status != "draft":
        raise HTTPException(status_code=409, detail="Only a draft quote's line items can be edited")
    deal = db.get(Deal, quote.deal_id)
    price_list_id = _deal_price_list_id(db, deal) if deal else None
    quote.line_items = _apply_line_item_defaults(db, entity.id, payload.line_items, price_list_id)
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


@router.delete("/{quote_id}")
def delete_quote(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    db.delete(quote)
    db.commit()
    return {"deleted": True}


@router.post("/{quote_id}/approve", response_model=QuoteOut)
def approve_quote(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """A quote only reaches approval_status="approved" once every approver configured in
    CrmSettings.quote_approver_user_ids has signed off (Quote.approvals) -- an empty approver
    list falls back to the original "anyone can approve" behavior."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    # Row-locked, not a plain db.get -- two approvers signing off at the same instant both read
    # the same Quote.approvals JSON before either writes, and a plain read-modify-write silently
    # drops one approval (lost update). Locking serializes concurrent approvers onto this row.
    quote = db.scalar(select(Quote).where(Quote.id == quote_id).with_for_update())
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.approval_status != "pending":
        raise HTTPException(status_code=409, detail="This quote isn't waiting for approval")
    settings_row = db.get(CrmSettings, entity.id)
    approvers_required = (settings_row.quote_approver_user_ids or []) if settings_row else []
    if approvers_required and user.id not in approvers_required:
        raise HTTPException(status_code=403, detail="You're not one of this account's configured quote approvers")
    approvals = list(quote.approvals or [])
    if any(a["user_id"] == user.id for a in approvals):
        raise HTTPException(status_code=409, detail="You've already approved this quote")
    approvals.append({"user_id": user.id, "approved_at": datetime.now(timezone.utc).isoformat()})
    quote.approvals = approvals
    if not approvers_required or all(uid in {a["user_id"] for a in approvals} for uid in approvers_required):
        quote.approval_status = "approved"
        quote.approved_by_user_id = user.id
        quote.approved_at = datetime.now(timezone.utc)
        if quote.created_by_user_id and quote.created_by_user_id != user.id:
            notify_user(db, entity.id, quote.created_by_user_id, "quote_approved", "Quote approved", f"Quote {quote.quote_number or quote.id} was approved and can now be sent", "/crm-quotes")
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


def _get_pdf_bytes(db: Session, quote: Quote) -> bytes:
    deal = db.get(Deal, quote.deal_id)
    contact = db.get(CrmContact, deal.contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    entity = db.get(Entity, quote.entity_id)
    organization = db.get(Organization, entity.organization_id)
    entity_state = organization.state_code or state_code_from_gstin(organization.gstin)
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(db, quote.line_items, entity_state, company_state)
    return _render_line_items_pdf("Quote", quote.quote_number, quote.line_items, contact, company, organization, totals)


@router.get("/{quote_id}/pdf")
def download_quote_pdf(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    pdf_bytes = _get_pdf_bytes(db, quote)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={quote.quote_number or quote.id}.pdf"})


@router.post("/{quote_id}/send-whatsapp", response_model=QuoteOut)
def send_quote_via_whatsapp(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.approval_status == "pending":
        raise HTTPException(status_code=422, detail="This quote is waiting for manager approval before it can be sent")
    deal = db.get(Deal, quote.deal_id)
    contact = db.get(CrmContact, deal.contact_id)
    if not contact.phone:
        raise HTTPException(status_code=422, detail="This contact has no phone number to send to")
    wa_id = "".join(ch for ch in contact.phone if ch.isdigit())
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before sending quotes")

    if not quote.quote_number:
        db.execute(text("CREATE SEQUENCE IF NOT EXISTS quote_number_seq"))
        seq_val = db.execute(text("SELECT nextval('quote_number_seq')")).scalar()
        quote.quote_number = f"QUO-{datetime.now(timezone.utc).year}-{seq_val:06d}"

    pdf_bytes = _get_pdf_bytes(db, quote)
    directory = os.path.join(settings.uploads_dir, "crm_quotes")
    os.makedirs(directory, exist_ok=True)
    local_copy_path = os.path.join(directory, f"{quote.id}.pdf")
    with open(local_copy_path, "wb") as f:
        f.write(pdf_bytes)
    quote.pdf_path = local_copy_path

    from .waba_dispatch import send_whatsapp_media, send_whatsapp_text
    from .waba_meta import MetaApiError
    filename = f"{quote.quote_number}.pdf"
    try:
        send_whatsapp_media(db, entity.id, wa_id, pdf_bytes, filename, "application/pdf", "document", f"Quote {quote.quote_number}", sent_by_user_id=user.id)
        signing_link = f"{settings.web_origin}/public-quote/{quote.id}"
        send_whatsapp_text(db, entity.id, wa_id, f"Review and accept this quote online: {signing_link}", sent_by_user_id=user.id)
    except (DomainError, MetaApiError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this quote: {exc}") from exc

    quote.status = "sent"
    quote.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)


@router.get("/invoices", response_model=list[SalesInvoiceOut])
def list_sales_invoices(deal_id: str | None = None, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    query = select(SalesInvoice).where(SalesInvoice.entity_id == entity.id)
    if deal_id:
        query = query.where(SalesInvoice.deal_id == deal_id)
    invoices = db.scalars(query.order_by(SalesInvoice.created_at.desc())).all()
    return [_sales_invoice_out(db, i) for i in invoices]


def _sales_invoice_out(db: Session, invoice: SalesInvoice) -> SalesInvoiceOut:
    deal = db.get(Deal, invoice.deal_id)
    contact = db.get(CrmContact, deal.contact_id) if deal else None
    company = db.get(Company, contact.company_id) if contact and contact.company_id else None
    entity = db.get(Entity, invoice.entity_id)
    organization = db.get(Organization, entity.organization_id) if entity else None
    entity_state = (organization.state_code or state_code_from_gstin(organization.gstin)) if organization else None
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(db, invoice.line_items, entity_state, company_state)
    return SalesInvoiceOut(
        id=invoice.id, deal_id=invoice.deal_id, quote_id=invoice.quote_id, invoice_number=invoice.invoice_number,
        line_items=invoice.line_items, status=invoice.status,
        subtotal=totals["subtotal"], discount_total=totals["discount_total"],
        cgst=totals["cgst"], sgst=totals["sgst"], igst=totals["igst"], total=totals["total"],
        has_pdf=bool(invoice.pdf_path), created_at=invoice.created_at.isoformat(),
        sent_at=invoice.sent_at.isoformat() if invoice.sent_at else None,
        paid_at=invoice.paid_at.isoformat() if invoice.paid_at else None,
    )


def _get_sales_invoice_pdf_bytes(db: Session, invoice: SalesInvoice) -> bytes:
    deal = db.get(Deal, invoice.deal_id)
    contact = db.get(CrmContact, deal.contact_id)
    company = db.get(Company, contact.company_id) if contact.company_id else None
    entity = db.get(Entity, invoice.entity_id)
    organization = db.get(Organization, entity.organization_id)
    entity_state = organization.state_code or state_code_from_gstin(organization.gstin)
    company_state = state_code_from_gstin(company.gstin) if company else None
    totals = _compute_totals(db, invoice.line_items, entity_state, company_state)
    return _render_line_items_pdf("TAX INVOICE", invoice.invoice_number, invoice.line_items, contact, company, organization, totals, tax_invoice=True)


@router.post("/{quote_id}/convert-to-invoice", response_model=SalesInvoiceOut)
def convert_quote_to_invoice(quote_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Issues a real, tenant-to-client GST Tax Invoice (SalesInvoice) from an accepted quote --
    genuinely different from the platform Invoice model (models.py), which only ever bills the
    CRM tenant itself, never their own client. Line items are copied as-is from the quote (same
    snapshot discipline as everywhere else in this module: a later Product/DiscountRule edit must
    never change an already-issued document's numbers)."""
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.status != "accepted":
        raise HTTPException(status_code=409, detail="Only an accepted quote can be converted to an invoice")
    if quote.converted_invoice_id:
        raise HTTPException(status_code=409, detail="This quote has already been converted to an invoice")

    invoice = SalesInvoice(entity_id=entity.id, deal_id=quote.deal_id, quote_id=quote.id, line_items=quote.line_items, created_by_user_id=user.id)
    db.add(invoice)
    db.flush()

    db.execute(text("CREATE SEQUENCE IF NOT EXISTS sales_invoice_number_seq"))
    seq_val = db.execute(text("SELECT nextval('sales_invoice_number_seq')")).scalar()
    invoice.invoice_number = f"SINV-{datetime.now(timezone.utc).year}-{seq_val:06d}"

    pdf_bytes = _get_sales_invoice_pdf_bytes(db, invoice)
    directory = os.path.join(settings.uploads_dir, "crm_sales_invoices")
    os.makedirs(directory, exist_ok=True)
    pdf_path = os.path.join(directory, f"{invoice.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    invoice.pdf_path = pdf_path

    quote.converted_invoice_id = invoice.id
    db.commit()
    db.refresh(invoice)
    return _sales_invoice_out(db, invoice)


@router.get("/invoices/{invoice_id}/pdf")
def download_sales_invoice_pdf(invoice_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    invoice = db.get(SalesInvoice, invoice_id)
    if not invoice or invoice.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    pdf_bytes = _get_sales_invoice_pdf_bytes(db, invoice)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={invoice.invoice_number or invoice.id}.pdf"})


@router.post("/invoices/{invoice_id}/send-whatsapp", response_model=SalesInvoiceOut)
def send_sales_invoice_via_whatsapp(invoice_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    invoice = db.get(SalesInvoice, invoice_id)
    if not invoice or invoice.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    deal = db.get(Deal, invoice.deal_id)
    contact = db.get(CrmContact, deal.contact_id)
    if not contact.phone:
        raise HTTPException(status_code=422, detail="This contact has no phone number to send to")
    wa_id = "".join(ch for ch in contact.phone if ch.isdigit())
    connection = db.get(WabaConnection, entity.id)
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=422, detail="Connect a WhatsApp number before sending invoices")

    pdf_bytes = _get_sales_invoice_pdf_bytes(db, invoice)
    from .waba_dispatch import send_whatsapp_media
    from .waba_meta import MetaApiError
    try:
        send_whatsapp_media(db, entity.id, wa_id, pdf_bytes, f"{invoice.invoice_number}.pdf", "application/pdf", "document", f"Tax Invoice {invoice.invoice_number}", sent_by_user_id=user.id)
    except (DomainError, MetaApiError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not send this invoice: {exc}") from exc

    invoice.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invoice)
    return _sales_invoice_out(db, invoice)


@router.post("/invoices/{invoice_id}/mark-paid", response_model=SalesInvoiceOut)
def mark_sales_invoice_paid(invoice_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    invoice = db.get(SalesInvoice, invoice_id)
    if not invoice or invoice.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == "paid":
        raise HTTPException(status_code=409, detail="This invoice is already marked paid")
    invoice.status = "paid"
    invoice.paid_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invoice)
    return _sales_invoice_out(db, invoice)


@router.post("/{quote_id}/status/{status}", response_model=QuoteOut)
def set_quote_status(quote_id: str, status: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if status not in ("accepted", "rejected"):
        raise HTTPException(status_code=422, detail="status must be accepted or rejected")
    entity = _resolve_entity(db, user)
    _require_crm(db, entity.id)
    quote = db.get(Quote, quote_id)
    if not quote or quote.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Quote not found")
    quote.status = status
    db.commit()
    db.refresh(quote)
    return _quote_out(db, quote)
