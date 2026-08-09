import hashlib
import hmac
import http.client
import ipaddress
import secrets
import socket
import ssl
import time
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


class _PinnedIPHTTPSConnection(http.client.HTTPSConnection):
    """Connects at the TCP layer to a specific, already-validated IP rather than letting the
    connection re-resolve the hostname itself -- while still sending the original hostname as SNI
    and verifying the server certificate against it, so this doesn't break normal TLS validation
    for the customer's real domain/cert. This is what actually closes the DNS-rebinding gap:
    resolving+validating a hostname's IPs and then connecting by hostname again (as urlopen/a
    normal HTTPSConnection does) leaves a window where DNS can answer differently the second time;
    pinning means the address that was checked is the address that gets connected to."""
    def __init__(self, pinned_ip: str, hostname: str, port: int, timeout: float):
        super().__init__(hostname, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        context = ssl.create_default_context()
        self.sock = context.wrap_socket(sock, server_hostname=self.host)


def open_safe_webhook_connection(url: str, timeout: float = 5) -> tuple[_PinnedIPHTTPSConnection, str]:
    """SSRF-safe outbound connection for a customer-supplied webhook URL (e.g.
    ChannelSettings.dr_webhook_url), for use right at relay time -- not a substitute for
    assert_safe_webhook_url, which still gates saving the URL in the first place. Resolves and
    validates the hostname exactly like assert_safe_webhook_url, but then hands back a connection
    already pinned to the specific IP that was validated (see _PinnedIPHTTPSConnection), so there
    is no gap between "this address was checked" and "this is the address actually connected to"
    for a hostname under attacker-controlled DNS to exploit. Caller is responsible for closing the
    returned connection."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Webhook URL must use https://")
    host = (parsed.hostname or "").lower()
    if not host or host in {"localhost", "0.0.0.0"}:
        raise ValueError("Webhook URL cannot point at a local address")
    port = parsed.port or 443
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(f"Webhook URL hostname could not be resolved: {host}") from exc
        pinned_ip = None
        for family, _type, _proto, _canonname, sockaddr in resolved:
            candidate = ipaddress.ip_address(sockaddr[0])
            _reject_if_unsafe_ip(candidate)
            if pinned_ip is None:
                pinned_ip = sockaddr[0]
    else:
        _reject_if_unsafe_ip(ip)
        pinned_ip = host
    conn = _PinnedIPHTTPSConnection(pinned_ip, host, port, timeout)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return conn, path


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


def verify_totp(secret: str, code: str, last_used_step: int | None = None) -> int | None:
    """Returns the matching 30-second time-step counter if `code` is a currently-valid TOTP code
    (allowing +-1 step of clock skew, same tolerance as before), or None if it doesn't match any
    step in that window. When last_used_step is given, a code whose matching step is <= it is
    also treated as invalid (returns None) -- otherwise a valid code stays usable for its whole
    ~90-second window, so anyone who observes it once (shoulder-surfing, a log line, a proxy) can
    replay it for a second sensitive action (e.g. login, then immediately step-up 2FA) within that
    window. Callers should persist the returned step back onto last_used_step after a success."""
    totp = pyotp.TOTP(secret)
    current_step = int(time.time() // totp.interval)
    for offset in (-1, 0, 1):
        step = current_step + offset
        if hmac.compare_digest(totp.at(step * totp.interval), code):
            if last_used_step is not None and step <= last_used_step:
                return None
            return step
    return None


def generate_otp(length: int = 6) -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


# Excludes visually ambiguous characters (0/O, 1/I/L) since these are hand-typed from a printed/
# saved list, unlike a TOTP code that's copied from an app.
_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(_RECOVERY_CODE_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def normalize_recovery_code(code: str) -> str:
    # Case- and formatting-insensitive lookup -- a user retyping "ab3d9-xk2p7" or "AB3D9 XK2P7"
    # should match the same stored hash as the canonical "AB3D9-XK2P7" it was shown as.
    return code.strip().upper().replace("-", "").replace(" ", "")


def hash_otp(code: str) -> str:
    # A 6-digit numeric code is only 10^6 possible values -- plain SHA-256 would let anyone who
    # ever saw a code_hash column (a DB backup, etc.) recover every code instantly via a
    # precomputed table. Keying with jwt_secret (already a required, unique-per-deployment,
    # never-exposed secret -- see config.py's production fail-hard check) makes that
    # precomputation infeasible without also already holding the ability to forge JWTs.
    return hmac.new(settings.jwt_secret.encode(), code.encode(), hashlib.sha256).hexdigest()
