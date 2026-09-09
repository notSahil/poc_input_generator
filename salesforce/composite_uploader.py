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
    batch_size: int = 50,
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

    # In REST Composite API, null fields are explicitly wiped by sending None (JSON null)
    # Convert '#N/A' strings from clean_payload to None
    prepared_records: list[dict[str, Any]] = []
    for r in records:
        rec_clean: dict[str, Any] = {"attributes": {"type": clean_obj}}
        for k, v in r.items():
            if v == "#N/A" or (is_rb and (v is None or str(v).strip() == "")):
                rec_clean[k] = None
            else:
                rec_clean[k] = v
        prepared_records.append(rec_clean)

    # 4. Chunk into batches of batch_size (default 50)
    batch_size = max(1, min(batch_size, 200))
    chunks = [
        prepared_records[i : i + batch_size]
        for i in range(0, len(prepared_records), batch_size)
    ]
    total_chunks = len(chunks)

    total_records = len(prepared_records)
    successful_records = 0
    failed_records = 0
    failures_list: list[dict[str, Any]] = []

    logger.info(
        "Starting REST Composite ingest for %s: %d records in %d chunks (batch_size=%d)",
        clean_obj, total_records, total_chunks, batch_size
    )

    for chunk_idx, chunk in enumerate(chunks, 1):
        payload = {"allOrNone": False, "records": chunk}

        try:
            # PATCH /services/data/vXX.X/composite/sobjects
            response = sf.restful("composite/sobjects", method="PATCH", json=payload)
            if not response or not isinstance(response, list):
                raise ValueError(f"Unexpected response format from composite/sobjects: {response}")

            for item in response:
                is_success = item.get("success", False)
                rec_id = item.get("id") or "UNKNOWN_ID"
                if is_success:
                    successful_records += 1
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
                        "sf__Id": rec_id,
                        "sf__Error": f"{'; '.join(err_codes)}: {'; '.join(err_msgs)}",
                        "sf__Fields": ", ".join(err_fields) if err_fields else "",
                    })

        except Exception as exc:
            logger.error("Error executing Composite batch %d/%d for %s: %s", chunk_idx, total_chunks, clean_obj, exc)
            for rec in chunk:
                failed_records += 1
                failures_list.append({
                    "sf__Id": rec.get("Id", "UNKNOWN_ID"),
                    "sf__Error": f"HTTP_BATCH_ERROR: {exc}",
                    "sf__Fields": "",
                })

        # Progress reporting callback
        if progress_callback:
            try:
                progress_callback({
                    "object_name": object_name,
                    "clean_object": clean_obj,
                    "current_chunk": chunk_idx,
                    "total_chunks": total_chunks,
                    "chunk_size": len(chunk),
                    "processed_records": successful_records + failed_records,
                    "total_records": total_records,
                    "successful_records": successful_records,
                    "failed_records": failed_records,
                })
            except Exception as cb_err:
                logger.warning("Error in composite progress_callback: %s", cb_err)

    # 5. Save failures CSV if any failed
    failures_csv_path = None
    if failures_list:
        failures_csv_path = csv_file.parent / "bulk_upload_failures.csv"
        try:
            fail_df = pd.DataFrame(failures_list)
            fail_df.to_csv(failures_csv_path, index=False)
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
    )
