"""Every financial transaction produces an Invoice. `create_draft_invoice` always runs first;
`issue_invoice` is what assigns the invoice number, renders the PDF, writes it to disk (same
uploads_dir pattern as _save_upload in channels.py), and emails it to the organization's primary
contact. Auto-invoiced transactions (recharge, DLT fee, channel subscription) call both back to
back; an admin manual credit to someone else's entity may leave the draft unissued until an
admin approves it later."""
import html
import os
from datetime import datetime, timezone

from fpdf import FPDF
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .email_service import render_email, send_email
from .models import Entity, Invoice, Organization
from .services import PlatformCompanyInfo, get_platform_company_info, resolve_primary_user, sac_code_for_invoice_type
from .zoho_books import sync_invoice_to_zoho

INVOICE_TYPE_LABELS = {
    "wallet_recharge": "SMS Wallet Recharge",
    "dlt_fee": "DLT Registration Fee",
    "channel_subscription": "Channel Subscription Fee",
    "admin_credit": "Manual SMS Credit",
}


def _safe_text(value: str | None) -> str:
    """fpdf2's core Helvetica font only supports Latin-1 -- a business name, address, or
    admin-entered note containing anything outside that range (a regional-language name, an
    emoji, certain typographic quotes) would otherwise raise mid-render and crash invoice
    issuance for an already-captured payment. Replacing unencodable characters trades a few
    '?' glyphs for guaranteed-successful invoice generation."""
    if not value:
        return ""
    return value.encode("latin-1", errors="replace").decode("latin-1")


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")).strip()


def _three_digit_words(n: int) -> str:
    if n >= 100:
        rest = n % 100
        return f"{_ONES[n // 100]} Hundred" + (f" {_two_digit_words(rest)}" if rest else "")
    return _two_digit_words(n)


def _indian_number_words(n: int) -> str:
    """Indian numbering (lakh/crore groups), the way Tally itself renders the amount-in-words
    line -- plain Western thousand-grouping would misstate anything above 99,999."""
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 1_00_00_000)
    lakh, n = divmod(n, 1_00_000)
    thousand, hundred = divmod(n, 1000)
    if crore:
        parts.append(f"{_three_digit_words(crore)} Crore")
    if lakh:
        parts.append(f"{_three_digit_words(lakh)} Lakh")
    if thousand:
        parts.append(f"{_three_digit_words(thousand)} Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))
    return " ".join(parts)


def _amount_in_words(amount: float) -> str:
    rupees = int(amount)
    paise = round((amount - rupees) * 100)
    words = f"Rupees {_indian_number_words(rupees)}"
    if paise:
        words += f" and {_indian_number_words(paise)} Paise"
    return f"{words} Only"


def create_draft_invoice(db: Session, entity: Entity, type: str, base_amount: float, gst_amount: float, reference: str | None = None, notes: str | None = None, created_by_admin_id: str | None = None, credits_purchased: float | None = None, price_per_sms: float | None = None, mark_as_paid: bool = True) -> Invoice:
    invoice = Invoice(
        entity_id=entity.id,
        type=type,
        status="draft",
        base_amount=base_amount,
        gst_amount=gst_amount,
        total_amount=base_amount + gst_amount,
        credits_purchased=credits_purchased,
        price_per_sms=price_per_sms,
        reference=reference,
        notes=notes,
        created_by_admin_id=created_by_admin_id,
        zoho_mark_paid=mark_as_paid,
    )
    db.add(invoice)
    db.flush()
    return invoice


def _render_invoice_pdf(invoice: Invoice, entity: Entity, organization: Organization, company: PlatformCompanyInfo) -> bytes:
    """A Tally-style Indian tax invoice: bordered header/party/item/total blocks, CGST+SGST split
    (assumes intra-state supply -- there's no buyer-state field captured anywhere to determine
    IGST vs CGST/SGST), amount-in-words, and a signatory block, matching the layout every Indian
    business and accountant already recognizes from Tally/Zoho/ClearTax invoices."""
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    left, right = 12.0, 198.0
    width = right - left

    def hline(y: float) -> None:
        pdf.set_draw_color(90, 90, 90)
        pdf.set_line_width(0.3)
        pdf.line(left, y, right, y)

    def vline(x: float, y1: float, y2: float) -> None:
        pdf.set_draw_color(90, 90, 90)
        pdf.set_line_width(0.3)
        pdf.line(x, y1, x, y2)

    def labeled_line(x: float, w: float, label: str, value: str) -> None:
        pdf.set_x(x)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(28, 5.5, label)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(w - 28, 5.5, value, ln=True)
        pdf.set_x(x)

    # ---- Title ----
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(width, 9, "TAX INVOICE", align="C", ln=True)
    hline(pdf.get_y() + 1)
    pdf.ln(4)

    # ---- Seller (left) / invoice meta (right), split by a vertical rule ----
    section_top = pdf.get_y()
    mid = left + width * 0.58
    col_gap = 4

    pdf.set_xy(left, section_top)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(mid - left - col_gap, 6, _safe_text(company.company_name))
    pdf.set_font("Helvetica", "", 9)
    if company.company_address:
        pdf.set_x(left)
        pdf.multi_cell(mid - left - col_gap, 5, _safe_text(company.company_address))
    if company.company_phone:
        pdf.set_x(left)
        pdf.cell(mid - left - col_gap, 5, f"Phone: {_safe_text(company.company_phone)}", ln=True)
    if company.company_gstin:
        pdf.set_x(left)
        pdf.cell(mid - left - col_gap, 5, f"GSTIN: {company.company_gstin}", ln=True)
    if company.company_state:
        state_line = company.company_state + (f" ({company.company_state_code})" if company.company_state_code else "")
        pdf.set_x(left)
        pdf.cell(mid - left - col_gap, 5, f"State: {state_line}", ln=True)
    left_bottom = pdf.get_y()

    labeled_line(mid + col_gap, right - mid - col_gap, "Invoice No:", invoice.invoice_number or "-")
    labeled_line(mid + col_gap, right - mid - col_gap, "Invoice Date:", invoice.issued_at.strftime("%d-%b-%Y") if invoice.issued_at else "-")
    labeled_line(mid + col_gap, right - mid - col_gap, "Reference:", _safe_text(invoice.reference) or "-")
    right_bottom = pdf.get_y()

    section_bottom = max(left_bottom, right_bottom) + 2
    vline(mid, section_top - 1, section_bottom)
    pdf.set_y(section_bottom)
    hline(section_bottom)
    pdf.ln(4)

    # ---- Billed To ----
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(width, 5, "Billed To", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(width, 5, _safe_text(organization.name), ln=True)
    if organization.address:
        pdf.multi_cell(width, 5, _safe_text(organization.address))
    if organization.gstin:
        pdf.cell(width, 5, f"GSTIN: {organization.gstin}", ln=True)
    pdf.cell(width, 5, f"Entity: {_safe_text(entity.name)}", ln=True)
    buyer_bottom = pdf.get_y() + 2
    pdf.set_y(buyer_bottom)
    hline(buyer_bottom)
    pdf.ln(4)

    # ---- Item table ----
    table_top = pdf.get_y()
    col_sno, col_sac, col_amount = 12.0, 30.0, 45.0
    col_desc = width - col_sno - col_sac - col_amount

    pdf.set_fill_color(232, 232, 232)
    pdf.set_font("Helvetica", "B", 9)
    x = left
    for w, text in ((col_sno, "#"), (col_desc, "Description"), (col_sac, "SAC Code"), (col_amount, "Amount (Rs.)")):
        pdf.set_xy(x, table_top)
        pdf.cell(w, 7, text, border=1, align="C" if text != "Description" else "L", fill=True)
        x += w
    row_y = table_top + 7

    pdf.set_font("Helvetica", "", 9)
    x = left
    row_cells = ((col_sno, "1", "C"), (col_desc, INVOICE_TYPE_LABELS.get(invoice.type, invoice.type), "L"), (col_sac, sac_code_for_invoice_type(invoice.type), "C"), (col_amount, f"{float(invoice.base_amount):.2f}", "R"))
    for w, text, align in row_cells:
        pdf.set_xy(x, row_y)
        pdf.cell(w, 7, text, border=1, align=align)
        x += w
    pdf.set_y(row_y + 7)
    pdf.ln(4)

    # ---- Tax summary ----
    gst_amount = float(invoice.gst_amount)
    half_gst = gst_amount / 2
    summary_x = left + width - 85

    def summary_row(label: str, value: str, bold: bool = False) -> None:
        pdf.set_x(summary_x)
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        pdf.cell(45, 6, label)
        pdf.cell(40, 6, value, align="R", ln=True)

    summary_row("Taxable Value", f"Rs. {float(invoice.base_amount):.2f}")
    if gst_amount > 0:
        summary_row("CGST @ 9%", f"Rs. {half_gst:.2f}")
        summary_row("SGST @ 9%", f"Rs. {half_gst:.2f}")
    summary_row("Total", f"Rs. {float(invoice.total_amount):.2f}", bold=True)
    summary_bottom = pdf.get_y() + 2
    pdf.set_y(summary_bottom)
    hline(summary_bottom)
    pdf.ln(4)

    # ---- Amount in words ----
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(width, 5, "Amount Chargeable (in words)", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(width, 5, _amount_in_words(float(invoice.total_amount)))
    pdf.ln(2)

    if invoice.notes:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(width, 5, "Notes", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(width, 5, _safe_text(invoice.notes))
        pdf.ln(2)

    words_bottom = pdf.get_y()
    hline(words_bottom)
    pdf.ln(5)

    # ---- Declaration + signatory ----
    decl_y = pdf.get_y()
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(width - 60, 4.5, "This is a system-generated tax invoice and does not require a physical signature. Subject to reconciliation.")

    sig_x, sig_w = left + width - 55, 55.0
    pdf.set_xy(sig_x, decl_y)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(sig_w, 5, f"For {_safe_text(company.company_name)}", align="C")
    pdf.set_xy(sig_x, decl_y + 18)
    pdf.cell(sig_w, 5, "Authorized Signatory", align="C")

    bottom = max(pdf.get_y(), decl_y + 23) + 3
    hline(bottom)

    return bytes(pdf.output())


INTRO_LINES = {
    "wallet_recharge": "We've received your payment",
    "dlt_fee": "We've received your payment",
    "channel_subscription": "We've received your payment",
    "admin_credit": "Your account has been credited",
}


def issue_invoice(db: Session, invoice: Invoice) -> Invoice:
    """Zoho Books (if the organization has been linked -- see zoho_books.py) is the source of
    truth for the invoice document itself; Textzi's own fpdf2 rendering only ever runs as a
    fallback, so a customer is never left with literally no invoice while a Zoho-side issue gets
    retried later. Two emails go out: an immediate one the moment the charge/credit is recorded
    (before the Zoho round trip, which can take a few seconds), and the real invoice-with-PDF
    once it's ready."""
    if invoice.status == "issued":
        return invoice
    entity = db.get(Entity, invoice.entity_id)
    organization = db.get(Organization, entity.organization_id)

    # A Postgres sequence, not a count-then-increment query, so two invoices issued at the same
    # instant can never compute the same number -- nextval() is atomic regardless of concurrent
    # transactions. The year is cosmetic; uniqueness comes entirely from the sequence.
    year = datetime.now(timezone.utc).year
    seq_val = db.execute(text("SELECT nextval('invoice_number_seq')")).scalar()
    invoice.invoice_number = f"INV-{year}-{seq_val:06d}"
    invoice.status = "issued"
    invoice.issued_at = datetime.now(timezone.utc)
    db.commit()

    primary_user = resolve_primary_user(db, organization.id)
    if primary_user:
        send_email(
            db,
            to=primary_user.email,
            subject="Your Textzi invoice is on its way",
            html_body=render_email(
                INTRO_LINES.get(invoice.type, "Your invoice is being prepared"),
                f"<p>Hi {html.escape(primary_user.full_name)},</p>"
                f"<p>{INTRO_LINES.get(invoice.type, 'Your invoice is being prepared')} of "
                f"<b>Rs. {float(invoice.total_amount):.2f}</b> for {INVOICE_TYPE_LABELS.get(invoice.type, invoice.type)}. "
                f"Your invoice ({invoice.invoice_number}) will be emailed to you shortly.</p>",
            ),
        )

    pdf_bytes = sync_invoice_to_zoho(db, invoice, organization)
    if pdf_bytes is None:
        # Organization not yet linked to Zoho, Zoho unconfigured, or the sync failed (see
        # invoice.zoho_sync_status/_error) -- fall back to Textzi's own rendering so the customer
        # isn't left with no invoice at all while an admin links/retries the Zoho side later.
        pdf_bytes = _render_invoice_pdf(invoice, entity, organization, get_platform_company_info(db))

    directory = os.path.join(settings.uploads_dir, "invoices")
    os.makedirs(directory, exist_ok=True)
    pdf_path = os.path.join(directory, f"{invoice.id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)
    invoice.pdf_path = pdf_path
    db.commit()

    if primary_user:
        send_email(
            db,
            to=primary_user.email,
            subject=f"Textzi Invoice {invoice.invoice_number}",
            html_body=render_email(
                "Your invoice is ready",
                f"<p>Hi {html.escape(primary_user.full_name)},</p>"
                f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"margin:16px 0; width:100%;\">"
                f"<tr><td style=\"padding:6px 0; color:#6a6a6a;\">Invoice number</td><td style=\"padding:6px 0; text-align:right;\"><b>{invoice.invoice_number}</b></td></tr>"
                f"<tr><td style=\"padding:6px 0; color:#6a6a6a;\">{INVOICE_TYPE_LABELS.get(invoice.type, invoice.type)}</td><td style=\"padding:6px 0; text-align:right;\"><b>Rs. {float(invoice.total_amount):.2f}</b></td></tr>"
                f"</table>"
                f"<p>Your invoice is attached to this email as a PDF. Thank you for using Textzi.</p>",
            ),
            attachment_bytes=pdf_bytes,
            attachment_filename=f"{invoice.invoice_number}.pdf",
        )
    return invoice
