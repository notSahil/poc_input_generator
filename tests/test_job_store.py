"""Unit tests for core/job_store.py (SQLite persistent queue, locks, checkpoints, notifications)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from core.job_store import (
    acquire_lock,
    complete_job,
    create_job,
    create_notification,
    create_schedule,
    delete_schedule,
    get_active_jobs,
    get_due_schedules,
    get_job,
    get_schedule,
    get_unread_count,
    get_unread_notifications,
    init_db,
    list_schedules,
    mark_all_read,
    mark_interrupted_on_startup,
    mark_job_running,
    mark_notification_read,
    record_schedule_run,
    release_lock,
    update_job,
    update_job_progress,
    update_schedule,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Provides a fresh, isolated SQLite test database."""
    test_db = tmp_path / "test_jobs.db"
    init_db(test_db)
    return test_db


def test_init_db_creates_tables(db_path: Path):
    """Verify all 4 core tables and indexes are created properly."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    assert "jobs" in tables
    assert "job_locks" in tables
    assert "notifications" in tables
    assert "schedules" in tables


def test_job_lifecycle(db_path: Path, tmp_path: Path):
    """Verify create -> mark_running -> checkpoint -> complete lifecycle."""
    job_id = create_job(
        run_dir=tmp_path,
        report_name="Apollo 10G",
        profile="sandbox",
        target_object="BT_Project__c",
        engine="composite",
        total_records=100,
        db_path=db_path,
    )
    assert job_id is not None

    job = get_job(job_id, db_path=db_path)
    assert job["status"] == "QUEUED"
    assert job["report_name"] == "Apollo 10G"
    assert job["total_records"] == 100

    mark_job_running(job_id, db_path=db_path)
    assert get_job(job_id, db_path=db_path)["status"] == "RUNNING"

    update_job_progress(
        job_id,
        processed=50,
        successful=48,
        failed=2,
        current_chunk=2,
        total_chunks=4,
        checkpoint_json='{"chunk": 2}',
        db_path=db_path,
    )
    updated = get_job(job_id, db_path=db_path)
    assert updated["processed"] == 50
    assert updated["successful"] == 48
    assert updated["failed"] == 2
    assert updated["current_chunk"] == 2
    assert updated["checkpoint_json"] == '{"chunk": 2}'

    complete_job(job_id, "COMPLETED_WITH_ERRORS", error_summary="2 records rejected", db_path=db_path)
    completed = get_job(job_id, db_path=db_path)
    assert completed["status"] == "COMPLETED_WITH_ERRORS"
    assert completed["error_summary"] == "2 records rejected"
    assert completed["completed_at"] is not None


def test_mark_interrupted_on_startup(db_path: Path, tmp_path: Path):
    """Verify orphaned RUNNING jobs are marked INTERRUPTED and locks cleared."""
    j1 = create_job(run_dir=tmp_path, report_name="Rep1", db_path=db_path)
    j2 = create_job(run_dir=tmp_path, report_name="Rep2", db_path=db_path)
    mark_job_running(j1, db_path=db_path)
    # j2 stays QUEUED

    acquire_lock("Rep1:sandbox:All", j1, db_path=db_path)

    interrupted_count = mark_interrupted_on_startup(db_path=db_path)
    assert interrupted_count == 1

    job1 = get_job(j1, db_path=db_path)
    assert job1["status"] == "INTERRUPTED"
    assert "Process terminated abruptly" in job1["error_summary"]

    job2 = get_job(j2, db_path=db_path)
    assert job2["status"] == "QUEUED"  # Untouched

    # Lock must be cleared, so acquiring now succeeds
    assert acquire_lock("Rep1:sandbox:All", "new_job", db_path=db_path) is True


def test_locking_concurrency(db_path: Path):
    """Verify mutual exclusion and stale lock eviction."""
    res_key = "Apollo_10G:sandbox:Site"
    # Acquire lock 1
    assert acquire_lock(res_key, "job_1", db_path=db_path) is True
    # Second acquire should fail
    assert acquire_lock(res_key, "job_2", db_path=db_path) is False

    # Release by different job shouldn't release if specified
    release_lock(res_key, job_id="wrong_job", db_path=db_path)
    assert acquire_lock(res_key, "job_2", db_path=db_path) is False

    # Release by correct job
    release_lock(res_key, job_id="job_1", db_path=db_path)
    assert acquire_lock(res_key, "job_2", db_path=db_path) is True

    # Test stale lock replacement
    # Backdate acquired_at by 2 hours
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    conn.execute("UPDATE job_locks SET acquired_at = ?", (old_time,))
    conn.commit()
    conn.close()

    # Should detect stale and acquire successfully
    assert acquire_lock(res_key, "job_3", timeout_seconds=1800, db_path=db_path) is True


def test_notifications_profile_scoping(db_path: Path):
    """Verify notifications are scoped to environment profile and read states work."""
    n1 = create_notification(
        profile="sandbox",
        title="Sandbox Alert",
        message="Upload finished",
        notification_type="SUCCESS",
        db_path=db_path,
    )
    n2 = create_notification(
        profile="prod",
        title="Prod Alert",
        message="Production run complete",
        notification_type="SUCCESS",
        db_path=db_path,
    )
    n3 = create_notification(
        profile="all",
        title="System Notice",
        message="Maintenance tonight",
        notification_type="INFO",
        db_path=db_path,
    )

    # Sandbox sees n1 and n3
    sb_unread = get_unread_notifications("sandbox", db_path=db_path)
    assert len(sb_unread) == 2
    assert {n["id"] for n in sb_unread} == {n1, n3}
    assert get_unread_count("sandbox", db_path=db_path) == 2

    # Prod sees n2 and n3
    prod_unread = get_unread_notifications("prod", db_path=db_path)
    assert len(prod_unread) == 2
    assert {n["id"] for n in prod_unread} == {n2, n3}
    assert get_unread_count("prod", db_path=db_path) == 2

    # Mark n1 as read
    mark_notification_read(n1, db_path=db_path)
    assert get_unread_count("sandbox", db_path=db_path) == 1

    # Mark all read for prod
    mark_all_read("prod", db_path=db_path)
    assert get_unread_count("prod", db_path=db_path) == 0


def test_schedules_crud_and_runs(db_path: Path):
    """Verify full CRUD for schedules and recording runs."""
    future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    sched_id = create_schedule(
        name="Apollo Daily",
        report_name="Apollo 10G",
        profile="sandbox",
        schedule_type="recurring",
        frequency="daily",
        run_at_time="08:30",
        next_run_at=future_time,
        db_path=db_path,
    )
    assert sched_id is not None

    sched = get_schedule(sched_id, db_path=db_path)
    assert sched["name"] == "Apollo Daily"
    assert sched["is_active"] == 1
    assert sched["consecutive_failures"] == 0

    # Update
    update_schedule(sched_id, run_at_time="09:00", db_path=db_path)
    assert get_schedule(sched_id, db_path=db_path)["run_at_time"] == "09:00"

    # Due schedules (future time is not due)
    assert len(get_due_schedules(db_path=db_path)) == 0

    # Backdate next_run_at to past
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    update_schedule(sched_id, next_run_at=past_time, db_path=db_path)
    due = get_due_schedules(db_path=db_path)
    assert len(due) == 1
    assert due[0]["id"] == sched_id

    # Record failure run
    record_schedule_run(
        sched_id,
        job_id="job_err",
        status="FAILED",
        next_run_at=future_time,
        db_path=db_path,
    )
    s_failed = get_schedule(sched_id, db_path=db_path)
    assert s_failed["total_runs"] == 1
    assert s_failed["consecutive_failures"] == 1
    assert s_failed["last_run_status"] == "FAILED"

    # Record success run (resets consecutive_failures)
    record_schedule_run(
        sched_id,
        job_id="job_succ",
        status="SUCCESS",
        next_run_at=future_time,
        db_path=db_path,
    )
    s_succ = get_schedule(sched_id, db_path=db_path)
    assert s_succ["total_runs"] == 2
    assert s_succ["consecutive_failures"] == 0
    assert s_succ["last_run_status"] == "SUCCESS"

    # Delete
    assert delete_schedule(sched_id, db_path=db_path) is True
    assert get_schedule(sched_id, db_path=db_path) is None


def test_update_job(db_path: Path, tmp_path: Path):
    """Verify arbitrary job record fields can be updated via update_job."""
    job_id = create_job(run_dir=tmp_path / "init", report_name="Apollo 10G", db_path=db_path)
    new_dir = tmp_path / "actual_run_123"
    update_job(job_id, run_dir=str(new_dir), target_object="Site__c", db_path=db_path)

    job = get_job(job_id, db_path=db_path)
    assert job["run_dir"] == str(new_dir)
    assert job["target_object"] == "Site__c"


def test_mark_interrupted_syncs_ingest_progress_file(db_path: Path, tmp_path: Path):
    """Verify mark_interrupted_on_startup flips ingest_progress.json on disk to INTERRUPTED."""
    import json
    run_dir = tmp_path / "run_crash"
    run_dir.mkdir(parents=True)
    p_file = run_dir / "ingest_progress.json"
    p_file.write_text(json.dumps({"status": "RUNNING", "current_object": "Site__c"}), encoding="utf-8")

    job_id = create_job(run_dir=run_dir, report_name="Apollo 10G", db_path=db_path)
    mark_job_running(job_id, db_path=db_path)

    interrupted = mark_interrupted_on_startup(db_path=db_path)
    assert interrupted == 1

    # Verify SQLite
    assert get_job(job_id, db_path=db_path)["status"] == "INTERRUPTED"

    # Verify disk file
    saved_prog = json.loads(p_file.read_text(encoding="utf-8"))
    assert saved_prog["status"] == "INTERRUPTED"
    assert "terminated abruptly" in saved_prog["error_summary"]
