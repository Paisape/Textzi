from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./textzi.db"

    @field_validator("database_url")
    @classmethod
    def _normalize_postgres_scheme(cls, v: str) -> str:
        # SQLAlchemy only registers the dialect name "postgresql", not the shorter "postgres" --
        # many hosts/tools (Heroku-style conventions, some PaaS auto-generated connection strings)
        # emit "postgres://", which fails at create_engine() with a cryptic NoSuchModuleError
        # instead of anything mentioning the URL itself. Normalize both that and a bare
        # "postgresql://" (no driver) to the psycopg v3 driver this project actually installs.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v
    jwt_secret: str = "development-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 60
    web_origin: str = "http://localhost:5173"
    environment: str = "development"
    admin_bootstrap_key: str = "development-admin-key-change-me"
    worker_key: str = "development-worker-key-change-me"
    provider_secret_key: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # dev-only placeholder Fernet key; override in .env
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    uploads_dir: str = "/app/uploads"  # dev-mode local disk storage; move to real object storage (S3/Blob) in production
    # SMTP config lives in PlatformSmtpSettings (DB-backed, editable from the admin UI) instead
    # of here -- see email_service.py.
    trust_proxy_headers: bool = False  # only enable behind a reverse proxy that itself sets/overwrites X-Forwarded-For -- otherwise it's client-spoofable and defeats the API-key IP allow-list entirely
    # Fallback defaults only -- the admin-editable PlatformGeneralSettings table (see
    # services.get_platform_company_info) is the primary source for all of these; a value here is
    # only ever used until an admin sets it from Settings > Platform Settings > General. Seller-
    # side invoice details are blank by default (never a fake GSTIN); the invoice template only
    # prints a field if it's set.
    company_name: str = "Textzi"
    company_address: str = ""
    company_gstin: str = ""
    company_state: str = ""
    company_state_code: str = ""
    company_phone: str = ""
    support_email: str = "support@textzi.in"
    # Externally-reachable base URL of this API (e.g. "https://api.textzi.in"), used to build the
    # webhook URL providers call back with delivery reports. Blank by default (never guess a
    # deployment's real public domain) -- while blank (in both .env and PlatformGeneralSettings),
    # DR webhooks are simply not requested, same fail-open behavior as before this feature existed.
    public_api_base_url: str = ""
    # Shared-across-replicas request throttle for SMS send (services.enforce_rate_limit), backed
    # by the redis service docker-compose.yml already provisions -- per calling entity, since
    # that's the tenant/billing boundary a compromised or careless API key can hammer.
    redis_url: str = "redis://localhost:6379/0"
    sms_rate_limit_max_requests: int = 120
    sms_rate_limit_window_seconds: int = 60
    # Cold-tier archive retention windows (archiving.py) -- how long a Message stays in Postgres
    # with full detail before its heavy fields move to local gzip, and how long the local gzip
    # file lives before promotion to R2. R2 credentials themselves live in PlatformR2Settings
    # (DB-backed, admin-editable), not here -- same convention as PlatformSmtpSettings.
    archive_local_after_days: int = 7
    archive_r2_after_days: int = 30


settings = Settings()

if settings.environment != "development":
    # admin_bootstrap_key/worker_key also have a per-request guard (see admin.py's require_admin,
    # main.py's require_worker) that already rejects them while they still start with
    # "development-" -- but that guard only ever ran once a request came in, and only ever caught
    # the literal default/development- prefixed values, not a merely weak-but-different key an
    # admin typed in by hand. jwt_secret and provider_secret_key have no per-request guard at all,
    # since they're used far too pervasively (every JWT issue/verify; every
    # encrypt_secret/decrypt_secret call protecting provider credentials, SMTP passwords, 2FA TOTP
    # secrets, and encrypted message content) to gate at each call site. All four are printed in
    # this very file, so leaving any of them at its default (or merely too short to be a real
    # generated secret) in a real deployment is a complete authentication bypass (JWT_SECRET,
    # ADMIN_BOOTSTRAP_KEY, WORKER_KEY) or a complete break of every "encrypted" secret in the
    # system (PROVIDER_SECRET_KEY) -- fail at import time, before the app can serve a single
    # request, rather than relying on a per-request check that only catches the exact placeholder.
    MIN_SECRET_LENGTH = 20  # same floor as the API key length already enforced elsewhere (main.py)
    if settings.jwt_secret == "development-only-change-me" or len(settings.jwt_secret) < MIN_SECRET_LENGTH:
        raise RuntimeError("JWT_SECRET must be set to a real, unique secret (at least 20 characters) outside development (see .env.example)")
    if settings.provider_secret_key == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=":
        raise RuntimeError("PROVIDER_SECRET_KEY must be set to a real generated Fernet key outside development (see .env.example)")
    if settings.admin_bootstrap_key.startswith("development-") or len(settings.admin_bootstrap_key) < MIN_SECRET_LENGTH:
        raise RuntimeError("ADMIN_BOOTSTRAP_KEY must be set to a real, unique secret (at least 20 characters) outside development (see .env.example)")
    if settings.worker_key.startswith("development-") or len(settings.worker_key) < MIN_SECRET_LENGTH:
        raise RuntimeError("WORKER_KEY must be set to a real, unique secret (at least 20 characters) outside development (see .env.example)")
