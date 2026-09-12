"""Unit tests for core/audit_logger.py."""

from pathlib import Path
from unittest.mock import patch
import pytest

from core.audit_logger import AuditLogger, mask_secrets, resolve_user_identity


def test_mask_secrets():
    raw_1 = "Connected using Bearer 00D8b0000001xyz!AQwE.fake_token_value_here"
    masked_1 = mask_secrets(raw_1)
    assert "fake_token_value_here" not in masked_1
    assert "Bearer [MASKED_TOKEN]" in masked_1

    raw_2 = "client_secret = 'super_secret_password_123' and password: 'secret'"
    masked_2 = mask_secrets(raw_2)
    assert "super_secret_password_123" not in masked_2
    assert "[MASKED_SECRET]" in masked_2


def test_resolve_user_identity_offline():
    identity = resolve_user_identity(profile="non_existent_profile")
    assert isinstance(identity, dict)
    assert "user_name" in identity
    assert "org_name" in identity
    assert "profile" in identity


def test_audit_logger_lifecycle(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    logger.start_run(
        run_id="run_2026-09-12_01",
        report_name="Apollo 10G",
        mode="Guided Pipeline",
        user="sahil@example.com",
        org="Partial Copy Sandbox",
    )
    logger.info("Source input processed", tag="INPUT", Source_File="apollo.xlsx", Rows=100)
    logger.warning("Duplicate key detected", tag="VALIDATION", Key="TM-999")
    logger.finish(status="SUCCESS", duration_sec=12.4, successes=100, failures=0, output_files=["final_input_file.csv"])

    log_content = logger.read_log()
    assert "Run initialized: Apollo 10G" in log_content
    assert "[START]" in log_content
    assert "sahil@example.com" in log_content
    assert "[INPUT] Source input processed" in log_content
    assert "Rows: 100" in log_content
    assert "[WARNING] [VALIDATION] Duplicate key detected" in log_content
    assert "[FINISH] Run completed with status: SUCCESS" in log_content
    assert "Duration: 12.4s" in log_content


def test_audit_logger_record_error(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    logger.record_error(
        record_id="a0i8b00000H8xYZAAY",
        object_name="sitetracker__Project__c",
        field_name="Actual_End_Date__c",
        error_code="FIELD_CUSTOM_VALIDATION_EXCEPTION",
        message="Actual Date cannot be updated when status is Approved.",
    )

    log_content = logger.read_log()
    assert "[ERROR] [RECORD_ERROR]" in log_content
    assert "a0i8b00000H8xYZAAY" in log_content
    assert "Actual_End_Date__c" in log_content
    assert "FIELD_CUSTOM_VALIDATION_EXCEPTION" in log_content
    assert "Actual Date cannot be updated when status is Approved." in log_content


def test_audit_logger_network_error(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    import requests
    timeout_err = requests.exceptions.ConnectTimeout("HTTPSConnectionPool: Read timed out after 30s")
    logger.network_error(
        operation="Salesforce REST Composite Upload",
        error=timeout_err,
        attempt=2,
        timeout=30.0,
        Target_URL="https://company.my.salesforce.com/services/data/v60.0/composite/sobjects",
    )

    log_content = logger.read_log()
    assert "[ERROR] [NETWORK_ERROR]" in log_content
    assert "ConnectTimeout" in log_content
    assert "Attempt: 2" in log_content
    assert "Timeout_Seconds: 30.0" in log_content


def test_audit_logger_exception_traceback(tmp_path: Path):
    logger = AuditLogger(tmp_path)
    try:
        # Deliberate division by zero to generate a real traceback
        _ = 1 / 0
    except ZeroDivisionError as e:
        logger.exception("Unexpected calculation crash", exc=e, Operation="Delta Engine")

    log_content = logger.read_log()
    assert "[ERROR] [EXCEPTION] Unexpected calculation crash" in log_content
    assert "ZeroDivisionError: division by zero" in log_content
    assert "test_audit_logger.py" in log_content
    assert "line " in log_content


def test_audit_logger_write_failure_safety(tmp_path: Path):
    # Pass a path that cannot be written to or mock an exception
    logger = AuditLogger(tmp_path)
    with patch("builtins.open", side_effect=PermissionError("Mocked Permission Denied")):
        # Must not raise an exception to the caller
        logger.info("Test message that fails to write")
        logger.record_error("rec1", "obj1", "err")
        logger.exception("crash")
