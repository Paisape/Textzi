import hashlib
import ipaddress
import secrets
import socket
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlparse

import jwt
import pyotp
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from .config import settings

_password_hasher = PasswordHash.recommended()


def _reject_if_unsafe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise ValueError("Webhook URL cannot point at a private/internal address")


def assert_safe_webhook_url(url: str) -> None:
    """SSRF guard for customer-supplied webhook URLs (e.g. ChannelSettings.dr_webhook_url).
    Textzi's own backend makes the outbound request when relaying a delivery report, so without
    this a customer could point it at an internal service or a cloud metadata endpoint. A literal
    IP is checked directly; a hostname is resolved via DNS right now and every returned address is
    checked too -- this still doesn't defeat DNS rebinding (a hostname that resolves safely here
    but to a private address at actual request time), which is why webhooks.py calls this again
    immediately before every outbound relay, not just once at save time."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Webhook URL must use https://")
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "0.0.0.0"}:
        raise ValueError("Webhook URL cannot point at a local address")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # not a literal IP -- fall through to DNS resolution below
    else:
        _reject_if_unsafe_ip(ip)
        return
    try:
        resolved = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"Webhook URL hostname could not be resolved: {host}") from exc
    for family, _type, _proto, _canonname, sockaddr in resolved:
        _reject_if_unsafe_ip(ipaddress.ip_address(sockaddr[0]))


def hash_password(value: str) -> str:
    return _password_hasher.hash(value)


def verify_password(value: str, password_hash: str) -> bool:
    return _password_hasher.verify(value, password_hash)


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@lru_cache
def _fernet() -> Fernet:
    return Fernet(settings.provider_secret_key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def decrypt_recipient_lenient(value: str) -> str:
    """Message.recipient only started being encrypted (matching rendered_body) once this fix
    shipped -- existing rows with is_encrypted=True from before it still hold a genuine plaintext
    number, not a Fernet token, since encrypting them retroactively wasn't done. A value that
    isn't valid Fernet ciphertext is assumed to be exactly that: pre-existing plaintext, not an
    error."""
    try:
        return decrypt_secret(value)
    except InvalidToken:
        return value


def create_access_token(subject: str, extra_claims: dict | None = None, ttl_minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    claims = {"sub": subject, "iat": now, "exp": now + timedelta(minutes=ttl_minutes or settings.jwt_access_ttl_minutes), **(extra_claims or {})}
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="Textzi")


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_otp(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()
