"""Data normalization utilities."""

from collections.abc import Iterable
from datetime import datetime
import re
import warnings
import pandas as pd


class DataNormalizer:
    @staticmethod
    def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """Strip invisible unicode characters and extra whitespace from DataFrame column names."""
        df.columns = (
            df.columns.astype(str)
            .str.replace("\ufeff", "", regex=False)
            .str.replace("\u00a0", "", regex=False)
            .str.strip()
        )
        return df

    @staticmethod
    def resolve_source_column(
        candidates: Iterable[str],
        s_col: str,
        st_col: str | None = None,
        api_col: str | None = None,
    ) -> str | None:
        """Resolve which column in `candidates` matches a mapped field.

        Search hierarchy:
        1. Exact match for `s_col` (Source File Column Name from mapping)
        2. Exact match for `st_col` (Sitetracker Field Name from mapping)
        3. Exact match for `api_col` (Salesforce API Name from mapping)
        4. Case-insensitive / whitespace-stripped match for `s_col`
        5. Case-insensitive / whitespace-stripped match for `st_col`
        6. Case-insensitive / whitespace-stripped match for `api_col`

        Returns the exact candidate string from `candidates` if matched, else None.
        """
        cand_list = [str(c).strip() for c in candidates if pd.notna(c) and str(c).strip() and str(c).strip().lower() != "nan"]
        cand_set = set(cand_list)

        # 1. Exact matches in priority order
        if s_col and str(s_col).strip() in cand_set:
            return str(s_col).strip()
        if st_col and str(st_col).strip() in cand_set:
            return str(st_col).strip()
        if api_col and str(api_col).strip() in cand_set:
            return str(api_col).strip()

        # 2. Case-insensitive / whitespace-stripped matches in priority order
        s_clean = str(s_col).strip().lower() if s_col else ""
        st_clean = str(st_col).strip().lower() if st_col else ""
        api_clean = str(api_col).strip().lower() if api_col else ""

        for target in (s_clean, st_clean, api_clean):
            if not target or target == "nan":
                continue
            for c in cand_list:
                if c.lower() == target:
                    return c

        return None

    @staticmethod
    def normalize_value(v) -> str:
        """Convert null/nan values to empty string and strip string values."""
        if pd.isna(v) or v is None:
            return ""
        val = str(v).strip()
        if val.lower() in ("none", "nan", "null", "<na>"):
            return ""
        return val

    @staticmethod
    def comparable_text(v) -> str:
        """Normalize dashes, whitespace and strip for reliable delta comparison."""
        if pd.isna(v) or v is None:
            return ""
        text = str(v).replace("–", "-").replace("—", "-")
        norm = re.sub(r"\s+", " ", text).strip()
        if norm.lower() in ("none", "nan", "null", "<na>"):
            return ""
        return norm

    @staticmethod
    def normalize_date_uk(v) -> tuple[str, bool]:
        """
        Normalize date string or datetime object to UK format (dd/mm/yyyy).
        Returns (formatted_date_string, is_valid_boolean).
        """
        if pd.isna(v) or v is None or str(v).strip() == "":
            return "", True

        if isinstance(v, (pd.Timestamp, datetime)):
            return v.strftime("%d/%m/%Y"), True

        v_str = str(v).strip()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                if re.match(r"^\d{4}-\d{2}-\d{2}", v_str):
                    dt = pd.to_datetime(v_str, errors="raise", dayfirst=False)
                else:
                    dt = pd.to_datetime(v_str, errors="raise", dayfirst=True)
            return dt.strftime("%d/%m/%Y"), True
        except Exception:
            return "", False

    @staticmethod
    def valid_project_ref(v) -> bool:
        """Check if project reference / primary key contains valid alphanumeric/dash/underscore characters."""
        if pd.isna(v) or v is None or str(v).strip() == "":
            return False
        return bool(re.match(r"^[A-Za-z0-9_-]+$", str(v).strip()))

    @staticmethod
    def normalize_text_case(v) -> str:
        """Title-case a string value while preserving empty values."""
        if pd.isna(v) or v is None:
            return ""
        return str(v).strip().title()

    @staticmethod
    def validate_number(v) -> tuple[str, bool]:
        """
        Validate and normalize a number value (int or float).
        Empty/blank is allowed (returns '', True).
        Returns (normalized_string, is_valid).
        """
        if pd.isna(v) or v is None or str(v).strip() == "":
            return "", True
        v_str = str(v).strip().replace(",", "")  # allow comma-formatted numbers
        try:
            parsed = float(v_str)
            # Return as int string if whole number, else float string
            if parsed == int(parsed):
                return str(int(parsed)), True
            return str(parsed), True
        except (ValueError, OverflowError):
            return "", False

    @staticmethod
    def validate_boolean(v) -> tuple[str, bool]:
        """
        Validate and normalize a boolean value.
        Accepts: True/False/Yes/No/1/0 (case-insensitive).
        Empty/blank is allowed (returns '', True).
        Returns (normalized_string, is_valid).
        """
        if pd.isna(v) or v is None or str(v).strip() == "":
            return "", True
        v_str = str(v).strip().lower()
        true_vals = {"true", "yes", "1", "y"}
        false_vals = {"false", "no", "0", "n"}
        if v_str in true_vals:
            return "true", True
        if v_str in false_vals:
            return "false", True
        return "", False

    @staticmethod
    def validate_text_length(v, max_len: int = 255) -> tuple[str, bool]:
        """
        Validate that a text value does not exceed Salesforce's default field length.
        Empty/blank is allowed.
        Returns (value, is_valid).
        """
        if pd.isna(v) or v is None or str(v).strip() == "":
            return "", True
        v_str = str(v).strip()
        if len(v_str) > max_len:
            return v_str, False
        return v_str, True

    @staticmethod
    def read_spreadsheet(file_or_path, nrows: int | None = None) -> pd.DataFrame:
        """
        Universally read Excel (.xlsx, .xls) or CSV files into a DataFrame.
        Supports file paths (str, Path) or file-like objects (e.g. Streamlit UploadedFile, io.BytesIO).
        All columns are converted to str and stripped of special characters.
        Handles both UTF-8 and Windows latin-1 / ANSI encodings gracefully.
        """
        from pathlib import Path

        # Check if file_or_path is a file-like object (e.g. Streamlit UploadedFile, BytesIO)
        if hasattr(file_or_path, "read"):
            filename = getattr(file_or_path, "name", "")
            ext = Path(filename).suffix.lower() if filename else ""

            if hasattr(file_or_path, "seek"):
                file_or_path.seek(0)

            if ext in (".xlsx", ".xls"):
                try:
                    df = pd.read_excel(file_or_path, dtype=str, nrows=nrows)
                except Exception:
                    if hasattr(file_or_path, "seek"):
                        file_or_path.seek(0)
                    df = pd.read_excel(file_or_path, nrows=nrows)
            else:
                try:
                    df = pd.read_csv(file_or_path, dtype=str, nrows=nrows, encoding="utf-8")
                except UnicodeDecodeError:
                    if hasattr(file_or_path, "seek"):
                        file_or_path.seek(0)
                    df = pd.read_csv(
                        file_or_path,
                        dtype=str,
                        nrows=nrows,
                        encoding="latin1",
                        engine="python",
                        on_bad_lines="skip",
                    )
        else:
            path = Path(file_or_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")

            ext = path.suffix.lower()
            if ext in (".xlsx", ".xls"):
                try:
                    df = pd.read_excel(path, dtype=str, nrows=nrows)
                except Exception:
                    df = pd.read_excel(path, nrows=nrows)
            else:
                try:
                    df = pd.read_csv(path, dtype=str, nrows=nrows, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(
                        path,
                        dtype=str,
                        nrows=nrows,
                        encoding="latin1",
                        engine="python",
                        on_bad_lines="skip",
                    )

        df = DataNormalizer.normalize_columns(df)
        return df.fillna("").astype(str)

