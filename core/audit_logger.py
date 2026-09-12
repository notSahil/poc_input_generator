"""Simple, reliable per-run audit and diagnostic logger.

Produces a human-readable audit.log in each run directory for operational tracking
and root-cause troubleshooting across data validation, network requests, and Salesforce APIs.
"""

from datetime import datetime
import getpass
import logging
from pathlib import Path
import re
import threading
import traceback
from typing import Any

logger = logging.getLogger(__name__)

# Patterns for masking sensitive data (OAuth tokens, bearer auth, passwords)
_TOKEN_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.!]+", re.IGNORECASE)
_SESSION_PATTERN = re.compile(r"(00D[a-zA-Z0-9]{12,15}![A-Za-z0-9_\-\.]+)")
_KEY_VALUE_SECRET = re.compile(r"(password|client_secret|access_token|refresh_token)\s*[:=]\s*['\"]?([^'\"\s,]+)['\"]?", re.IGNORECASE)


def mask_secrets(text: str) -> str:
    """Mask OAuth tokens, passwords, and secret strings from log messages."""
    if not text:
        return ""
    s = str(text)
    s = _TOKEN_PATTERN.sub(r"\1[MASKED_TOKEN]", s)
    s = _SESSION_PATTERN.sub(r"[MASKED_SESSION_ID]", s)
    s = _KEY_VALUE_SECRET.sub(r"\1=[MASKED_SECRET]", s)
    return s


def resolve_user_identity(profile: str | None = None) -> dict[str, str]:
    """
    Resolve logged-in Salesforce user identity safely.
    Falls back gracefully to local environment details if offline or unauthenticated.
    """
    identity = {
        "user_name": "Local Operator",
        "user_id": "N/A",
        "org_name": "Offline / Local Environment",
        "org_id": "N/A",
        "profile": profile or "default",
        "is_sandbox": "Unknown",
    }

    try:
        from salesforce.auth import get_active_profile, load_token
        active_prof = profile or get_active_profile()
        identity["profile"] = active_prof

        token_data = load_token(active_prof)
        if token_data:
            if "instance_url" in token_data:
                identity["org_name"] = token_data.get("instance_url", "").replace("https://", "")

            # Attempt to query userinfo endpoint if token exists
            try:
                from salesforce.userinfo import get_user_info
                u_info = get_user_info(active_prof)
                if u_info and isinstance(u_info, dict):
                    identity["user_name"] = u_info.get("preferred_username") or u_info.get("username") or u_info.get("email") or identity["user_name"]
                    identity["user_id"] = u_info.get("user_id") or u_info.get("sub", "").split("/")[-1] or "N/A"
                    identity["org_id"] = u_info.get("organization_id") or "N/A"
                    identity["is_sandbox"] = str(u_info.get("is_sandbox", active_prof in ("sandbox", "partial")))
            except Exception as u_err:
                logger.debug("Could not fetch remote userinfo: %s", u_err)
                # Fallback to local token details
                if "username" in token_data:
                    identity["user_name"] = token_data["username"]

        if identity["user_name"] == "Local Operator":
            try:
                identity["user_name"] = f"{getpass.getuser()} (Local OS User)"
            except Exception:
                pass

    except Exception as e:
        logger.debug("Error resolving user identity: %s", e)

    return identity


class AuditLogger:
    """
    Thread-safe, non-blocking per-run audit logger.
    Guarantees that log write failures will never crash the calling data load process.
    """

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.log_file = self.run_dir / "audit.log"
        self._lock = threading.Lock()

    def _format_details(self, details: dict[str, Any]) -> str:
        """Format detail key-values into clean pipe-delimited string."""
        if not details:
            return ""
        items = []
        for k, v in details.items():
            if v is not None:
                clean_val = mask_secrets(str(v))
                items.append(f"{k}: {clean_val}")
        return " | ".join(items)

    def _write_line(self, level: str, tag: str, message: str, **details) -> None:
        """Core safe write method. Never raises an exception to the caller."""
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            clean_msg = mask_secrets(str(message))
            det_str = self._format_details(details)
            line = f"[{ts}] [{level}] [{tag}] {clean_msg}"
            if det_str:
                line += f" | {det_str}"
            line += "\n"

            with self._lock:
                self.run_dir.mkdir(parents=True, exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as e:
            logger.warning("AuditLogger failed to write to %s: %s", self.log_file, e)

    def start_run(
        self,
        run_id: str,
        report_name: str,
        mode: str,
        user: str | None = None,
        org: str | None = None,
        **extra
    ) -> None:
        """Checkpoint 1: Record run initialization."""
        self._write_line(
            "INFO", "START",
            f"Run initialized: {report_name}",
            Run_ID=run_id,
            Mode=mode,
            User=user or "N/A",
            Org=org or "N/A",
            **extra
        )

    def info(self, message: str, tag: str = "INFO", **details) -> None:
        """Record general operational milestone."""
        self._write_line("INFO", tag, message, **details)

    def warning(self, message: str, tag: str = "WARNING", **details) -> None:
        """Record potential issue or validation warning."""
        self._write_line("WARNING", tag, message, **details)

    def error(self, message: str, tag: str = "ERROR", **details) -> None:
        """Record operational or validation error."""
        self._write_line("ERROR", tag, message, **details)

    def record_error(
        self,
        record_id: str,
        object_name: str,
        message: str,
        field_name: str | None = None,
        error_code: str | None = None,
        **extra
    ) -> None:
        """Checkpoint 4: Record Salesforce per-record rejection."""
        self._write_line(
            "ERROR", "RECORD_ERROR",
            f"Record update rejected: {record_id}",
            Object=object_name,
            Field=field_name or "N/A",
            Code=error_code or "SALESFORCE_ERROR",
            Message=message,
            **extra
        )

    def network_error(
        self,
        operation: str,
        error: Exception | str,
        attempt: int | None = None,
        timeout: float | None = None,
        **extra
    ) -> None:
        """Record network or HTTP transport errors (timeouts, connection drops, retries)."""
        err_msg = str(error)
        err_type = type(error).__name__ if isinstance(error, Exception) else "NetworkError"
        details: dict[str, Any] = {
            "Operation": operation,
            "Error_Type": err_type,
            "Detail": err_msg,
        }
        if attempt is not None:
            details["Attempt"] = attempt
        if timeout is not None:
            details["Timeout_Seconds"] = timeout
        details.update(extra)

        self._write_line("ERROR", "NETWORK_ERROR", f"Network fault during {operation}", **details)

    def exception(self, message: str, exc: Exception | None = None, tag: str = "EXCEPTION", **details) -> None:
        """
        Checkpoint 5: Record unexpected Python exceptions with standard traceback.
        Uses standard traceback.format_exc() capturing traceback, filenames, and line numbers
        without exposing sensitive local variables.
        """
        try:
            tb_str = traceback.format_exc() if exc is None else "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            if not tb_str or tb_str.strip() == "NoneType: None":
                tb_str = "No active traceback available."

            clean_tb = mask_secrets(tb_str.strip())
            self._write_line("ERROR", tag, f"{message} — Traceback below:", **details)

            # Write formatted indented traceback block
            with self._lock:
                self.run_dir.mkdir(parents=True, exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as f:
                    for tb_line in clean_tb.splitlines():
                        f.write(f"    | {tb_line}\n")
        except Exception as e:
            logger.warning("AuditLogger failed to write exception: %s", e)

    def finish(
        self,
        status: str,
        duration_sec: float | None = None,
        successes: int = 0,
        failures: int = 0,
        output_files: list[str] | None = None,
        **summary
    ) -> None:
        """Checkpoint 6: Record run completion."""
        dur_str = f"{duration_sec:.1f}s" if duration_sec is not None else "N/A"
        files_str = ", ".join(output_files) if output_files else "None"
        self._write_line(
            "INFO", "FINISH",
            f"Run completed with status: {status}",
            Status=status,
            Duration=dur_str,
            Total_Success=successes,
            Total_Failed=failures,
            Output_Files=files_str,
            **summary
        )

    def read_log(self) -> str:
        """Read the full audit log contents if available."""
        if not self.log_file.exists():
            return "No audit.log found for this run."
        try:
            return self.log_file.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading audit.log: {e}"
