"""Three-tier retention for message/telemetry data (Message, DeliveryAttempt, ApiLog):

  0-7 days   -- live in Postgres, full detail (the "hot" tier every normal query hits).
  8-30 days  -- local disk, gzip+JSONL, FULL detail preserved (one file per calendar month,
                uploads_dir/archives/local/). The live rows lose their heavy JSON/text fields
                (nulled out) but the lightweight summary (status, credits, recipient, dates)
                stays in Postgres forever for fast billing/usage-history queries.
  31+ days   -- Cloudflare R2 (S3-compatible object storage), Parquet+zstd, TRIMMED to just the
                fields a customer report actually needs (drops the raw provider request/response
                telemetry, which is mostly identical boilerplate by this age and has little
                remaining value) -- deliberately much smaller than the local tier, since this is
                the tier meant to live indefinitely rather than get pruned further.

ArchiveManifest is the source of truth for "has this month been archived/promoted yet" (makes
both steps idempotent -- safe to re-run daily) and for read_archived_rows() below to know which
tier holds a given month's full raw telemetry, for cold-storage/support lookups. The customer-
facing report export (reports.py) never needs this -- it reads Postgres directly, since archiving
only clears heavy JSON fields and never deletes the Message/DeliveryAttempt/ApiLog rows.

Two entry points, meant to run as a daily job (see archive_jobs.py): archive_to_local() then
promote_to_r2(). R2 credentials are optional and DB-backed (PlatformR2Settings, editable from the
admin UI -- see platform_admin.py) -- promote_to_r2() is a no-op while unset, matching this
codebase's existing fail-open convention for optional third-party integrations (Razorpay, SMTP)."""
import gzip
import io
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ApiLog, ArchiveManifest, DeliveryAttempt, Message, PlatformR2Settings
from .security import decrypt_secret

LOCAL_ARCHIVE_DIR = os.path.join(settings.uploads_dir, "archives", "local")


def _month_period(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


def _serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _message_to_full_record(message: Message, attempts: list[DeliveryAttempt], api_log: ApiLog | None) -> dict:
    """Everything the live row held before archiving -- this is the one place all of a message's
    detail still exists once its Postgres row has been trimmed."""
    return {
        "message": {
            "id": message.id, "entity_id": message.entity_id, "template_id": message.template_id,
            "recipient": message.recipient, "rendered_body": message.rendered_body, "is_encrypted": message.is_encrypted,
            "status": message.status, "route": message.route, "credits_charged": message.credits_charged,
            "idempotency_key": message.idempotency_key,
            "request_payload": message.request_payload, "response_payload": message.response_payload,
            "created_at": _serialize_dt(message.created_at),
        },
        "delivery_attempts": [
            {
                "id": a.id, "route": a.route, "provider_message_id": a.provider_message_id, "status": a.status, "error": a.error,
                "delivery_status_code": a.delivery_status_code, "delivered_at": _serialize_dt(a.delivered_at),
                "request_payload": a.request_payload, "response_body": a.response_body, "webhook_payload": a.webhook_payload,
                "customer_webhook_url": a.customer_webhook_url, "customer_webhook_payload": a.customer_webhook_payload,
                "customer_webhook_status": a.customer_webhook_status, "customer_webhook_error": a.customer_webhook_error,
                "customer_webhook_sent_at": _serialize_dt(a.customer_webhook_sent_at), "created_at": _serialize_dt(a.created_at),
            }
            for a in attempts
        ],
        "api_log": None if not api_log else {
            "id": api_log.id, "endpoint": api_log.endpoint, "status_code": api_log.status_code, "latency_ms": api_log.latency_ms,
            "metadata_json": api_log.metadata_json, "ip_address": api_log.ip_address, "country": api_log.country,
            "user_agent": api_log.user_agent, "created_at": _serialize_dt(api_log.created_at),
        },
    }


def _full_record_to_trimmed(record: dict) -> dict:
    """The R2-tier shape: just what a customer report needs (recipient, body, status, delivery
    outcome, dates) -- drops the raw provider-facing request/response/webhook JSON and the
    api_log entirely, since that's internal debugging detail with little value this far out, and
    is the majority of the local tier's byte size."""
    m = record["message"]
    attempts = record["delivery_attempts"]
    last_attempt = attempts[-1] if attempts else None
    return {
        "message_id": m["id"], "entity_id": m["entity_id"], "recipient": m["recipient"], "rendered_body": m["rendered_body"],
        "status": m["status"], "route": m["route"], "credits_charged": m["credits_charged"],
        "delivery_status_code": last_attempt["delivery_status_code"] if last_attempt else None,
        "delivered_at": last_attempt["delivered_at"] if last_attempt else None,
        "delivery_error": last_attempt["error"] if last_attempt else None,
        "created_at": m["created_at"],
    }


def _local_archive_path(period: str) -> str:
    return os.path.join(LOCAL_ARCHIVE_DIR, f"messages-{period}.jsonl.gz")


ARCHIVE_BATCH_SIZE = 2000


def archive_to_local(db: Session) -> dict:
    """Step 1 of the daily job. Finds Message rows older than archive_local_after_days that
    haven't been archived yet, appends their full detail to the appropriate month's local gzip
    file, then nulls the heavy fields on the live rows (keeping the row itself for fast
    lightweight history/billing queries).

    Processes ARCHIVE_BATCH_SIZE messages at a time, committing after each batch, rather than one
    query + one giant transaction for the whole backlog -- on a database that's never run this
    job before (weeks/months of un-archived history), an unbounded version would hold every
    matching Message/DeliveryAttempt/ApiLog row (and their write locks) in memory for the entire
    run. Each batch's WHERE clause naturally excludes rows the previous batch already marked
    archived_at, so this is just a resumable loop, not a change in what ultimately gets archived."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.archive_local_after_days)
    os.makedirs(LOCAL_ARCHIVE_DIR, exist_ok=True)
    total_archived = 0
    periods_touched: set[str] = set()

    while True:
        messages = db.scalars(
            select(Message).where(Message.created_at < cutoff, Message.archived_at.is_(None)).order_by(Message.created_at).limit(ARCHIVE_BATCH_SIZE),
        ).all()
        if not messages:
            break

        message_ids = [m.id for m in messages]
        attempts_by_message: dict[str, list[DeliveryAttempt]] = defaultdict(list)
        for a in db.scalars(select(DeliveryAttempt).where(DeliveryAttempt.message_id.in_(message_ids)).order_by(DeliveryAttempt.created_at)).all():
            attempts_by_message[a.message_id].append(a)
        api_log_by_message: dict[str, ApiLog] = {
            l.message_id: l for l in db.scalars(select(ApiLog).where(ApiLog.message_id.in_(message_ids))).all() if l.message_id
        }

        by_period: dict[str, list[Message]] = defaultdict(list)
        for m in messages:
            by_period[_month_period(m.created_at)].append(m)

        now = datetime.now(timezone.utc)
        for period, period_messages in by_period.items():
            path = _local_archive_path(period)
            with gzip.open(path, "at", encoding="utf-8") as f:
                for m in period_messages:
                    record = _message_to_full_record(m, attempts_by_message.get(m.id, []), api_log_by_message.get(m.id))
                    f.write(json.dumps(record) + "\n")
            size = os.path.getsize(path)
            manifest = db.scalar(select(ArchiveManifest).where(ArchiveManifest.tier == "local", ArchiveManifest.period == period))
            if manifest:
                manifest.record_count += len(period_messages)
                manifest.size_bytes = size
            else:
                db.add(ArchiveManifest(tier="local", period=period, path=path, record_count=len(period_messages), size_bytes=size))
            for m in period_messages:
                m.request_payload = None
                m.response_payload = None
                m.archived_at = now
                for a in attempts_by_message.get(m.id, []):
                    a.request_payload = None
                    a.response_body = None
                    a.webhook_payload = None
                    a.customer_webhook_payload = None
                log = api_log_by_message.get(m.id)
                if log:
                    log.metadata_json = {}
                    log.user_agent = None
            periods_touched.add(period)
        db.commit()
        total_archived += len(messages)
        if len(messages) < ARCHIVE_BATCH_SIZE:
            break

    return {"archived": total_archived, "periods": sorted(periods_touched)}


def _r2_client(db: Session):
    """Credentials come from PlatformR2Settings (DB-backed, editable from the admin UI) rather
    than config.py -- same convention as PlatformSmtpSettings. Returns None (caller no-ops) while
    unconfigured."""
    row = db.get(PlatformR2Settings, "platform")
    if not (row and row.account_id and row.access_key_id and row.secret_access_key_encrypted and row.bucket_name):
        return None
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=f"https://{row.account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=row.access_key_id,
        aws_secret_access_key=decrypt_secret(row.secret_access_key_encrypted),
        region_name="auto",
    )


def promote_to_r2(db: Session) -> dict:
    """Step 2 of the daily job. Finds local-tier months old enough (archive_r2_after_days) that
    haven't been promoted yet, trims each record down to just what a report needs, writes a
    Parquet+zstd file, and uploads it to R2. The local gzip file is only deleted after a
    confirmed-successful upload -- never both missing at once. No-op (returns immediately) if R2
    isn't configured, so this is always safe to call from the daily job regardless of
    deployment/environment."""
    client = _r2_client(db)
    if not client:
        return {"promoted": 0, "reason": "R2 not configured"}
    bucket_name = db.get(PlatformR2Settings, "platform").bucket_name

    import pyarrow as pa
    import pyarrow.parquet as pq

    cutoff_period = _month_period(datetime.now(timezone.utc) - timedelta(days=settings.archive_r2_after_days))
    candidates = db.scalars(
        select(ArchiveManifest).where(ArchiveManifest.tier == "local", ArchiveManifest.period < cutoff_period),
    ).all()
    already_promoted = {
        m.period for m in db.scalars(select(ArchiveManifest).where(ArchiveManifest.tier == "r2")).all()
    }
    promoted = []
    for manifest in candidates:
        if manifest.period in already_promoted or not os.path.exists(manifest.path):
            continue
        trimmed_records = []
        with gzip.open(manifest.path, "rt", encoding="utf-8") as f:
            for line in f:
                trimmed_records.append(_full_record_to_trimmed(json.loads(line)))
        if not trimmed_records:
            continue

        table = pa.Table.from_pylist(trimmed_records)
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="zstd", compression_level=19)
        buffer.seek(0)
        object_key = f"archives/messages-{manifest.period}.parquet"
        client.put_object(Bucket=bucket_name, Key=object_key, Body=buffer.getvalue())

        db.add(ArchiveManifest(tier="r2", period=manifest.period, path=object_key, record_count=len(trimmed_records), size_bytes=len(buffer.getvalue())))
        db.commit()
        os.remove(manifest.path)  # only after the R2 upload + manifest commit above both succeeded
        promoted.append(manifest.period)
    return {"promoted": len(promoted), "periods": promoted}


def read_archived_rows(db: Session, entity_id: str, date_from: datetime, date_to: datetime) -> list[dict]:
    """Used by the reports export endpoint. Reads whichever archive tier(s) cover the requested
    range, filtering strictly to entity_id before returning anything -- the archive files
    themselves hold every customer's data mixed together, so this filtering must happen here,
    server-side, never left to the caller."""
    periods = set()
    cur = date_from.replace(day=1)
    while cur <= date_to:
        periods.add(_month_period(cur))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

    manifests = db.scalars(select(ArchiveManifest).where(ArchiveManifest.period.in_(periods))).all()
    by_period: dict[str, ArchiveManifest] = {}
    for m in manifests:
        # Prefer the local tier if (unexpectedly) both exist for the same period -- it has full
        # detail, R2's trimmed copy is the fallback only.
        if m.period not in by_period or (by_period[m.period].tier == "r2" and m.tier == "local"):
            by_period[m.period] = m

    results: list[dict] = []
    client = None
    for period, manifest in by_period.items():
        if manifest.tier == "local":
            if not os.path.exists(manifest.path):
                continue
            with gzip.open(manifest.path, "rt", encoding="utf-8") as f:
                for line in f:
                    record = json.loads(line)
                    m = record["message"]
                    if m["entity_id"] != entity_id:
                        continue
                    created_at = datetime.fromisoformat(m["created_at"])
                    if date_from <= created_at <= date_to:
                        results.append(_full_record_to_trimmed(record) | {"_tier": "local"})
        else:
            client = client or _r2_client(db)
            if not client:
                continue
            bucket_name = db.get(PlatformR2Settings, "platform").bucket_name
            import pyarrow.parquet as pq
            obj = client.get_object(Bucket=bucket_name, Key=manifest.path)
            table = pq.read_table(io.BytesIO(obj["Body"].read()))
            for row in table.to_pylist():
                if row["entity_id"] != entity_id:
                    continue
                created_at = datetime.fromisoformat(row["created_at"])
                if date_from <= created_at <= date_to:
                    results.append(row | {"_tier": "r2"})
    results.sort(key=lambda r: r["created_at"])
    return results
