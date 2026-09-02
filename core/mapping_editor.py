"""Read, edit, and save the mapping file with version history."""

import logging
from pathlib import Path
import shutil
from datetime import datetime
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "Report Name",
    "Object Name",
    "Source File Column Name",
    "Sitetracker Field Name",
    "API Name",
    "Data Type",
    "Primary Key?"
]


class MappingEditor:
    def __init__(self, mapping_file: Path | None = None, history_dir: Path | None = None):
        self.file_path = mapping_file or settings.MAPPING_FILE
        self.history_dir = history_dir or settings.MAPPING_HISTORY_DIR
        self._df: pd.DataFrame | None = None

    def load(self) -> pd.DataFrame:
        """Load the full mapping file as a DataFrame."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"Mapping file not found: {self.file_path}")

        self._df = pd.read_excel(self.file_path, dtype=str)
        self._df.columns = self._df.columns.astype(str).str.strip()

        # Ensure all expected columns exist
        for col in EXPECTED_COLUMNS:
            if col not in self._df.columns:
                self._df[col] = ""

        return self._df.copy()

    def get_reports(self) -> list[str]:
        """Return list of unique report names."""
        df = self.load()
        return sorted(df["Report Name"].dropna().astype(str).str.strip().unique().tolist())

    def get_rows_for_report(self, report_name: str) -> pd.DataFrame:
        """Return mapping rows filtered for a specific report."""
        df = self.load()
        return df[df["Report Name"].astype(str).str.strip() == report_name].copy()

    def add_row(self, row: dict) -> None:
        """Add a new mapping row."""
        df = self.load()

        clean_row = {col: str(row.get(col, "")).strip() for col in EXPECTED_COLUMNS}
        new_row_df = pd.DataFrame([clean_row])
        self._df = pd.concat([df, new_row_df], ignore_index=True)

    def add_rows(self, rows: list[dict]) -> None:
        """Add multiple mapping rows at once."""
        df = self.load()
        clean_rows = [{col: str(row.get(col, "")).strip() for col in EXPECTED_COLUMNS} for row in rows]
        new_rows_df = pd.DataFrame(clean_rows)
        self._df = pd.concat([df, new_rows_df], ignore_index=True)

    def replace_from_upload(self, uploaded_file) -> Path:
        """Replace the active mapping file with an uploaded Excel file, creating a backup first."""
        new_df = pd.read_excel(uploaded_file, dtype=str)
        new_df.columns = new_df.columns.astype(str).str.strip()
        for col in EXPECTED_COLUMNS:
            if col not in new_df.columns:
                raise ValueError(f"Uploaded file is missing required column: '{col}'")
        backup = self._create_backup(reason="before_upload_replace")
        self._df = new_df
        self.save(reason="user_upload")
        return backup

    def update_row(self, index: int, updates: dict) -> None:
        """Update a specific row by its DataFrame index."""
        if self._df is None:
            self.load()

        for col, val in updates.items():
            if col in self._df.columns:
                self._df.at[index, col] = str(val).strip()

    def delete_row(self, index: int) -> None:
        """Delete a row by its DataFrame index."""
        if self._df is None:
            self.load()
        self._df = self._df.drop(index).reset_index(drop=True)

    def save(self, reason: str = "") -> Path:
        """Save the mapping file. Creates a versioned backup first."""
        if self._df is None:
            raise RuntimeError("No data loaded in MappingEditor. Call load() first.")

        # Create backup of the current file before saving new edits
        backup_path = self._create_backup(reason)

        # Reorder columns to standard order
        ordered_cols = [c for c in EXPECTED_COLUMNS if c in self._df.columns]
        remaining_cols = [c for c in self._df.columns if c not in EXPECTED_COLUMNS]
        self._df = self._df[ordered_cols + remaining_cols]

        # Write to Excel
        self._df.to_excel(self.file_path, index=False, engine="openpyxl")
        logger.info("Mapping file saved to %s. Backup: %s", self.file_path, backup_path)

        return backup_path

    def _create_backup(self, reason: str = "") -> Path:
        """Create a timestamped backup of the current mapping file."""
        self.history_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_reason = "".join(c for c in reason if c.isalnum() or c in "_-")
        suffix = f"_{clean_reason}" if clean_reason else ""
        backup_name = f"Mapping_file_{timestamp}{suffix}.xlsx"
        backup_path = self.history_dir / backup_name

        if self.file_path.exists():
            shutil.copy2(self.file_path, backup_path)
            logger.info("Created mapping backup: %s", backup_path)

        return backup_path

    def list_history(self) -> list[dict]:
        """List all historical versions of the mapping file."""
        if not self.history_dir.exists():
            return []

        versions = []
        for f in sorted(self.history_dir.glob("Mapping_file_*.xlsx"), reverse=True):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                size_kb = round(f.stat().st_size / 1024, 1)
                versions.append({
                    "filename": f.name,
                    "path": str(f),
                    "modified": mtime,
                    "size_kb": size_kb
                })
            except Exception as e:
                logger.warning("Error reading backup file %s: %s", f, e)

        return versions

    def restore_version(self, version_path: str | Path) -> None:
        """Restore a historical version as the current active mapping file."""
        version = Path(version_path)
        if not version.exists():
            raise FileNotFoundError(f"Version file not found: {version_path}")

        # Backup current version before restoring
        self._create_backup(reason="before_restore")

        shutil.copy2(version, self.file_path)
        # Reload memory
        self.load()
        logger.info("Restored mapping from: %s", version_path)
