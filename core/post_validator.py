"""Post-Update Live Salesforce Validation & Discrepancy Reconciliation Engine.

Compares expected updates against live Salesforce records to detect:
1. Exact verified matches.
2. Silent Apex trigger / workflow rule mutations.
3. Unmodified / stale records.
4. Failed null wipes.
"""

from datetime import datetime
import logging
from pathlib import Path
from typing import Any
import pandas as pd

from core.models import PostUpdateFieldResult, PostUpdateValidationResult
from core.normalizer import DataNormalizer

logger = logging.getLogger(__name__)


def evaluate_field_match(
    expected_val: Any,
    live_val: Any,
    old_val: Any = "",
    data_type: str = "text",
) -> tuple[str, str]:
    """Compare expected value vs live Salesforce value using semantic equivalence.

    Returns:
        tuple[str, str]: (Status, Notes/Reason)
        Statuses:
          - 'VERIFIED_MATCH'
          - 'TRIGGER_MUTATION'
          - 'UNMODIFIED_STALE'
          - 'NULL_WIPE_FAILED'
    """
    exp_str = DataNormalizer.normalize_value(expected_val)
    live_str = DataNormalizer.normalize_value(live_val)
    old_str = DataNormalizer.normalize_value(old_val)

    # 1. Null / Blank Wipe Check (#N/A or empty expected)
    if exp_str in ("#N/A", ""):
        if live_str == "":
            return "VERIFIED_MATCH", ""
        return "NULL_WIPE_FAILED", f"Expected field clear (#N/A), but Salesforce still holds '{live_str}'"

    # 2. Date Comparison
    if data_type == "date" or "/" in exp_str or "-" in exp_str:
        exp_uk, exp_ok = DataNormalizer.normalize_date_uk(exp_str)
        live_uk, live_ok = DataNormalizer.normalize_date_uk(live_str)
        if exp_ok and live_ok and exp_uk and live_uk:
            if exp_uk == live_uk:
                return "VERIFIED_MATCH", ""
            # Check if unchanged from old
            old_uk, old_ok = DataNormalizer.normalize_date_uk(old_str)
            if old_ok and old_uk == live_uk:
                return "UNMODIFIED_STALE", f"Date remained at pre-update value '{old_str}'"
            return "TRIGGER_MUTATION", f"Date altered from expected '{exp_str}' to '{live_str}' in Salesforce"

    # 3. Number Comparison
    if data_type == "number":
        exp_num, exp_num_ok = DataNormalizer.validate_number(exp_str)
        live_num, live_num_ok = DataNormalizer.validate_number(live_str)
        if exp_num_ok and live_num_ok:
            try:
                if float(exp_num) == float(live_num):
                    return "VERIFIED_MATCH", ""
            except (ValueError, TypeError):
                pass
            old_num, old_num_ok = DataNormalizer.validate_number(old_str)
            if old_num_ok:
                try:
                    if float(old_num) == float(live_num):
                        return "UNMODIFIED_STALE", f"Number remained at pre-update value '{old_str}'"
                except (ValueError, TypeError):
                    pass
            return "TRIGGER_MUTATION", f"Number altered from expected '{exp_str}' to '{live_str}'"

    # 4. Boolean Comparison
    if data_type == "boolean" or exp_str.lower() in ("true", "false", "yes", "no"):
        exp_bool, exp_b_ok = DataNormalizer.validate_boolean(exp_str)
        live_bool, live_b_ok = DataNormalizer.validate_boolean(live_str)
        if exp_b_ok and live_b_ok:
            if exp_bool == live_bool:
                return "VERIFIED_MATCH", ""
            old_bool, old_b_ok = DataNormalizer.validate_boolean(old_str)
            if old_b_ok and old_bool == live_bool:
                return "UNMODIFIED_STALE", f"Boolean remained at pre-update value '{old_str}'"
            return "TRIGGER_MUTATION", f"Boolean altered from expected '{exp_str}' to '{live_str}'"

    # 5. Text & Default Semantic Comparison
    exp_comp = DataNormalizer.comparable_text(exp_str)
    live_comp = DataNormalizer.comparable_text(live_str)
    old_comp = DataNormalizer.comparable_text(old_str)

    if exp_comp == live_comp:
        return "VERIFIED_MATCH", ""

    if old_comp and live_comp == old_comp:
        return "UNMODIFIED_STALE", f"Field remained at pre-update value '{old_str}'"

    return "TRIGGER_MUTATION", f"Field altered from expected '{exp_str}' to '{live_str}'"


def reconcile_post_update(
    run_dir: Path,
    object_name: str,
    live_df: pd.DataFrame,
    final_input_df: pd.DataFrame,
    field_changes_df: pd.DataFrame | None = None,
    pk_column: str = "Project Reference",
) -> PostUpdateValidationResult:
    """Audit live Salesforce records against expected changes and generate reports.

    Args:
        run_dir: Path to timestamped run directory.
        object_name: Salesforce object name (e.g. 'sitetracker__Site__c').
        live_df: DataFrame of live records fetched from Salesforce.
        final_input_df: DataFrame containing submitted input records with 'Id'.
        field_changes_df: Optional DataFrame of field-level changes (from field_level_changes.csv).
        pk_column: Name of the human-readable primary key column.

    Returns:
        PostUpdateValidationResult with aggregated metrics and report paths.
    """
    if final_input_df.empty:
        return PostUpdateValidationResult(all_verified=True)

    # Index live records by 18-char or 15-char Salesforce Id
    live_by_id: dict[str, dict[str, Any]] = {}
    if not live_df.empty and "Id" in live_df.columns:
        for row in live_df.to_dict("records"):
            r_id = str(row.get("Id", "")).strip()
            if r_id:
                live_by_id[r_id] = row
                # Also store 15-character prefix for case-insensitive matching
                if len(r_id) == 18:
                    live_by_id[r_id[:15]] = row

    # Build field change lookup: (record_id, api_field) -> old_value
    old_vals_lookup: dict[tuple[str, str], str] = {}
    field_label_lookup: dict[str, str] = {}
    if field_changes_df is not None and not field_changes_df.empty:
        id_col = "Id" if "Id" in field_changes_df.columns else "Salesforce ID"
        api_col = "API Field" if "API Field" in field_changes_df.columns else "Column"
        old_col = "Old Value" if "Old Value" in field_changes_df.columns else ""
        label_col = "Source Column" if "Source Column" in field_changes_df.columns else "Sitetracker Column"

        for row in field_changes_df.to_dict("records"):
            sf_id = str(row.get(id_col, "")).strip()
            a_field = str(row.get(api_col, "")).strip()
            if sf_id and a_field:
                if old_col:
                    old_vals_lookup[(sf_id, a_field)] = str(row.get(old_col, ""))
                if label_col:
                    field_label_lookup[a_field] = str(row.get(label_col, a_field))

    # Identify fields to check (all columns in final_input_df except 'Id' and primary keys)
    pk_cols = {pk_column, "Project Reference", "Primary_Key", "Project Ref", "Site ID"}
    target_fields = [c for c in final_input_df.columns if c != "Id" and c not in pk_cols]

    field_results: list[PostUpdateFieldResult] = []
    verified_cnt = 0
    mutation_cnt = 0
    stale_cnt = 0
    not_found_cnt = 0
    total_fields = 0

    for row in final_input_df.to_dict("records"):
        rec_id = str(row.get("Id", "")).strip()
        pk_val = ""
        for pk_c in pk_cols:
            if pk_c in row and str(row[pk_c]).strip():
                pk_val = str(row[pk_c]).strip()
                break

        if not rec_id:
            continue

        live_row = live_by_id.get(rec_id) or (live_by_id.get(rec_id[:15]) if len(rec_id) >= 15 else None)

        for fld in target_fields:
            exp_val = row.get(fld, "")
            # If expected value is blank and not explicitly marked #N/A, skip checking untouched fields
            if DataNormalizer.normalize_value(exp_val) == "":
                continue

            total_fields += 1
            f_label = field_label_lookup.get(fld, fld)
            old_v = old_vals_lookup.get((rec_id, fld), "")

            if live_row is None:
                not_found_cnt += 1
                field_results.append(PostUpdateFieldResult(
                    record_id=rec_id,
                    primary_key=pk_val,
                    object_name=object_name,
                    api_field=fld,
                    field_label=f_label,
                    old_value=old_v,
                    expected_value=str(exp_val),
                    live_value="[NOT_FOUND_IN_SALESFORCE]",
                    status="RECORD_NOT_FOUND",
                    notes="Record could not be retrieved from Salesforce",
                ))
                continue

            live_v = live_row.get(fld, "")
            status, notes = evaluate_field_match(
                expected_val=exp_val,
                live_val=live_v,
                old_val=old_v,
                data_type="text",
            )

            if status == "VERIFIED_MATCH":
                verified_cnt += 1
            elif status == "TRIGGER_MUTATION":
                mutation_cnt += 1
            elif status in ("UNMODIFIED_STALE", "NULL_WIPE_FAILED"):
                stale_cnt += 1

            field_results.append(PostUpdateFieldResult(
                record_id=rec_id,
                primary_key=pk_val,
                object_name=object_name,
                api_field=fld,
                field_label=f_label,
                old_value=old_v,
                expected_value=str(exp_val),
                live_value=str(live_v),
                status=status,
                notes=notes,
            ))

    # Write post_update_validation_report.csv
    report_path = run_dir / "post_update_validation_report.csv"
    discrepancies_path = run_dir / "post_update_discrepancies.csv"

    records_dict = [
        {
            "Record_Id": r.record_id,
            "Primary_Key": r.primary_key,
            "Object": r.object_name,
            "API_Field": r.api_field,
            "Field_Label": r.field_label,
            "Old_Value": r.old_value,
            "Expected_Value": r.expected_value,
            "Live_Salesforce_Value": r.live_value,
            "Status": r.status,
            "Notes": r.notes,
        }
        for r in field_results
    ]

    report_df = pd.DataFrame(records_dict)
    report_df.to_csv(report_path, index=False)

    discrepancies = [r for r in field_results if r.status != "VERIFIED_MATCH"]
    if discrepancies:
        disc_df = report_df[report_df["Status"] != "VERIFIED_MATCH"]
        disc_df.to_csv(discrepancies_path, index=False)
    else:
        discrepancies_path = None

    all_ver = (mutation_cnt == 0 and stale_cnt == 0 and not_found_cnt == 0)

    logger.info(
        "Post-update validation completed for %s: %d/%d fields verified (mutations: %d, stale: %d)",
        object_name, verified_cnt, total_fields, mutation_cnt, stale_cnt,
    )

    return PostUpdateValidationResult(
        total_records_audited=len(final_input_df),
        total_fields_checked=total_fields,
        verified_fields_count=verified_cnt,
        trigger_mutation_count=mutation_cnt,
        stale_count=stale_cnt,
        not_found_count=not_found_cnt,
        all_verified=all_ver,
        report_csv_path=report_path,
        discrepancies_csv_path=discrepancies_path,
        discrepancies=discrepancies,
    )
