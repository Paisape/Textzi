"""ERPNext (self-hosted Frappe) is the source of truth for the invoice DOCUMENT itself -- every
issued invoice creates (or reuses) a Customer, ensures the mapped Item exists, creates a Sales
Invoice, and fetches the rendered PDF back, all via the Frappe REST API. Textzi's own fpdf2
rendering (invoicing.py's _render_invoice_pdf) only ever runs as a fallback -- when ERPNext isn't
configured at all, or when any step of this chain fails -- so a customer is never left with no
invoice while a failure gets retried later (admin.py's retry endpoint calls the exact same
sync_invoice_to_erpnext used here). Every call is logged to ErpNextApiCallLog, success or
failure, so an admin can see exactly what happened without digging through server logs."""
import hashlib
import json
import logging
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import ErpNextApiCallLog, Invoice, Organization, PlatformErpNextSettings
from .security import decrypt_secret
from .services import GST_RATE, GST_SAC_CODE

logger = logging.getLogger("textzi.erpnext")

ITEM_CODE_FIELDS = {
    "wallet_recharge": "item_code_wallet_recharge",
    "dlt_fee": "item_code_dlt_fee",
    "channel_subscription": "item_code_channel_subscription",
    "admin_credit": "item_code_admin_credit",
}
ITEM_LABELS = {
    "wallet_recharge": "SMS Wallet Recharge",
    "dlt_fee": "DLT Registration Fee",
    "channel_subscription": "Channel Subscription Fee",
    "admin_credit": "Manual SMS Credit",
}


class ErpNextCallError(Exception):
    """Raised by _request/_fetch_invoice_pdf on any non-2xx response or connection failure --
    already logged to ErpNextApiCallLog by the time it's raised."""


def get_erpnext_settings(db: Session) -> PlatformErpNextSettings | None:
    row = db.get(PlatformErpNextSettings, "platform")
    if not row or not row.base_url or not row.api_key or not row.api_secret_encrypted or not row.company:
        return None
    return row


def _auth_header(settings_row: PlatformErpNextSettings) -> str:
    return f"token {settings_row.api_key}:{decrypt_secret(settings_row.api_secret_encrypted)}"


def _log(db: Session, invoice_id: str | None, method: str, path: str, status: str, status_code: int | None, error: str | None) -> None:
    db.add(ErpNextApiCallLog(invoice_id=invoice_id, method=method, path=path, status=status, status_code=status_code, error=error[:500] if error else None))
    db.commit()


def _request(db: Session, settings_row: PlatformErpNextSettings, method: str, path: str, invoice_id: str | None, body: dict | None = None) -> dict:
    # Frappe doctype names routinely contain spaces ("Sales Invoice") -- http.client rejects a
    # raw space outright, so the path needs escaping regardless of which resource this is for.
    url = f"{settings_row.base_url.rstrip('/')}{quote(path)}"
    # Some self-hosted ERPNext instances sit behind Cloudflare (or similar) with bot-detection
    # rules that reject requests carrying Python's default User-Agent outright -- a real,
    # confirmed failure mode here, not hypothetical. A descriptive UA is enough to clear that
    # specific rule; it can't spoof deeper fingerprinting, so a persistent block still needs an
    # allow-rule on the ERPNext side for this server's own IP or this UA string.
    headers = {
        "Authorization": _auth_header(settings_row), "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "Textzi-ERPNext-Integration/1.0",
    }
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())
        _log(db, invoice_id, method, path, "success", response.status, None)
        return result
    except HTTPError as exc:
        try:
            error_body = exc.read().decode(errors="replace")[:400]
        except OSError:
            error_body = ""
        message = f"HTTP {exc.code}: {error_body}" if error_body else f"HTTP {exc.code}"
        _log(db, invoice_id, method, path, "failed", exc.code, message)
        raise ErpNextCallError(message) from exc
    except Exception as exc:  # noqa: BLE001 -- must never leak an unanticipated exception type
        # past this boundary; see this module's own docstring.
        _log(db, invoice_id, method, path, "failed", None, str(exc))
        raise ErpNextCallError(str(exc)) from exc


def _get_resource(db: Session, settings_row: PlatformErpNextSettings, doctype: str, name: str, invoice_id: str | None) -> dict | None:
    """None if the resource doesn't exist (404) -- any other failure still raises."""
    try:
        return _request(db, settings_row, "GET", f"/api/resource/{doctype}/{name}", invoice_id)
    except ErpNextCallError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise


def _ensure_customer(db: Session, settings_row: PlatformErpNextSettings, organization: Organization, invoice_id: str) -> str:
    """Returns the ERPNext Customer doctype name for this organization, creating one the first
    time and remembering it on the Organization row so every later invoice reuses it."""
    if organization.erpnext_customer_name:
        return organization.erpnext_customer_name
    result = _request(db, settings_row, "POST", "/api/resource/Customer", invoice_id, {
        "customer_name": organization.name,
        "tax_id": organization.gstin or None,
        "customer_group": settings_row.customer_group,
        "territory": settings_row.territory,
    })
    customer_name = result["data"]["name"]
    organization.erpnext_customer_name = customer_name
    db.commit()
    return customer_name


def _ensure_item(db: Session, settings_row: PlatformErpNextSettings, item_code: str, invoice_type: str, invoice_id: str) -> str:
    """Auto-creates the mapped Item the first time it's referenced -- the admin only has to pick
    a code in the settings page, not go create it in ERPNext by hand first."""
    if _get_resource(db, settings_row, "Item", item_code, invoice_id):
        return item_code
    _request(db, settings_row, "POST", "/api/resource/Item", invoice_id, {
        "item_code": item_code,
        "item_name": ITEM_LABELS.get(invoice_type, item_code),
        "item_group": "Services",
        "stock_uom": "Nos",
        "is_stock_item": 0,
        "include_item_in_manufacturing": 0,
        # Required once an India-compliance app (GST) is installed -- same SAC code Textzi's own
        # PDF invoice already prints for every line item (invoicing.py's GST_SAC_CODE).
        "gst_hsn_code": GST_SAC_CODE,
    })
    return item_code


def _fetch_invoice_pdf(db: Session, settings_row: PlatformErpNextSettings, invoice_name: str, invoice_id: str) -> bytes:
    path = "/api/method/frappe.utils.print_format.download_pdf"
    query = f"?doctype={quote('Sales Invoice')}&name={quote(invoice_name)}"
    if settings_row.print_format:
        query += f"&format={quote(settings_row.print_format)}"
    url = f"{settings_row.base_url.rstrip('/')}{path}{query}"
    headers = {"Authorization": _auth_header(settings_row), "User-Agent": "Textzi-ERPNext-Integration/1.0"}
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            pdf_bytes = response.read()
        _log(db, invoice_id, "GET", path, "success", response.status, None)
        return pdf_bytes
    except HTTPError as exc:
        try:
            error_body = exc.read().decode(errors="replace")[:400]
        except OSError:
            error_body = ""
        message = f"HTTP {exc.code}: {error_body}" if error_body else f"HTTP {exc.code}"
        _log(db, invoice_id, "GET", path, "failed", exc.code, message)
        raise ErpNextCallError(message) from exc
    except Exception as exc:  # noqa: BLE001
        _log(db, invoice_id, "GET", path, "failed", None, str(exc))
        raise ErpNextCallError(str(exc)) from exc


def _submit_if_needed(db: Session, settings_row: PlatformErpNextSettings, current_docstatus: int, invoice_name: str, invoice_id: str) -> None:
    """A freshly-created Sales Invoice sits at docstatus=0 (Draft), which is not a legally final
    GST document -- it must be submitted (docstatus=1) to actually count. This was previously
    missing entirely (create, then straight to PDF fetch), which live testing caught: every
    invoice was being left in Draft forever. No-op if already submitted, so this is safe to call
    from both the fresh-create path and a retry against an already-existing invoice."""
    if current_docstatus == 1:
        return
    _request(db, settings_row, "PUT", f"/api/resource/Sales Invoice/{invoice_name}", invoice_id, {"docstatus": 1})


def _advisory_lock_key(invoice_id: str) -> int:
    """Deterministically maps an invoice id to a signed 64-bit int for pg_advisory_lock, so
    concurrent calls for the SAME invoice serialize on the SAME key."""
    return int.from_bytes(hashlib.sha256(invoice_id.encode()).digest()[:8], "big", signed=True)


def sync_invoice_to_erpnext(db: Session, invoice: Invoice, organization: Organization) -> bytes | None:
    """The single entry point both issue_invoice() and the admin retry endpoint call. Returns the
    fetched PDF bytes on success (and leaves invoice.erpnext_sync_status="synced"), or None on
    any failure (leaving invoice.erpnext_sync_status="failed" with erpnext_sync_error set) --
    never raises, so a caller never needs its own try/except around this."""
    # A session-level Postgres advisory lock, not a `SELECT ... FOR UPDATE` row lock -- this
    # function calls db.commit() several times internally (inside _ensure_customer/_ensure_item,
    # after recording erpnext_invoice_name), and a row lock is released by the FIRST of those
    # intermediate commits, not held until this function returns -- confirmed live: two concurrent
    # calls under a row-lock version of this fix still each created their own Sales Invoice,
    # because the lock was already gone (released inside _ensure_customer's own commit) long
    # before erpnext_invoice_name ever got set. An advisory lock survives intermediate commits on
    # the same connection and is only released in the `finally` below, which is what actually
    # serializes two concurrent retries (or a retry racing issue_invoice) on the same invoice.
    lock_key = _advisory_lock_key(invoice.id)
    db.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
    try:
        # Pick up erpnext_invoice_name (or any other field) as it stands right now -- another
        # call may have committed changes to this same row while we were blocked above.
        db.refresh(invoice)

        settings_row = get_erpnext_settings(db)
        if not settings_row:
            raise ErpNextCallError("ERPNext is not configured")

        # A retry after a failure must never re-create the Sales Invoice -- it already exists in
        # ERPNext at this point (erpnext_invoice_name was committed the moment creation succeeded,
        # specifically so a retry can tell). But the ORIGINAL failure could have been the
        # total-mismatch check below, not just the PDF fetch -- so this branch must re-verify the
        # total against ERPNext's current state every time, not just skip straight to the PDF.
        # Blindly trusting "erpnext_invoice_name is set" == "the invoice is correct" would let an
        # admin click Retry on a still-wrong (e.g. still auto-taxed) invoice and have it marked
        # "synced" while quietly handing the customer a PDF with the wrong total.
        if invoice.erpnext_invoice_name:
            existing = _get_resource(db, settings_row, "Sales Invoice", invoice.erpnext_invoice_name, invoice.id)
            if existing is None:
                raise ErpNextCallError(
                    f"ERPNext Sales Invoice {invoice.erpnext_invoice_name} no longer exists there -- "
                    f"was it deleted or cancelled? This needs manual investigation before retrying.",
                )
            existing_data = existing.get("data", {})
            erpnext_total = float(existing_data.get("grand_total", 0))
            expected_total = float(invoice.total_amount)
            if abs(erpnext_total - expected_total) > 0.005:
                raise ErpNextCallError(
                    f"ERPNext still records a different total (Rs {erpnext_total:.2f}) than what was "
                    f"actually charged (Rs {expected_total:.2f}) for invoice {invoice.erpnext_invoice_name} "
                    f"-- fix the Sales Invoice in ERPNext directly (its tax template/amount) before retrying.",
                )
            _submit_if_needed(db, settings_row, int(existing_data.get("docstatus", 0)), invoice.erpnext_invoice_name, invoice.id)
            pdf_bytes = _fetch_invoice_pdf(db, settings_row, invoice.erpnext_invoice_name, invoice.id)
            invoice.erpnext_sync_status = "synced"
            invoice.erpnext_sync_error = None
            db.commit()
            return pdf_bytes

        item_code_field = ITEM_CODE_FIELDS.get(invoice.type)
        item_code = getattr(settings_row, item_code_field, None) if item_code_field else None
        if not item_code:
            raise ErpNextCallError(f"No ERPNext item code configured for invoice type '{invoice.type}'")

        customer_name = _ensure_customer(db, settings_row, organization, invoice.id)
        _ensure_item(db, settings_row, item_code, invoice.type, invoice.id)

        taxes = []
        if float(invoice.gst_amount) > 0:
            if not settings_row.cgst_account_head or not settings_row.sgst_account_head:
                raise ErpNextCallError("GST amount is non-zero but CGST/SGST account heads are not configured")
            # "Actual" (a fixed rupee amount, not a rate) was tried first and confirmed live to be
            # rejected outright on a real india_compliance-enabled site: "Charge Type is set to
            # Actual. However, this would not compute item taxes, and your further reporting will
            # be affected" -- india_compliance requires a per-item computed tax detail (rate-based)
            # for its own GST reporting (GSTR-1 etc.), which "Actual" skips entirely. "On Net Total"
            # with a percentage rate is what actually works, confirmed live: on Textzi's single-line
            # invoice (always exactly one item), this computes identically to Textzi's own flat
            # GST_RATE split in half per side -- the total-mismatch check right after creation is
            # what actually guards against any drift, not the tax line's own construction here.
            half_rate_percent = round(GST_RATE / 2 * 100, 4)
            taxes = [
                {"charge_type": "On Net Total", "account_head": settings_row.cgst_account_head, "rate": half_rate_percent, "description": "CGST"},
                {"charge_type": "On Net Total", "account_head": settings_row.sgst_account_head, "rate": half_rate_percent, "description": "SGST"},
            ]
        payload = {
            "customer": customer_name,
            "company": settings_row.company,
            "items": [{"item_code": item_code, "qty": 1, "rate": float(invoice.base_amount)}],
            "taxes": taxes,
            # Explicitly empty -- otherwise ERPNext/india_compliance can silently auto-apply a
            # default tax template (confirmed live: a customer with no taxes sent still came back
            # with 18% GST added). The verification right after this call is the real safeguard;
            # this is just the first line of defense.
            "taxes_and_charges": "",
            "remarks": f"Textzi invoice {invoice.invoice_number}" if invoice.invoice_number else f"Textzi invoice {invoice.id}",
        }
        if settings_row.sales_invoice_naming_series:
            payload["naming_series"] = settings_row.sales_invoice_naming_series
        result = _request(db, settings_row, "POST", "/api/resource/Sales Invoice", invoice.id, payload)
        erpnext_name = result["data"]["name"]
        # Committed immediately -- before the total-mismatch check and the PDF fetch, both of
        # which can still fail on their own -- so a retry never risks creating a *second* Sales
        # Invoice for the same Textzi invoice, even one that's already known to be wrong (see
        # the mismatch check right below: that invoice still exists in ERPNext, just flagged).
        invoice.erpnext_invoice_name = erpnext_name
        db.commit()

        # Never trust that "creation succeeded" means "the amount matches" -- ERPNext computes
        # its own grand_total server-side (auto-tax templates, rounding rules, ...) independent of
        # what was sent. If it doesn't match what Textzi actually charged the customer, that's a
        # sync failure needing admin attention -- and the ERPNext invoice just created is WRONG
        # and needs manual correction there, not a silently-accepted mismatch in the books.
        erpnext_total = float(result["data"].get("grand_total", 0))
        expected_total = float(invoice.total_amount)
        if abs(erpnext_total - expected_total) > 0.005:
            raise ErpNextCallError(
                f"ERPNext recorded a different total (Rs {erpnext_total:.2f}) than what was actually "
                f"charged (Rs {expected_total:.2f}) for invoice {erpnext_name} -- likely an auto-applied "
                f"tax template. That ERPNext invoice needs manual correction; check the default Sales "
                f"Taxes and Charges Template for this customer/company.",
            )

        _submit_if_needed(db, settings_row, int(result["data"].get("docstatus", 0)), erpnext_name, invoice.id)
        pdf_bytes = _fetch_invoice_pdf(db, settings_row, erpnext_name, invoice.id)
        invoice.erpnext_sync_status = "synced"
        invoice.erpnext_sync_error = None
        db.commit()
        return pdf_bytes
    except ErpNextCallError as exc:
        invoice.erpnext_sync_status = "failed"
        invoice.erpnext_sync_error = str(exc)[:500]
        db.commit()
        logger.warning("erpnext sync failed invoice_id=%s error=%s", invoice.id, exc)
        return None
    except Exception as exc:  # noqa: BLE001 -- must never leak past this boundary or crash the
        # caller (issue_invoice / the admin retry endpoint), same reasoning as _request's own
        # blanket catch. A 200 response that doesn't match the expected shape -- missing "data" or
        # "name", a non-numeric/null grand_total, an unexpected type anywhere this code assumes a
        # specific one -- is exactly as much "this sync attempt failed" as a network error or a
        # 4xx/5xx, and must degrade the same way: erpnext_sync_status="failed" with a real error
        # message, never an unhandled 500 while the call log still shows the underlying HTTP call
        # as a clean "success" (the crash happens in response-parsing code that runs after that
        # log line already recorded success, which is why this needs its own catch here rather
        # than relying on _request's).
        invoice.erpnext_sync_status = "failed"
        invoice.erpnext_sync_error = f"Unexpected error parsing ERPNext's response: {exc}"[:500]
        db.commit()
        logger.warning("erpnext sync failed (unexpected) invoice_id=%s error=%s", invoice.id, exc)
        return None
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
