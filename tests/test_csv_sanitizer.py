"""Unit tests for salesforce/csv_sanitizer.py.

Verifies that raw Salesforce Bulk API 2.0 failure CSV responses with unescaped
internal double quotes, multiline Apex stack traces, and unquoted commas are
repaired into valid RFC 4180 CSV without dropping a single record.
"""

from __future__ import annotations

import io
import pandas as pd
import pytest

from salesforce.csv_sanitizer import is_valid_salesforce_id, sanitize_failure_csv


class TestIsValidSalesforceId:
    """Test suite for is_valid_salesforce_id."""

    def test_valid_custom_object_18char(self):
        assert is_valid_salesforce_id("a1e4J000000RTohQAG") is True
        assert is_valid_salesforce_id("a0i8e000000NzWCAA0") is True

    def test_valid_custom_object_15char(self):
        assert is_valid_salesforce_id("a1e4J000000RToh") is True
        assert is_valid_salesforce_id("a0i8e000000NzWC") is True

    def test_valid_standard_object_account(self):
        # 001 prefix is Account in standard Salesforce
        assert is_valid_salesforce_id("0018e000001AbCdEFG") is True
        assert is_valid_salesforce_id("0018e000001AbCd") is True

    def test_valid_standard_object_case(self):
        # 500 prefix is Case in standard Salesforce
        assert is_valid_salesforce_id("5008e000001XyZ1234") is True

    def test_valid_test_fixture_short_id(self):
        # Unit test fixtures frequently use short synthetic IDs like 'a123'
        assert is_valid_salesforce_id("a123") is True
        assert is_valid_salesforce_id("test1") is True

    def test_rejects_empty_or_whitespace(self):
        assert is_valid_salesforce_id("") is False
        assert is_valid_salesforce_id("   ") is False
        assert is_valid_salesforce_id(None) is False

    def test_rejects_nan_and_sentinels(self):
        assert is_valid_salesforce_id("nan") is False
        assert is_valid_salesforce_id("NaN") is False
        assert is_valid_salesforce_id("null") is False
        assert is_valid_salesforce_id("UNKNOWN_ID") is False
        assert is_valid_salesforce_id("sf__Id") is False

    def test_rejects_error_fragments(self):
        # Stack trace fragments that appear at the start of continuation lines
        assert is_valid_salesforce_id("caused by: System.DmlException") is False
        assert is_valid_salesforce_id("Class.BT_Project_Trigger: line 42") is False
        assert is_valid_salesforce_id('Validation Formula "Rule"') is False
        assert is_valid_salesforce_id("(max length=12):WES_PSID__c --") is False


class TestSanitizeFailureCsv:
    """Test suite for sanitize_failure_csv."""

    def test_empty_input_handling(self):
        assert sanitize_failure_csv("") == ""
        assert sanitize_failure_csv("   \n\r  ") == ""

    def test_non_failure_csv_passthrough(self):
        sample = "Col1,Col2\nVal1,Val2\n"
        assert sanitize_failure_csv(sample) == sample

    def test_clean_csv_passthrough(self):
        clean_csv = (
            "sf__Id,sf__Error,Ran_Priority__c,Id\n"
            "a1e4J000000RTohQAG,FIELD_CUSTOM_VALIDATION_EXCEPTION: Missing document,Cisco,a1e4J000000RTohQAG\n"
            "a1e8e000000kjz7AAA,STRING_TOO_LONG: Value too long,Cisco,a1e8e000000kjz7AAA\n"
        )
        sanitized = sanitize_failure_csv(clean_csv)
        df = pd.read_csv(io.StringIO(sanitized), dtype=str, on_bad_lines="warn", engine="python")
        assert len(df) == 2
        assert df.iloc[0]["sf__Id"] == "a1e4J000000RTohQAG"
        assert df.iloc[1]["sf__Id"] == "a1e8e000000kjz7AAA"

    def test_unescaped_internal_double_quotes_repaired(self):
        # Unescaped internal quotes inside validation rule message
        malformed = (
            'sf__Id,sf__Error,WES_PSID__c,Id\n'
            'a0i8e000000NzWCAA0,"FIELD_CUSTOM_VALIDATION_EXCEPTION:Formula "Actual_Date_Cant_Updated" Invalid:--",BW-SAFE-004,a0i8e000000NzWCAA0\n'
            'a0iTe000008aH5mIAE,STRING_TOO_LONG: Value too long,BTWD-TOOLONG-999,a0iTe000008aH5mIAE\n'
        )
        sanitized = sanitize_failure_csv(malformed)
        df = pd.read_csv(io.StringIO(sanitized), dtype=str, on_bad_lines="warn", engine="python")
        # Assert BOTH records are retained, zero rows dropped
        assert len(df) == 2
        assert df.iloc[0]["sf__Id"] == "a0i8e000000NzWCAA0"
        assert "Actual_Date_Cant_Updated" in df.iloc[0]["sf__Error"]
        assert df.iloc[0]["WES_PSID__c"] == "BW-SAFE-004"
        assert df.iloc[1]["sf__Id"] == "a0iTe000008aH5mIAE"

    def test_multiline_apex_stack_trace_stitched(self):
        # Multiline stack trace without proper CSV quote wrapping
        multiline = (
            "sf__Id,sf__Error,WES_PSID__c,Id\n"
            "a0i8e000000NzWCAA0,CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY:BTProjectTrigger: execution of AfterUpdate\n"
            "caused by: System.DmlException: Insert failed.\n"
            "Class.BT_Project_Trigger_Handler: line 84:--,BW-SAFE-004,a0i8e000000NzWCAA0\n"
            "a0iTe000008aH5mIAE,Normal Error,BTWD-TOOLONG-999,a0iTe000008aH5mIAE\n"
        )
        sanitized = sanitize_failure_csv(multiline)
        df = pd.read_csv(io.StringIO(sanitized), dtype=str, on_bad_lines="warn", engine="python")
        # Assert both records are retained
        assert len(df) == 2
        rec1 = df.iloc[0]
        assert rec1["sf__Id"] == "a0i8e000000NzWCAA0"
        assert "execution of AfterUpdate" in rec1["sf__Error"]
        assert "System.DmlException" in rec1["sf__Error"]
        assert "line 84" in rec1["sf__Error"]
        assert rec1["WES_PSID__c"] == "BW-SAFE-004"
        assert rec1["Id"] == "a0i8e000000NzWCAA0"

    def test_two_column_failure_csv(self):
        # 2-column format (sf__Id, sf__Error) common in minimal Bulk API jobs
        two_col = (
            "sf__Id,sf__Error\n"
            "a123,CANNOT_INSERT_UPDATE_ACTIVATE_ENTITY:BTProjectTrigger: System.LimitException: Too many DML statements: 151:--\n"
            "caused by: line 42\n"
            "a456,DUPLICATE_VALUE: duplicate value found: Name duplicates value on record with id: a123\n"
        )
        sanitized = sanitize_failure_csv(two_col)
        df = pd.read_csv(io.StringIO(sanitized), dtype=str, on_bad_lines="warn", engine="python")
        assert len(df) == 2
        assert df.iloc[0]["sf__Id"] == "a123"
        assert "Too many DML statements" in df.iloc[0]["sf__Error"]
        assert "caused by: line 42" in df.iloc[0]["sf__Error"]
        assert df.iloc[1]["sf__Id"] == "a456"

    def test_embedded_commas_in_error_preserved(self):
        raw = (
            "sf__Id,sf__Error\n"
            "a1e4J000000RTohQAG,FIELD_CUSTOM_VALIDATION_EXCEPTION:Error message, with comma, and details:--\n"
        )
        sanitized = sanitize_failure_csv(raw)
        df = pd.read_csv(io.StringIO(sanitized), dtype=str, on_bad_lines="warn", engine="python")
        assert len(df) == 1
        assert "with comma, and details" in df.iloc[0]["sf__Error"]
