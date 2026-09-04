"""Salesforce Bulk API 2.0 uploader for pushing delta input files directly to Sitetracker."""

from dataclasses import dataclass, field
from datetime import datetime
import io
import json
import logging
from pathlib import Path
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


def clean_payload_for_salesforce(df: pd.DataFrame, report_name: str | None = None) -> list[dict]:
    """
    Ensure only valid Salesforce API field names and 'Id' are sent to Bulk API.
    Removes human-readable source column headers (e.g. 'Project Ref').
    Converts date fields to ISO 'YYYY-MM-DD' as required by Salesforce xsd:date.
    """
    valid_api_fields: set[str] = {"Id"}
    date_api_fields: set[str] = set()

    if report_name:
        try:
            mapping = MappingLoader(settings.MAPPING_FILE, report_name)
            m_df = mapping.load()
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
    cols_to_keep = []
    for col in df.columns:
        c_strip = str(col).strip()
        if c_strip == "Id" or c_strip in valid_api_fields or c_strip.endswith("__c"):
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
                try:
                    dt = pd.to_datetime(val_str, dayfirst=True)
                    return dt.strftime("%Y-%m-%d")
                except Exception:
                    return val_str

            clean_df[col] = clean_df[col].apply(_format_date)

    # Replace NaN with None for valid JSON serialization
    records = clean_df.where(pd.notnull(clean_df), None).to_dict("records")
    return records


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
def push_delta_to_sitetracker(
    csv_path: Path,
    object_name: str,
    report_name: str | None = None,
    operation: str = "update"
) -> BulkUploadResult:
    """
    Push a generated delta CSV to Sitetracker/Salesforce via Bulk API 2.0.

    Args:
        csv_path: Path to final_input_file.csv.
        object_name: Target Salesforce SObject API name (e.g. 'Site__c', 'Project__c').
        report_name: Optional report name for column filtering against mapping.
        operation: Bulk operation ('update', 'upsert', 'insert'). Default is 'update'.

    Returns:
        BulkUploadResult with job metrics and failure logs.
    """
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"Input file not found at: {csv_file}")

    try:
        df = pd.read_csv(csv_file, dtype=str)
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

    # 1. Clean payload
    records = clean_payload_for_salesforce(df, report_name)
    if not records:
        return BulkUploadResult(
            total_records=0,
            successful_records=0,
            failed_records=0,
            job_id="N/A_NO_VALID_RECORDS",
            all_succeeded=True
        )

    # 2. Connect to Salesforce
    sf = get_sf_connection()

    # Ensure object name formatting
    clean_obj = object_name.strip().replace(" ", "_")
    if clean_obj.lower() == "site":
        clean_obj = "sitetracker__Site__c"
    elif not clean_obj.endswith("__c") and clean_obj not in ("Account", "Contact", "Opportunity", "Lead", "Case"):
        clean_obj = f"{clean_obj}__c"

    bulk_type = getattr(sf.bulk2, clean_obj)
    logger.info(
        "Submitting %d records to Bulk API 2.0 (%s on %s)",
        len(records), operation, clean_obj
    )

    # 3. Execute Bulk Operation
    if operation == "update":
        job_results = bulk_type.update(records=records)
    elif operation == "upsert":
        job_results = bulk_type.upsert(records=records, external_id_field="Id")
    elif operation == "insert":
        job_results = bulk_type.insert(records=records)
    else:
        raise ValueError(f"Unsupported Bulk 2.0 operation: {operation}")

    # Aggregate batch results
    total_recs = sum(r.get("numberRecordsTotal", 0) for r in job_results)
    failed_recs = sum(r.get("numberRecordsFailed", 0) for r in job_results)
    processed_recs = sum(r.get("numberRecordsProcessed", 0) for r in job_results)
    job_ids = [r.get("job_id", "") for r in job_results if r.get("job_id")]
    primary_job_id = job_ids[0] if job_ids else "UNKNOWN_JOB"
    success_recs = max(0, processed_recs - failed_recs)

    # 4. Handle record-level failures
    failures_csv_path = None
    failures_list = []
    if failed_recs > 0 and primary_job_id != "UNKNOWN_JOB":
        try:
            failed_csv_content = bulk_type.get_failed_records(primary_job_id)
            if failed_csv_content:
                failures_csv_path = csv_file.parent / "bulk_upload_failures.csv"
                failures_csv_path.write_text(failed_csv_content, encoding="utf-8")
                logger.warning(
                    "%d records failed in Bulk API 2.0 upload. Saved failure details to %s",
                    failed_recs, failures_csv_path
                )
                # Parse failures into list of dicts for UI preview
                fail_df = pd.read_csv(io.StringIO(failed_csv_content), dtype=str)
                failures_list = fail_df.to_dict("records")
        except Exception as e:
            logger.error("Failed to retrieve Bulk API 2.0 failure details: %s", e)

    # 5. Write execution audit log (bulk_upload_audit.json)
    audit_data = {
        "timestamp": datetime.now().isoformat(),
        "report_name": report_name,
        "object_name": clean_obj,
        "operation": operation,
        "job_id": primary_job_id,
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
