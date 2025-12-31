# engine/normalizer.py

import pandas as pd
import re
from datetime import datetime


class DataNormalizer:
    @staticmethod
    def normalize_columns(df):
        df.columns = (
            df.columns.astype(str)
            .str.replace("\ufeff", "", regex=False)
            .str.replace("\u00a0", "", regex=False)
            .str.strip()
        )
        return df

    @staticmethod
    def normalize_value(v):
        if pd.isna(v):
            return ""
        return str(v).strip()

    @staticmethod
    def comparable_text(v):
        if pd.isna(v):
            return ""
        text = str(v).replace("–", "-").replace("—", "-")
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def normalize_date_uk(v):
        if pd.isna(v) or str(v).strip() == "":
            return "", True

        if isinstance(v, (pd.Timestamp, datetime)):
            return v.strftime("%d/%m/%Y"), True

        try:
            dt = pd.to_datetime(str(v).strip(), errors="raise", dayfirst=True)
            return dt.strftime("%d/%m/%Y"), True
        except Exception:
            return "", False

    @staticmethod
    def valid_project_ref(v):
        return bool(re.match(r"^[A-Za-z0-9_-]+$", str(v)))

    @staticmethod
    def normalize_text_case(v):
        if pd.isna(v):
            return ""
        return str(v).strip().title()