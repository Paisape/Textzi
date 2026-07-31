"""Self-service invoice access: a caller only ever sees their own entity's ISSUED invoices --
drafts are an internal admin-side pending state (an admin manual credit awaiting approval) and
are never exposed here, only under /v1/admin/invoices."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Invoice, User
from .permissions import require_capability
from .schemas import InvoiceOut
from .services import DomainError, resolve_user_entity

router = APIRouter(prefix="/v1/invoices", tags=["invoices"])


def _out(invoice: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=invoice.id, entity_id=invoice.entity_id, invoice_number=invoice.invoice_number,
        type=invoice.type, status=invoice.status, base_amount=float(invoice.base_amount),
        gst_amount=float(invoice.gst_amount), total_amount=float(invoice.total_amount),
        reference=invoice.reference, notes=invoice.notes, created_at=invoice.created_at.isoformat(),
        issued_at=invoice.issued_at.isoformat() if invoice.issued_at else None,
    )


@router.get("", response_model=list[InvoiceOut])
def list_my_invoices(user: User = Depends(require_capability("invoices:view")), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    invoices = db.scalars(select(Invoice).where(Invoice.entity_id == entity.id, Invoice.status == "issued").order_by(Invoice.issued_at.desc())).all()
    return [_out(i) for i in invoices]


@router.get("/{invoice_id}/pdf")
def download_my_invoice(invoice_id: str, user: User = Depends(require_capability("invoices:view")), db: Session = Depends(get_db)):
    try:
        entity = resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    invoice = db.get(Invoice, invoice_id)
    if not invoice or invoice.entity_id != entity.id or not invoice.pdf_path:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return FileResponse(invoice.pdf_path, filename=f"{invoice.invoice_number}.pdf", media_type="application/pdf")
