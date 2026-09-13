"""Generates Tally-importable XML for an issued Invoice and, for a customer whose own Tally is
genuinely reachable (a cloud-hosted Tally VPS, VPN, or deliberately port-forwarded office PC --
Tally's own XML/HTTP gateway on port 9000 is explicitly documented as never meant to be exposed to
the public internet, so this is opt-in, not the default path), pushes it there directly via a
plain HTTP POST -- no TDL/custom Tally add-on needed for this: Tally's own built-in gateway accepts
a correctly-shaped "Import Data" envelope with zero add-on code loaded into Tally itself. See
TallyConnection's own docstring for the full reasoning on why this is opt-in rather than
automatic, unlike the Zoho/Shopify/WooCommerce integrations, which talk to real cloud APIs.

XML envelope/voucher shape confirmed against Tally's own documented XML interface (Gateway of
Tally > Import Data accepts exactly this "Vouchers" REQUESTDESC shape); the debit-negative/
credit-positive sign convention on ALLLEDGERENTRIES.LIST amounts is Tally's own documented
requirement, not a Textzi choice."""
import logging
from datetime import datetime, timezone
from xml.sax.saxutils import escape

import requests
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from .auth import require_user
from .database import get_db
from .invoicing import INVOICE_TYPE_LABELS
from .models import Entity, Invoice, Organization, TallyConnection, User
from .schemas import TallyConnectionOut, TallyConnectRequest, TallyPushResponse
from .services import DomainError, get_platform_company_info, resolve_user_entity

logger = logging.getLogger("textzi.tally")

router = APIRouter(prefix="/v1/tally", tags=["tally"])

REQUEST_TIMEOUT_SECONDS = 15


class TallyGatewayError(Exception):
    pass


def _resolve_entity(db: Session, user: User) -> Entity:
    try:
        return resolve_user_entity(db, user)
    except DomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def build_voucher_xml(invoice: Invoice, organization: Organization, company_name: str, tally_company_name: str) -> str:
    """One SALES voucher per Invoice -- the party ledger is the platform itself (the organization
    is buying Textzi's own service), so PARTYLEDGERNAME is Textzi's own company name, matching
    what actually appears on the invoice PDF's seller block. A real accountant importing this
    still needs the "Textzi Technologies..." ledger and a matching GST/sales ledger to already
    exist in their books (Tally's own documented "masters-first" requirement) -- this generates
    the transaction, not the chart of accounts, same division of responsibility every other
    Tally-XML integration referenced in this module's own research leaves to the accountant."""
    voucher_date = (invoice.issued_at or datetime.now(timezone.utc)).strftime("%Y%m%d")
    item_label = INVOICE_TYPE_LABELS.get(invoice.type, invoice.type.replace("_", " ").title())
    base = float(invoice.base_amount)
    gst = float(invoice.gst_amount)
    total = float(invoice.total_amount)
    voucher_number = escape(invoice.invoice_number or invoice.id)
    party = escape(company_name)
    narration = escape(f"{item_label} -- {organization.name}")

    return f"""<ENVELOPE>
 <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
 <BODY>
  <IMPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Vouchers</REPORTNAME>
    <STATICVARIABLES>
     <SVCURRENTCOMPANY>{escape(tally_company_name)}</SVCURRENTCOMPANY>
    </STATICVARIABLES>
   </REQUESTDESC>
   <REQUESTDATA>
    <TALLYMESSAGE xmlns:UDF="TallyUDF">
     <VOUCHER VCHTYPE="Sales" ACTION="Create" OBJVIEW="Invoice Voucher View">
      <DATE>{voucher_date}</DATE>
      <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
      <VOUCHERNUMBER>{voucher_number}</VOUCHERNUMBER>
      <PARTYLEDGERNAME>{party}</PARTYLEDGERNAME>
      <NARRATION>{narration}</NARRATION>
      <ISINVOICE>Yes</ISINVOICE>
      <ALLLEDGERENTRIES.LIST>
       <LEDGERNAME>{party}</LEDGERNAME>
       <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
       <AMOUNT>-{total:.2f}</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
       <LEDGERNAME>{escape(item_label)}</LEDGERNAME>
       <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
       <AMOUNT>{base:.2f}</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
       <LEDGERNAME>GST</LEDGERNAME>
       <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
       <AMOUNT>{gst:.2f}</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
     </VOUCHER>
    </TALLYMESSAGE>
   </REQUESTDATA>
  </IMPORTDATA>
 </BODY>
</ENVELOPE>"""


def _connection_out(connection: TallyConnection | None) -> TallyConnectionOut:
    if not connection:
        return TallyConnectionOut(connected=False, company_name=None, gateway_url=None, enabled=False)
    return TallyConnectionOut(connected=True, company_name=connection.company_name, gateway_url=connection.gateway_url, enabled=connection.enabled)


@router.get("/connection", response_model=TallyConnectionOut)
def get_tally_connection(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    return _connection_out(db.get(TallyConnection, entity.id))


@router.post("/connect", response_model=TallyConnectionOut)
def connect_tally(payload: TallyConnectRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """No credential to verify here -- unlike Zoho/Shopify/WooCommerce, there's nothing to test
    a connection against until an actual invoice push is attempted (Tally's gateway has no
    "are you there" ping this integration needs beyond the push itself, and a customer choosing
    the download-only path never sets gateway_url at all)."""
    entity = _resolve_entity(db, user)
    connection = db.get(TallyConnection, entity.id)
    if not connection:
        connection = TallyConnection(entity_id=entity.id)
        db.add(connection)
    connection.company_name = payload.company_name.strip()
    connection.gateway_url = payload.gateway_url.strip().rstrip("/") if payload.gateway_url and payload.gateway_url.strip() else None
    connection.enabled = True
    db.commit(); db.refresh(connection)
    return _connection_out(connection)


@router.delete("/connection")
def disconnect_tally(user: User = Depends(require_user), db: Session = Depends(get_db)):
    entity = _resolve_entity(db, user)
    connection = db.get(TallyConnection, entity.id)
    if not connection:
        raise HTTPException(status_code=404, detail="Tally export isn't set up.")
    db.delete(connection)
    db.commit()
    return {"disconnected": True}


def _get_invoice_and_org(db: Session, user: User, invoice_id: str) -> tuple[Invoice, Organization, TallyConnection]:
    entity = _resolve_entity(db, user)
    invoice = db.get(Invoice, invoice_id)
    if not invoice or invoice.entity_id != entity.id:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status != "issued":
        raise HTTPException(status_code=409, detail="This invoice hasn't been issued yet")
    connection = db.get(TallyConnection, entity.id)
    if not connection or not connection.enabled:
        raise HTTPException(status_code=422, detail="Set up Tally export first (Reports > Purchase Ledger > Tally Export).")
    organization = db.get(Organization, entity.organization_id)
    if not organization:
        raise HTTPException(status_code=422, detail="Could not resolve this invoice's organization")
    return invoice, organization, connection


@router.get("/invoices/{invoice_id}/export.xml")
def export_invoice_xml(invoice_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The universal path -- works for every customer regardless of network setup. The customer
    downloads this file and imports it themselves via Gateway of Tally > Import > Data."""
    invoice, organization, connection = _get_invoice_and_org(db, user, invoice_id)
    company = get_platform_company_info(db)
    xml_body = build_voucher_xml(invoice, organization, company.company_name, connection.company_name)
    return Response(
        content=xml_body, media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_number or invoice.id}.xml"'},
    )


@router.post("/invoices/{invoice_id}/push", response_model=TallyPushResponse)
def push_invoice_to_tally(invoice_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """The opt-in direct path -- only reachable if the customer has set a gateway_url (see
    TallyConnection's own docstring for why this can't be the default/only path)."""
    invoice, organization, connection = _get_invoice_and_org(db, user, invoice_id)
    if not connection.gateway_url:
        raise HTTPException(status_code=422, detail="No Tally gateway URL is configured -- download the XML instead and import it manually.")
    company = get_platform_company_info(db)
    xml_body = build_voucher_xml(invoice, organization, company.company_name, connection.company_name)
    try:
        response = requests.post(connection.gateway_url, data=xml_body.encode("utf-8"), headers={"Content-Type": "text/xml"}, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach your Tally gateway: {exc}") from exc
    if not response.ok:
        raise HTTPException(status_code=502, detail=f"Tally gateway returned HTTP {response.status_code}")
    # Tally's own gateway responds with an XML body containing <CREATED>/<ERRORS>/<LINEERROR>
    # counts, not an HTTP status code alone -- a 200 OK with an embedded <LINEERROR> is Tally's
    # way of saying the voucher was rejected (e.g. a referenced ledger doesn't exist yet), so this
    # must be treated as a real failure, not silently reported as success.
    body_text = response.text
    if "<LINEERROR>" in body_text or "<EXCEPTION" in body_text.upper():
        error_snippet = body_text[body_text.find("<LINEERROR>"):][:300] if "<LINEERROR>" in body_text else body_text[:300]
        raise HTTPException(status_code=422, detail=f"Tally rejected this voucher: {error_snippet}")
    logger.info("tally push succeeded invoice_id=%s entity_id=%s", invoice.id, invoice.entity_id)
    return TallyPushResponse(invoice_id=invoice.id, pushed=True)
