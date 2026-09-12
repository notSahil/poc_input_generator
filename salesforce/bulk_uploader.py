"""Salesforce Bulk API 2.0 uploader for pushing delta input files directly to Sitetracker."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import io
import json
import logging
from pathlib import Path
from typing import Any
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from config import settings
from core.mapping_loader import MappingLoader
from salesforce.sf_client import get_sf_connection

logger = logging.getLogger(__name__)


@dataclass
class BulkUploadResult:
    """Structured result of a Bulk API 2.0 upload job."""
    total_records: int
    successful_records: int
    failed_records: int
    job_id: str
    all_succeeded: bool
    failures_csv_path: Path | None = None
    error_summary: str | None = None
    failures: list[dict] = field(default_factory=list)


def clean_payload_for_salesforce(
    df: pd.DataFrame,
    report_name: str | None = None,
    is_rollback: bool = False,
    target_object: str | None = None,
) -> list[dict]:
    """
    Ensure only valid Salesforce API field names and 'Id' are sent to Bulk API.
    Removes human-readable source column headers (e.g. 'Project Ref').
    Converts date fields to ISO 'YYYY-MM-DD' as required by Salesforce xsd:date.
    When target_object is specified, ensures ONLY API fields belonging to that object are included.
    """
    valid_api_fields: set[str] = {"Id"}
    date_api_fields: set[str] = set()

    if report_name:
        try:
            mapping = MappingLoader(settings.MAPPING_FILE, report_name)
            m_df = mapping.load()
            if target_object and "Object Name" in m_df.columns:
                from salesforce.data_fetcher import normalize_salesforce_object_name
                norm_target = normalize_salesforce_object_name(target_object).lower()
                filtered = m_df[
                    m_df["Object Name"].astype(str).str.strip().apply(
                        lambda o: normalize_salesforce_object_name(o).lower() == norm_target
                    )
                ]
                if not filtered.empty:
                    m_df = filtered

            for _, row in m_df.iterrows():
                api_name = str(row.get("API Name", "")).strip()
                dtype = str(row.get("Data Type", "")).strip()
                if api_name and api_name.lower() != "nan":
                    valid_api_fields.add(api_name)
                    if dtype.lower() == "date":
                        date_api_fields.add(api_name)
        except Exception as e:
            logger.warning("Could not load mapping for API filtering: %s", e)

    # Filter columns
    has_specific_fields = len(valid_api_fields.difference({"Id"})) > 0
    cols_to_keep = []
    for col in df.columns:
        c_strip = str(col).strip()
        if c_strip == "Id" or (c_strip in valid_api_fields if has_specific_fields else c_strip.endswith("__c")):
            cols_to_keep.append(col)

    if not cols_to_keep or "Id" not in cols_to_keep:
        cols_to_keep = list(df.columns)

    clean_df = df[cols_to_keep].dropna(how="all").copy()

    # Convert date values to ISO format (YYYY-MM-DD) for Salesforce xsd:date
    for col in clean_df.columns:
        c_strip = str(col).strip()
        if c_strip in date_api_fields or "date" in c_strip.lower():
            def _format_date(val):
                if pd.isna(val) or not str(val).strip() or str(val).lower() == "nan":
                    return None
                val_str = str(val).strip()
                if val_str == "#N/A":
                    return "#N/A"
                try:
                    dt = pd.to_datetime(val_str, dayfirst=True)
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    return val_str

            clean_df[col] = clean_df[col].apply(_format_date)

    # For rollback payloads, convert any empty/null/None/NaN values to '#N/A'
    # so Salesforce Bulk API 2.0 explicitly clears the fields back to null instead of ignoring them.
    if is_rollback:
        for c in clean_df.columns:
            if c != "Id":
                clean_df[c] = clean_df[c].apply(
                    lambda v: "#N/A" if (pd.isna(v) or not str(v).strip() or str(v).lower() in ("none", "nan")) else v
                )
    else:
        # Convert empty strings to None while preserving explicit '#N/A' null-wipes
        clean_df = clean_df.replace({"": None})

    records = clean_df.where(pd.notnull(clean_df), None).to_dict("records")
    return records


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def push_delta_to_sitetracker(
    csv_path: Path,
    object_name: str,
    report_name: str | None = None,
    operation: str = "update",
    is_rollback: bool = False,
    profile: str | None = None,
    batch_size: int = 25,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> BulkUploadResult:
    """
    Push a generated delta CSV to Sitetracker/Salesforce via Bulk API 2.0.

    Args:
        csv_path: Path to final_input_file.csv or rollback_file.csv.
        object_name: Target Salesforce SObject API name (e.g. 'Site__c', 'Project__c').
        report_name: Optional report name for column filtering against mapping.
        operation: Bulk operation ('update', 'upsert', 'insert'). Default is 'update'.
        is_rollback: Whether this upload is a rollback operation (clears fields with #N/A).
        profile: Optional Salesforce profile name ('sandbox', 'partial', 'prod').
        batch_size: Number of records per Apex transaction context (default 25 to stay within 150 DML limit).
        progress_callback: Optional callable receiving progress status dict per chunk.

    Returns:
        BulkUploadResult with job metrics and failure logs.
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"Input file not found at: {csv_file}")

    is_rb = is_rollback or ("rollback" in csv_file.name.lower())

    try:
        df = pd.read_csv(csv_file, dtype=str, keep_default_na=False)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame()

    if df.empty:
        logger.info("Empty input file; 0 records to upload.")
        return BulkUploadResult(
            total_records=0,
            successful_records=0,
            failed_records=0,
            job_id="N/A_EMPTY",
            all_succeeded=True
        )

    # 1. Clean payload with object-level field isolation
    records = clean_payload_for_salesforce(df, report_name, is_rollback=is_rb, target_object=object_name)
    if not records:
        return BulkUploadResult(
            total_records=0,
            successful_records=0,
            failed_records=0,
            job_id="N/A_NO_VALID_RECORDS",
            all_succeeded=True
        )

    # 2. Connect to Salesforce with environment profile awareness
    sf = get_sf_connection(profile=profile)

    # Ensure canonical Salesforce object name formatting (e.g. Project -> sitetracker__Project__c)
    from salesforce.data_fetcher import normalize_salesforce_object_name
    clean_obj = normalize_salesforce_object_name(object_name)
    if not clean_obj.endswith("__c") and clean_obj not in ("Account", "Contact", "Opportunity", "Lead", "Case"):
        clean_obj = f"{clean_obj}__c"

    bulk_type = getattr(sf.bulk2, clean_obj)
    logger.info(
        "Submitting %d records to Bulk API 2.0 (%s on %s, batch_size=%d)",
        len(records), operation, clean_obj, batch_size
    )

    # 3. Execute Bulk Operation with safe micro-batch chunking & real-time progress callbacks
    effective_batch = batch_size if (batch_size and batch_size > 0) else len(records)
    chunks = [records[i : i + effective_batch] for i in range(0, len(records), effective_batch)]
    total_chunks = len(chunks)
    job_results = []
    processed_count = 0
    success_count = 0
    failed_count = 0

    for chunk_idx, chunk in enumerate(chunks, 1):
        chunk_start = (chunk_idx - 1) * effective_batch + 1
        chunk_end = min(chunk_idx * effective_batch, len(records))
        try:
            if operation == "update":
                res_list = bulk_type.update(records=chunk)
            elif operation == "upsert":
                res_list = bulk_type.upsert(records=chunk, external_id_field="Id")
            elif operation == "insert":
                res_list = bulk_type.insert(records=chunk)
            else:
                raise ValueError(f"Unsupported Bulk 2.0 operation: {operation}")

            job_results.extend(res_list)
            c_proc = sum(r.get("numberRecordsProcessed", 0) for r in res_list)
            c_fail = sum(r.get("numberRecordsFailed", 0) for r in res_list)
            c_succ = max(0, c_proc - c_fail)
            processed_count += c_proc
            failed_count += c_fail
            success_count += c_succ
        except Exception as e:
            logger.error("Bulk API 2.0 job submission failed for %s chunk %d/%d: %s", clean_obj, chunk_idx, total_chunks, e)
            job_results.append({
                "numberRecordsTotal": len(chunk),
                "numberRecordsProcessed": len(chunk),
                "numberRecordsFailed": len(chunk),
                "job_id": f"FAILED_CHUNK_{chunk_idx}",
            })
            processed_count += len(chunk)
            failed_count += len(chunk)

        if progress_callback:
            progress_callback({
                "stage": "completed_chunk",
                "current_chunk": chunk_idx,
                "total_chunks": total_chunks,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "chunk_size": len(chunk),
                "processed_records": processed_count,
                "successful_records": success_count,
                "failed_records": failed_count,
            })

    # Aggregate batch results across all chunks
    total_recs = sum(r.get("numberRecordsTotal", 0) for r in job_results)
    failed_recs = sum(r.get("numberRecordsFailed", 0) for r in job_results)
    processed_recs = sum(r.get("numberRecordsProcessed", 0) for r in job_results)
    job_ids = [r.get("job_id", "") for r in job_results if r.get("job_id")]
    primary_job_id = ", ".join(job_ids) if job_ids else "UNKNOWN_JOB"
    success_recs = max(0, processed_recs - failed_recs)

    # 4. Handle record-level failures across all chunk jobs
    failures_csv_path = None
    failures_list = []
    if failed_recs > 0:
        failures_csv_path = csv_file.parent / "bulk_upload_failures.csv"
        aggregated_fail_content = []
        for j_id in job_ids:
            if not j_id:
                continue
            try:
                failed_csv_content = bulk_type.get_failed_records(j_id)
                if failed_csv_content:
                    aggregated_fail_content.append(failed_csv_content.strip())
                    # Parse failures into list of dicts for UI preview safely (using python engine to handle commas in error strings)
                    fail_df = pd.read_csv(
                        io.StringIO(failed_csv_content),
                        dtype=str,
                        on_bad_lines="skip",
                        engine="python"
                    )
                    failures_list.extend(fail_df.to_dict("records"))
            except Exception as e:
                logger.warning("Could not retrieve Bulk API 2.0 failure details for job %s: %s", j_id, e)

        if aggregated_fail_content:
            try:
                failures_csv_path.write_text("\n".join(aggregated_fail_content), encoding="utf-8")
                logger.warning(
                    "%d records failed in Bulk API 2.0 upload. Saved failure details to %s",
                    failed_recs, failures_csv_path
                )
            except Exception as e:
                logger.error("Failed to write failures CSV: %s", e)

    # 5. Write execution audit log (bulk_upload_audit.json)
    audit_data = {
        "timestamp": datetime.now().isoformat(),
        "report_name": report_name,
        "object_name": clean_obj,
        "operation": operation,
        "job_id": primary_job_id,
        "batch_size": batch_size,
        "total_records": total_recs if total_recs > 0 else len(records),
        "successful_records": success_recs,
        "failed_records": failed_recs,
        "all_succeeded": (failed_recs == 0),
        "failures_file": str(failures_csv_path.name) if failures_csv_path else None
    }
    audit_path = csv_file.parent / "bulk_upload_audit.json"
    try:
        audit_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
        logger.info("Saved bulk upload audit log to %s", audit_path)
    except Exception as e:
        logger.warning("Could not write bulk upload audit log: %s", e)

    return BulkUploadResult(
        total_records=total_recs if total_recs > 0 else len(records),
        successful_records=success_recs,
        failed_records=failed_recs,
        job_id=primary_job_id,
        all_succeeded=(failed_recs == 0),
        failures_csv_path=failures_csv_path,
        failures=failures_list
    )


def push_multi_object_deltas_to_sitetracker(
    run_dir: Path,
    report_name: str,
    operation: str = "update",
    is_rollback: bool = False,
    profile: str | None = None,
    batch_size: int = 25,
) -> dict[str, BulkUploadResult]:
    """
    Push dedicated delta files for all objects in a multi-object report sequentially.

    Args:
        run_dir: Directory containing run artifacts (e.g. final_input_file_*.csv).
        report_name: Report name (e.g. 'Apollo 10G').
        operation: Bulk operation ('update', 'upsert', 'insert'). Default is 'update'.
        is_rollback: Whether this upload is a rollback operation.
        profile: Optional Salesforce profile ('sandbox', 'partial', 'prod').
        batch_size: Number of records per batch chunk (default 25).

    Returns:
        dict mapping object_name -> BulkUploadResult.
    """
    mapping = MappingLoader(settings.MAPPING_FILE, report_name)
    objects = mapping.objects()
    results: dict[str, BulkUploadResult] = {}

    run_path = Path(run_dir)
    file_prefix = "rollback_file" if is_rollback else "final_input_file"

    for obj in objects:
        clean_obj = obj.strip().replace(" ", "_")
        target_file = run_path / f"{file_prefix}_{clean_obj}.csv"

        # Fallback / self-healing: if dedicated file doesn't exist, extract from main file
        if not target_file.exists():
            main_file = run_path / f"{file_prefix}.csv"
            if main_file.exists():
                try:
                    df_main = pd.read_csv(main_file, dtype=str, keep_default_na=False)
                    from salesforce.data_fetcher import normalize_salesforce_object_name
                    norm_target = normalize_salesforce_object_name(obj).lower()
                    m_df = mapping.load()
                    obj_fields = set(
                        m_df[
                            m_df["Object Name"].astype(str).str.strip().apply(
                                lambda o: normalize_salesforce_object_name(o).lower() == norm_target
                            )
                        ]["API Name"].dropna().astype(str).str.strip().tolist()
                    )
                    cols = [c for c in df_main.columns if c in ("Id", "Project Ref", "Project Reference") or c in obj_fields]
                    field_cols = [c for c in cols if c not in ("Id", "Project Ref", "Project Reference")]
                    if field_cols:
                        has_changes = df_main[field_cols].apply(
                            lambda row: any(str(v).strip() and str(v).strip().lower() != "nan" for v in row if pd.notna(v)),
                            axis=1
                        )
                        filtered_df = df_main.loc[has_changes, cols]
                        if not filtered_df.empty:
                            filtered_df.to_csv(target_file, index=False)
                except Exception as e:
                    logger.warning("Could not dynamically extract %s: %s", target_file.name, e)

        if not target_file.exists():
            logger.info("No payload file found for object '%s', skipping.", obj)
            continue

        try:
            df_check = pd.read_csv(target_file, dtype=str, keep_default_na=False)
        except Exception:
            df_check = pd.DataFrame()

        if df_check.empty:
            logger.info("Payload for object '%s' has 0 records, skipping.", obj)
            continue

        # Execute push for this object with error shielding
        try:
            res = push_delta_to_sitetracker(
                csv_path=target_file,
                object_name=obj,
                report_name=report_name,
                operation=operation,
                is_rollback=is_rollback,
                profile=profile,
                batch_size=batch_size,
            )
            results[obj] = res
        except Exception as e:
            logger.error("Failed during bulk push for object %s: %s", obj, e)
            results[obj] = BulkUploadResult(
                total_records=len(df_check),
                successful_records=0,
                failed_records=len(df_check),
                job_id="ERROR_BATCH",
                all_succeeded=False,
                error_summary=str(e),
            )

    return results

