"""Email provider boundary, mirroring providers.py's SMS shape: callers never depend on whether
sending is simulated (dev, no SMTP configured) or real (SmtpEmailProvider once an admin has
configured PlatformSmtpSettings) -- same pattern used for SimulatedSmsProvider vs
HttpsSmsProvider. Config is DB-backed (PlatformSmtpSettings, editable from the admin UI) rather
than `.env`, so every call needs a `db` session."""
import logging
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Protocol

from sqlalchemy.orm import Session

from .models import PlatformSmtpSettings
from .security import decrypt_secret

logger = logging.getLogger("textzi.email")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html_body: str
    attachment_bytes: bytes | None = None
    attachment_filename: str | None = None


@dataclass(frozen=True)
class EmailResult:
    accepted: bool
    error: str | None = None


class EmailProvider(Protocol):
    name: str

    def send(self, message: EmailMessage) -> EmailResult: ...


class SimulatedEmailProvider:
    """Local-only adapter; keeps development safe from accidentally emailing anyone."""
    name = "simulated"

    def send(self, message: EmailMessage) -> EmailResult:
        attachment_note = f" with attachment '{message.attachment_filename}'" if message.attachment_bytes else ""
        logger.info("simulated email to=%s subject=%r%s", message.to, message.subject, attachment_note)
        return EmailResult(accepted=True)


class SmtpEmailProvider:
    name = "smtp"

    def __init__(self, settings_row: PlatformSmtpSettings):
        self.settings_row = settings_row

    def send(self, message: EmailMessage) -> EmailResult:
        row = self.settings_row
        mime = MIMEMultipart()
        mime["From"] = row.from_address
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.attach(MIMEText(message.html_body, "html"))
        if message.attachment_bytes and message.attachment_filename:
            part = MIMEApplication(message.attachment_bytes, Name=message.attachment_filename)
            part["Content-Disposition"] = f'attachment; filename="{message.attachment_filename}"'
            mime.attach(part)
        try:
            with smtplib.SMTP(row.host, row.port, timeout=10) as server:
                if row.use_tls:
                    server.starttls()
                if row.username and row.password_encrypted:
                    server.login(row.username, decrypt_secret(row.password_encrypted))
                server.sendmail(row.from_address, [message.to], mime.as_string())
            return EmailResult(accepted=True)
        except (smtplib.SMTPException, OSError) as exc:
            return EmailResult(accepted=False, error=str(exc))


def email_provider(db: Session) -> EmailProvider:
    row = db.get(PlatformSmtpSettings, "platform")
    if row and row.host:
        return SmtpEmailProvider(row)
    return SimulatedEmailProvider()


_BRAND_ORANGE = "#F1600D"
_BRAND_ORANGE_DARK = "#D84F06"


def render_email(heading: str, body_html: str, cta_label: str | None = None, cta_url: str | None = None) -> str:
    """Wraps a caller's inner content in one consistent branded shell -- every outbound email
    (OTP codes, invites, invoices, welcome messages) was previously just a bare unstyled <p>
    fragment with no header, footer, or visual identity at all. Table-based layout and inline
    styles throughout, not a <style> block or flexbox/grid, since most email clients (Outlook
    especially) strip <style> tags and don't support modern CSS layout."""
    cta_html = ""
    if cta_label and cta_url:
        cta_html = f"""
        <tr>
          <td style="padding:8px 40px 32px 40px;">
            <a href="{cta_url}" style="display:inline-block; background:{_BRAND_ORANGE}; color:#ffffff; text-decoration:none; font-family:Arial,Helvetica,sans-serif; font-size:15px; font-weight:bold; padding:12px 28px; border-radius:6px;">{cta_label}</a>
          </td>
        </tr>"""
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0; padding:0; background:#f4f4f5;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5; padding:32px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff; border-radius:8px; overflow:hidden; font-family:Arial,Helvetica,sans-serif;">
          <tr>
            <td style="background:{_BRAND_ORANGE}; padding:20px 40px;">
              <span style="color:#ffffff; font-size:20px; font-weight:bold;">Textzi</span>
            </td>
          </tr>
          <tr>
            <td style="padding:32px 40px 8px 40px;">
              <h1 style="margin:0 0 16px 0; font-size:19px; color:#1a1a1a;">{heading}</h1>
              <div style="font-size:14px; line-height:1.6; color:#3a3a3a;">{body_html}</div>
            </td>
          </tr>
          {cta_html}
          <tr>
            <td style="padding:20px 40px; background:#fafafa; border-top:1px solid #ececec;">
              <span style="font-size:12px; color:#9a9a9a;">This is an automated message from Textzi &mdash; please don't reply directly to this email.</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_email(db: Session, to: str, subject: str, html_body: str, attachment_bytes: bytes | None = None, attachment_filename: str | None = None) -> EmailResult:
    return email_provider(db).send(EmailMessage(to=to, subject=subject, html_body=html_body, attachment_bytes=attachment_bytes, attachment_filename=attachment_filename))
