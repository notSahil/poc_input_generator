"""Core Input File Engine for computing delta changes between source and sitetracker."""

import logging
import os
from pathlib import Path
import shutil
import warnings
from datetime import datetime
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.exceptions import EngineSkipError, MappingError, ValidationError
from core.mapping_loader import MappingLoader
from core.models import FieldChange, RunResult
from core.normalizer import DataNormalizer
from core.validator import InputValidator

warnings.filterwarnings("ignore", message="Parsing dates", category=UserWarning)


class InputFileEngine:
    def __init__(self, report_name: str, *, insert_nulls: bool = False):
        self.report_name = report_name
        self.logger = logging.getLogger(f"core.engine.{report_name}")
        self.yaml_cfg = YamlConfigLoader.load(report_name)
        self.insert_nulls = insert_nulls or self.yaml_cfg.get("behavior", {}).get("insert_nulls", False)

        folders = self.yaml_cfg["folders"]
        self.base_dir = settings.DATA_DIR / folders["work_dir"]
        self.source_dir = self.base_dir / folders["source_dir"]
        self.sitetracker_dir = self.base_dir / folders["sitetracker_dir"]
        self.runs_dir = self.base_dir / folders["runs_dir"]
        self.archive_dir = self.base_dir / folders["archive_dir"]

        self.sf_id_column = self.yaml_cfg.get("report", {}).get("sf_id_column", "Id")
        self.text_case_columns = self.yaml_cfg.get("text_case_columns", [])

    def _assert_single_file(self, folder: Path, label: str) -> Path:
        if not folder.exists():
            raise EngineSkipError(f"{label} folder does not exist: {folder}")

        files = [f for f in folder.iterdir() if not f.name.startswith(".")]

        if len(files) == 0:
            raise EngineSkipError(f"No files found in {label} folder: {folder}")

        if len(files) > 1:
            raise ValueError(f"{label} folder must contain exactly ONE file, found {len(files)}: {[f.name for f in files]}")

        return files[0]

    def run(self, skip_validation: bool = False) -> RunResult:
        """Run the delta comparison engine and return a structured RunResult."""
        self.logger.info("Engine run started for report: %s", self.report_name)

        # 1. Validation check
        if not skip_validation:
            validator = InputValidator(self.report_name)
            val_result = validator.validate_all()
            if not val_result.is_valid:
                raise ValidationError("Input validation failed", errors=val_result.errors)
            for w in val_result.warnings:
                self.logger.warning("Validation warning: %s", w)

        # 2. File discovery
        source_file = self._assert_single_file(self.source_dir, "Source")
        st_file = self._assert_single_file(self.sitetracker_dir, "Sitetracker")

        # 3. Create run directory
        run_day = datetime.now().strftime("%Y-%m-%d")
        run_time = datetime.now().strftime("run_%H-%M-%S")
        run_dir = self.runs_dir / run_day / run_time
        run_dir.mkdir(parents=True, exist_ok=True)

        def out(name: str) -> Path:
            return run_dir / name

        # 4. Load mapping
        mapping = MappingLoader(settings.MAPPING_FILE, self.report_name)
        mapping.load()
        pk_src, pk_st = mapping.primary_keys()
        field_map = mapping.field_mapping()

        # 5. Load & normalize source data
        src_df = DataNormalizer.normalize_columns(
            pd.read_excel(source_file, dtype=str)
        )

        for col in self.text_case_columns:
            if col in src_df.columns:
                src_df[col] = src_df[col].apply(DataNormalizer.normalize_text_case)

        # 6. Load & normalize Sitetracker data
        st_df = DataNormalizer.normalize_columns(
            pd.read_csv(
                st_file,
                dtype=str,
                encoding="latin1",
                engine="python",
                on_bad_lines="skip"
            )
        )

        # Locate Salesforce ID column
        if self.sf_id_column in st_df.columns:
            sf_id_col = self.sf_id_column
        else:
            matching_cols = [
                col for col in st_df.columns
                if st_df[col].astype(str).str.match(r"^a[0-9A-Za-z]{17}$").any()
            ]
            if matching_cols:
                sf_id_col = matching_cols[0]
            else:
                raise MappingError(
                    f"Salesforce ID column '{self.sf_id_column}' not found in Sitetracker export. "
                    f"Available columns: {list(st_df.columns)}"
                )

        src_df[pk_src] = src_df[pk_src].apply(DataNormalizer.normalize_value)
        st_df[pk_st] = st_df[pk_st].apply(DataNormalizer.normalize_value)

        # 7. Check Primary Key Validity
        src_df["VALID"] = src_df[pk_src].apply(DataNormalizer.valid_project_ref)
        invalid_pks_df = src_df[~src_df["VALID"]]
        if not invalid_pks_df.empty:
            invalid_pks_df.to_csv(out("invalid_primary_key.csv"), index=False)

        valid_src = src_df[src_df["VALID"]]
        st_index = st_df.set_index(pk_st)

        # Track duplicate occurrences (First Occurrence Wins)
        seen_pks: dict[str, int] = {}  # pk -> first_row_number
        duplicate_rows: list[dict] = []
        duplicate_pk_values: list[str] = []

        # ================================================================
        # 8. Compute Deltas — Enterprise Row-Level Validation
        # ================================================================
        updates: list[dict] = []          # → final_input_file.csv + success_records.csv
        rollback_updates: list[dict] = [] # → rollback_file.csv (pre-change Sitetracker values)
        changes: list[dict] = []          # → field_level_changes.csv
        error_rows: list[dict] = []       # → error_records.csv
        skipped_rows: list[dict] = []     # → skipped_records.csv
        validation_rows: list[dict] = []  # → validation_report.csv

        date_error_count = 0
        type_error_count = 0

        for row_num, (_, src) in enumerate(valid_src.iterrows(), start=1):
            pr = src[pk_src]

            # ── Smart Deduplication (First Occurrence Wins) ──────────────
            if pr in seen_pks:
                first_row = seen_pks[pr]
                dup_entry = {
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "First_Occurrence_Row": first_row,
                    "Status": "DUPLICATE_SKIPPED",
                    "Reason": f"Duplicate of Primary Key '{pr}' (First occurrence at Row {first_row} was processed)",
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
                    "Error_Details": f"Duplicate Primary Key (first occurrence at Row {first_row} was processed)",
                })
                continue
            else:
                seen_pks[pr] = row_num


            # ── Primary key not found in Sitetracker ─────────────────────
            if pr not in st_index.index:
                skipped_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "Id": "",
                    "Reason": "PK_NOT_FOUND_IN_SITETRACKER",
                })
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": "N/A",
                    "Data_Types_OK": "N/A",
                    "Has_Changes": False,
                    "Final_Status": "SKIPPED",
                    "Error_Details": "PK not found in Sitetracker export",
                })
                continue

            st = st_index.loc[pr]
            if isinstance(st, pd.DataFrame):
                st = st.iloc[0]

            sf_id = str(st[sf_id_col])
            update = {"Id": sf_id, pk_src: pr}
            row_rollback = {"Id": sf_id, pk_src: pr}
            row_errors: list[str] = []
            row_rejected = False
            changed = False
            has_date_error = False
            has_type_error = False

            for src_col, st_col, api_col, dtype in field_map:
                if src_col == pk_src:
                    continue

                src_val = DataNormalizer.normalize_value(src.get(src_col))
                st_val = DataNormalizer.normalize_value(st.get(st_col))

                # ── Smart blank handling ──────────────────────────────────
                # If BOTH source and sitetracker are blank → skip this field
                if src_val == "" and st_val == "":
                    continue

                # If source is blank and insert_nulls is disabled → safely ignore blank (preserve Sitetracker value)
                if src_val == "" and not self.insert_nulls:
                    continue

                # ── Data type validation ──────────────────────────────────
                if src_val == "":
                    # Explicit wipe requested via insert_nulls: use Salesforce Bulk API '#N/A'
                    src_fmt = "#N/A"
                    st_fmt = st_val
                elif dtype == "date":
                    src_fmt, ok = DataNormalizer.normalize_date_uk(src_val)
                    if not ok:
                        row_errors.append(
                            f"INVALID_DATE: '{src_val}' in field '{src_col}' — "
                            f"value cannot be parsed as a real calendar date"
                        )
                        has_date_error = True
                        row_rejected = True
                        break  # Reject the entire row
                    st_fmt, _ = DataNormalizer.normalize_date_uk(st_val)

                elif dtype == "number":
                    src_fmt, ok = DataNormalizer.validate_number(src_val)
                    if not ok:
                        row_errors.append(
                            f"INVALID_NUMBER: '{src_val}' in field '{src_col}' — "
                            f"expected a numeric value"
                        )
                        has_type_error = True
                        row_rejected = True
                        break
                    st_fmt = st_val

                elif dtype == "boolean":
                    src_fmt, ok = DataNormalizer.validate_boolean(src_val)
                    if not ok:
                        row_errors.append(
                            f"INVALID_BOOLEAN: '{src_val}' in field '{src_col}' — "
                            f"expected one of: True/False/Yes/No/1/0"
                        )
                        has_type_error = True
                        row_rejected = True
                        break
                    st_fmt = st_val

                else:  # text — allow anything; check length
                    src_fmt, ok = DataNormalizer.validate_text_length(src_val)
                    if not ok:
                        row_errors.append(
                            f"TEXT_TOO_LONG: field '{src_col}' has {len(src_val)} chars "
                            f"(max 255)"
                        )
                        has_type_error = True
                        row_rejected = True
                        break
                    st_fmt = st_val

                # ── If source is blank but sitetracker has value → clear ──
                # (src_fmt is "" here, st_fmt has a value — intentional wipe)
                update[api_col] = src_fmt
                row_rollback[api_col] = st_fmt

                if DataNormalizer.comparable_text(src_fmt) != DataNormalizer.comparable_text(st_fmt):
                    changed = True
                    changes.append({
                        "Project Reference": pr,
                        "Id": sf_id,
                        "Source Column": src_col,
                        "Sitetracker Column": st_col,
                        "API Field": api_col,
                        "Old Value": st_val,
                        "New Value": src_fmt,
                    })

            # ── Row classification ────────────────────────────────────────
            if row_rejected:
                if has_date_error:
                    date_error_count += 1
                if has_type_error:
                    type_error_count += 1
                error_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "Id": sf_id,
                    "Error_Code": (
                        "INVALID_DATE" if has_date_error else
                        "INVALID_TYPE_ON_FIELD_IN_RECORD"
                    ),
                    "Error_Message": " | ".join(row_errors),
                    "Error_Field": "",  # populated from message
                    "sf__Error": " | ".join(row_errors),  # Dataloader.io compatible column
                })
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": not has_date_error,
                    "Data_Types_OK": not has_type_error,
                    "Has_Changes": False,
                    "Final_Status": "ERROR",
                    "Error_Details": " | ".join(row_errors),
                })
            elif not changed:
                skipped_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "Id": sf_id,
                    "Reason": "NO_CHANGES_DETECTED",
                })
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": True,
                    "Data_Types_OK": True,
                    "Has_Changes": False,
                    "Final_Status": "SKIPPED",
                    "Error_Details": "",
                })
            else:
                # SUCCESS — has changes and all validations passed
                updates.append(update)
                rollback_updates.append(row_rollback)
                validation_rows.append({
                    "Row_Number": row_num,
                    "Primary_Key": pr,
                    "PK_Valid": True,
                    "Date_Fields_Valid": True,
                    "Data_Types_OK": True,
                    "Has_Changes": True,
                    "Final_Status": "SUCCESS",
                    "Error_Details": "",
                })

        # Add invalid PK rows to validation report
        for row_num, (_, inv_row) in enumerate(invalid_pks_df.iterrows(), start=1):
            validation_rows.append({
                "Row_Number": row_num,
                "Primary_Key": inv_row.get(pk_src, ""),
                "PK_Valid": False,
                "Date_Fields_Valid": "N/A",
                "Data_Types_OK": "N/A",
                "Has_Changes": False,
                "Final_Status": "ERROR",
                "Error_Details": f"MALFORMED_ID: '{inv_row.get(pk_src)}' is not a valid primary key format",
            })
            error_rows.append({
                "Row_Number": row_num,
                "Primary_Key": inv_row.get(pk_src, ""),
                "Id": "",
                "Error_Code": "MALFORMED_ID",
                "Error_Message": f"'{inv_row.get(pk_src)}' is not a valid primary key (must be alphanumeric/dash/underscore, no spaces)",
                "Error_Field": pk_src,
                "sf__Error": f"MALFORMED_ID: {pk_src}: id value of incorrect type: {inv_row.get(pk_src)}",
            })

        # ================================================================
        # 9. Write all output files (guarantee column headers even if empty)
        # ================================================================

        # 1. final_input_file.csv — records ready for Sitetracker upload
        pd.DataFrame(updates).to_csv(out("final_input_file.csv"), index=False)

        # 2. rollback_file.csv — pre-change values for 1-click rollback
        rollback_df = pd.DataFrame(rollback_updates) if rollback_updates else pd.DataFrame(
            columns=["Id", pk_src]
        )
        rollback_df.to_csv(out("rollback_file.csv"), index=False)

        # 3. field_level_changes.csv — per-field old vs new
        changes_df = pd.DataFrame(changes) if changes else pd.DataFrame(
            columns=["Project Reference", "Id", "Source Column", "Sitetracker Column", "API Field", "Old Value", "New Value"]
        )
        changes_df.to_csv(out("field_level_changes.csv"), index=False)

        # 4. success_records.csv — all successful rows with change summary
        success_summary = []
        for u in updates:
            pr_val = u.get(pk_src, "")
            relevant_changes = [c for c in changes if c["Project Reference"] == pr_val]
            success_summary.append({
                "Primary_Key": pr_val,
                "Id": u.get("Id", ""),
                "Fields_Changed": len(relevant_changes),
                "Change_Summary": " | ".join(
                    f"{c['API Field']}: '{c['Old Value']}' → '{c['New Value']}'"
                    for c in relevant_changes
                ),
            })
        success_df = pd.DataFrame(success_summary) if success_summary else pd.DataFrame(
            columns=["Primary_Key", "Id", "Fields_Changed", "Change_Summary"]
        )
        success_df.to_csv(out("success_records.csv"), index=False)

        # 5. error_records.csv — all failed rows with exact error code (Dataloader.io style)
        error_df = pd.DataFrame(error_rows) if error_rows else pd.DataFrame(
            columns=["Row_Number", "Primary_Key", "Id", "Error_Code", "Error_Message", "Error_Field", "sf__Error"]
        )
        error_df.to_csv(out("error_records.csv"), index=False)

        # 6. skipped_records.csv — valid rows with no changes or PK not found
        skipped_df = pd.DataFrame(skipped_rows) if skipped_rows else pd.DataFrame(
            columns=["Row_Number", "Primary_Key", "Id", "Reason"]
        )
        skipped_df.to_csv(out("skipped_records.csv"), index=False)

        # 7. validation_report.csv — every row with per-check pass/fail
        val_df = pd.DataFrame(validation_rows) if validation_rows else pd.DataFrame(
            columns=["Row_Number", "Primary_Key", "PK_Valid", "Date_Fields_Valid", "Data_Types_OK", "Has_Changes", "Final_Status", "Error_Details"]
        )
        val_df.to_csv(out("validation_report.csv"), index=False)

        # 8. duplicate_primary_keys.csv — quarantined duplicate occurrences
        if duplicate_rows:
            pd.DataFrame(duplicate_rows).to_csv(out("duplicate_primary_keys.csv"), index=False)
        else:
            pd.DataFrame(
                columns=["Row_Number", "Primary_Key", "First_Occurrence_Row", "Status", "Reason"]
            ).to_csv(out("duplicate_primary_keys.csv"), index=False)


        # ================================================================
        # 10. Write enhanced run_summary.txt
        # ================================================================
        total_errors = len(error_rows)
        total_skipped = len(skipped_rows)
        not_found_count = sum(1 for r in skipped_rows if r["Reason"] == "PK_NOT_FOUND_IN_SITETRACKER")

        with open(out("run_summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"Report Name: {self.report_name}\n")
            f.write(f"Run time: {run_day} {run_time}\n")
            f.write(f"Insert Nulls: {'ENABLED (Overwriting blanks with #N/A)' if self.insert_nulls else 'DISABLED (Blanks ignored - Safe Mode)'}\n\n")

            f.write("==== COUNTS ====\n")
            f.write(f"Total source records:    {len(src_df)}\n")
            f.write(f"Invalid primary keys:    {len(invalid_pks_df)}\n")
            f.write(f"Valid source records:     {len(valid_src)}\n")
            f.write(f"\n")
            f.write(f"  ✅ SUCCESS (uploaded): {len(updates)}\n")
            f.write(f"  🚫 ERRORS (rejected):  {total_errors}\n")
            f.write(f"     ↳ Invalid dates:    {date_error_count}\n")
            f.write(f"     ↳ Invalid types:    {type_error_count}\n")
            f.write(f"     ↳ Invalid PKs:      {len(invalid_pks_df)}\n")
            f.write(f"  ⏭️  SKIPPED:            {total_skipped}\n")
            f.write(f"     ↳ No changes:       {total_skipped - not_found_count}\n")
            f.write(f"     ↳ PK not in ST:     {not_found_count}\n")
            f.write(f"  🔀 DUPLICATE PKs:      {len(duplicate_pk_values)}\n")
            f.write(f"\nField-level changes:     {len(changes)}\n\n")

            f.write("==== PRIMARY KEY ====\n")
            f.write(f"Source: {pk_src}\n")
            f.write(f"Sitetracker: {pk_st}\n\n")

            f.write("==== FIELD MAPPING USED ====\n")
            for src_col, st_col, api_col, dtype in field_map:
                f.write(f"- {src_col} → {st_col} → {api_col} (type={dtype})\n")

            f.write("\n==== OUTPUT FILES ====\n")
            f.write("final_input_file.csv    → Records ready for Sitetracker upload\n")
            f.write("rollback_file.csv       → Pre-change Sitetracker values for 1-click rollback\n")
            f.write("success_records.csv     → All successful rows with change summary\n")
            f.write("error_records.csv       → All rejected rows with Salesforce-style error codes\n")
            f.write("skipped_records.csv     → Valid rows with no changes or PK not found\n")
            f.write("validation_report.csv   → Full audit trail — every row, every check\n")
            f.write("field_level_changes.csv → Per-field old vs new value comparison\n")

            if duplicate_pk_values:
                f.write("\n==== DUPLICATE PRIMARY KEYS (SOURCE) ====\n")
                f.write(f"Duplicate keys found: {len(duplicate_pk_values)}\n")
                for v in duplicate_pk_values:
                    f.write(f"- {v}\n")

            if error_rows:
                f.write("\n==== VALIDATION ERRORS ====\n")
                for err in error_rows:
                    f.write(f"- [{err['Error_Code']}] PK={err['Primary_Key']}: {err['Error_Message']}\n")

        # ================================================================
        # 11. Archive input files
        # ================================================================
        if self.yaml_cfg.get("behavior", {}).get("archive_after_success", True):
            archive = self.archive_dir / run_day / run_time
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_file), str(archive / source_file.name))
            shutil.copy2(str(st_file), str(archive / st_file.name))
            self.logger.info("Archived copies of input files to %s", archive)

        self.logger.info("Run finished. Output written to %s", run_dir)

        return RunResult(
            success=True,
            report_name=self.report_name,
            run_dir=run_dir,
            total_source_records=len(src_df),
            valid_source_records=len(valid_src),
            delta_records=len(updates),
            field_changes_count=len(changes),
            invalid_primary_keys=invalid_pks_df[pk_src].tolist() if not invalid_pks_df.empty else [],
            duplicate_primary_keys=duplicate_pk_values,
            invalid_dates=[e["Error_Message"] for e in error_rows if e.get("Error_Code") == "INVALID_DATE"],
            insert_nulls=self.insert_nulls,
            # New counters
            error_records=total_errors,
            skipped_records=total_skipped,
            not_found_records=not_found_count,
            date_error_records=date_error_count,
            type_error_records=type_error_count,
            primary_key_source=pk_src,
            primary_key_sitetracker=pk_st,
            field_mappings=field_map,
        )
