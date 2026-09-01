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
    def __init__(self, report_name: str):
        self.report_name = report_name
        self.logger = logging.getLogger(f"core.engine.{report_name}")
        self.yaml_cfg = YamlConfigLoader.load(report_name)

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

        # Check Duplicates
        non_empty_pk_df = valid_src[
            valid_src[pk_src].notna() &
            (valid_src[pk_src].str.strip() != "")
        ]
        duplicate_pk_df = non_empty_pk_df[
            non_empty_pk_df.duplicated(subset=[pk_src], keep=False)
        ]
        duplicate_pk_values = sorted(duplicate_pk_df[pk_src].unique().tolist()) if not duplicate_pk_df.empty else []

        if duplicate_pk_values:
            duplicate_pk_df.to_csv(out("duplicate_primary_keys.csv"), index=False)

        # 8. Compute Deltas
        updates: list[dict] = []
        changes: list[dict] = []
        invalid_dates: list[str] = []

        for _, src in valid_src.iterrows():
            pr = src[pk_src]
            if pr not in st_index.index:
                continue

            st = st_index.loc[pr]
            if isinstance(st, pd.DataFrame):
                st = st.iloc[0]

            update = {"Id": st[sf_id_col], pk_src: pr}
            changed = False

            for src_col, st_col, api_col, dtype in field_map:
                if src_col == pk_src:
                    continue

                src_val = DataNormalizer.normalize_value(src.get(src_col))
                st_val = DataNormalizer.normalize_value(st.get(st_col))

                if dtype == "date":
                    src_fmt, ok = DataNormalizer.normalize_date_uk(src_val)
                    st_fmt, _ = DataNormalizer.normalize_date_uk(st_val)
                    if not ok:
                        invalid_dates.append(f"{pr} | {src_col}: {src_val}")
                        continue
                else:
                    src_fmt, st_fmt = src_val, st_val

                update[api_col] = src_fmt

                if DataNormalizer.comparable_text(src_fmt) != DataNormalizer.comparable_text(st_fmt):
                    changed = True
                    changes.append({
                        "Project Reference": pr,
                        "Id": st[sf_id_col],
                        "Source Column": src_col,
                        "Sitetracker Column": st_col,
                        "API Field": api_col,
                        "Old Value": st_val,
                        "New Value": src_fmt
                    })

            if changed:
                updates.append(update)

        # 9. Output CSV files
        pd.DataFrame(updates).to_csv(out("final_input_file.csv"), index=False)
        pd.DataFrame(changes).to_csv(out("field_level_changes.csv"), index=False)

        # 10. Write run summary text file
        with open(out("run_summary.txt"), "w", encoding="utf-8") as f:
            f.write(f"Report Name: {self.report_name}\n")
            f.write(f"Run time: {run_day} {run_time}\n\n")

            f.write("==== COUNTS ====\n")
            f.write(f"Total source records: {len(src_df)}\n")
            f.write(f"Valid source records: {len(valid_src)}\n")
            f.write(f"Delta Records: {len(updates)}\n")
            f.write(f"Fields updated: {len(changes)}\n\n")

            f.write("==== PRIMARY KEY ====\n")
            f.write(f"Source: {pk_src}\n")
            f.write(f"Sitetracker: {pk_st}\n\n")

            f.write("==== FIELD MAPPING USED ====\n")
            for src_col, st_col, api_col, dtype in field_map:
                f.write(f"- {src_col} → {st_col} → {api_col} (type={dtype})\n")

            f.write("\n==== DUPLICATE PRIMARY KEYS (SOURCE) ====\n")
            f.write(f"Duplicate keys found: {len(duplicate_pk_values)}\n")
            for v in duplicate_pk_values:
                f.write(f"- {v}\n")

            if invalid_dates:
                f.write("\n==== INVALID DATE FIELDS (SOURCE) ====\n")
                f.write(f"Total invalid date values: {len(invalid_dates)}\n")
                for line in invalid_dates:
                    f.write(line + "\n")

        # 11. Archive if enabled (copy files to archive while preserving originals in input/)
        if self.yaml_cfg.get("behavior", {}).get("archive_after_success", True):
            archive = self.archive_dir / run_day / run_time
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_file), str(archive / source_file.name))
            shutil.copy2(str(st_file), str(archive / st_file.name))
            self.logger.info("Archived copies of input files to %s", archive)

        self.logger.info("Run finished successfully. Output written to %s", run_dir)

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
            invalid_dates=invalid_dates,
            primary_key_source=pk_src,
            primary_key_sitetracker=pk_st,
            field_mappings=field_map,
        )
