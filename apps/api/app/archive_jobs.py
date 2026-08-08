"""Daily retention job -- runs both archiving steps in order (archiving.py has the actual logic).
Wired into main.py's lifespan to run automatically once a day (see main.py); also safe to invoke
manually via the admin "Run Now" button (admin.py's run_archive_now) or straight from the CLI.

Idempotency assumes runs don't actually overlap in time, though -- two genuinely concurrent runs
(a manual re-run while the scheduled one is still going, or a retry after a timeout) could both
see the same un-archived Message rows under READ COMMITTED and double-append them to the same
gzip file, or race on ArchiveManifest's (tier, period) unique constraint. A Postgres advisory lock
held for the whole run makes that impossible instead of trying to handle the race after the fact:
a run that can't acquire the lock just skips itself, and the next scheduled run picks up whatever
was missed (same principle as ArchiveManifest's idempotency -- nothing is lost by skipping a run
entirely).

Every attempt -- success or failure, for each of the two steps -- is recorded to ArchiveRunLog
(unlike ArchiveManifest, which only ever records a successful period-completion), so the admin
archive-status page can show whether the job is actually running and whether it's working.

Usage: python -m app.archive_jobs
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from .archiving import archive_to_local, promote_to_r2
from .database import SessionLocal
from .models import ArchiveRunLog

logger = logging.getLogger("textzi.archiving")

# Arbitrary fixed key in Postgres's advisory-lock keyspace -- only meaningful in that it's unique
# to this job (no other code in the app should ever call pg_advisory_lock with this same value).
_ARCHIVE_JOB_LOCK_KEY = 8823001


def _run_step(db: Session, job: str, fn) -> dict:
    started_at = datetime.now(timezone.utc)
    try:
        result = fn(db)
        db.add(ArchiveRunLog(
            job=job, status="success", records_processed=result.get("archived") or result.get("promoted") or 0,
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        db.commit()
        logger.info("%s archive step succeeded: %s", job, result)
        return result
    except Exception as exc:
        db.rollback()
        db.add(ArchiveRunLog(
            job=job, status="failed", records_processed=0, error=str(exc)[:2000],
            started_at=started_at, finished_at=datetime.now(timezone.utc),
        ))
        db.commit()
        logger.exception("%s archive step failed", job)
        return {"error": str(exc)}


def run(db: Session | None = None) -> dict:
    """db=None (the CLI/scheduler path) opens and closes its own session. Passed a session (the
    admin "Run Now" endpoint), reuses the caller's -- so ArchiveRunLog rows are visible to that
    same request's response without a round-trip."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        acquired = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ARCHIVE_JOB_LOCK_KEY}).scalar()
        if not acquired:
            logger.info("archive job already running elsewhere -- skipping this run")
            return {"skipped": True, "reason": "already running elsewhere"}
        try:
            local_result = _run_step(db, "local", archive_to_local)
            r2_result = _run_step(db, "r2", promote_to_r2)
            return {"local": local_result, "r2": r2_result}
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ARCHIVE_JOB_LOCK_KEY})
            db.commit()
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
