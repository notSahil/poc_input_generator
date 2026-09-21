"""Multi-channel notification dispatcher (In-App, Email/SMTP, Slack, MS Teams).

Enforces defensive error boundaries so notification delivery failures never disrupt
the data pipeline. Applies strict secret masking to prevent token/credential leaks.
"""

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import logging
from pathlib import Path
import smtplib
import threading
from typing import Any
import requests

from config import settings
from core.audit_logger import mask_secrets
from core.job_store import create_notification
from core.models import RunResult

logger = logging.getLogger(__name__)


def build_notification_payload(
    *,
    report_name: str,
    profile: str,
    status: str,
    total_records: int = 0,
    successful_records: int = 0,
    failed_records: int = 0,
    skipped_records: int = 0,
    run_dir: Path | str | None = None,
    job_id: str | None = None,
    schedule_name: str | None = None,
    error_summary: str | None = None,
    is_rollback: bool = False,
    engine: str = "composite",
) -> dict[str, Any]:
    """Construct standardized title, message, and metadata across all channels."""
    op_type = "Rollback Revert" if is_rollback else "Ingest Upload"
    engine_label = "Lightning REST Collections" if engine == "composite" else "Bulk API 2.0"
    prof_label = settings.PROFILES.get(profile, profile.title())

    if status == "SUCCESS":
        icon = "🚀" if not is_rollback else "⏪"
        title = f"{icon} Sitetracker {op_type} Completed: {report_name}"
        notification_type = "SUCCESS"
    elif status == "COMPLETED_WITH_ERRORS":
        icon = "⚠️"
        title = f"{icon} Sitetracker {op_type} Completed with Errors: {report_name}"
        notification_type = "WARNING"
    elif status == "SKIPPED":
        icon = "⏭️"
        title = f"{icon} Sitetracker Scheduled Run Skipped: {report_name}"
        notification_type = "SKIPPED"
    else:
        icon = "❌"
        title = f"{icon} Sitetracker {op_type} Failed: {report_name}"
        notification_type = "FAILURE"

    lines: list[str] = []
    if schedule_name:
        lines.append(f"• **Schedule:** {schedule_name}")
    lines.append(f"• **Environment:** {prof_label}")
    lines.append(f"• **Engine:** {engine_label}")

    if status == "SKIPPED":
        lines.append(f"• **Reason:** {error_summary or 'No source file available or concurrency lock active'}")
    else:
        lines.append(f"• **Results:** {successful_records} updated, {failed_records} errors, {skipped_records} unchanged (Total: {total_records})")
        if error_summary:
            lines.append(f"• **Error Summary:** {error_summary}")
        if run_dir:
            lines.append(f"• **Run Directory:** `{Path(run_dir).name}`")

    message = "\n".join(lines)

    metadata = {
        "report_name": report_name,
        "profile": profile,
        "status": status,
        "total_records": total_records,
        "successful_records": successful_records,
        "failed_records": failed_records,
        "skipped_records": skipped_records,
        "run_dir": str(run_dir) if run_dir else None,
        "job_id": job_id,
        "schedule_name": schedule_name,
        "is_rollback": is_rollback,
    }

    return {
        "title": mask_secrets(title),
        "message": mask_secrets(message),
        "profile": profile,
        "notification_type": notification_type,
        "metadata": metadata,
        "subject": mask_secrets(f"[Sitetracker Data Hub] {title}"),
    }



def dispatch_notification(
    *,
    title: str,
    message: str,
    profile: str,
    notification_type: str = "INFO",
    subject: str | None = None,
    job_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    recipient_emails: list[str] | None = None,
    channels: list[str] | None = None,
    async_dispatch: bool = True,
    db_path: Path | None = None,
) -> None:
    """Dispatches notifications across In-App, Email, Slack, and MS Teams.

    Args:
        title: Notification header.
        message: Notification body (supports markdown).
        profile: Salesforce environment profile ('sandbox', 'partial', 'prod', 'all').
        notification_type: 'SUCCESS', 'WARNING', 'FAILURE', 'SKIPPED', 'INFO'.
        subject: Email subject line (defaults to title).
        job_id: Optional persistent job ID.
        metadata: Structured data dictionary stored alongside in-app notification.
        recipient_emails: Optional override for email recipients.
        channels: Specific channels to notify (default: all configured).
        async_dispatch: If True, external network calls run in a background thread.
        db_path: Optional custom database path for SQLite.
    """
    clean_title = mask_secrets(title)
    clean_message = mask_secrets(message)
    clean_subject = mask_secrets(subject or title)

    # 1. In-App Notification (Always synchronous & instant SQLite write)
    if channels is None or "in_app" in channels:
        try:
            create_notification(
                profile=profile,
                title=clean_title,
                message=clean_message,
                notification_type=notification_type,
                job_id=job_id,
                metadata=metadata,
                db_path=db_path,
            )
        except Exception as e:
            logger.error("Failed to store in-app notification: %s", e)


    # 2. External channels (Email, Slack, Teams)
    def _send_external():
        # Email
        if channels is None or "email" in channels:
            _send_email_safe(
                subject=clean_subject,
                message=clean_message,
                notification_type=notification_type,
                recipient_emails=recipient_emails,
                metadata=metadata,
            )

        # Slack
        if channels is None or "slack" in channels:
            _send_slack_safe(
                title=clean_title,
                message=clean_message,
                notification_type=notification_type,
            )

        # Teams
        if channels is None or "teams" in channels:
            _send_teams_safe(
                title=clean_title,
                message=clean_message,
                notification_type=notification_type,
            )

    if async_dispatch:
        t = threading.Thread(target=_send_external, daemon=True)
        t.start()
    else:
        _send_external()


# ==============================================================================
# INTERNAL CHANNEL HANDLERS (SHIELDED)
# ==============================================================================

def _send_email_safe(
    *,
    subject: str,
    message: str,
    notification_type: str,
    recipient_emails: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Send HTML + plain text email via SMTP. Returns True on success, False otherwise."""
    smtp_host = settings.SMTP_HOST
    if not smtp_host:
        logger.debug("SMTP_HOST not configured, skipping email notification.")
        return False

    recipients = recipient_emails or settings.NOTIFICATION_EMAILS
    if not recipients:
        logger.debug("No notification email recipients specified, skipping email.")
        return False

    # Pick banner color
    color_map = {
        "SUCCESS": "#04844B",
        "WARNING": "#FE9339",
        "FAILURE": "#EA001E",
        "SKIPPED": "#64748B",
        "INFO": "#0176D3",
    }
    header_color = color_map.get(notification_type, "#0176D3")

    # Render HTML
    msg_lines = message.replace("\n", "<br/>").replace("•", "&bull;")
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; background-color: #F4F6F9; color: #0F172A; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #FFFFFF; border-radius: 8px; overflow: hidden; border: 1px solid #E2E8F0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }}
        .header {{ background-color: {header_color}; color: #FFFFFF; padding: 18px 24px; font-size: 18px; font-weight: 700; }}
        .content {{ padding: 24px; line-height: 1.6; font-size: 14px; }}
        .footer {{ background-color: #F8FAFC; border-top: 1px solid #E2E8F0; padding: 14px 24px; font-size: 12px; color: #64748B; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">⚡ Sitetracker Data Hub Alert</div>
        <div class="content">
          <p>{msg_lines}</p>
        </div>
        <div class="footer">
          This is an automated notification from the Sitetracker Data Hub platform.
        </div>
      </div>
    </body>
    </html>
    """

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_SENDER
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(message, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        server = smtplib.SMTP(smtp_host, settings.SMTP_PORT, timeout=10.0)
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(settings.SMTP_SENDER, recipients, msg.as_string())
        server.quit()
        logger.info("Notification email successfully sent to %s", recipients)
        return True
    except Exception as e:
        logger.warning("Failed to send notification email via %s:%s: %s", smtp_host, settings.SMTP_PORT, e)
        return False


def _send_slack_safe(title: str, message: str, notification_type: str) -> bool:
    """Send formatted Slack Block Kit alert."""
    webhook_url = settings.SLACK_WEBHOOK_URL
    if not webhook_url:
        return False

    payload = {
        "text": f"{title}\n{message}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message}
            }
        ]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=5.0)
        return res.status_code == 200
    except Exception as e:
        logger.warning("Failed to send Slack webhook notification: %s", e)
        return False


def _send_teams_safe(title: str, message: str, notification_type: str) -> bool:
    """Send formatted MS Teams MessageCard alert."""
    webhook_url = settings.TEAMS_WEBHOOK_URL
    if not webhook_url:
        return False

    color_map = {
        "SUCCESS": "04844B",
        "WARNING": "FE9339",
        "FAILURE": "EA001E",
        "SKIPPED": "64748B",
        "INFO": "0176D3",
    }
    theme_color = color_map.get(notification_type, "0176D3")

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": theme_color,
        "summary": title,
        "sections": [{
            "activityTitle": title,
            "text": message.replace("\n", "<br/>"),
            "markdown": True
        }]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=5.0)
        return res.status_code == 200
    except Exception as e:
        logger.warning("Failed to send MS Teams webhook notification: %s", e)
        return False
