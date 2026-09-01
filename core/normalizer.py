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
