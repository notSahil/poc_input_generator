"""Ad-Hoc / Manual Dataloader Processing Engine.

Provides an isolated, headless engine to perform delta comparisons, validations,
and audit artifact generation for arbitrary Salesforce objects and fields.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Any
import pandas as pd

from config import settings
from core.exceptions import MappingError, ValidationError
from core.normalizer import DataNormalizer

logger = logging.getLogger(__name__)


@dataclass
class AdhocFieldMapping:
    """Individual field mapping definition."""
    source_column: str
    target_field_api: str
    target_field_label: str
    data_type: str = "text"  # 'text', 'date', 'number', 'boolean'
    upload_enabled: bool = True
    match_confidence: str = "Manual"  # 'Exact', 'Normalized', 'Manual', 'None'


@dataclass
class AdhocEngineConfig:
    """Configuration for an ad-hoc dataloader execution."""
    object_name: str
    source_pk_col: str
    target_pk_field: str
    sf_id_field: str = "Id"
    insert_nulls: bool = True
    mappings: list[AdhocFieldMapping] = field(default_factory=list)


@dataclass
class AdhocRunResult:
    """Summary and artifact locations for an ad-hoc run."""
    run_dir: Path
    object_name: str
    total_source_rows: int
    valid_rows: int
    changed_records: int
    unchanged_records: int
    invalid_pks: int
    duplicate_pks: int
    skipped_pks: int
    error_rows: int
    artifacts: dict[str, Path] = field(default_factory=dict)


def _clean_str(s: str) -> str:
    """Normalize string for fuzzy comparison."""
    return re.sub(r"[^a-zA-Z0-9]", "", str(s).lower())


def detect_target_object(source_columns: list[str]) -> str | None:
    """
    Auto-detect the intended Salesforce object based on uploaded spreadsheet column names.
    Uses Mapping_file.xlsx and common column heuristics.
    """
    clean_cols = {_clean_str(c) for c in source_columns}

    # 1. Check known Mapping_file.xlsx
    mapping_file = Path(settings.DATA_DIR) / "common" / "Mapping_file.xlsx"
    if not mapping_file.exists():
        mapping_file = Path("data/common/Mapping_file.xlsx")

    if mapping_file.exists():
        try:
            mf = pd.read_excel(mapping_file)
            obj_scores: dict[str, int] = {}
            for _, row in mf.iterrows():
                obj = str(row.get("Object Name", "")).strip()
                src_col = str(row.get("Source File Column Name", "")).strip()
                sf_field = str(row.get("Sitetracker Field Name", "")).strip()
                api_name = str(row.get("API Name", "")).strip()

                for candidate in (src_col, sf_field, api_name):
                    if candidate and _clean_str(candidate) in clean_cols:
                        obj_scores[obj] = obj_scores.get(obj, 0) + 1

            if obj_scores:
                best_obj = max(obj_scores, key=obj_scores.get)
                obj_lower = best_obj.lower()
                if "site" in obj_lower:
                    return "sitetracker__Site__c"
                elif "bt project" in obj_lower:
                    return "BT_Project__c"
                elif "project" in obj_lower:
                    return "sitetracker__Project__c"
        except Exception as e:
            logger.warning("Could not parse Mapping_file.xlsx for object auto-detection: %s", e)

    # 2. Heuristic fallback based on distinctive column names
    for col in source_columns:
        c_clean = _clean_str(col)
        if any(term in c_clean for term in ("tmcellid", "siteonmastersitelist", "dateofmastersitelisting", "sitetrackersitec")):
            return "sitetracker__Site__c"
        if any(term in c_clean for term in ("projectref", "projectreference", "ranpriority", "hemeasdelay")):
            return "BT_Project__c"
        if any(term in c_clean for term in ("wespsid", "hemeasstatus")):
            return "sitetracker__Project__c"

    return None


def suggest_field_mappings(
    source_columns: list[str],
    sf_fields: list[dict[str, Any]],
    source_pk_col: str | None = None,
    target_pk_field: str | None = None,
    object_name: str | None = None,
) -> list[AdhocFieldMapping]:
    """
    Intelligently match uploaded CSV column names to Salesforce object fields.

    Matches by:
    1. Explicit PK override
    2. Exact API name match (case-insensitive)
    3. Mapping_file.xlsx canonical rules (e.g. TM Cell ID -> Name)
    4. Normalized API name match (ignoring namespaces like sitetracker__ and __c)
    5. Normalized label match (comparing words)

    Returns:
        List of AdhocFieldMapping objects.
    """
    mappings: list[AdhocFieldMapping] = []
    used_sf_apis: set[str] = set()

    # Pre-index SF fields for fast lookup
    sf_by_clean_api: dict[str, dict[str, Any]] = {}
    sf_by_stripped_api: dict[str, dict[str, Any]] = {}
    sf_by_clean_label: dict[str, dict[str, Any]] = {}

    for f in sf_fields:
        api = f["api_name"]
        label = f["label"]
        clean_api = _clean_str(api)
        sf_by_clean_api[clean_api] = f

        # Strip prefixes and suffixes (e.g. sitetracker__site_id__c -> siteid)
        stripped_api = re.sub(r"^sitetracker__", "", api, flags=re.IGNORECASE)
        stripped_api = re.sub(r"__c$", "", stripped_api, flags=re.IGNORECASE)
        sf_by_stripped_api[_clean_str(stripped_api)] = f

        clean_label = _clean_str(label)
        sf_by_clean_label[clean_label] = f

    # Load Mapping_file.xlsx canonical rules if available
    mf_rules: dict[str, str] = {}
    mapping_file = Path(settings.DATA_DIR) / "common" / "Mapping_file.xlsx"
    if not mapping_file.exists():
        mapping_file = Path("data/common/Mapping_file.xlsx")

    if mapping_file.exists():
        try:
            mf = pd.read_excel(mapping_file)
            for _, row in mf.iterrows():
                obj = str(row.get("Object Name", "")).strip().lower()
                src_col = str(row.get("Source File Column Name", "")).strip()
                sf_field = str(row.get("Sitetracker Field Name", "")).strip()
                api_name = str(row.get("API Name", "")).strip()

                applies = True
                if object_name:
                    obj_norm = object_name.lower()
                    if "site" in obj_norm and "site" not in obj:
                        applies = False
                    elif "bt_project" in obj_norm and "bt" not in obj:
                        applies = False
                    elif "sitetracker__project" in obj_norm and ("bt" in obj or "project" not in obj):
                        applies = False

                if applies and api_name:
                    if src_col:
                        mf_rules[_clean_str(src_col)] = api_name
                    if sf_field:
                        mf_rules[_clean_str(sf_field)] = api_name
        except Exception as e:
            logger.warning("Could not read Mapping_file.xlsx for field suggestions: %s", e)

    for col in source_columns:
        clean_col = _clean_str(col)
        matched_field: dict[str, Any] | None = None
        confidence = "None"

        # Explicit PK override if set
        if source_pk_col and col == source_pk_col and target_pk_field:
            for f in sf_fields:
                if f["api_name"] == target_pk_field:
                    matched_field = f
                    confidence = "Exact"
                    break

        if not matched_field:
            # 1. Exact API match
            if clean_col in sf_by_clean_api:
                matched_field = sf_by_clean_api[clean_col]
                confidence = "Exact"
            # 2. Canonical Mapping_file.xlsx match
            elif clean_col in mf_rules and _clean_str(mf_rules[clean_col]) in sf_by_clean_api:
                matched_field = sf_by_clean_api[_clean_str(mf_rules[clean_col])]
                confidence = "Exact"
            # 3. Stripped API match
            elif clean_col in sf_by_stripped_api:
                matched_field = sf_by_stripped_api[clean_col]
                confidence = "Normalized"
            # 4. Label match
            elif clean_col in sf_by_clean_label:
                matched_field = sf_by_clean_label[clean_col]
                confidence = "Normalized"

        if matched_field:
            target_api = matched_field["api_name"]
            target_label = matched_field["label"]
            dtype = matched_field.get("data_type", "text")
            is_pk = bool(
                (source_pk_col and col == source_pk_col)
                or (target_pk_field and target_api == target_pk_field)
            )
            is_id_field = (target_api.lower() == "id")
            is_updateable = matched_field.get("updateable", True)

            # In Salesforce, Record ID and primary key lookup fields can NEVER be modified in an update
            is_enabled = bool(not is_pk and not is_id_field and is_updateable)
            used_sf_apis.add(target_api)
        else:
            target_api = ""
            target_label = ""
            dtype = "text"
            is_enabled = False

        mappings.append(AdhocFieldMapping(
            source_column=col,
            target_field_api=target_api,
            target_field_label=target_label,
            data_type=dtype,
            upload_enabled=is_enabled,
            match_confidence=confidence,
        ))

    return mappings


class ManualLoadEngine:
    """
    Executes delta comparisons, validates constraints, and produces
    the standard 5 output artifacts + rollback file for ad-hoc operations.
    """

    def __init__(self, config: AdhocEngineConfig, custom_run_dir: Path | None = None):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.ManualLoadEngine")

        if custom_run_dir:
            self.run_dir = Path(custom_run_dir)
        else:
            now = datetime.now()
            clean_obj = re.sub(r"[^a-zA-Z0-9_]", "_", self.config.object_name)
            self.run_dir = (
                settings.DATA_DIR
                / "manual_runs"
                / clean_obj
                / now.strftime("%Y-%m-%d")
                / now.strftime("run_%H-%M-%S")
            )
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def _out(self, filename: str) -> Path:
        return self.run_dir / filename

    def run(
        self,
        source_df: pd.DataFrame,
        live_sf_df: pd.DataFrame,
    ) -> AdhocRunResult:
        """
        Execute delta comparison and validation between source and live Salesforce data.

        Args:
            source_df: DataFrame loaded from uploaded CSV/Excel.
            live_sf_df: DataFrame fetched via live SOQL from Salesforce.

        Returns:
            AdhocRunResult with execution metrics and artifact paths.
        """
        self.logger.info("Starting manual load engine for object: %s", self.config.object_name)

        # 1. Filter enabled mappings (strictly exclude primary key and Salesforce Record ID from updates list)
        active_mappings = [
            m for m in self.config.mappings
            if m.upload_enabled and m.target_field_api and m.source_column
            and m.target_field_api.lower() != "id"
            and m.source_column != self.config.source_pk_col
            and m.target_field_api != self.config.target_pk_field
        ]

        pk_src = self.config.source_pk_col
        pk_sf = self.config.target_pk_field
        sf_id_col = self.config.sf_id_field

        if pk_src not in source_df.columns:
            raise MappingError(f"Primary key column '{pk_src}' not found in uploaded file columns.")

        # Normalize source columns
        src_df = DataNormalizer.normalize_columns(source_df.copy().astype(str))
        st_df = DataNormalizer.normalize_columns(live_sf_df.copy().astype(str))

        if sf_id_col not in st_df.columns:
            # Fallback: check if 'Id' exists in any case
            id_matches = [c for c in st_df.columns if c.lower() == "id"]
            if id_matches:
                sf_id_col = id_matches[0]
            else:
                raise MappingError(f"Salesforce ID column '{sf_id_col}' not found in Salesforce data.")

        if pk_sf not in st_df.columns:
            raise MappingError(f"Salesforce primary key field '{pk_sf}' not found in fetched live records.")

        # 2. Normalize PK values
        src_df[pk_src] = src_df[pk_src].apply(DataNormalizer.normalize_value)
        st_df[pk_sf] = st_df[pk_sf].apply(DataNormalizer.normalize_value)

        # 3. Check Primary Key Validity
        src_df["VALID"] = src_df[pk_src].apply(DataNormalizer.valid_project_ref)
        invalid_pks_df = src_df[~src_df["VALID"]]
        if not invalid_pks_df.empty:
            invalid_pks_df.to_csv(self._out("invalid_primary_key.csv"), index=False)
        else:
            pd.DataFrame(columns=src_df.columns).to_csv(self._out("invalid_primary_key.csv"), index=False)

        valid_src = src_df[src_df["VALID"]]
        st_index = st_df.set_index(pk_sf)

        # 4. Duplicate PK tracking (First Occurrence Wins)
        seen_pks: dict[str, int] = {}
        duplicate_rows: list[dict[str, Any]] = []
        duplicate_pk_values: list[str] = []

        updates: list[dict[str, Any]] = []           # -> final_input_file.csv + success_records.csv
        rollback_updates: list[dict[str, Any]] = []  # -> rollback_file.csv
        changes: list[dict[str, Any]] = []           # -> field_level_changes.csv
        error_rows: list[dict[str, Any]] = []        # -> error_records.csv
        skipped_rows: list[dict[str, Any]] = []      # -> skipped_records.csv
        validation_rows: list[dict[str, Any]] = []   # -> validation_report.csv

        date_error_count = 0
        type_error_count = 0

        for row_num, (_, src) in enumerate(valid_src.iterrows(), start=1):
            pr = src[pk_src]

            # Duplicate Check
            if pr in seen_pks:
                first_row = seen_pks[pr]
                dup_entry = {
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "First_Occurrence_Row": first_row,
                    "Status": "DUPLICATE_SKIPPED",
                    "Reason": f"Duplicate of Primary Key '{pr}' (First occurrence at Row {first_row} processed)",
                }
                for c in valid_src.columns:
                    dup_entry[c] = src.get(c)
                duplicate_rows.append(dup_entry)
                if pr not in duplicate_pk_values:
                    duplicate_pk_values.append(pr)

                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": "N/A",
                    "Data_Types_OK": "N/A",
                    "Has_Changes": False,
                    "Final_Status": "DUPLICATE_SKIPPED",
                    "Error_Details": f"Duplicate Primary Key (first occurrence at Row {first_row})",
                })
                continue
            else:
                seen_pks[pr] = row_num

            # PK Missing in Salesforce
            if pr not in st_index.index:
                skipped_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "Id": "",
                    "Reason": "PK_NOT_FOUND_IN_SALESFORCE",
                })
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": "N/A",
                    "Data_Types_OK": "N/A",
                    "Has_Changes": False,
                    "Final_Status": "SKIPPED",
                    "Error_Details": "Primary Key not found in Salesforce live query",
                })
                continue

            st_row = st_index.loc[pr]
            if isinstance(st_row, pd.DataFrame):
                st_row = st_row.iloc[0]

            sf_id = str(st_row[sf_id_col])
            update = {"Id": sf_id, pk_src: pr}
            row_rollback = {"Id": sf_id, pk_src: pr}
            row_errors: list[str] = []
            changed = False
            has_date_error = False
            has_type_error = False

            # Compare enabled mapped fields
            for m in active_mappings:
                src_col = m.source_column
                api_col = m.target_field_api
                dtype = m.data_type

                # Record ID and Primary Key lookup fields must NEVER be modified in an update
                if api_col.lower() == "id" or api_col == sf_id_col:
                    continue
                if src_col == pk_src or api_col == pk_sf:
                    continue

                src_val = DataNormalizer.normalize_value(src.get(src_col))
                # Look up live value either by API name or by source col
                st_val = DataNormalizer.normalize_value(
                    st_row.get(api_col, st_row.get(src_col, ""))
                )

                if src_val == "" and st_val == "":
                    continue

                if src_val == "" and not self.config.insert_nulls:
                    continue

                # Type Normalization & Validation
                if src_val == "":
                    src_fmt = "#N/A"
                    st_fmt = st_val
                elif dtype == "date":
                    src_fmt, ok = DataNormalizer.normalize_date_uk(src_val)
                    if not ok:
                        row_errors.append(f"INVALID_DATE: '{src_val}' in field '{src_col}'")
                        has_date_error = True
                    st_fmt, _ = DataNormalizer.normalize_date_uk(st_val)
                elif dtype == "number":
                    src_fmt, ok = DataNormalizer.normalize_number(src_val)
                    if not ok:
                        row_errors.append(f"INVALID_NUMBER: '{src_val}' in field '{src_col}'")
                        has_type_error = True
                    st_fmt, _ = DataNormalizer.normalize_number(st_val)
                elif dtype == "boolean":
                    src_fmt = "true" if src_val.lower() in ("true", "yes", "1", "y") else "false"
                    st_fmt = "true" if st_val.lower() in ("true", "yes", "1", "y") else "false"
                else:
                    src_fmt = src_val
                    st_fmt = st_val

                # Track Field Change using comparable_text
                if DataNormalizer.comparable_text(src_fmt) != DataNormalizer.comparable_text(st_fmt):
                    changed = True
                    update[api_col] = src_fmt
                    # Bulk API 2.0: For rollback, if st_val is blank, use #N/A to wipe
                    row_rollback[api_col] = st_val if (st_val and str(st_val).strip()) else "#N/A"

                    changes.append({
                        "Row_Number": row_num,
                        "Primary_Key": pr,
                        "Id": sf_id,
                        "Source_Column": src_col,
                        "Salesforce_Field": api_col,
                        "Field_Name": m.target_field_label or api_col,
                        "Data_Type": dtype,
                        "Old_Value": st_fmt,
                        "New_Value": src_fmt,
                    })

            # Record row status
            if row_errors:
                date_error_count += int(has_date_error)
                type_error_count += int(has_type_error)
                error_entry = {
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "Id": sf_id,
                    "Errors": " | ".join(row_errors),
                }
                for c in valid_src.columns:
                    error_entry[c] = src.get(c)
                error_rows.append(error_entry)

                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": False if has_date_error else True,
                    "Data_Types_OK": False if has_type_error else True,
                    "Has_Changes": changed,
                    "Final_Status": "REJECTED_ERRORS",
                    "Error_Details": " | ".join(row_errors),
                })
            elif changed:
                updates.append(update)
                rollback_updates.append(row_rollback)
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": True,
                    "Data_Types_OK": True,
                    "Has_Changes": True,
                    "Final_Status": "READY_FOR_UPLOAD",
                    "Error_Details": "None",
                })
            else:
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": True,
                    "Data_Types_OK": True,
                    "Has_Changes": False,
                    "Final_Status": "UNCHANGED",
                    "Error_Details": "None",
                })

        # 5. Write Standard 5 Artifacts + Rollback & Diagnostics
        artifacts: dict[str, Path] = {}
        upload_fields = ["Id"] + [
            m.target_field_api for m in active_mappings if m.target_field_api != "Id"
        ]

        # 1. final_input_file.csv (only Id and updated fields)
        if updates:
            final_df = pd.DataFrame(updates)
            if pk_src in final_df.columns:
                final_df = final_df.drop(columns=[pk_src])
        else:
            final_df = pd.DataFrame(columns=upload_fields)
        final_path = self._out("final_input_file.csv")
        final_df.to_csv(final_path, index=False)
        artifacts["final_input_file"] = final_path

        # 2. rollback_file.csv
        if rollback_updates:
            rollback_df = pd.DataFrame(rollback_updates)
            if pk_src in rollback_df.columns:
                rollback_df = rollback_df.drop(columns=[pk_src])
        else:
            rollback_df = pd.DataFrame(columns=upload_fields)
        rollback_path = self._out("rollback_file.csv")
        rollback_df.to_csv(rollback_path, index=False)
        artifacts["rollback_file"] = rollback_path

        # 3. field_level_changes.csv
        changes_cols = [
            "Row_Number", "Primary_Key", "Id", "Source_Column",
            "Salesforce_Field", "Field_Name", "Data_Type", "Old_Value", "New_Value"
        ]
        changes_df = pd.DataFrame(changes) if changes else pd.DataFrame(columns=changes_cols)
        changes_path = self._out("field_level_changes.csv")
        changes_df.to_csv(changes_path, index=False)
        artifacts["field_level_changes"] = changes_path

        # 4. duplicate_primary_keys.csv
        dup_cols = ["Row_Number", "Primary_Key", "First_Occurrence_Row", "Status", "Reason"] + list(valid_src.columns)
        dup_df = pd.DataFrame(duplicate_rows) if duplicate_rows else pd.DataFrame(columns=dup_cols)
        dup_path = self._out("duplicate_primary_keys.csv")
        dup_df.to_csv(dup_path, index=False)
        artifacts["duplicate_primary_keys"] = dup_path

        # 5. invalid_primary_key.csv (already written)
        artifacts["invalid_primary_key"] = self._out("invalid_primary_key.csv")

        # 6. skipped_records.csv
        skipped_cols = ["Row_Number", "Primary_Key", "Id", "Reason"]
        skipped_df = pd.DataFrame(skipped_rows) if skipped_rows else pd.DataFrame(columns=skipped_cols)
        skipped_path = self._out("skipped_records.csv")
        skipped_df.to_csv(skipped_path, index=False)
        artifacts["skipped_records"] = skipped_path

        # 7. error_records.csv
        error_cols = ["Row_Number", "Primary_Key", "Id", "Errors"] + list(valid_src.columns)
        error_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame(columns=error_cols)
        error_path = self._out("error_records.csv")
        error_df.to_csv(error_path, index=False)
        artifacts["error_records"] = error_path

        # 8. validation_report.csv
        val_cols = [
            "Row_Number", "Primary_Key", "PK_Valid", "Date_Fields_Valid",
            "Data_Types_OK", "Has_Changes", "Final_Status", "Error_Details"
        ]
        val_df = pd.DataFrame(validation_rows) if validation_rows else pd.DataFrame(columns=val_cols)
        val_path = self._out("validation_report.csv")
        val_df.to_csv(val_path, index=False)
        artifacts["validation_report"] = val_path

        # 9. run_summary.txt
        summary_text = (
            f"Ad-Hoc Dataloader Execution Summary\n"
            f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Target Salesforce Object: {self.config.object_name}\n"
            f"Source Primary Key: {pk_src}\n"
            f"Salesforce Primary Key Field: {pk_sf}\n"
            f"============================================================\n"
            f"Total Source Rows:       {len(source_df)}\n"
            f"Valid Primary Keys:      {len(valid_src)}\n"
            f"Invalid Primary Keys:    {len(invalid_pks_df)}\n"
            f"Duplicate Primary Keys:  {len(duplicate_rows)}\n"
            f"Skipped (Not in SF):     {len(skipped_rows)}\n"
            f"Validation Errors:       {len(error_rows)}\n"
            f"Rows With Changes:       {len(updates)}\n"
            f"Rows Without Changes:    {len(valid_src) - len(updates) - len(duplicate_rows) - len(skipped_rows) - len(error_rows)}\n"
            f"Total Field Changes:     {len(changes)}\n"
        )
        summary_path = self._out("run_summary.txt")
        summary_path.write_text(summary_text, encoding="utf-8")
        artifacts["run_summary"] = summary_path

        unchanged_count = max(0, len(valid_src) - len(updates) - len(duplicate_rows) - len(skipped_rows) - len(error_rows))

        result = AdhocRunResult(
            run_dir=self.run_dir,
            object_name=self.config.object_name,
            total_source_rows=len(source_df),
            valid_rows=len(valid_src),
            changed_records=len(updates),
            unchanged_records=unchanged_count,
            invalid_pks=len(invalid_pks_df),
            duplicate_pks=len(duplicate_rows),
            skipped_pks=len(skipped_rows),
            error_rows=len(error_rows),
            artifacts=artifacts,
        )

        self.logger.info(
            "Manual load engine completed: %d rows to update, %d field changes",
            result.changed_records, len(changes),
        )
        return result
