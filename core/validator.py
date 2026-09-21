"""Input validation pipeline. Runs before the engine to catch problems early."""

import logging
from pathlib import Path
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.mapping_loader import MappingLoader
from core.models import ValidationResult
from core.normalizer import DataNormalizer

logger = logging.getLogger(__name__)


class InputValidator:
    def __init__(self, report_name: str, *, custom_mapping_df: pd.DataFrame | None = None):
        self.report_name = report_name
        self.custom_mapping_df = custom_mapping_df
        self.yaml_cfg = YamlConfigLoader.load(report_name)

        folders = self.yaml_cfg["folders"]
        self.base_dir = settings.DATA_DIR / folders["work_dir"]
        self.source_dir = self.base_dir / folders["source_dir"]
        self.sitetracker_dir = self.base_dir / folders["sitetracker_dir"]
        self.sf_id_column = self.yaml_cfg.get("report", {}).get("sf_id_column", "Id")

    def validate_all(self) -> ValidationResult:
        """Run all validation checks and return aggregated result."""
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Check directories exist
        errors.extend(self._check_directories())
        if errors:
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 2. Check files exist (exactly one in each folder)
        src_file, st_file, file_errors = self._check_files()
        errors.extend(file_errors)
        if errors or not src_file or not st_file:
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 3. Load mapping
        try:
            mapping = MappingLoader(settings.MAPPING_FILE, self.report_name, custom_df=self.custom_mapping_df)
            mapping.load()
            pk_src, pk_st = mapping.primary_keys()
            field_map = mapping.field_mapping()
        except Exception as e:
            errors.append(f"Mapping error: {e}")
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        # 4. Validate source file columns
        try:
            src_df = DataNormalizer.read_spreadsheet(src_file, nrows=10)

            # Check primary key column (supports source name, Sitetracker name, API name, or case variations)
            pk_col_found = DataNormalizer.resolve_source_column(src_df.columns, pk_src, pk_st, None)
            if not pk_col_found:
                for s_col, st_col, a_col, _ in field_map:
                    if s_col == pk_src:
                        pk_col_found = DataNormalizer.resolve_source_column(src_df.columns, s_col, st_col, a_col)
                        if pk_col_found:
                            break
            if not pk_col_found:
                errors.append(f"Source file missing primary key column: '{pk_src}' (or '{pk_st}')")

            matched_mapped_count = 0
            for src_col, st_col, api_col, _ in field_map:
                if src_col == pk_src:
                    continue
                matched_col = DataNormalizer.resolve_source_column(src_df.columns, src_col, st_col, api_col)
                if matched_col:
                    matched_mapped_count += 1
                else:
                    warnings.append(
                        f"Mapped column '{src_col}' (or '{st_col}') not found in source file — "
                        f"will be safely skipped (cloud values will remain untouched)."
                    )

            if matched_mapped_count == 0:
                errors.append(
                    f"No mapped data fields found in source file besides the primary key '{pk_src}'. "
                    f"At least one mapped field must be present to compute deltas. "
                    f"Available columns in source: {list(src_df.columns)}"
                )

            # Sample primary key check
            resolved_pk = pk_col_found if pk_col_found else pk_src
            if resolved_pk in src_df.columns:
                empty_pk = src_df[resolved_pk].isna().sum() + (src_df[resolved_pk].astype(str).str.strip() == "").sum()
                if empty_pk > 0:
                    warnings.append(f"{empty_pk} sample rows in source file have empty primary key '{resolved_pk}'")
        except Exception as e:
            errors.append(f"Failed to read source file: {e}")

        # 5. Validate sitetracker file columns
        try:
            st_df = DataNormalizer.read_spreadsheet(st_file, nrows=10)

            if self.sf_id_column not in st_df.columns:
                # Check regex fallback
                has_sf_id = any(
                    st_df[col].astype(str).str.match(r"^a[0-9A-Za-z]{17}$").any()
                    for col in st_df.columns
                )
                if not has_sf_id:
                    errors.append(f"Sitetracker file missing Salesforce ID column '{self.sf_id_column}'")

            if pk_st not in st_df.columns:
                errors.append(f"Sitetracker file missing primary key column: '{pk_st}'")

            for _, st_col, _, _ in field_map:
                if st_col not in st_df.columns:
                    errors.append(
                        f"Sitetracker file missing mapped column: '{st_col}'. "
                        f"Available: {list(st_df.columns)}"
                    )
        except Exception as e:
            errors.append(f"Failed to read Sitetracker baseline file: {e}")

        # 6. Check date format parseability (sample)
        if "src_df" in locals():
            for src_col, st_col, api_col, dtype in field_map:
                resolved_col = DataNormalizer.resolve_source_column(src_df.columns, src_col, st_col, api_col)
                if dtype == "date" and resolved_col and resolved_col in src_df.columns:
                    sample = src_df[resolved_col].dropna().head(5)
                    for val in sample:
                        _, ok = DataNormalizer.normalize_date_uk(val)
                        if not ok:
                            warnings.append(
                                f"Date column '{resolved_col}' has unparseable sample value: '{val}'"
                            )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _check_directories(self) -> list[str]:
        errors = []
        if not self.source_dir.exists():
            errors.append(f"Source directory does not exist: {self.source_dir}")
        if not self.sitetracker_dir.exists():
            errors.append(f"Sitetracker directory does not exist: {self.sitetracker_dir}")
        return errors

    def _check_files(self) -> tuple[Path | None, Path | None, list[str]]:
        errors: list[str] = []
        src_file = self._get_single_file(self.source_dir, "Source", errors)
        st_file = self._get_single_file(self.sitetracker_dir, "Sitetracker", errors)
        return src_file, st_file, errors

    @staticmethod
    def _get_single_file(folder: Path, label: str, errors: list) -> Path | None:
        if not folder.exists():
            return None
        files = [f for f in folder.iterdir() if f.is_file() and not f.name.startswith(".")]
        if len(files) == 0:
            errors.append(f"No files found in {label} directory: {folder}")
            return None
        if len(files) > 1:
            if label == "Sitetracker":
                live_files = [f for f in files if f.name.endswith("_sitetracker_live.csv")]
                if live_files:
                    return sorted(live_files, key=lambda x: x.stat().st_mtime, reverse=True)[0]
            errors.append(
                f"{label} directory must contain exactly 1 file, found {len(files)}: "
                f"{[f.name for f in files]}"
            )
            return None
        return files[0]
