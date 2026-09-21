"""Salesforce REST Composite SObject Collections Uploader.

Provides synchronous, high-speed record updates (1.5 - 2.5s per batch)
using PATCH /services/data/vXX.X/composite/sobjects.
Ideal for datasets under 2,000 records to eliminate Bulk API 2.0 queue delays.
"""

from collections.abc import Callable
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any
import pandas as pd

from config import settings
from core.mapping_loader import MappingLoader
from salesforce.bulk_uploader import BulkUploadResult, clean_payload_for_salesforce
from salesforce.data_fetcher import normalize_salesforce_object_name
from salesforce.sf_client import get_sf_connection

logger = logging.getLogger(__name__)


def push_delta_via_composite(
    csv_path: Path | str,
    object_name: str,
    report_name: str | None = None,
    is_rollback: bool = False,
    profile: str | None = None,
    batch_size: int = 15,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> BulkUploadResult:
    """Push a delta or rollback CSV to Salesforce using REST Composite SObject Collections.

    Processes in batches (default: 50 records) synchronously.
    Each batch runs in an isolated Apex transaction (~50-70 DMLs), safely below 150 DMLs.
    Total runtime for ~350 records is 10-20 seconds instead of 10 minutes in Bulk 2.0.

    Args:
        csv_path: Path to payload CSV.
        object_name: Target Salesforce object (e.g. 'BT Project' or 'BT_Project__c').
        report_name: Report name for field schema filtering.
        is_rollback: Whether this is a rollback operation (null-clearing).
        profile: Optional Salesforce profile ('sandbox', 'partial', 'prod').
        batch_size: Records per composite request (max 200, recommended 50 for Sitetracker triggers).
        progress_callback: Optional callable receiving progress status dict.

    Returns:
        BulkUploadResult with aggregated metrics and failures.
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
        logger.info("Empty input file; 0 records to upload via Composite Collections.")
        return BulkUploadResult(
            total_records=0,
            successful_records=0,
            failed_records=0,
            job_id="REST_EMPTY",
            all_succeeded=True,
        )

    # 1. Clean payload with object-level field isolation
    records = clean_payload_for_salesforce(
        df, report_name, is_rollback=is_rb, target_object=object_name
    )
    if not records:
        return BulkUploadResult(
            total_records=0,
            successful_records=0,
            failed_records=0,
            job_id="REST_NO_VALID_RECORDS",
            all_succeeded=True,
        )

    # 2. Canonical SObject API name
    clean_obj = normalize_salesforce_object_name(object_name)
    if not clean_obj.endswith("__c") and clean_obj not in (
        "Account", "Contact", "Opportunity", "Lead", "Case"
    ):
        clean_obj = f"{clean_obj}__c"

    # 3. Connect to Salesforce
    sf = get_sf_connection(profile=profile)

    # REST Composite API JSON semantics:
    #   "Field__c": "value"  →  UPDATE the field
    #   "Field__c": null     →  WIPE / CLEAR the field in Salesforce
    #   key omitted          →  LEAVE the field 100% UNTOUCHED
    #
    # To prevent accidental data loss, we OMIT keys that have no value
    # (None or empty string) unless it's an explicit wipe (#N/A) or rollback.
    prepared_records: list[dict[str, Any]] = []
    omitted_field_count = 0
    for r in records:
        rec_clean: dict[str, Any] = {"attributes": {"type": clean_obj}, "Id": r["Id"]}
        for k, v in r.items():
            if k == "Id":
                continue  # Already added above
            if v == "#N/A" or (is_rb and (v is None or str(v).strip() == "")):
                rec_clean[k] = None  # Explicit wipe intended
            elif v is not None and str(v).strip() != "":
                rec_clean[k] = v  # Real value update
            else:
                omitted_field_count += 1  # Omit key entirely — leave Salesforce untouched
        prepared_records.append(rec_clean)
    if omitted_field_count:
        logger.debug(
            "Key-omission safeguard: omitted %d empty fields across %d records "
            "to prevent accidental data wipe",
            omitted_field_count, len(prepared_records),
        )

    # 4. Chunk into batches of batch_size (default 50)
    batch_size = max(1, min(batch_size, 200))
    chunks = [
        prepared_records[i : i + batch_size]
        for i in range(0, len(prepared_records), batch_size)
    ]
    total_chunks = len(chunks)

    total_records = len(prepared_records)

    # Build ID-to-primary-key lookup and record lookup for Dataloader.io audit reporting
    pk_col_found = None
    if report_name:
        try:
            loader = MappingLoader(settings.MAPPING_FILE, report_name)
            pk_src, _ = loader.primary_keys()
            if pk_src in df.columns:
                pk_col_found = pk_src
        except Exception:
            pass

    candidate_pks = [
        pk_col_found, "Project Reference", "Project Ref", "Primary_Key", "TM Cell ID",
        "Site ID", "Site_ID__c", "Cell ID", "Site Reference",
    ]
    pk_cols = [c for c in candidate_pks if c and c in df.columns]

    id_to_pk: dict[str, str] = {}
    id_to_rec: dict[str, dict[str, Any]] = {}
    for r in df.to_dict("records"):
        r_id = str(r.get("Id", "")).strip()
        if r_id:
            id_to_rec[r_id] = r
            for pk_c in pk_cols:
                if pk_c in r and str(r[pk_c]).strip():
                    id_to_pk[r_id] = str(r[pk_c]).strip()
                    break

    # 4. Execute batches
    successful_records = 0
    failed_records = 0
    failures_list: list[dict[str, Any]] = []
    successes_list: list[dict[str, Any]] = []

    logger.info(
        "Starting REST Composite ingest for %s: %d records in %d chunks (batch_size=%d)",
        clean_obj, total_records, total_chunks, batch_size
    )

    for chunk_idx, chunk in enumerate(chunks, 1):
        payload = {"allOrNone": False, "records": chunk}
        chunk_start = (chunk_idx - 1) * batch_size + 1
        chunk_end = min(chunk_idx * batch_size, total_records)

        # Notify before executing request so UI immediately reflects active work
        if progress_callback:
            try:
                progress_callback({
                    "stage": "in_flight",
                    "object_name": object_name,
                    "clean_object": clean_obj,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "chunk_size": len(chunk),
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "processed_records": successful_records + failed_records,
                    "total_records": total_records,
                    "successful_records": successful_records,
                    "failed_records": failed_records,
                })
            except Exception as cb_err:
                logger.warning("Error in composite progress_callback (in_flight): %s", cb_err)

        try:
            # PATCH /services/data/vXX.X/composite/sobjects with explicit timeout
            response = sf.restful("composite/sobjects", method="PATCH", json=payload, timeout=180)
            if not response or not isinstance(response, list):
                raise ValueError(f"Unexpected response format from composite/sobjects: {response}")

            for item in response:
                is_success = item.get("success", False)
                rec_id = item.get("id") or "UNKNOWN_ID"
                pk_val = id_to_pk.get(rec_id, "")
                if is_success:
                    successful_records += 1
                    succ_row = {
                        "Record_Id": rec_id,
                        "Primary_Key": pk_val,
                        "Status": "SUCCESS",
                    }
                    # Include target field values sent
                    if rec_id in id_to_rec:
                        for k, v in id_to_rec[rec_id].items():
                            if k not in ("Id", "Record_Id", "sf__Id", "Primary_Key") and k not in pk_cols:
                                succ_row[k] = v
                    successes_list.append(succ_row)
                else:
                    failed_records += 1
                    err_msgs = []
                    err_codes = []
                    err_fields = []
                    for e in item.get("errors", []):
                        err_msgs.append(e.get("message", ""))
                        err_codes.append(e.get("statusCode", ""))
                        if e.get("fields"):
                            err_fields.extend(e.get("fields", []))

                    failures_list.append({
                        "Record_Id": rec_id,
                        "Primary_Key": pk_val,
                        "sf__Error": f"{'; '.join(err_codes)}: {'; '.join(err_msgs)}",
                        "sf__Fields": ", ".join(err_fields) if err_fields else "",
                        "sf__Id": rec_id,
                    })

        except Exception as exc:
            logger.error("Error executing Composite batch %d/%d for %s: %s", chunk_idx, total_chunks, clean_obj, exc)
            for rec in chunk:
                failed_records += 1
                r_id = rec.get("Id", "UNKNOWN_ID")
                failures_list.append({
                    "Record_Id": r_id,
                    "Primary_Key": id_to_pk.get(r_id, ""),
                    "sf__Error": f"HTTP_BATCH_ERROR: {exc}",
                    "sf__Fields": "",
                    "sf__Id": r_id,
                })

        # Progress reporting callback: chunk completed
        if progress_callback:
            try:
                progress_callback({
                    "stage": "completed_chunk",
                    "object_name": object_name,
                    "clean_object": clean_obj,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "chunk_size": len(chunk),
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "processed_records": successful_records + failed_records,
                    "total_records": total_records,
                    "successful_records": successful_records,
                    "failed_records": failed_records,
                })
            except Exception as cb_err:
                logger.warning("Error in composite progress_callback (completed): %s", cb_err)

    # 5. Save Dataloader.io audit files: success and error records
    successes_csv_path = None
    if successes_list:
        successes_csv_path = csv_file.parent / "salesforce_success_records.csv"
        try:
            succ_df = pd.DataFrame(successes_list)
            # Ensure single Record_Id column (drop any accidental Id or sf__Id duplicate columns)
            succ_df = succ_df.drop(columns=[c for c in ("Id", "sf__Id") if c in succ_df.columns], errors="ignore")
            cols = ["Record_Id", "Primary_Key"] + [c for c in succ_df.columns if c not in ("Record_Id", "Primary_Key")]
            succ_df = succ_df[cols]
            succ_df.to_csv(successes_csv_path, index=False)
            logger.info("Saved %d success records to %s", len(successes_list), successes_csv_path)
        except Exception as e:
            logger.error("Failed to write salesforce_success_records.csv: %s", e)

    failures_csv_path = None
    if failures_list:
        failures_csv_path = csv_file.parent / "salesforce_error_records.csv"
        legacy_failures_path = csv_file.parent / "bulk_upload_failures.csv"
        try:
            fail_df = pd.DataFrame(failures_list)
            # Legacy internal file retains sf__Id for backwards compatibility
            fail_df.to_csv(legacy_failures_path, index=False)
            # User-facing file has single clean Record_Id column
            clean_fail_df = fail_df.drop(columns=[c for c in ("Id", "sf__Id") if c in fail_df.columns], errors="ignore")
            cols = ["Record_Id", "Primary_Key"] + [c for c in clean_fail_df.columns if c not in ("Record_Id", "Primary_Key")]
            clean_fail_df = clean_fail_df[cols]
            clean_fail_df.to_csv(failures_csv_path, index=False)
            logger.warning(
                "%d records failed in Composite upload. Saved details to %s",
                failed_records, failures_csv_path
            )
        except Exception as e:
            logger.error("Failed to write composite failures CSV: %s", e)

    # 6. Save audit JSON
    audit_path = csv_file.parent / "bulk_upload_audit.json"
    audit_data = {
        "timestamp": datetime.now().isoformat(),
        "report_name": report_name,
        "object_name": clean_obj,
        "engine": "REST_COMPOSITE_SOBJECTS",
        "operation": "update",
        "job_id": f"REST_COMPOSITE_{clean_obj}_{datetime.now().strftime('%H%M%S')}",
        "batch_size": batch_size,
        "total_records": total_records,
        "successful_records": successful_records,
        "failed_records": failed_records,
        "all_succeeded": failed_records == 0,
        "successes_file": str(successes_csv_path.name) if successes_csv_path else None,
        "failures_file": str(failures_csv_path.name) if failures_csv_path else None,
    }
    try:
        audit_path.write_text(json.dumps(audit_data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to write composite upload audit log: %s", e)

    return BulkUploadResult(
        total_records=total_records,
        successful_records=successful_records,
        failed_records=failed_records,
        job_id=audit_data["job_id"],
        all_succeeded=(failed_records == 0),
        failures_csv_path=failures_csv_path,
        failures=failures_list,
        successes_csv_path=successes_csv_path,
        successes=successes_list,
    )
