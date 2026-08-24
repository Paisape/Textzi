"""City/country lookup for webchat visitor telemetry -- MaxMind GeoLite2 (local .mmdb file, no
per-request external call), not a third-party HTTP API: no latency added to chat-session-start,
and no visitor IP sent to a third party per session, matching this codebase's existing DPDP-
consent posture (Contact.consent_given_at's own docstring). Fully optional: if the database file
isn't present (no license key configured yet, or a fresh install before the first refresh job
runs), lookups just return (None, None) -- geo is a telemetry nicety, never something a chat
session's core function depends on."""
import logging
import threading

logger = logging.getLogger("textzi.geoip")

_DB_PATH = "/app/data/GeoLite2-City.mmdb"
_reader = None
_reader_lock = threading.Lock()
_load_attempted = False


def _get_reader():
    global _reader, _load_attempted
    if _load_attempted:
        return _reader
    with _reader_lock:
        if _load_attempted:
            return _reader
        _load_attempted = True
        try:
            import geoip2.database
            _reader = geoip2.database.Reader(_DB_PATH)
        except Exception:
            logger.info("geoip: GeoLite2 database not available at %s -- city/country lookup disabled", _DB_PATH)
            _reader = None
    return _reader


def lookup_geo(ip_address: str) -> tuple[str | None, str | None]:
    reader = _get_reader()
    if not reader:
        return None, None
    try:
        response = reader.city(ip_address)
        return response.country.name, response.city.name
    except Exception:
        return None, None
