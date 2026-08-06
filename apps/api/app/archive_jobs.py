"""Daily retention job -- runs both archiving steps in order (archiving.py has the actual logic).
Meant to be scheduled (cron/Coolify scheduled task) once a day; safe to run more often too, since
both steps are idempotent (ArchiveManifest tracks what's already been done, so re-running finds
nothing new to do).

That idempotency assumes runs don't actually overlap in time, though -- two genuinely concurrent
runs (a manual re-run while the scheduled one is still going, or a retry after a timeout) could
both see the same un-archived Message rows under READ COMMITTED and double-append them to the
same gzip file, or race on ArchiveManifest's (tier, period) unique constraint. A Postgres advisory
lock held for the whole run makes that impossible instead of trying to handle the race after the
fact: a run that can't acquire the lock just skips itself, and the next scheduled run picks up
whatever was missed (same principle as ArchiveManifest's idempotency -- nothing is lost by
skipping a run entirely).

Usage: python -m app.archive_jobs
"""
from sqlalchemy import text

from .archiving import archive_to_local, promote_to_r2
from .database import SessionLocal

# Arbitrary fixed key in Postgres's advisory-lock keyspace -- only meaningful in that it's unique
# to this job (no other code in the app should ever call pg_advisory_lock with this same value).
_ARCHIVE_JOB_LOCK_KEY = 8823001


def run() -> None:
    db = SessionLocal()
    try:
        acquired = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ARCHIVE_JOB_LOCK_KEY}).scalar()
        if not acquired:
            print("archive job already running elsewhere -- skipping this run")
            return
        try:
            local_result = archive_to_local(db)
            print(f"local archive: {local_result}")
            r2_result = promote_to_r2(db)
            print(f"r2 promotion: {r2_result}")
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ARCHIVE_JOB_LOCK_KEY})
    finally:
        db.close()


if __name__ == "__main__":
    run()
