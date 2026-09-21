"""Background Ingest Job Manager.

Runs Salesforce Bulk API 2.0 or REST Composite Ingest tasks in detached
background threads on the server.
Guarantees phone disconnect immunity (closing browser or switching apps
does not interrupt the upload) and writes real-time progress to ingest_progress.json.
"""

from datetime import datetime
import io
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
from salesforce.csv_sanitizer import is_valid_salesforce_id, sanitize_failure_csv

logger = logging.getLogger(__name__)

PROGRESS_FILE_NAME = "ingest_progress.json"
_ACTIVE_THREADS: dict[str, threading.Thread] = {}
_THREAD_LOCK = threading.Lock()


def simplify_salesforce_error(err_str: Any) -> str:
    """Translate cryptic Salesforce/Sitetracker SQL, PLSQL, and validation rule errors into clear, human-readable explanations."""
    if err_str is None or pd.isna(err_str):
        return "Salesforce update rejected"
    s = str(err_str).strip()
    if not s or s.lower() == "nan":
        return "Salesforce update rejected"

    if "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST" in s:
        import re
        val_match = re.search(r"bad value for restricted picklist field:\s*([^\n;]+)", s)
        val = val_match.group(1).strip() if val_match else "value"
        return f"Restricted Picklist: '{val}' is not an approved picklist option for this field"

    if "Actualized date (Order Placed) cannot be in the future" in s or ("cannot be in the future" in s and "Actual" in s):
        return "Future Date Not Allowed: Actual milestone dates cannot be in the future"

    if "Actual_Date_Cant_Updated_When_Approved" in s:
        return "Milestone Locked: Project milestone is already Approved or Completed; actual dates cannot be modified"

    if "requires a document to be uploaded" in s:
        return "Missing Attachment: Required completion document must be uploaded before setting the Actual Date"

    if "Too many retries of batch save" in s:
        return "Batch Rollback: Other invalid records in this batch caused Apex triggers to roll back the entire batch"

    if "FIELD_CUSTOM_VALIDATION_EXCEPTION" in s:
        import re
        msg_match = re.search(r"FIELD_CUSTOM_VALIDATION_EXCEPTION:\s*([^\n;]+)", s)
        if msg_match:
            clean_msg = msg_match.group(1).split("(")[0].strip()
            return f"Validation Rule: {clean_msg}"

    if "CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY" in s:
        return "Apex Trigger Failure: Database trigger blocked this update"

    if "DUPLICATE_VALUE" in s:
        return "Duplicate Value: Record with this unique key already exists in Salesforce"

    if "STRING_TOO_LONG" in s:
        return "Text Too Long: Value exceeds maximum character length permitted by Salesforce"

    return s[:120]


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

    # Additive SQLite persistent queue & lock initialization
    res_key = f"{report_name}:{profile or 'sandbox'}:{target_object or 'All'}"
    persistent_job_id = None
    try:
        from core import job_store
        persistent_job_id = job_store.create_job(
            run_dir=run_dir,
            report_name=report_name,
            profile=profile or "sandbox",
            target_object=target_object,
            engine=engine,
            batch_size=batch_size,
            is_rollback=is_rollback,
            total_records=total_records_overall,
        )
        job_store.mark_job_running(persistent_job_id, total_records=total_records_overall)
        job_store.acquire_lock(res_key, persistent_job_id)
    except Exception as hook_err:
        logger.debug("job_store hook init skipped: %s", hook_err)

    if total_records_overall == 0:
        progress_state["status"] = "COMPLETED"
        progress_state["end_time"] = datetime.now().isoformat()
        _save_progress(run_dir, progress_state)
        if persistent_job_id:
            try:
                job_store.complete_job(persistent_job_id, "COMPLETED")
                job_store.release_lock(res_key, job_id=persistent_job_id)
            except Exception:
                pass
        return


    # 2. Execute sequentially per object
    overall_processed = 0
    overall_success = 0
    overall_failed = 0

    from salesforce.bulk_uploader import push_delta_to_sitetracker
    from salesforce.composite_uploader import push_delta_via_composite

    accumulated_failure_dfs: list[pd.DataFrame] = []

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

                    if persistent_job_id:
                        try:
                            from core import job_store
                            job_store.update_job_progress(
                                persistent_job_id,
                                processed=base_proc + c_proc,
                                successful=base_succ + c_succ,
                                failed=base_fail + c_fail,
                                current_chunk=info.get("current_chunk", 0),
                                total_chunks=info.get("total_chunks", 0),
                            )
                        except Exception:
                            pass

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
                try:
                    f_path_res = Path(res.failures_csv_path)
                    if f_path_res.exists():
                        raw_failure_text = f_path_res.read_text(encoding="utf-8", errors="replace")
                        sanitized_failure_text = sanitize_failure_csv(raw_failure_text)
                        f_df = pd.read_csv(io.StringIO(sanitized_failure_text), dtype=str, on_bad_lines="warn", engine="python")
                        if "sf__Id" in f_df.columns:
                            valid_id_mask = f_df["sf__Id"].astype(str).apply(is_valid_salesforce_id)
                            if valid_id_mask.any():
                                f_df = f_df[valid_id_mask].copy()

                        if "sf__Error" in f_df.columns:
                            f_df["Simplified_Cause"] = f_df["sf__Error"].fillna("Salesforce update rejected").apply(simplify_salesforce_error)
                            cols = [c for c in f_df.columns if c != "Simplified_Cause"]
                            insert_idx = 1 if "sf__Id" in cols else 0
                            cols.insert(insert_idx, "Simplified_Cause")
                            f_df = f_df[cols]
                            f_df.to_csv(f_path_res, index=False)

                        # Save per-object failure file so multi-object runs do not overwrite
                        clean_obj_tag = obj.replace(" ", "_").replace("__c", "")
                        per_obj_fail_name = f"bulk_upload_failures_{clean_obj_tag}.csv"
                        per_obj_fail_path = run_dir / per_obj_fail_name
                        f_df.to_csv(per_obj_fail_path, index=False)
                        object_meta[obj]["failures_file"] = per_obj_fail_name

                        # Add Target_Object column for combined report
                        f_df_combined = f_df.copy()
                        if "Target_Object" not in f_df_combined.columns:
                            f_df_combined.insert(0, "Target_Object", obj)
                        accumulated_failure_dfs.append(f_df_combined)
                    else:
                        object_meta[obj]["failures_file"] = res.failures_csv_path.name
                except Exception as e_enrich:
                    logger.warning("Could not enrich failures CSV with simplified cause: %s", e_enrich)
                    object_meta[obj]["failures_file"] = res.failures_csv_path.name

            if res.successes_csv_path:
                object_meta[obj]["successes_file"] = res.successes_csv_path.name

            # Tier 2: Post-Update Ground-Truth Live Verification
            if not is_rollback and res.successful_records > 0 and f_path.exists():
                try:
                    from salesforce.post_fetcher import fetch_live_records_by_ids
                    from core.post_validator import reconcile_post_update

                    input_df = pd.read_csv(f_path, dtype=str, keep_default_na=False)
                    if "Id" in input_df.columns:
                        rec_ids = [str(r).strip() for r in input_df["Id"].tolist() if str(r).strip()]
                        target_fields = [c for c in input_df.columns if c != "Id" and not c.startswith("Unnamed")]
                        if rec_ids and target_fields:
                            live_df = fetch_live_records_by_ids(
                                object_name=obj,
                                record_ids=rec_ids,
                                fields=target_fields,
                                profile=profile,
                            )
                            flc_path = run_dir / "field_level_changes.csv"
                            flc_df = pd.read_csv(flc_path, dtype=str) if flc_path.exists() else None
                            post_val = reconcile_post_update(
                                run_dir=run_dir,
                                object_name=obj,
                                live_df=live_df,
                                final_input_df=input_df,
                                field_changes_df=flc_df,
                            )
                            object_meta[obj]["post_validation"] = {
                                "verified_fields": post_val.verified_fields_count,
                                "total_fields": post_val.total_fields_checked,
                                "trigger_mutations": post_val.trigger_mutation_count,
                                "stale_records": post_val.stale_count,
                                "all_verified": post_val.all_verified,
                                "report_file": post_val.report_csv_path.name if post_val.report_csv_path else None,
                                "discrepancies_file": post_val.discrepancies_csv_path.name if post_val.discrepancies_csv_path else None,
                            }
                            audit.info(
                                f"Post-update validation completed for {obj}",
                                tag="POST_AUDIT",
                                Verified_Fields=f"{post_val.verified_fields_count}/{post_val.total_fields_checked}",
                                Mutations=post_val.trigger_mutation_count,
                                Stale=post_val.stale_count,
                            )
                except Exception as pv_err:
                    logger.warning("Post-update live verification skipped or failed for %s: %s", obj, pv_err)

            if res.failures:
                for fail_item in res.failures:
                    try:
                        raw_val = fail_item.get("sf__Error") or fail_item.get("Error")
                        if raw_val is None or pd.isna(raw_val):
                            raw_err = "Salesforce update rejected"
                        else:
                            raw_err = str(raw_val).strip()
                            if not raw_err or raw_err.lower() == "nan":
                                raw_err = "Salesforce update rejected"

                        rec_id_val = fail_item.get("sf__Id") or fail_item.get("Id")
                        if rec_id_val is None or pd.isna(rec_id_val):
                            rec_id = "UNKNOWN_ID"
                        else:
                            rec_id = str(rec_id_val).strip()

                        # Skip phantom rows from split multiline stack traces using universal SF ID validator
                        if rec_id != "UNKNOWN_ID" and not is_valid_salesforce_id(rec_id):
                            continue

                        simple_err = simplify_salesforce_error(raw_err)
                        audit.record_error(
                            record_id=rec_id,
                            object_name=obj,
                            message=f"{simple_err} (Raw: {raw_err[:120]})",
                            field_name=str(fail_item.get("sf__Fields") or fail_item.get("Fields") or "") or None,
                        )
                    except Exception as err_log_ex:
                        logger.warning("Could not log individual record failure: %s", err_log_ex)

            overall_processed += res.total_records
            overall_success += res.successful_records
            overall_failed += res.failed_records

            progress_state["processed_records_overall"] = overall_processed
            progress_state["successful_records_overall"] = overall_success
            progress_state["failed_records_overall"] = overall_failed
        if accumulated_failure_dfs:
            try:
                combined_fail_df = pd.concat(accumulated_failure_dfs, ignore_index=True)
                combined_fail_df.to_csv(run_dir / "bulk_upload_failures.csv", index=False)
            except Exception as e_comb:
                logger.warning("Could not write combined failures CSV: %s", e_comb)

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
        if persistent_job_id:
            try:
                from core import job_store
                from core.notifier import build_notification_payload, dispatch_notification
                job_store.complete_job(persistent_job_id, fin_status)
                notif_payload = build_notification_payload(
                    report_name=report_name,
                    profile=profile or "sandbox",
                    status=fin_status,
                    total_records=total_records_overall,
                    successful_records=overall_success,
                    failed_records=overall_failed,
                    run_dir=run_dir,
                    job_id=persistent_job_id,
                    is_rollback=is_rollback,
                    engine=engine,
                )
                dispatch_notification(**notif_payload, job_id=persistent_job_id)
            except Exception as n_err:
                logger.debug("Persistent job complete notification hook skipped: %s", n_err)

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

        if persistent_job_id:
            try:
                from core import job_store
                from core.notifier import build_notification_payload, dispatch_notification
                job_store.complete_job(persistent_job_id, "FAILED", error_summary=str(exc))
                notif_payload = build_notification_payload(
                    report_name=report_name,
                    profile=profile or "sandbox",
                    status="FAILURE",
                    total_records=total_records_overall,
                    successful_records=overall_success,
                    failed_records=overall_failed,
                    run_dir=run_dir,
                    job_id=persistent_job_id,
                    is_rollback=is_rollback,
                    error_summary=str(exc),
                    engine=engine,
                )
                dispatch_notification(**notif_payload, job_id=persistent_job_id)
            except Exception:
                pass

    finally:
        if persistent_job_id:
            try:
                from core import job_store
                job_store.release_lock(res_key, job_id=persistent_job_id)
            except Exception:
                pass

        key = str(run_dir.resolve())
        with _THREAD_LOCK:
            _ACTIVE_THREADS.pop(key, None)

