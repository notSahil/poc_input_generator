"""Core Task Scheduler Engine.

Handles timezone-aware next-run calculations (Europe/London), one-off specific datetime
scheduling, automated SOQL extraction, delta engine reconciliation, and optional
Salesforce cloud ingest with comprehensive failure boundaries and circuit breaking.
"""

import calendar
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import threading
import time
from typing import Any
import zoneinfo

from config import settings
from core.config_loader import YamlConfigLoader
from core.engine import InputFileEngine
from core.exceptions import ConcurrencyLockError, SchedulerError
from core.job_store import (
    acquire_lock,
    complete_job,
    create_job,
    get_due_schedules,
    get_schedule,
    init_db,
    mark_job_running,
    record_schedule_run,
    release_lock,
    update_job,
    update_schedule,
)
from core.notifier import build_notification_payload, dispatch_notification
from salesforce.data_fetcher import fetch_sitetracker_data

logger = logging.getLogger(__name__)


def get_uk_timezone() -> zoneinfo.ZoneInfo:
    """Return the configured project timezone (default: Europe/London)."""
    try:
        return zoneinfo.ZoneInfo(settings.SCHEDULER_TIMEZONE)
    except Exception:
        return zoneinfo.ZoneInfo("Europe/London")


def get_current_uk_time() -> datetime:
    """Return current datetime in UK timezone."""
    return datetime.now(get_uk_timezone())


# ==============================================================================
# TIMEZONE-AWARE NEXT-RUN CALCULATION
# ==============================================================================

def compute_next_run(
    *,
    schedule_type: str,
    frequency: str | None = None,
    run_at_time: str | None = "08:30",
    run_on_day: str | None = None,
    one_off_datetime: str | None = None,
    from_time: datetime | None = None,
    tz: zoneinfo.ZoneInfo | None = None,
) -> datetime | None:
    """Calculate the exact next execution datetime in UK timezone.

    Args:
        schedule_type: 'one_off' or 'recurring'.
        frequency: 'hourly', 'daily', 'weekly', 'monthly'.
        run_at_time: Time of day ('HH:MM', e.g. '08:30') or minute for hourly ('30').
        run_on_day: Day of week ('MON'..'SUN') or day of month ('1'..'31').
        one_off_datetime: ISO 8601 string for one-off tasks.
        from_time: Baseline time (defaults to current UK time).
        tz: Timezone object (defaults to Europe/London).

    Returns:
        Next run datetime (timezone-aware) or None if expired one-off.
    """
    target_tz = tz or get_uk_timezone()
    if from_time:
        if from_time.tzinfo is None:
            ref_time = from_time.replace(tzinfo=target_tz)
        else:
            ref_time = from_time.astimezone(target_tz)
    else:
        ref_time = get_current_uk_time()

    # 1. One-off specific datetime
    if schedule_type == "one_off":
        if not one_off_datetime:
            return None
        try:
            # Parse ISO string
            dt = datetime.fromisoformat(one_off_datetime.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=target_tz)
            else:
                dt = dt.astimezone(target_tz)

            if dt > ref_time:
                return dt
            return None  # In the past -> expired
        except Exception as e:
            logger.warning("Could not parse one_off_datetime '%s': %s", one_off_datetime, e)
            return None

    # 2. Recurring schedules
    freq = (frequency or "daily").lower()

    # Parse HH:MM or minute
    hour = 8
    minute = 30
    if run_at_time:
        t_clean = str(run_at_time).strip()
        if ":" in t_clean:
            parts = t_clean.split(":")
            hour = int(parts[0])
            minute = int(parts[1])
        else:
            try:
                val = int(t_clean)
                if freq == "hourly":
                    minute = val
                else:
                    hour = val
            except ValueError:
                pass

    if freq == "hourly":
        candidate = ref_time.replace(minute=minute, second=0, microsecond=0)
        if candidate <= ref_time:
            candidate += timedelta(hours=1)
        return candidate

    elif freq == "daily":
        candidate = ref_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= ref_time:
            candidate += timedelta(days=1)
        return candidate

    elif freq == "weekly":
        day_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
        target_day = 0  # Default Monday
        if run_on_day:
            day_str = str(run_on_day).strip().upper()[:3]
            target_day = day_map.get(day_str, 0)

        # Days until target day
        days_ahead = (target_day - ref_time.weekday()) % 7
        candidate = (ref_time + timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if candidate <= ref_time:
            candidate += timedelta(days=7)
        return candidate

    elif freq == "monthly":
        try:
            target_dom = int(run_on_day) if run_on_day else 1
            target_dom = max(1, min(target_dom, 31))
        except (ValueError, TypeError):
            target_dom = 1

        year = ref_time.year
        month = ref_time.month

        # Clamp day to month's length
        _, max_day = calendar.monthrange(year, month)
        actual_day = min(target_dom, max_day)

        candidate = datetime(year, month, actual_day, hour, minute, 0, tzinfo=target_tz)
        if candidate <= ref_time:
            # Advance to next month
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            _, max_day = calendar.monthrange(year, month)
            actual_day = min(target_dom, max_day)
            candidate = datetime(year, month, actual_day, hour, minute, 0, tzinfo=target_tz)

        return candidate

    # Fallback to daily
    candidate = ref_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= ref_time:
        candidate += timedelta(days=1)
    return candidate


# ==============================================================================
# SCHEDULED TASK EXECUTION
# ==============================================================================

def execute_scheduled_task(
    schedule_id: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Execute a single scheduled task with complete error boundaries.

    Returns a dict with execution summary (status, total, updated, errors, etc.).
    """
    sched = get_schedule(schedule_id, db_path=db_path)
    if not sched:
        raise SchedulerError(f"Schedule with ID '{schedule_id}' not found.")

    report_name = sched["report_name"]
    profile = sched["profile"]
    schedule_name = sched["name"]
    exec_mode = sched.get("execution_mode", "reconcile_only")
    auto_push_confirmed = bool(sched.get("auto_push_confirmed", False))
    batch_size = sched.get("batch_size", 15)

    resource_key = f"{report_name}:{profile}:scheduled"
    job_id = create_job(
        run_dir=settings.PROJECT_ROOT / "runs" / "pending",
        report_name=report_name,
        profile=profile,
        triggered_by="schedule",
        schedule_id=schedule_id,
        db_path=db_path,
    )

    # 1. Acquire Concurrency Lock
    if not acquire_lock(resource_key, job_id, timeout_seconds=settings.SCHEDULER_EXECUTION_TIMEOUT_MINUTES * 60, db_path=db_path):
        logger.warning(
            "Schedule '%s' (%s) skipped: resource '%s' is locked by another job.",
            schedule_name, report_name, resource_key,
        )
        complete_job(job_id, "SKIPPED", error_summary="Resource locked by another active job", db_path=db_path)
        payload = build_notification_payload(
            report_name=report_name,
            profile=profile,
            status="SKIPPED",
            schedule_name=schedule_name,
            error_summary="Resource is locked by another active operation. Task will re-run on next cycle.",
        )
        dispatch_notification(**payload, job_id=job_id, db_path=db_path)
        return {"status": "SKIPPED", "job_id": job_id, "reason": "Resource locked"}

    try:
        mark_job_running(job_id, db_path=db_path)

        # 2. Check source file availability
        yaml_cfg = YamlConfigLoader.load(report_name)
        folders = yaml_cfg.get("folders", {})
        work_dir = settings.DATA_DIR / folders.get("work_dir", report_name.replace(" ", "_"))
        source_dir = work_dir / folders.get("source_dir", "input/source")

        source_files = [f for f in source_dir.iterdir() if not f.name.startswith(".") and f.is_file()] if source_dir.exists() else []

        if not source_files:
            logger.info("Schedule '%s' skipped: no source file in %s", schedule_name, source_dir)
            complete_job(job_id, "SKIPPED", error_summary=f"No source file in {source_dir}", db_path=db_path)
            # Advance next_run_at
            _advance_schedule_after_run(sched, job_id=job_id, status="SKIPPED", db_path=db_path)
            payload = build_notification_payload(
                report_name=report_name,
                profile=profile,
                status="SKIPPED",
                schedule_name=schedule_name,
                error_summary=f"No source file found in {source_dir.name}/ folder.",
            )
            dispatch_notification(**payload, job_id=job_id, db_path=db_path)
            return {"status": "SKIPPED", "job_id": job_id, "reason": "No source file"}


        # 3. Pull live Sitetracker baseline via SOQL
        logger.info("Schedule '%s': Fetching live Sitetracker SOQL baseline...", schedule_name)
        fetch_sitetracker_data(report_name=report_name, profile=profile)

        # 4. Execute Core Delta Engine
        logger.info("Schedule '%s': Running InputFileEngine...", schedule_name)
        engine = InputFileEngine(report_name)
        run_result = engine.run(skip_validation=False)

        # Update job run_dir to actual runs directory
        update_job(
            job_id,
            run_dir=str(run_result.run_dir),
            db_path=db_path,
        )

        successful_records = run_result.delta_records
        failed_records = run_result.error_records
        total_records = run_result.total_source_records
        skipped_records = run_result.skipped_records

        # 5. Optional Auto-Push to Salesforce
        pushed_to_salesforce = False
        if exec_mode == "reconcile_and_push":
            if profile == "prod" and not settings.ALLOW_SCHEDULED_PROD_PUSH:
                logger.warning("Schedule '%s': Scheduled push to Production disabled by ALLOW_SCHEDULED_PROD_PUSH setting.", schedule_name)
            elif not auto_push_confirmed:
                logger.warning("Schedule '%s': auto_push_confirmed is False, skipping push.", schedule_name)
            else:
                logger.info("Schedule '%s': Auto-pushing deltas to Salesforce (%s records)...", schedule_name, successful_records)
                from salesforce.composite_uploader import push_delta_via_composite
                # Push final input file for the primary object
                final_file = run_result.run_dir / "final_input_file.csv"
                if final_file.exists() and successful_records > 0:
                    upload_res = push_delta_via_composite(
                        csv_path=final_file,
                        object_name=yaml_cfg.get("report", {}).get("salesforce_object", "sitetracker__Site__c"),
                        report_name=report_name,
                        profile=profile,
                        batch_size=batch_size,
                    )
                    successful_records = upload_res.successful_records
                    failed_records = upload_res.failed_records
                    pushed_to_salesforce = True

        fin_status = "SUCCESS" if failed_records == 0 else "COMPLETED_WITH_ERRORS"
        complete_job(job_id, fin_status, db_path=db_path)
        _advance_schedule_after_run(sched, job_id=job_id, status=fin_status, db_path=db_path)

        # 6. Dispatch Notification
        payload = build_notification_payload(
            report_name=report_name,
            profile=profile,
            status=fin_status,
            total_records=total_records,
            successful_records=successful_records,
            failed_records=failed_records,
            skipped_records=skipped_records,
            run_dir=run_result.run_dir,
            job_id=job_id,
            schedule_name=schedule_name,
        )
        dispatch_notification(**payload, job_id=job_id, db_path=db_path)

        return {
            "status": fin_status,
            "job_id": job_id,
            "run_dir": str(run_result.run_dir),
            "total_records": total_records,
            "successful_records": successful_records,
            "failed_records": failed_records,
            "pushed_to_salesforce": pushed_to_salesforce,
        }

    except Exception as exc:
        logger.exception("Scheduled task '%s' failed: %s", schedule_name, exc)
        complete_job(job_id, "FAILED", error_summary=str(exc), db_path=db_path)
        _advance_schedule_after_run(sched, job_id=job_id, status="FAILED", db_path=db_path)

        payload = build_notification_payload(
            report_name=report_name,
            profile=profile,
            status="FAILURE",
            schedule_name=schedule_name,
            error_summary=str(exc),
        )
        dispatch_notification(**payload, job_id=job_id, db_path=db_path)
        return {"status": "FAILED", "job_id": job_id, "error": str(exc)}


    finally:
        release_lock(resource_key, job_id=job_id, db_path=db_path)


def _advance_schedule_after_run(
    sched: dict[str, Any],
    job_id: str,
    status: str,
    db_path: Path | None = None,
) -> None:
    """Calculate and save next run time or auto-deactivate one-off schedules."""
    sched_id = sched["id"]
    sched_type = sched.get("schedule_type", "recurring")

    if sched_type == "one_off":
        # Auto-deactivate one-off after it has executed
        update_schedule(
            sched_id,
            is_active=0,
            last_run_status=status,
            last_run_id=job_id,
            last_run_at=datetime.now(timezone.utc).isoformat(),
            db_path=db_path,
        )
        logger.info("One-off schedule '%s' completed and auto-deactivated.", sched["name"])
        return

    # Recurring: compute next run
    next_dt = compute_next_run(
        schedule_type="recurring",
        frequency=sched.get("frequency"),
        run_at_time=sched.get("run_at_time"),
        run_on_day=sched.get("run_on_day"),
        from_time=get_current_uk_time() + timedelta(seconds=10),
    )
    next_iso = next_dt.isoformat() if next_dt else datetime.now(timezone.utc).isoformat()

    record_schedule_run(
        sched_id,
        job_id=job_id,
        status=status,
        next_run_at=next_iso,
        db_path=db_path,
    )


# ==============================================================================
# SCHEDULER RUNNER & BACKGROUND LOOP
# ==============================================================================

def run_due_tasks(db_path: Path | None = None) -> list[dict[str, Any]]:
    """Query all active schedules due for execution and run them sequentially."""
    due_list = get_due_schedules(db_path=db_path)
    if not due_list:
        return []

    logger.info("Scheduler: Found %d due tasks to execute.", len(due_list))
    results: list[dict[str, Any]] = []

    for sched in due_list:
        sched_id = sched["id"]
        sched_name = sched["name"]
        max_retries = sched.get("max_retries", settings.SCHEDULER_MAX_RETRIES)
        fails = sched.get("consecutive_failures", 0)

        # Circuit breaker: auto-pause if consecutive failures exceed threshold
        if fails >= max_retries:
            logger.warning(
                "Circuit breaker: Auto-pausing schedule '%s' after %d consecutive failures.",
                sched_name, fails,
            )
            update_schedule(sched_id, is_active=0, db_path=db_path)
            dispatch_notification(
                title=f"🚨 Schedule Auto-Paused: {sched_name}",
                message=f"Schedule has failed {fails} times in a row and has been paused to protect system health. Please inspect logs and resume manually.",
                profile=sched.get("profile", "sandbox"),
                notification_type="FAILURE",
                metadata={"schedule_id": sched_id, "failures": fails},
                db_path=db_path,
            )
            results.append({"schedule_id": sched_id, "status": "CIRCUIT_BROKEN"})

            continue

        res = execute_scheduled_task(sched_id, db_path=db_path)
        results.append({"schedule_id": sched_id, **res})

    return results


def start_scheduler_loop(
    poll_interval: int | None = None,
    stop_event: threading.Event | None = None,
    db_path: Path | None = None,
) -> None:
    """Run persistent scheduler loop.

    Can be invoked in a background thread from Streamlit or as foreground CLI daemon.
    """
    interval = poll_interval or settings.SCHEDULER_POLL_INTERVAL_SECONDS
    logger.info("Scheduler background loop started (polling every %ds)...", interval)

    while True:
        if stop_event and stop_event.is_set():
            logger.info("Scheduler loop stopping gracefully.")
            break
        try:
            run_due_tasks(db_path=db_path)
        except Exception as e:
            logger.error("Error during scheduler poll execution: %s", e)

        # Sleep interval with periodic stop_event checks
        for _ in range(max(1, interval)):
            if stop_event and stop_event.is_set():
                break
            time.sleep(1)
