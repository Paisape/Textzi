from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./textzi.db"
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


settings = Settings()

if settings.environment != "development":
    # admin_bootstrap_key/worker_key already refuse to authenticate anything while left at their
    # default (see admin.py's require_admin, main.py's require_worker) -- jwt_secret and
    # provider_secret_key have no equivalent per-request guard since they're used far too
    # pervasively (every JWT issue/verify; every encrypt_secret/decrypt_secret call protecting
    # provider credentials, SMTP passwords, 2FA TOTP secrets, and encrypted message content) to
    # gate at each call site. Both are printed in this very file, so leaving either one at its
    # default in a real deployment is a complete authentication bypass (JWT_SECRET) or a complete
    # break of every "encrypted" secret in the system (PROVIDER_SECRET_KEY) -- fail at import
    # time, before the app can serve a single request, rather than silently running compromised.
    if settings.jwt_secret == "development-only-change-me":
        raise RuntimeError("JWT_SECRET must be set to a real, unique secret outside development (see .env.example)")
    if settings.provider_secret_key == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=":
        raise RuntimeError("PROVIDER_SECRET_KEY must be set to a real generated Fernet key outside development (see .env.example)")
