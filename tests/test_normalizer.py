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


class TestValidateNumber:
    def test_integer(self):
        val, ok = DataNormalizer.validate_number("123")
        assert ok is True
        assert val == "123"

    def test_float(self):
        val, ok = DataNormalizer.validate_number("123.45")
        assert ok is True
        assert val == "123.45"

    def test_with_commas(self):
        val, ok = DataNormalizer.validate_number("1,234.50")
        assert ok is True
        assert val == "1234.5"

    def test_empty_is_valid(self):
        val, ok = DataNormalizer.validate_number("")
        assert ok is True
        assert val == ""

    def test_invalid_text_is_rejected(self):
        _, ok = DataNormalizer.validate_number("one hundred")
        assert ok is False


class TestValidateBoolean:
    def test_true_values(self):
        for v in ["true", "True", "YES", "Yes", "1", "y"]:
            val, ok = DataNormalizer.validate_boolean(v)
            assert ok is True
            assert val == "true"

    def test_false_values(self):
        for v in ["false", "False", "NO", "No", "0", "n"]:
            val, ok = DataNormalizer.validate_boolean(v)
            assert ok is True
            assert val == "false"

    def test_empty_is_valid(self):
        val, ok = DataNormalizer.validate_boolean("")
        assert ok is True
        assert val == ""

    def test_invalid_boolean_is_rejected(self):
        _, ok = DataNormalizer.validate_boolean("maybe")
        assert ok is False


class TestValidateTextLength:
    def test_within_limit(self):
        val, ok = DataNormalizer.validate_text_length("hello", max_len=10)
        assert ok is True
        assert val == "hello"

    def test_exceeding_limit(self):
        _, ok = DataNormalizer.validate_text_length("hello world", max_len=5)
        assert ok is False


class TestImpossibleCalendarDates:
    def test_november_31st_is_invalid(self):
        _, ok = DataNormalizer.normalize_date_uk("31/11/2025")
        assert ok is False

    def test_february_29_non_leap_year_is_invalid(self):
        _, ok = DataNormalizer.normalize_date_uk("29/02/2025")
        assert ok is False

    def test_month_13_is_invalid(self):
        _, ok = DataNormalizer.normalize_date_uk("15/13/2025")
        assert ok is False

