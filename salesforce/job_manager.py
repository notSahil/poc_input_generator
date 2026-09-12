"""Background Ingest Job Manager.

Runs Salesforce Bulk API 2.0 or REST Composite Ingest tasks in detached
background threads on the server.
Guarantees phone disconnect immunity (closing browser or switching apps
does not interrupt the upload) and writes real-time progress to ingest_progress.json.
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import threading
from typing import Any
import pandas as pd

from config import settings
from core.audit_logger import AuditLogger
from core.mapping_loader import MappingLoader
from salesforce.bulk_uploader import BulkUploadResult

logger = logging.getLogger(__name__)

PROGRESS_FILE_NAME = "ingest_progress.json"
_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_THREAD_LOCK = threading.Lock()


def get_progress_file(run_dir: Path) -> Path:
    return run_dir / PROGRESS_FILE_NAME


def get_job_progress(run_dir: Path) -> dict[str, Any] | None:
    """Read the current ingest progress JSON file if it exists."""
    p_file = get_progress_file(run_dir)
    if not p_file.exists():
        return None
    try:
        content = p_file.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning("Could not read progress file %s: %s", p_file, e)
        return None


def clear_job_progress(run_dir: Path) -> None:
    """Remove the progress file to reset state for a fresh run."""
    p_file = get_progress_file(run_dir)
    if p_file.exists():
        try:
            p_file.unlink()
        except Exception as e:
            logger.warning("Failed to delete progress file %s: %s", p_file, e)


def is_job_active(run_dir: Path) -> bool:
    """Check if a background thread is currently running for this run_dir."""
    key = str(run_dir.resolve())
    with _THREAD_LOCK:
        thread = _ACTIVE_THREADS.get(key)
        if thread and thread.is_alive():
            return True

    prog = get_job_progress(run_dir)
    if prog and prog.get("status") == "RUNNING":
        # Check if the thread crashed or process restarted
        # If last update is older than 15 minutes, consider it stalled
        up_time = prog.get("update_time")
        if up_time:
            try:
                dt = datetime.fromisoformat(up_time)
                if (datetime.now() - dt).total_seconds() > 900:
                    prog["status"] = "FAILED"
                    prog["error_summary"] = "Job timed out or worker process restarted."
                    _save_progress(run_dir, prog)
                    return False
            except Exception:
                pass
        return True
    return False


def _save_progress(run_dir: Path, data: dict[str, Any]) -> None:
    data["update_time"] = datetime.now().isoformat()
    p_file = get_progress_file(run_dir)
    try:
        temp_file = p_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_file.replace(p_file)
    except Exception as e:
        logger.error("Failed to write progress to %s: %s", p_file, e)


def start_background_ingest(
    run_dir: Path,
    report_name: str,
    is_rollback: bool = False,
    profile: str | None = None,
    batch_size: int = 15,
    target_object: str | None = None,
    engine: str = "composite",
) -> None:
    """Start an ingest or rollback job in a detached background thread.

    Even if the browser is closed or phone switches apps, this continues on server.
    """
    key = str(run_dir.resolve())
    with _THREAD_LOCK:
        if key in _ACTIVE_THREADS and _ACTIVE_THREADS[key].is_alive():
            logger.warning("Job already active for %s", run_dir)
            return

    thread = threading.Thread(
        target=_ingest_worker,
        kwargs={
            "run_dir": run_dir,
            "report_name": report_name,
            "is_rollback": is_rollback,
            "profile": profile,
            "batch_size": batch_size,
            "target_object": target_object,
            "engine": engine,
        },
        daemon=True,
    )
    with _THREAD_LOCK:
        _ACTIVE_THREADS[key] = thread
    thread.start()


def _ingest_worker(
    run_dir: Path,
    report_name: str,
    is_rollback: bool,
    profile: str | None,
    batch_size: int,
    target_object: str | None,
    engine: str,
) -> None:
    """Background worker executing the data load across all objects."""
    logger.info("Background ingest worker started for %s (engine=%s)", run_dir, engine)
    audit = AuditLogger(run_dir)

    # 1. Determine targets and inspect record counts
    if target_object and target_object != "All Objects":
        target_objects = [target_object]
    else:
        try:
            loader = MappingLoader(settings.MAPPING_FILE, report_name)
            all_objects = loader.objects()
            is_multi = not target_object or "All Objects" in target_object
            target_objects = all_objects if is_multi else [target_object]
        except Exception:
            target_objects = [target_object] if target_object else ["sitetracker__Site__c"]

    if is_rollback:
        audit.info(
            f"Rollback execution started for {report_name}",
            tag="ROLLBACK",
            Engine="Lightning REST Collections" if engine == "composite" else "Bulk API 2.0",
            Target_Objects=", ".join(target_objects),
            Batch_Size=batch_size,
        )
    else:
        audit.info(
            f"Cloud upload started for {report_name}",
            tag="UPLOAD",
            Engine="Lightning REST Collections" if engine == "composite" else "Bulk API 2.0",
            Target_Objects=", ".join(target_objects),
            Batch_Size=batch_size,
        )

    prefix = "rollback_file_" if is_rollback else "final_input_file_"

    object_files: dict[str, Path] = {}
    total_records_overall = 0
    object_meta: dict[str, dict[str, Any]] = {}

    for obj in target_objects:
        c_name = obj.strip().replace(" ", "_")
        f_path = run_dir / f"{prefix}{c_name}.csv"
        if not f_path.exists() and len(target_objects) == 1:
            fallback = run_dir / ("rollback_file.csv" if is_rollback else "final_input_file.csv")
            if fallback.exists():
                f_path = fallback

        rec_count = 0
        if f_path.exists():
            try:
                df = pd.read_csv(f_path, dtype=str)
                rec_count = len(df)
            except Exception:
                rec_count = 0

        object_files[obj] = f_path
        total_records_overall += rec_count
        object_meta[obj] = {
            "status": "PENDING",
            "total_records": rec_count,
            "processed_records": 0,
            "successful_records": 0,
            "failed_records": 0,
            "job_id": None,
            "failures_file": None,
        }

    progress_state: dict[str, Any] = {
        "status": "RUNNING",
        "engine": engine,
        "is_rollback": is_rollback,
        "report_name": report_name,
        "start_time": datetime.now().isoformat(),
        "total_objects": len(target_objects),
        "current_object_index": 0,
        "current_object": target_objects[0] if target_objects else "",
        "total_records_overall": total_records_overall,
        "processed_records_overall": 0,
        "successful_records_overall": 0,
        "failed_records_overall": 0,
        "objects": object_meta,
        "error_summary": None,
    }
    _save_progress(run_dir, progress_state)

    if total_records_overall == 0:
        progress_state["status"] = "COMPLETED"
        progress_state["end_time"] = datetime.now().isoformat()
        _save_progress(run_dir, progress_state)
        return

    # 2. Execute sequentially per object
    overall_processed = 0
    overall_success = 0
    overall_failed = 0

    from salesforce.bulk_uploader import push_delta_to_sitetracker
    from salesforce.composite_uploader import push_delta_via_composite

    try:
        for idx, obj in enumerate(target_objects, 1):
            f_path = object_files[obj]
            if not f_path.exists() or object_meta[obj]["total_records"] == 0:
                object_meta[obj]["status"] = "SKIPPED"
                continue

            progress_state["current_object_index"] = idx
            progress_state["current_object"] = obj
            object_meta[obj]["status"] = "RUNNING"
            _save_progress(run_dir, progress_state)

            def make_callback(o_name: str, base_proc: int, base_succ: int, base_fail: int):
                def cb(info: dict[str, Any]):
                    nonlocal overall_processed, overall_success, overall_failed
                    c_proc = info.get("processed_records", 0)
                    c_succ = info.get("successful_records", 0)
                    c_fail = info.get("failed_records", 0)
                    stage = info.get("stage", "completed_chunk")

                    object_meta[o_name]["processed_records"] = c_proc
                    object_meta[o_name]["successful_records"] = c_succ
                    object_meta[o_name]["failed_records"] = c_fail
                    object_meta[o_name]["current_chunk"] = info.get("current_chunk", 0)
                    object_meta[o_name]["total_chunks"] = info.get("total_chunks", 0)
                    object_meta[o_name]["chunk_start"] = info.get("chunk_start", 0)
                    object_meta[o_name]["chunk_end"] = info.get("chunk_end", 0)
                    object_meta[o_name]["chunk_size"] = info.get("chunk_size", 0)
                    object_meta[o_name]["stage"] = stage

                    progress_state["stage"] = stage
                    progress_state["current_chunk"] = info.get("current_chunk", 0)
                    progress_state["total_chunks"] = info.get("total_chunks", 0)
                    progress_state["chunk_start"] = info.get("chunk_start", 0)
                    progress_state["chunk_end"] = info.get("chunk_end", 0)
                    progress_state["chunk_size"] = info.get("chunk_size", 0)
                    progress_state["processed_records_overall"] = base_proc + c_proc
                    progress_state["successful_records_overall"] = base_succ + c_succ
                    progress_state["failed_records_overall"] = base_fail + c_fail
                    _save_progress(run_dir, progress_state)

                    if stage == "completed_chunk":
                        audit.info(
                            f"{o_name} batch {info.get('current_chunk')}/{info.get('total_chunks')} completed",
                            tag="BATCH",
                            Object=o_name,
                            Records=f"{info.get('chunk_start')}-{info.get('chunk_end')}",
                            Batch_Size=info.get('chunk_size'),
                            Success=info.get('successful_records'),
                            Failed=info.get('failed_records'),
                        )
                return cb

            cb_func = make_callback(obj, overall_processed, overall_success, overall_failed)

            if engine == "composite":
                res: BulkUploadResult = push_delta_via_composite(
                    csv_path=f_path,
                    object_name=obj,
                    report_name=report_name,
                    is_rollback=is_rollback,
                    profile=profile,
                    batch_size=batch_size,
                    progress_callback=cb_func,
                )
            else:
                res = push_delta_to_sitetracker(
                    csv_path=f_path,
                    object_name=obj,
                    report_name=report_name,
                    operation="update",
                    is_rollback=is_rollback,
                    profile=profile,
                    batch_size=batch_size,
                    progress_callback=cb_func,
                )

            object_meta[obj]["status"] = "COMPLETED" if res.all_succeeded else "COMPLETED_WITH_ERRORS"
            object_meta[obj]["successful_records"] = res.successful_records
            object_meta[obj]["failed_records"] = res.failed_records
            object_meta[obj]["processed_records"] = res.total_records
            object_meta[obj]["job_id"] = res.job_id
            if res.failures_csv_path:
                object_meta[obj]["failures_file"] = res.failures_csv_path.name

            if res.failures:
                for fail_item in res.failures:
                    audit.record_error(
                        record_id=fail_item.get("sf__Id") or fail_item.get("Id") or "UNKNOWN_ID",
                        object_name=obj,
                        message=fail_item.get("sf__Error") or fail_item.get("Error") or "Salesforce update rejected",
                        field_name=fail_item.get("sf__Fields") or fail_item.get("Fields") or None,
                    )

            overall_processed += res.total_records
            overall_success += res.successful_records
            overall_failed += res.failed_records

            progress_state["processed_records_overall"] = overall_processed
            progress_state["successful_records_overall"] = overall_success
            progress_state["failed_records_overall"] = overall_failed
            _save_progress(run_dir, progress_state)

        fin_status = "SUCCESS" if overall_failed == 0 else "COMPLETED_WITH_ERRORS"
        progress_state["status"] = "COMPLETED"
        progress_state["end_time"] = datetime.now().isoformat()
        _save_progress(run_dir, progress_state)
        audit.finish(
            status=fin_status,
            successes=overall_success,
            failures=overall_failed,
            output_files=[f.name for f in object_files.values() if f.exists()],
        )
        logger.info("Background ingest worker completed successfully for %s", run_dir)

    except Exception as exc:
        logger.exception("Background ingest worker failed: %s", exc)
        audit.exception("Background ingest worker encountered unhandled error", exc=exc)
        if any(term in str(exc).lower() for term in ("timeout", "connection", "network", "socket", "eof")):
            audit.network_error(operation=f"Salesforce upload for {progress_state.get('current_object')}", error=exc)
        audit.finish(
            status="FAILED",
            successes=overall_success,
            failures=overall_failed,
            Error=str(exc),
        )
        progress_state["status"] = "FAILED"
        progress_state["error_summary"] = str(exc)
        progress_state["end_time"] = datetime.now().isoformat()
        _save_progress(run_dir, progress_state)

    finally:
        key = str(run_dir.resolve())
        with _THREAD_LOCK:
            _ACTIVE_THREADS.pop(key, None)
