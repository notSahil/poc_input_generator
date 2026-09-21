"""SQLite-backed persistent job queue, atomic locking, checkpointing, and notifications.

Guarantees restart resilience across systemd/server restarts, prevents conflicting concurrent
uploads, and provides environment-scoped in-app notifications.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from config import settings

logger = logging.getLogger(__name__)


def _get_db_path(db_path: Path | None = None) -> Path:
    if db_path is not None:
        return db_path
    path = settings.JOBS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_db(db_path: Path | None = None):
    """Context manager for SQLite database connection with WAL mode and row factory."""
    target_path = _get_db_path(db_path)
    is_memory = str(target_path) == ":memory:" or ":memory:" in str(target_path)
    conn = sqlite3.connect(
        str(target_path),
        timeout=10.0,
        isolation_level="DEFERRED",
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    try:
        if not is_memory:
            conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    """Initialize database tables and indexes if they do not exist. Idempotent."""
    with get_db(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id                  TEXT PRIMARY KEY,
            run_dir             TEXT NOT NULL,
            report_name         TEXT NOT NULL,
            profile             TEXT DEFAULT 'sandbox',
            target_object       TEXT,
            engine              TEXT DEFAULT 'composite',
            batch_size          INTEGER DEFAULT 15,
            is_rollback         INTEGER DEFAULT 0,
            status              TEXT NOT NULL DEFAULT 'QUEUED',
            total_records       INTEGER DEFAULT 0,
            processed           INTEGER DEFAULT 0,
            successful          INTEGER DEFAULT 0,
            failed              INTEGER DEFAULT 0,
            current_chunk       INTEGER DEFAULT 0,
            total_chunks        INTEGER DEFAULT 0,
            checkpoint_json     TEXT,
            error_summary       TEXT,
            retry_count         INTEGER DEFAULT 0,
            triggered_by        TEXT DEFAULT 'manual',
            schedule_id         TEXT,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            completed_at        TEXT
        );

        CREATE TABLE IF NOT EXISTS job_locks (
            resource_key        TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL,
            acquired_at         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT,
            profile             TEXT NOT NULL,
            title               TEXT NOT NULL,
            message             TEXT NOT NULL,
            notification_type   TEXT DEFAULT 'INFO',
            metadata_json       TEXT,
            is_read             INTEGER DEFAULT 0,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS schedules (
            id                  TEXT PRIMARY KEY,
            name                TEXT NOT NULL UNIQUE,
            report_name         TEXT NOT NULL,
            profile             TEXT NOT NULL DEFAULT 'sandbox',
            schedule_type       TEXT NOT NULL DEFAULT 'recurring',
            frequency           TEXT,
            cron_expression     TEXT,
            run_at_time         TEXT,
            run_on_day          TEXT,
            one_off_datetime    TEXT,
            execution_mode      TEXT DEFAULT 'reconcile_only',
            auto_push_confirmed INTEGER DEFAULT 0,
            batch_size          INTEGER DEFAULT 15,
            is_active           INTEGER DEFAULT 1,
            last_run_at         TEXT,
            last_run_status     TEXT,
            last_run_id         TEXT,
            next_run_at         TEXT NOT NULL,
            total_runs          INTEGER DEFAULT 0,
            consecutive_failures INTEGER DEFAULT 0,
            max_retries         INTEGER DEFAULT 3,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_schedule_id ON jobs(schedule_id);
        CREATE INDEX IF NOT EXISTS idx_notifications_profile ON notifications(profile, is_read);
        CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON schedules(is_active, next_run_at);
        """)
    logger.debug("Persistent job store initialized successfully.")


# ==============================================================================
# JOB LIFECYCLE & CHECKPOINTING
# ==============================================================================

def create_job(
    *,
    run_dir: Path | str,
    report_name: str,
    profile: str = "sandbox",
    target_object: str | None = None,
    engine: str = "composite",
    batch_size: int = 15,
    is_rollback: bool = False,
    triggered_by: str = "manual",
    schedule_id: str | None = None,
    total_records: int = 0,
    db_path: Path | None = None,
) -> str:
    """Create a new job entry in QUEUED state. Returns the UUID job_id."""
    job_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, run_dir, report_name, profile, target_object, engine,
                batch_size, is_rollback, status, total_records,
                triggered_by, schedule_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(run_dir),
                report_name,
                profile,
                target_object,
                engine,
                batch_size,
                1 if is_rollback else 0,
                total_records,
                triggered_by,
                schedule_id,
                now_iso,
                now_iso,
            ),
        )
    logger.info("Created persistent job %s for %s (%s)", job_id, report_name, profile)
    return job_id


def mark_job_running(job_id: str, total_records: int | None = None, db_path: Path | None = None) -> None:
    """Transition job status to RUNNING."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        if total_records is not None:
            conn.execute(
                "UPDATE jobs SET status = 'RUNNING', total_records = ?, updated_at = ? WHERE id = ?",
                (total_records, now_iso, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET status = 'RUNNING', updated_at = ? WHERE id = ?",
                (now_iso, job_id),
            )


def update_job_progress(
    job_id: str,
    *,
    processed: int,
    successful: int,
    failed: int,
    current_chunk: int,
    total_chunks: int,
    checkpoint_json: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Update in-flight job progress metrics and checkpoint data."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs SET
                processed = ?,
                successful = ?,
                failed = ?,
                current_chunk = ?,
                total_chunks = ?,
                checkpoint_json = COALESCE(?, checkpoint_json),
                updated_at = ?
            WHERE id = ?
            """,
            (processed, successful, failed, current_chunk, total_chunks, checkpoint_json, now_iso, job_id),
        )


def complete_job(
    job_id: str,
    status: str,
    *,
    error_summary: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Mark a job as terminal (COMPLETED, COMPLETED_WITH_ERRORS, FAILED, CANCELLED)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs SET
                status = ?,
                error_summary = ?,
                completed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, error_summary, now_iso, now_iso, job_id),
        )


def get_job(job_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Retrieve full job dictionary by ID."""
    with get_db(db_path) as conn:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_active_jobs(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Retrieve all jobs in QUEUED or RUNNING status."""
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('QUEUED', 'RUNNING') ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def update_job(
    job_id: str,
    db_path: Path | None = None,
    **updates: Any,
) -> None:
    """Update arbitrary fields of an existing job record."""
    if not updates:
        return
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    cols = []
    vals = []
    for k, v in updates.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(job_id)

    with get_db(db_path) as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", tuple(vals))


def mark_interrupted_on_startup(db_path: Path | None = None) -> int:
    """Detect orphaned RUNNING jobs left over from server restart and mark them INTERRUPTED.

    Also clears any stale locks and synchronizes ingest_progress.json on disk.
    Returns count of interrupted jobs.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    count = 0
    with get_db(db_path) as conn:
        cursor = conn.execute("SELECT id, run_dir FROM jobs WHERE status = 'RUNNING'")
        running_jobs = cursor.fetchall()
        for job_row in running_jobs:
            jid = job_row["id"]
            r_dir_str = job_row["run_dir"]

            # Synchronize ingest_progress.json if it exists on disk
            try:
                p_file = Path(r_dir_str) / "ingest_progress.json"
                if p_file.exists():
                    p_data = json.loads(p_file.read_text(encoding="utf-8"))
                    if p_data.get("status") == "RUNNING":
                        p_data["status"] = "INTERRUPTED"
                        p_data["error_summary"] = "Process terminated abruptly (systemd/server restart)"
                        p_data["end_time"] = now_iso
                        p_file.write_text(json.dumps(p_data, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug("Could not synchronize progress file for job %s: %s", jid, e)

            conn.execute(
                """
                UPDATE jobs SET
                    status = 'INTERRUPTED',
                    error_summary = 'Process terminated abruptly (systemd/server restart)',
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, jid),
            )
            count += 1
        conn.execute("DELETE FROM job_locks")
    if count > 0:
        logger.warning("Startup recovery: marked %d orphaned RUNNING jobs as INTERRUPTED", count)
    return count


# ==============================================================================
# CONCURRENCY LOCKS
# ==============================================================================

def acquire_lock(
    resource_key: str,
    job_id: str,
    timeout_seconds: int = 1800,
    db_path: Path | None = None,
) -> bool:
    """Atomically acquire an exclusive lock for resource_key.

    If a lock already exists:
    - If older than timeout_seconds, it is treated as stale and forcibly replaced.
    - If fresh, acquisition fails and returns False.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "SELECT job_id, acquired_at FROM job_locks WHERE resource_key = ?",
            (resource_key,),
        )
        row = cursor.fetchone()
        if row:
            existing_job = row["job_id"]
            acquired_str = row["acquired_at"]
            is_stale = False
            try:
                dt = datetime.fromisoformat(acquired_str)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > timeout_seconds:
                    is_stale = True
            except Exception:
                is_stale = True

            if is_stale:
                logger.warning(
                    "Stale lock detected for %s (held by %s). Evicting and acquiring.",
                    resource_key, existing_job,
                )
                conn.execute("DELETE FROM job_locks WHERE resource_key = ?", (resource_key,))
            else:
                return False

        try:
            conn.execute(
                "INSERT INTO job_locks (resource_key, job_id, acquired_at) VALUES (?, ?, ?)",
                (resource_key, job_id, now_iso),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def release_lock(
    resource_key: str,
    job_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    """Release lock on resource_key. If job_id is specified, only releases if held by that job."""
    with get_db(db_path) as conn:
        if job_id:
            conn.execute(
                "DELETE FROM job_locks WHERE resource_key = ? AND job_id = ?",
                (resource_key, job_id),
            )
        else:
            conn.execute("DELETE FROM job_locks WHERE resource_key = ?", (resource_key,))


# ==============================================================================
# NOTIFICATIONS (IN-APP)
# ==============================================================================

def create_notification(
    *,
    profile: str,
    title: str,
    message: str,
    notification_type: str = "INFO",
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> str:
    """Create an in-app notification record scoped to an environment profile."""
    notif_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_str = json.dumps(metadata or {})

    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO notifications (
                id, job_id, profile, title, message, notification_type,
                metadata_json, is_read, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (notif_id, job_id, profile, title, message, notification_type, meta_str, now_iso),
        )
    return notif_id


def get_unread_notifications(
    profile: str,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve unread notifications for a specific profile (or 'all')."""
    with get_db(db_path) as conn:
        if profile == "all":
            cursor = conn.execute(
                "SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM notifications WHERE (profile = ? OR profile = 'all') AND is_read = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (profile, limit),
            )
        return [dict(row) for row in cursor.fetchall()]


def get_unread_count(profile: str, db_path: Path | None = None) -> int:
    """Get the count of unread notifications for an environment profile."""
    with get_db(db_path) as conn:
        if profile == "all":
            cursor = conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read = 0")
        else:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE (profile = ? OR profile = 'all') AND is_read = 0",
                (profile,),
            )
        row = cursor.fetchone()
        return row[0] if row else 0


def mark_notification_read(notification_id: str, db_path: Path | None = None) -> None:
    """Mark a single notification as read."""
    with get_db(db_path) as conn:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))


def mark_all_read(profile: str, db_path: Path | None = None) -> None:
    """Mark all notifications for a profile as read."""
    with get_db(db_path) as conn:
        if profile == "all":
            conn.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
        else:
            conn.execute(
                "UPDATE notifications SET is_read = 1 WHERE (profile = ? OR profile = 'all') AND is_read = 0",
                (profile,),
            )


# ==============================================================================
# SCHEDULES CRUD
# ==============================================================================

def create_schedule(
    *,
    name: str,
    report_name: str,
    profile: str = "sandbox",
    schedule_type: str = "recurring",
    frequency: str | None = "daily",
    cron_expression: str | None = None,
    run_at_time: str | None = "08:30",
    run_on_day: str | None = None,
    one_off_datetime: str | None = None,
    execution_mode: str = "reconcile_only",
    auto_push_confirmed: bool = False,
    batch_size: int = 15,
    next_run_at: str,
    max_retries: int = 3,
    db_path: Path | None = None,
) -> str:
    """Create a new schedule configuration."""
    sched_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO schedules (
                id, name, report_name, profile, schedule_type, frequency,
                cron_expression, run_at_time, run_on_day, one_off_datetime,
                execution_mode, auto_push_confirmed, batch_size, is_active,
                next_run_at, max_retries, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                sched_id,
                name.strip(),
                report_name.strip(),
                profile,
                schedule_type,
                frequency,
                cron_expression,
                run_at_time,
                run_on_day,
                one_off_datetime,
                execution_mode,
                1 if auto_push_confirmed else 0,
                batch_size,
                next_run_at,
                max_retries,
                now_iso,
                now_iso,
            ),
        )
    logger.info("Created schedule '%s' (%s) -> Next run: %s", name, sched_id, next_run_at)
    return sched_id


def update_schedule(
    schedule_id: str,
    db_path: Path | None = None,
    **updates: Any,
) -> None:
    """Update fields of an existing schedule."""
    if not updates:
        return
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    cols = []
    vals = []
    for k, v in updates.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(schedule_id)

    with get_db(db_path) as conn:
        conn.execute(f"UPDATE schedules SET {', '.join(cols)} WHERE id = ?", tuple(vals))


def delete_schedule(schedule_id: str, db_path: Path | None = None) -> bool:
    """Delete a schedule by ID."""
    with get_db(db_path) as conn:
        cursor = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        return cursor.rowcount > 0


def get_schedule(schedule_id: str, db_path: Path | None = None) -> dict[str, Any] | None:
    """Get single schedule by ID."""
    with get_db(db_path) as conn:
        cursor = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_schedules(
    active_only: bool = False,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """List all schedules sorted by next run time."""
    with get_db(db_path) as conn:
        if active_only:
            cursor = conn.execute(
                "SELECT * FROM schedules WHERE is_active = 1 ORDER BY next_run_at ASC"
            )
        else:
            cursor = conn.execute("SELECT * FROM schedules ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_due_schedules(
    now_iso: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all active schedules where next_run_at <= now."""
    threshold = now_iso or datetime.now(timezone.utc).isoformat()
    with get_db(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM schedules
            WHERE is_active = 1 AND next_run_at <= ?
            ORDER BY next_run_at ASC
            """,
            (threshold,),
        )
        return [dict(row) for row in cursor.fetchall()]


def record_schedule_run(
    schedule_id: str,
    *,
    job_id: str,
    status: str,
    next_run_at: str | None,
    db_path: Path | None = None,
) -> None:
    """Record the outcome of a scheduled run and advance next_run_at."""
    now_iso = datetime.now(timezone.utc).isoformat()
    is_success = status == "SUCCESS"

    with get_db(db_path) as conn:
        if is_success:
            conn.execute(
                """
                UPDATE schedules SET
                    last_run_at = ?,
                    last_run_status = ?,
                    last_run_id = ?,
                    next_run_at = COALESCE(?, next_run_at),
                    total_runs = total_runs + 1,
                    consecutive_failures = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, status, job_id, next_run_at, now_iso, schedule_id),
            )
        else:
            conn.execute(
                """
                UPDATE schedules SET
                    last_run_at = ?,
                    last_run_status = ?,
                    last_run_id = ?,
                    next_run_at = COALESCE(?, next_run_at),
                    total_runs = total_runs + 1,
                    consecutive_failures = consecutive_failures + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (now_iso, status, job_id, next_run_at, now_iso, schedule_id),
            )
