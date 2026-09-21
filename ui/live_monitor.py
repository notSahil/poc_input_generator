"""Universal Live Ingest Telemetry Monitor.

Provides real-time visibility into server-side background uploads, allowing operators
to safely close tabs or disconnect and re-attach anytime without interrupting cloud operations.
"""

from datetime import datetime
import logging
from pathlib import Path
import time
import streamlit as st
import pandas as pd

from config import settings
from core import job_store
from salesforce.job_manager import get_job_progress, is_job_active, start_background_ingest
from ui.components import (
    render_back_button,
    render_download_with_confirmation,
    render_header,
)
from ui.styles import render_pill

logger = logging.getLogger(__name__)


def render(go):
    """Render the Universal Live Ingest Telemetry Monitor."""
    render_header(
        "⚡ Live Ingest Telemetry Monitor",
        "Real-time background server progress for cloud uploads and emergency rollbacks.",
    )

    col_nav1, col_nav2 = st.columns([3, 1])
    with col_nav1:
        render_back_button(go, label="⬅ Back to Home", target="home")
    with col_nav2:
        if st.button("🔄 Refresh Status", key="btn_telemetry_refresh", use_container_width=True):
            st.rerun()

    # Identify target job
    job_id = st.session_state.get("active_monitor_job_id")
    job = None

    job_store.init_db()

    if job_id:
        job = job_store.get_job(job_id)

    # Fallback: find latest active job, or latest job overall
    if not job:
        active_list = job_store.get_active_jobs()
        if active_list:
            job = active_list[0]
            st.session_state.active_monitor_job_id = job["id"]
        else:
            with job_store.get_db() as conn:
                cursor = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 1")
                row = cursor.fetchone()
                if row:
                    job = dict(row)
                    st.session_state.active_monitor_job_id = job["id"]

    if not job:
        st.info("No active or historical background jobs found on this server.")
        return

    # Extract Job Metadata
    run_dir = Path(job["run_dir"])
    report_name = job.get("report_name", "Unknown Report")
    profile = job.get("profile", "sandbox")
    is_rb = bool(job.get("is_rollback", False))
    engine = job.get("engine", "composite")
    created_at_str = job.get("created_at", "")[:19].replace("T", " ")

    # Get live progress from progress JSON
    prog = get_job_progress(run_dir) or {}
    status = prog.get("status", job.get("status", "QUEUED"))

    # Environment Pill
    prof_label = settings.PROFILES.get(profile, profile.title())
    prof_color = "purple" if profile == "partial" else ("amber" if profile == "sandbox" else "blue")
    engine_label = "⚡ Lightning REST Collections" if engine == "composite" else "📦 Bulk API 2.0"
    op_label = "⏪ Revert / Rollback" if is_rb else "🚀 Cloud Ingest"

    # Top Metadata Card
    st.markdown(
        f"""
        <div class="slds-card" style="margin-bottom: 18px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <span style="font-size: 1.15rem; font-weight: 700; color: #032D60;">{report_name}</span>
                    <div style="margin-top: 4px; display: flex; gap: 8px; align-items: center;">
                        {render_pill(op_label, "purple" if is_rb else "blue")}
                        {render_pill(prof_label, prof_color)}
                        {render_pill(engine_label, "grey")}
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600; text-transform: uppercase;">Run Directory</div>
                    <div style="font-size: 0.85rem; font-family: monospace; color: #032D60;">{run_dir.name}</div>
                    <div style="font-size: 0.75rem; color: #94A3B8;">Started: {created_at_str} UTC</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # =========================================================================
    # STATE 1: RUNNING
    # =========================================================================
    if status == "RUNNING":
        proc_overall = prog.get("processed_records_overall", job.get("processed", 0))
        total_overall = max(1, prog.get("total_records_overall", job.get("total_records", 1)))
        succ_overall = prog.get("successful_records_overall", job.get("successful", 0))
        fail_overall = prog.get("failed_records_overall", job.get("failed", 0))
        pct = min(1.0, proc_overall / total_overall)
        curr_obj = prog.get("current_object", job.get("target_object") or "Salesforce Object")

        # Animated Progress Bar
        bar_text = f"{'Reverting' if is_rb else 'Synchronizing'} {curr_obj} — {proc_overall:,} of {total_overall:,} records ({int(pct * 100)}%)"
        st.progress(pct, text=bar_text)

        # 4 Metric Cards
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Processed Records", f"{proc_overall:,} / {total_overall:,}")
        m2.metric("Succeeded", f"{succ_overall:,}")
        m3.metric("Failed", f"{fail_overall:,}")

        start_str = prog.get("start_time") or job.get("created_at")
        elapsed_display = "N/A"
        if start_str:
            try:
                s_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                el_sec = int((datetime.now(s_dt.tzinfo) - s_dt).total_seconds())
                elapsed_display = f"{el_sec // 60}m {el_sec % 60}s"
            except Exception:
                pass
        m4.metric("Elapsed Time", elapsed_display)

        # In-Flight Batch Details
        c_chunk = prog.get("current_chunk", job.get("current_chunk", 0))
        t_chunk = prog.get("total_chunks", job.get("total_chunks", 0))
        r_start = prog.get("chunk_start", 0)
        r_end = prog.get("chunk_end", 0)

        if t_chunk > 0:
            st.markdown(
                f"""
                <div style="background: #EFF6FF; border: 1px solid #93C5FD; border-radius: 8px; padding: 12px 16px; margin: 16px 0;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span>⚙️</span>
                        <div>
                            <b>Active Micro-Batch In-Flight:</b> Evaluating Chunk <b>{c_chunk} of {t_chunk}</b> (Records {r_start} to {r_end} on <b>{curr_obj}</b>)<br>
                            <span style="font-size: 0.8rem; color: #1D4ED8;">Executing isolated Apex DML transaction with governor limit isolation...</span>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.info("💡 **Disconnect Immunity Active:** This operation is running detached on the server. You can safely close your browser or navigate to other pages; progress will not be interrupted.")

        # Auto-refresh helper
        col_auto, _ = st.columns([2, 2])
        with col_auto:
            auto_refresh = st.checkbox("Auto-refresh telemetry every 3 seconds", value=True)
            if auto_refresh:
                time.sleep(3)
                st.rerun()

    # =========================================================================
    # STATE 2: COMPLETED or COMPLETED_WITH_ERRORS
    # =========================================================================
    elif status in ("COMPLETED", "COMPLETED_WITH_ERRORS"):
        succ_records = prog.get("successful_records_overall", job.get("successful", 0))
        fail_records = prog.get("failed_records_overall", job.get("failed", 0))
        proc_records = prog.get("processed_records_overall", job.get("processed", succ_records + fail_records))

        if fail_records == 0:
            st.success(f"🎉 **{op_label} Completed Successfully!** All {succ_records:,} records updated in Salesforce.")
        else:
            st.warning(f"⚠️ **{op_label} Completed with Partial Failures.** {succ_records:,} succeeded, {fail_records:,} failed.")

        # KPI Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Records Succeeded", f"{succ_records:,}")
        c2.metric("Records Failed", f"{fail_records:,}")
        c3.metric("Total Processed", f"{proc_records:,}")

        st.divider()

        # Output Downloads & 1-Click Rollback
        col_dl, col_rb = st.columns([1.5, 1.5])

        with col_dl:
            st.subheader("📥 Export & Audit Files")
            files_to_check = [
                ("final_input_file.csv", "Final Ingest Payload", "text/csv"),
                ("field_level_changes.csv", "Field Level Delta Report", "text/csv"),
                ("rollback_file.csv", "Pre-Change Rollback Snapshot", "text/csv"),
                ("run_summary.txt", "Execution Summary Log", "text/plain"),
            ]
            for f_name, label, mime in files_to_check:
                f_path = run_dir / f_name
                if f_path.exists():
                    render_download_with_confirmation(
                        st,
                        button_label=f"Download {label}",
                        file_path=f_path,
                        download_filename=f"{report_name}_{f_name}",
                        mime=mime,
                        key=f"dl_{f_name}_{job['id']}",
                    )

        with col_rb:
            if not is_rb:
                st.subheader("⏪ 1-Click Emergency Rollback")
                rb_files = [f for f in run_dir.glob("rollback_file*.csv") if f.is_file() and f.stat().st_size > 0]
                if rb_files and succ_records > 0:
                    st.caption("Instantly restore previous Sitetracker values from the pre-change snapshot generated before this run.")
                    if st.button("⏪ Execute Emergency Rollback", type="secondary", use_container_width=True):
                        with st.spinner("Starting rollback worker..."):
                            start_background_ingest(
                                run_dir=run_dir,
                                report_name=report_name,
                                is_rollback=True,
                                profile=profile,
                                engine=engine,
                            )
                        st.rerun()
                else:
                    st.caption("Rollback is not required or snapshot is empty.")

    # =========================================================================
    # STATE 3: FAILED or INTERRUPTED
    # =========================================================================
    else:
        err_msg = prog.get("error_summary", job.get("error_summary", "Operation terminated unexpectedly."))
        st.error(f"❌ **{op_label} Failed or Interrupted**")
        st.code(err_msg, language="text")

        audit_file = run_dir / "audit.log"
        if audit_file.exists():
            st.subheader("📋 Forensic Audit Log")
            try:
                st.text_area("Audit Log Output", audit_file.read_text(encoding="utf-8")[-4000:], height=250)
            except Exception:
                pass
            render_download_with_confirmation(
                st,
                button_label="Download Forensic audit.log",
                file_path=audit_file,
                download_filename=f"{report_name}_audit.log",
                mime="text/plain",
                key=f"dl_audit_{job['id']}",
            )
