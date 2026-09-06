"""Mapping configuration loader for Excel mapping files."""

import logging
from pathlib import Path
import pandas as pd

from config import settings
from core.exceptions import MappingError, MappingFileNotFoundError

logger = logging.getLogger(__name__)


class MappingLoader:
    def __init__(self, mapping_file: str | Path | None = None, report_name: str = ""):
        self.mapping_file = Path(mapping_file) if mapping_file else settings.MAPPING_FILE
        self.report_name = report_name
        self.mapping_df: pd.DataFrame | None = None

    def load(self) -> pd.DataFrame:
        """Load mapping rows for the current report from the Excel mapping file."""
        if not self.mapping_file.exists():
            raise MappingFileNotFoundError(f"Mapping file not found at: {self.mapping_file}")

        try:
            df = pd.read_excel(self.mapping_file, dtype=str)
        except Exception as e:
            raise MappingError(f"Failed to read mapping file {self.mapping_file}: {e}")

        df.columns = df.columns.astype(str).str.strip()

        if "Report Name" not in df.columns:
            raise MappingError(f"Mapping file missing 'Report Name' column. Columns found: {list(df.columns)}")

        report_df = df[df["Report Name"] == self.report_name]

        if report_df.empty:
            available = sorted(df["Report Name"].dropna().unique().tolist())
            raise MappingError(
                f"No mapping rows found for report '{self.report_name}' in {self.mapping_file.name}.\n"
                f"Available reports in mapping file: {available}"
            )

        self.mapping_df = report_df
        return report_df

    def primary_keys(self) -> tuple[str, str]:
        """Return (source_primary_key_col, sitetracker_primary_key_col)."""
        if self.mapping_df is None:
            self.load()

        if "Primary Key?" not in self.mapping_df.columns:
            raise MappingError("Mapping file missing 'Primary Key?' column.")

        pk_row = self.mapping_df[
            self.mapping_df["Primary Key?"].astype(str).str.strip().str.upper() == "YES"
        ]

        if pk_row.empty:
            raise MappingError(f"Primary key not defined for report '{self.report_name}' in mapping file (no 'YES' in 'Primary Key?' column).")

        src_pk = pk_row.iloc[0].get("Source File Column Name")
        st_pk = pk_row.iloc[0].get("Sitetracker Field Name")

        if not src_pk or not st_pk:
            raise MappingError(f"Primary key row has empty column name for source or sitetracker: src='{src_pk}', st='{st_pk}'")

        return str(src_pk).strip(), str(st_pk).strip()

    def all_primary_keys(self) -> list[dict[str, str]]:
        """Return all primary key definitions for this report (supporting multiple or per-object PKs)."""
        if self.mapping_df is None:
            self.load()

        if "Primary Key?" not in self.mapping_df.columns:
            return []

        pk_rows = self.mapping_df[
            self.mapping_df["Primary Key?"].astype(str).str.strip().str.upper().isin(["YES", "Y", "TRUE"])
        ]

        results = []
        for _, r in pk_rows.iterrows():
            src_pk = str(r.get("Source File Column Name", "")).strip()
            st_pk = str(r.get("Sitetracker Field Name", "")).strip()
            obj = str(r.get("Object Name", "")).strip()
            api = str(r.get("API Name", "")).strip()
            if src_pk and st_pk:
                results.append({
                    "source": src_pk,
                    "sitetracker": st_pk,
                    "object": obj,
                    "api_name": api,
                })
        return results

    def objects(self) -> list[str]:
        """Return list of distinct Salesforce object names defined for this report."""
        if self.mapping_df is None:
            self.load()

        if "Object Name" not in self.mapping_df.columns:
            return []

        raw_objs = self.mapping_df["Object Name"].dropna().unique().tolist()
        return [str(o).strip() for o in raw_objs if str(o).strip() and str(o).strip().lower() != "nan"]

    def field_mapping(self) -> list[tuple[str, str, str, str]]:
        """Return list of (Source Col, Sitetracker Col, API Name, Data Type)."""
        if self.mapping_df is None:
            self.load()

        required_cols = ["Source File Column Name", "Sitetracker Field Name", "API Name", "Data Type"]
        for col in required_cols:
            if col not in self.mapping_df.columns:
                raise MappingError(f"Mapping file missing required column: '{col}'")

        return [
            (
                str(r["Source File Column Name"]).strip(),
                str(r["Sitetracker Field Name"]).strip(),
                str(r["API Name"]).strip(),
                str(r["Data Type"]).strip().lower()
            )
            for _, r in self.mapping_df.iterrows()
        ]
