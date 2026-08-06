"""Daily retention job -- runs both archiving steps in order (archiving.py has the actual logic).
Meant to be scheduled (cron/Coolify scheduled task) once a day; safe to run more often too, since
both steps are idempotent (ArchiveManifest tracks what's already been done, so re-running finds
nothing new to do).

Usage: python -m app.archive_jobs
"""
from .archiving import archive_to_local, promote_to_r2
from .database import SessionLocal


def run() -> None:
    db = SessionLocal()
    try:
        local_result = archive_to_local(db)
        print(f"local archive: {local_result}")
        r2_result = promote_to_r2(db)
        print(f"r2 promotion: {r2_result}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
