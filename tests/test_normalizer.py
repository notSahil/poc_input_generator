"""Unit tests for DataNormalizer."""

from datetime import datetime
import pandas as pd
import pytest
from core.normalizer import DataNormalizer


class TestNormalizeValue:
    def test_none_returns_empty_string(self):
        assert DataNormalizer.normalize_value(None) == ""

    def test_nan_returns_empty_string(self):
        assert DataNormalizer.normalize_value(float("nan")) == ""

    def test_whitespace_stripped(self):
        assert DataNormalizer.normalize_value("  Hello World  ") == "Hello World"

    def test_number_converted_to_string(self):
        assert DataNormalizer.normalize_value(12345) == "12345"


class TestComparableText:
    def test_en_dash_normalized(self):
        assert DataNormalizer.comparable_text("Site–A") == "Site-A"

    def test_em_dash_normalized(self):
        assert DataNormalizer.comparable_text("Site—A") == "Site-A"

    def test_multiple_spaces_collapsed(self):
        assert DataNormalizer.comparable_text("London   Central   Hub") == "London Central Hub"

    def test_none_returns_empty(self):
        assert DataNormalizer.comparable_text(None) == ""


class TestNormalizeDateUK:
    def test_valid_uk_date_string(self):
        fmt, ok = DataNormalizer.normalize_date_uk("15/03/2024")
        assert ok is True
        assert fmt == "15/03/2024"

    def test_iso_date_string(self):
        fmt, ok = DataNormalizer.normalize_date_uk("2024-03-15")
        assert ok is True
        assert fmt == "15/03/2024"

    def test_timestamp_object(self):
        dt = pd.Timestamp("2024-03-15")
        fmt, ok = DataNormalizer.normalize_date_uk(dt)
        assert ok is True
        assert fmt == "15/03/2024"

    def test_empty_value_is_valid(self):
        fmt, ok = DataNormalizer.normalize_date_uk("")
        assert ok is True
        assert fmt == ""

    def test_none_value_is_valid(self):
        fmt, ok = DataNormalizer.normalize_date_uk(None)
        assert ok is True
        assert fmt == ""

    def test_invalid_date_returns_false(self):
        fmt, ok = DataNormalizer.normalize_date_uk("not-a-valid-date")
        assert ok is False
        assert fmt == ""


class TestValidProjectRef:
    def test_alphanumeric_is_valid(self):
        assert DataNormalizer.valid_project_ref("SITE123") is True

    def test_dashes_and_underscores_are_valid(self):
        assert DataNormalizer.valid_project_ref("SITE-123_A") is True

    def test_empty_string_is_invalid(self):
        assert DataNormalizer.valid_project_ref("") is False

    def test_spaces_are_invalid(self):
        assert DataNormalizer.valid_project_ref("SITE 123") is False

    def test_special_characters_are_invalid(self):
        assert DataNormalizer.valid_project_ref("SITE@123#") is False


class TestNormalizeTextCase:
    def test_lower_to_title(self):
        assert DataNormalizer.normalize_text_case("london central") == "London Central"

    def test_upper_to_title(self):
        assert DataNormalizer.normalize_text_case("LONDON CENTRAL") == "London Central"

    def test_none_returns_empty(self):
        assert DataNormalizer.normalize_text_case(None) == ""


class TestNormalizeColumns:
    def test_bom_and_nbsp_stripped(self):
        df = pd.DataFrame(columns=["\ufeffSite Ref", "Name\u00a0", "  Date  "])
        clean_df = DataNormalizer.normalize_columns(df)
        assert list(clean_df.columns) == ["Site Ref", "Name", "Date"]
