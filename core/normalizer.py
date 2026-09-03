"""Data normalization utilities."""

import re
import warnings
from datetime import datetime
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
    def normalize_value(v) -> str:
        """Convert null/nan values to empty string and strip string values."""
        if pd.isna(v) or v is None:
            return ""
        return str(v).strip()

    @staticmethod
    def comparable_text(v) -> str:
        """Normalize dashes, whitespace and strip for reliable delta comparison."""
        if pd.isna(v) or v is None:
            return ""
        text = str(v).replace("–", "-").replace("—", "-")
        return re.sub(r"\s+", " ", text).strip()

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
