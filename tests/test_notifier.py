"""Unit tests for core/notifier.py (In-App, Email, Slack, and MS Teams alerts)."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from core.job_store import get_unread_notifications, init_db
from core.notifier import (
    _send_email_safe,
    _send_slack_safe,
    _send_teams_safe,
    build_notification_payload,
    dispatch_notification,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    test_db = tmp_path / "test_jobs.db"
    init_db(test_db)
    return test_db


def test_build_notification_payload():
    """Verify title, message, and secret masking in payload construction."""
    payload = build_notification_payload(
        report_name="Apollo 10G",
        profile="sandbox",
        status="SUCCESS",
        total_records=100,
        successful_records=95,
        failed_records=0,
        skipped_records=5,
        schedule_name="Daily Apollo",
    )
    assert "Apollo 10G" in payload["title"]
    assert "Daily Apollo" in payload["message"]
    assert "95 updated" in payload["message"]
    assert payload["notification_type"] == "SUCCESS"


def test_build_notification_payload_masks_tokens():
    """Verify sensitive tokens are masked in output messages."""
    payload = build_notification_payload(
        report_name="Apollo 10G",
        profile="sandbox",
        status="FAILURE",
        error_summary="Failed with Bearer 00D5e000000Xyz!AR8Q token error",
    )
    assert "00D5e000000Xyz!AR8Q" not in payload["message"]
    assert "[MASKED_TOKEN]" in payload["message"] or "[MASKED_SESSION_ID]" in payload["message"]


def test_dispatch_in_app_notification(db_path: Path, monkeypatch):
    """Verify in-app notifications are stored properly in the database."""
    monkeypatch.setattr("config.settings.JOBS_DB_PATH", db_path)

    dispatch_notification(
        title="Test Ingest",
        message="Testing in-app storage",
        profile="sandbox",
        notification_type="SUCCESS",
        async_dispatch=False,
    )

    unread = get_unread_notifications("sandbox", db_path=db_path)
    assert len(unread) == 1
    assert unread[0]["title"] == "Test Ingest"
    assert unread[0]["message"] == "Testing in-app storage"


def test_email_notification_mocked(monkeypatch):
    """Verify SMTP interaction when configured."""
    monkeypatch.setattr("config.settings.SMTP_HOST", "smtp.test.relay")
    monkeypatch.setattr("config.settings.SMTP_PORT", 587)
    monkeypatch.setattr("config.settings.SMTP_USER", "test_user")
    monkeypatch.setattr("config.settings.SMTP_PASSWORD", "test_pass")
    monkeypatch.setattr("config.settings.SMTP_SENDER", "alerts@test.com")
    monkeypatch.setattr("config.settings.SMTP_USE_TLS", True)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        success = _send_email_safe(
            subject="Test Subject",
            message="Test Message Content",
            notification_type="SUCCESS",
            recipient_emails=["ops@test.com"],
        )
        assert success is True
        mock_smtp_cls.assert_called_once_with("smtp.test.relay", 587, timeout=10.0)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("test_user", "test_pass")
        mock_smtp_instance.sendmail.assert_called_once()


def test_email_notification_unconfigured(monkeypatch):
    """When SMTP is not configured, silently skips and returns False."""
    monkeypatch.setattr("config.settings.SMTP_HOST", "")
    assert _send_email_safe(subject="Subj", message="Msg", notification_type="INFO") is False


def test_slack_notification_mocked(monkeypatch):
    """Verify Slack webhook POST request."""
    monkeypatch.setattr("config.settings.SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T00/B00/X00")
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        success = _send_slack_safe("Title", "Message", "SUCCESS")
        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "https://hooks.slack.com" in args[0]
        assert "blocks" in kwargs["json"]


def test_teams_notification_mocked(monkeypatch):
    """Verify MS Teams webhook POST request."""
    monkeypatch.setattr("config.settings.TEAMS_WEBHOOK_URL", "https://company.webhook.office.com/webhookb2/XXX")
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        success = _send_teams_safe("Title", "Message", "SUCCESS")
        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "MessageCard" in kwargs["json"]["@type"]


def test_dispatch_error_boundary(monkeypatch):
    """Ensure unexpected external network failure never raises an exception."""
    monkeypatch.setattr("config.settings.SMTP_HOST", "bad.host")
    with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("Connection refused")):
        # Must complete cleanly without raising
        dispatch_notification(
            title="Safe Alert",
            message="No crash expected",
            profile="sandbox",
            channels=["email"],
            async_dispatch=False,
        )
