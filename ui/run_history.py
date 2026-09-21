"""Streamlit UI page for Historical Runs and Audit Log."""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
import streamlit as st
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from ui.components import render_back_button, render_download_with_confirmation, render_footer, render_header

logger = logging.getLogger(__name__)


def _safe_read_csv(f_path: Path, **kwargs) -> pd.DataFrame:
    """Read a CSV safely, returning an empty DataFrame if file is missing or corrupt."""
    try:
        if f_path.exists() and f_path.stat().st_size > 0:
            return pd.read_csv(f_path, **kwargs)
    except Exception:
        pass
    return pd.DataFrame()


def _render_rollback_safety_net(
    r_dir: Path,
    report_name: str,
    key_prefix: str,
    selected_run_id: str,
    target_object: str | None = None,
) -> None:
    """Render an authoritative 1-Click Rollback / Revert Safety Net card in Run History."""
    rb_single = r_dir / "rollback_file.csv"
    multi_rb_files = sorted(r_dir.glob("rollback_file_*.csv"))

    has_rb = (rb_single.exists() and len(_safe_read_csv(rb_single)) > 0) or any(
        len(_safe_read_csv(f)) > 0 for f in multi_rb_files
    )
    if not has_rb:
        return

    st.markdown("---")
    st.markdown("### ⏪ Emergency Rollback / Revert Safety Net")
    st.warning(
        "⚠️ **Safety Net**: Revert modified records from this run back to their exact original "
        "pre-change Sitetracker values in Salesforce."
    )

    # Active or completed job progress check
    prog_f = r_dir / "ingest_progress.json"
    if prog_f.exists():
        try:
            p_data = json.loads(prog_f.read_text(encoding="utf-8"))
            if p_data.get("status") == "RUNNING" and p_data.get("is_rollback", False):
                tot = max(1, p_data.get("total_records_overall", 1))
                proc = p_data.get("processed_records_overall", 0)
                pct = min(1.0, proc / tot)
                st.info(f"🔄 **Rollback Revert in Progress on Server**: Restoring {proc:,} of {tot:,} records ({int(pct * 100)}%)...")
                st.progress(pct)
                time.sleep(1.5)
                st.rerun()
                return
            elif p_data.get("status") in ("COMPLETED", "COMPLETED_WITH_ERRORS") and p_data.get("is_rollback", False):
                succ = p_data.get("successful_records_overall", 0)
                tot = p_data.get("total_records_overall", 0)
                st.success(f"✅ **Rollback Previously Completed**: Reverted {succ:,} of {tot:,} records back to pre-change values in Salesforce.")
        except Exception:
            pass

    # Inspect rollback records breakdown
    with st.expander("🔍 Inspect Rollback Payloads (Values to be restored)", expanded=False):
        if multi_rb_files:
            rb_tabs = st.tabs([f"⏪ {f.stem.replace('rollback_file_', '').replace('_', ' ')}" for f in multi_rb_files])
            for f, tab in zip(multi_rb_files, rb_tabs):
                with tab:
                    df_rb = _safe_read_csv(f, dtype=str)
                    clean_target = f.stem.replace('rollback_file_', '').replace('_', ' ')
                    st.caption(f"**{len(df_rb):,}** rollback records ready for **{clean_target}**")
                    if not df_rb.empty:
                        st.dataframe(df_rb.head(50), use_container_width=True)
        elif rb_single.exists():
            df_rb = _safe_read_csv(rb_single, dtype=str)
            st.caption(f"**{len(df_rb):,}** rollback records ready to restore")
            if not df_rb.empty:
                st.dataframe(df_rb.head(50), use_container_width=True)

    col_c1, col_c2 = st.columns([2, 1])
    with col_c1:
        revert_confirm_text = st.text_input(
            "Type REVERT to enable rollback:",
            placeholder="REVERT",
            key=f"hist_revert_input_{key_prefix}_{selected_run_id}",
        )
    with col_c2:
        st.write("")
        st.write("")
        revert_active = (revert_confirm_text.strip() == "REVERT")
        btn_label = "⏪ Execute Rollback for All Objects" if multi_rb_files else "⏪ Execute Rollback Now"
        if st.button(
            btn_label,
            type="secondary",
            disabled=not revert_active,
            key=f"hist_revert_btn_{key_prefix}_{selected_run_id}",
            use_container_width=True,
        ):
            from salesforce.job_manager import start_background_ingest
            from salesforce.auth import get_active_profile
            prof = get_active_profile()
            start_background_ingest(
                run_dir=r_dir,
                report_name=report_name,
                is_rollback=True,
                profile=prof,
                batch_size=15,
                target_object=target_object,
                engine="composite",
            )
            st.session_state.active_job_run_dir = r_dir
            st.toast("⏪ Rollback initiated in server background thread! Tracking progress...")
            time.sleep(0.5)
            st.rerun()


def _format_count(val: str | int) -> str:
    """Format numeric string or integer with commas (e.g. 19856 -> 19,856)."""
    try:
        return f"{int(val):,}"
    except (ValueError, TypeError):
        return str(val)


def parse_run_summary(summary_path: Path) -> dict:
    """Extract quick metrics from a run_summary.txt file."""
    metrics = {
        "total": "N/A",
        "updates": "N/A",
        "errors": "N/A",
        "skipped": "N/A",
        "duplicates": "N/A",
    }
    if not summary_path.exists():
        return metrics

    try:
        text = summary_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line_str = line.strip()
            if "Total source records:" in line_str or "Total Source Rows:" in line_str:
                metrics["total"] = line_str.split(":")[-1].strip()
            elif "SUCCESS (uploaded):" in line_str or "Delta Records:" in line_str or "Rows With Changes:" in line_str:
                metrics["updates"] = line_str.split(":")[-1].strip()
            elif "ERRORS (rejected):" in line_str or "Validation Errors:" in line_str:
                metrics["errors"] = line_str.split(":")[-1].strip()
            elif "SKIPPED:" in line_str or "Skipped (Not in SF):" in line_str:
                metrics["skipped"] = line_str.split(":")[-1].strip()
            elif "Duplicate keys found:" in line_str or "DUPLICATE PKs:" in line_str or "Duplicate Primary Keys:" in line_str:
                metrics["duplicates"] = line_str.split(":")[-1].strip()
    except Exception as e:
        logger.warning("Failed to parse run summary at %s: %s", summary_path, e)

    return metrics


def _parse_manual_run_metadata(run_dir: Path, obj_name: str, date_str: str, time_str: str) -> dict:
    """Extract or fall back to rich metadata for a manual run."""
    meta_file = run_dir / "run_metadata.json"
    if meta_file.exists():
        try:
            return json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Fallback to parsing audit.log and run_summary.txt
    user_name = "Local Operator"
    org_name = "Salesforce Org"
    profile = "unknown"
    source_pk = ""
    target_pk = ""
    source_filename = ""
    operation = "Update"

    # Check archive dir for source file
    arch_dir = run_dir / "archive"
    if arch_dir.exists():
        arch_files = [f.name for f in arch_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        if arch_files:
            source_filename = arch_files[0]

    # Parse audit.log
    audit_file = run_dir / "audit.log"
    if audit_file.exists():
        try:
            text = audit_file.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "[START]" in line:
                    if "User: " in line:
                        user_name = line.split("User: ")[1].split(" | ")[0].strip()
                    if "Org: " in line:
                        org_name = line.split("Org: ")[1].strip()
                    break
        except Exception:
            pass

    # Parse run_summary.txt
    summary_file = run_dir / "run_summary.txt"
    if summary_file.exists():
        try:
            text = summary_file.read_text(encoding="utf-8")
            for line in text.splitlines():
                line_s = line.strip()
                if line_s.startswith("Source Primary Key:"):
                    source_pk = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Salesforce Primary Key Field:"):
                    target_pk = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Source File:") and not source_filename:
                    source_filename = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Operator:") and user_name == "Local Operator":
                    user_name = line_s.split(":", 1)[1].strip()
                elif line_s.startswith("Salesforce Org:") and org_name == "Salesforce Org":
                    org_name = line_s.split(":", 1)[1].strip()
        except Exception:
            pass

    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
        fmt_date = dt.strftime("%d %b %Y")
        fmt_time = dt.strftime("%H:%M:%S IST")
    except Exception:
        fmt_date = date_str
        fmt_time = f"{time_str} IST"

    return {
        "run_id": run_dir.name,
        "date": date_str,
        "time": time_str,
        "formatted_date": fmt_date,
        "formatted_time": fmt_time,
        "target_object": obj_name,
        "operation": operation,
        "source_pk": source_pk,
        "target_pk": target_pk,
        "source_filename": source_filename or f"{obj_name}_source.csv",
        "user_name": user_name,
        "org_name": org_name,
        "profile": profile,
    }


def scan_guided_runs(report_filter: str | None = None) -> list[dict]:
    """Scan and return all predefined guided report runs sorted newest first."""
    runs = []
    reports = YamlConfigLoader.list_reports()

    for r in reports:
        if report_filter and report_filter != "All Reports" and r.name != report_filter:
            continue

        try:
            yaml_cfg = YamlConfigLoader.load(r.name)
            work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
            runs_dir = work_dir / yaml_cfg["folders"]["runs_dir"]
            archive_dir = work_dir / yaml_cfg["folders"]["archive_dir"]

            if not runs_dir.exists():
                continue

            for date_dir in sorted(runs_dir.iterdir(), reverse=True):
                if not date_dir.is_dir() or date_dir.name.startswith("."):
                    continue
                for run_dir in sorted(date_dir.iterdir(), reverse=True):
                    if not run_dir.is_dir() or run_dir.name.startswith("."):
                        continue

                    summary_file = run_dir / "run_summary.txt"
                    metrics = parse_run_summary(summary_file)
                    matching_archive = archive_dir / date_dir.name / run_dir.name
                    time_fmt = run_dir.name.replace("run_", "").replace("-", ":")
                    tot_rows = metrics.get("total", "N/A")
                    upd_rows = metrics.get("updates", "N/A")

                    prog_f = run_dir / "ingest_progress.json"
                    cloud_info = ""
                    cloud_synced = False
                    if prog_f.exists():
                        try:
                            p_data = json.loads(prog_f.read_text(encoding="utf-8"))
                            p_status = p_data.get("status")
                            if p_status in ("COMPLETED", "COMPLETED_WITH_ERRORS"):
                                succ_c = p_data.get("successful_records_overall", 0)
                                fail_c = p_data.get("failed_records_overall", 0)
                                cloud_synced = True
                                if fail_c > 0:
                                    cloud_info = f"🚀 {succ_c:,} synced (⚠️ {fail_c:,} failed)"
                                elif succ_c == 0 and str(upd_rows) not in ("0", "N/A"):
                                    cloud_info = f"⚠️ 0/{_format_count(upd_rows)} synced"
                                else:
                                    cloud_info = f"🚀 {succ_c:,} cloud synced"
                            elif p_status == "RUNNING":
                                cloud_synced = True
                                cloud_info = "🔄 Uploading..."
                        except Exception:
                            pass

                    label_parts = [f"📥 {r.name}", f"{date_dir.name} {time_fmt}"]
                    if tot_rows != "N/A":
                        label_parts.append(f"📄 {_format_count(tot_rows)} rows")

                    if cloud_synced and cloud_info:
                        label_parts.append(cloud_info)
                    elif upd_rows != "N/A":
                        label_parts.append(f"✅ {_format_count(upd_rows)} updates")

                    display_label = " • ".join(label_parts)

                    runs.append({
                        "report": r.name,
                        "type": "Guided Report",
                        "date": date_dir.name,
                        "time": time_fmt,
                        "run_id": display_label,
                        "raw_run_id": run_dir.name,
                        "run_dir": run_dir,
                        "archive_dir": matching_archive if matching_archive.exists() else None,
                        "summary_file": summary_file,
                        "metrics": metrics,
                    })
        except Exception as e:
            logger.warning("Error scanning runs for report %s: %s", r.name, e)

    runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return runs


def scan_manual_runs(object_filter: str | None = None) -> list[dict]:
    """Scan and return all ad-hoc manual dataloader runs sorted newest first with rich metadata."""
    runs = []
    manual_runs_dir = settings.DATA_DIR / "manual_runs"
    if not manual_runs_dir.exists():
        return runs

    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    for obj_dir in sorted(manual_runs_dir.iterdir()):
        if not obj_dir.is_dir() or obj_dir.name.startswith("."):
            continue

        obj_name = obj_dir.name
        if object_filter and object_filter != "All Objects" and obj_name != object_filter and f"Ad-Hoc: {obj_name}" != object_filter:
            continue

        for date_dir in sorted(obj_dir.iterdir(), reverse=True):
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            date_str = date_dir.name
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir() or run_dir.name.startswith("."):
                    continue

                time_str = run_dir.name.replace("run_", "").replace("-", ":")
                meta = _parse_manual_run_metadata(run_dir, obj_name, date_str, time_str)
                summary_file = run_dir / "run_summary.txt"
                metrics = parse_run_summary(summary_file)
                matching_archive = run_dir / "archive"

                try:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                except Exception:
                    dt = datetime.now()

                if date_str == today_str:
                    day_group = f"Today — {dt.strftime('%d %b %Y')}"
                elif date_str == yesterday_str:
                    day_group = f"Yesterday — {dt.strftime('%d %b %Y')}"
                else:
                    day_group = dt.strftime("%A — %d %b %Y")

                month_group = dt.strftime("%B %Y")
                src_file = meta.get("source_filename") or f"{obj_name}_source.csv"
                user_short = meta.get("user_name", "Local Operator").split("@")[0]
                upd_count = metrics.get("updates", "0")

                display_label = (
                    f"🕒 {time_str} • {obj_name} • 📄 {src_file} • 👤 {user_short} • ✅ {upd_count} updates"
                )

                runs.append({
                    "report": f"Ad-Hoc: {obj_name}",
                    "object_name": obj_name,
                    "type": "Manual Ingestion",
                    "date": date_str,
                    "time": time_str,
                    "datetime": dt,
                    "day_group": day_group,
                    "month_group": month_group,
                    "run_id": display_label,
                    "raw_run_id": run_dir.name,
                    "run_dir": run_dir,
                    "archive_dir": matching_archive if matching_archive.exists() else None,
                    "summary_file": summary_file,
                    "metrics": metrics,
                    "source_filename": src_file,
                    "user_name": meta.get("user_name", "Local Operator"),
                    "org_name": meta.get("org_name", "Salesforce Org"),
                    "profile": meta.get("profile", "unknown"),
                    "operation": meta.get("operation", "Update"),
                    "source_pk": meta.get("source_pk", ""),
                    "target_pk": meta.get("target_pk", ""),
                    "formatted_date": meta.get("formatted_date", dt.strftime("%d %b %Y")),
                    "formatted_time": meta.get("formatted_time", f"{time_str} IST"),
                })

    runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return runs


def scan_all_runs(report_filter: str | None = None) -> list[dict]:
    """Scan the data directory and return all runs (both guided and manual) sorted newest first."""
    all_runs = scan_guided_runs(report_filter) + scan_manual_runs(report_filter)
    all_runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return all_runs


def _render_post_audit_summary(r_dir: Path, key_prefix: str, selected_run_id: str):
    """Render Tier 2 post-update live reconciliation metrics & discrepancies if available."""
    pv_rep_f = r_dir / "post_update_validation_report.csv"
    pv_disc_f = r_dir / "post_update_discrepancies.csv"
    if not pv_rep_f.exists():
        return

    try:
        pv_df = pd.read_csv(pv_rep_f, dtype=str)
        if pv_df.empty or "Status" not in pv_df.columns:
            return

        st.markdown("---")
        st.markdown("##### 🔍 Post-Update Ground-Truth Audit & Reconciliation")
        st.caption("Live SOQL verification comparing submitted field values against actual Salesforce records.")
        pv_tot = len(pv_df)
        pv_ver = len(pv_df[pv_df["Status"] == "VERIFIED_MATCH"])
        pv_mut = len(pv_df[pv_df["Status"] == "TRIGGER_MUTATION"])
        pv_stale = len(pv_df[pv_df["Status"].isin(["UNMODIFIED_STALE", "NULL_WIPE_FAILED"])])
        pv_notf = len(pv_df[pv_df["Status"] == "RECORD_NOT_FOUND"])
        pv_pct = round((pv_ver / pv_tot * 100), 1) if pv_tot > 0 else 100.0

        pvc1, pvc2, pvc3, pvc4 = st.columns(4)
        pvc1.metric("Fields Audited", f"{pv_tot:,}")
        pvc2.metric("Verified Match", f"{pv_pct}%", delta=f"{pv_ver} verified")
        pvc3.metric("Trigger Overwrites", f"{pv_mut}", delta="- Alarmed" if pv_mut > 0 else None, delta_color="inverse")
        pvc4.metric("Stale / Not Saved", f"{pv_stale + pv_notf}", delta="- Failed" if (pv_stale + pv_notf) > 0 else None, delta_color="inverse")

        if pv_disc_f.exists():
            try:
                disc_df = pd.read_csv(pv_disc_f, dtype=str)
                if not disc_df.empty:
                    with st.expander(f"⚠️ View Post-Audit Discrepancies ({len(disc_df)} fields altered or un-saved)", expanded=False):
                        st.warning("The following fields in Salesforce differ from what was submitted. They may have been overwritten by Sitetracker managed package triggers or validation rules.")
                        st.dataframe(disc_df, use_container_width=True)
            except Exception as e_disc:
                logger.debug("Could not read post-update discrepancies: %s", e_disc)
    except Exception as e_pv:
        logger.debug("Failed to render post-audit summary in run history: %s", e_pv)


def _render_run_details(chosen_run: dict, key_prefix: str):
    """Render details, KPI metrics, file downloads, and audit logs for a guided report run."""
    st.subheader(f"🔍 Details: `{chosen_run['report']}` — {chosen_run['date']} {chosen_run['time']} IST")

    r_dir = chosen_run["run_dir"]
    met = chosen_run["metrics"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Rows", met["total"])
    c2.metric("✅ Updates", met["updates"])
    c3.metric("🚫 Errors", met["errors"])
    c4.metric("⏭️ Skipped", met["skipped"])
    c5.metric("🔀 Duplicates", met["duplicates"])

    # Cloud Ingestion Telemetry Banner if an upload was performed
    prog_f = r_dir / "ingest_progress.json"
    if prog_f.exists():
        try:
            p_data = json.loads(prog_f.read_text(encoding="utf-8"))
            if p_data.get("status") in ("COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"):
                succ_cnt = p_data.get("successful_records_overall", 0)
                fail_cnt = p_data.get("failed_records_overall", 0)
                tot_cnt = p_data.get("total_records_overall", 0)
                if fail_cnt > 0:
                    st.warning(f"🚀 **Cloud Salesforce Upload**: **{succ_cnt:,}** succeeded, **{fail_cnt:,}** failed out of **{tot_cnt:,}** records in Salesforce.")
                else:
                    st.success(f"🚀 **Cloud Salesforce Upload**: All **{succ_cnt:,} / {tot_cnt:,}** records successfully updated in Salesforce.")
        except Exception:
            pass

    # File Download Center
    st.markdown("##### 📥 Generated Output Files")
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5 = st.columns(5)

    clean_rep = chosen_run["report"].replace(":", "_").replace(" ", "_")
    selected_run_id = chosen_run.get("raw_run_id", chosen_run["run_id"])

    final_f = r_dir / "final_input_file.csv"
    render_download_with_confirmation(
        btn_c1, "📥 Final Input File", final_f,
        download_filename=f"{clean_rep}_final.csv",
        key=f"hist_{key_prefix}_final_{selected_run_id}"
    )

    rb_f = r_dir / "rollback_file.csv"
    render_download_with_confirmation(
        btn_c2, "🔙 Rollback File", rb_f,
        download_filename=f"{clean_rep}_rollback.csv",
        key=f"hist_{key_prefix}_rb_{selected_run_id}"
    )

    err_f = r_dir / "error_records.csv"
    render_download_with_confirmation(
        btn_c3, "🚫 Error Records", err_f,
        download_filename=f"{clean_rep}_errors.csv",
        key=f"hist_{key_prefix}_err_{selected_run_id}"
    )

    succ_f = r_dir / "success_records.csv"
    render_download_with_confirmation(
        btn_c4, "✅ Success Records", succ_f,
        download_filename=f"{clean_rep}_success.csv",
        key=f"hist_{key_prefix}_succ_{selected_run_id}"
    )

    val_f = r_dir / "validation_report.csv"
    render_download_with_confirmation(
        btn_c5, "📋 Validation Audit", val_f,
        download_filename=f"{clean_rep}_validation.csv",
        key=f"hist_{key_prefix}_val_{selected_run_id}"
    )

    # Extra diagnostics, cloud transactions & post-audit files if present
    extra_files = [
        ("salesforce_success_records.csv", "🟢 Cloud Successes"),
        ("salesforce_error_records.csv", "🔴 Cloud Failures"),
        ("post_update_validation_report.csv", "🔍 Post-Audit Report"),
        ("post_update_discrepancies.csv", "⚠️ Discrepancies"),
        ("field_level_changes.csv", "🔍 Field Changes"),
        ("duplicate_primary_keys.csv", "🔀 Source Duplicates"),
        ("duplicate_salesforce_records.csv", "⚠️ SF Duplicates"),
        ("skipped_records.csv", "⏭️ Skipped Records"),
        ("bulk_upload_failures.csv", "💥 Legacy Cloud Failures"),
    ]
    present_extras = [(fn, label, r_dir / fn) for fn, label in extra_files if (r_dir / fn).exists()]
    if present_extras:
        chunk_size = 4
        for row_idx in range(0, len(present_extras), chunk_size):
            chunk = present_extras[row_idx : row_idx + chunk_size]
            extra_cols = st.columns(len(chunk))
            for i, (fn, label, f_path) in enumerate(chunk):
                render_download_with_confirmation(
                    extra_cols[i], label, f_path,
                    download_filename=f"{clean_rep}_{fn}",
                    key=f"hist_{key_prefix}_{fn}_{selected_run_id}"
                )

    # Multi-Object dedicated payloads (e.g. Apollo 10G)
    multi_rb_files = sorted(r_dir.glob("rollback_file_*.csv"))
    multi_final_files = sorted(r_dir.glob("final_input_file_*.csv"))
    if multi_rb_files or multi_final_files:
        st.markdown("###### 📦 Multi-Object Dedicated Payloads")
        all_multi = [(f, f"🔙 Rollback: {f.stem.replace('rollback_file_', '').replace('_', ' ')}") for f in multi_rb_files] + \
                    [(f, f"📥 Final: {f.stem.replace('final_input_file_', '').replace('_', ' ')}") for f in multi_final_files]
        chunk_size = 4
        for row_idx in range(0, len(all_multi), chunk_size):
            chunk = all_multi[row_idx : row_idx + chunk_size]
            m_cols = st.columns(len(chunk))
            for i, (f_path, label) in enumerate(chunk):
                render_download_with_confirmation(
                    m_cols[i], label, f_path,
                    download_filename=f"{clean_rep}_{f_path.name}",
                    key=f"hist_{key_prefix}_{f_path.stem}_{selected_run_id}"
                )

    # Emergency 1-Click Rollback / Revert Safety Net
    _render_rollback_safety_net(r_dir, chosen_run["report"], key_prefix, selected_run_id)

    # Post-Update Live Reconciliation Summary (if available)
    _render_post_audit_summary(r_dir, key_prefix, selected_run_id)

    # Archived Inputs
    a_dir = chosen_run.get("archive_dir")
    if a_dir and a_dir.exists():
        st.markdown("##### 📁 Archived Inputs Used for this Run")
        arch_files = [f for f in a_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        if arch_files:
            arch_cols = st.columns(len(arch_files))
            for i, af in enumerate(arch_files):
                mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if af.suffix == ".xlsx" else "text/csv"
                render_download_with_confirmation(
                    arch_cols[i], f"📄 {af.name}", af,
                    mime=mime_type,
                    key=f"arch_{key_prefix}_{af.name}_{selected_run_id}"
                )

    # Full Run Summary Text
    sum_f = chosen_run.get("summary_file")
    if sum_f and sum_f.exists():
        with st.expander("📄 View Run Summary Log", expanded=False):
            with open(sum_f, "r", encoding="utf-8") as f:
                st.text(f.read())

    # Full Audit Log
    audit_f = r_dir / "audit.log"
    if audit_f.exists():
        with st.expander("📜 View Audit & Troubleshooting Log (audit.log)", expanded=True):
            with open(audit_f, "r", encoding="utf-8") as af:
                audit_text = af.read()
            st.code(audit_text, language="text")
            st.download_button(
                "📥 Download Audit Log (.log)",
                audit_text,
                file_name=f"{clean_rep}_{chosen_run['date']}_audit.log",
                mime="text/plain",
                key=f"hist_audit_btn_{key_prefix}_{selected_run_id}",
            )

    st.caption(f"📂 Storage Path: `{r_dir}`")


def _render_manual_run_details(chosen_run: dict, key_prefix: str = "manual"):
    """Render high-end enterprise inspection card specifically for manual dataloader runs."""
    r_dir = chosen_run["run_dir"]
    selected_run_id = chosen_run.get("raw_run_id", chosen_run["run_id"])
    clean_rep = chosen_run["report"].replace(":", "_").replace(" ", "_")

    # 1. 4-Column Executive Header Card
    st.markdown(
        f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; padding:18px 22px; margin: 16px 0 20px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap: 20px;">
                <div style="border-right: 1px solid #F1F5F9; padding-right: 12px;">
                    <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase; letter-spacing:0.5px;">👤 Operator & Org</div>
                    <div style="font-weight:700; color:#032D60; font-size:0.95rem; margin-top:4px; word-break:break-all;">{chosen_run.get('user_name', 'Local Operator')}</div>
                    <div style="font-size:0.78rem; color:#64748B; margin-top:2px;">{chosen_run.get('org_name', 'Salesforce Org')}</div>
                </div>
                <div style="border-right: 1px solid #F1F5F9; padding-right: 12px;">
                    <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase; letter-spacing:0.5px;">🎯 Target Salesforce Object</div>
                    <div style="font-weight:700; color:#032D60; font-size:0.95rem; margin-top:4px;">{chosen_run.get('object_name', '')}</div>
                    <div style="font-size:0.78rem; color:#04844B; font-weight:600; margin-top:2px;">Operation: {chosen_run.get('operation', 'Update')}</div>
                </div>
                <div style="border-right: 1px solid #F1F5F9; padding-right: 12px;">
                    <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase; letter-spacing:0.5px;">📄 Uploaded Source File</div>
                    <div style="font-weight:700; color:#032D60; font-size:0.95rem; margin-top:4px; word-break:break-all;">{chosen_run.get('source_filename', 'source_input.csv')}</div>
                    <div style="font-size:0.78rem; color:#64748B; margin-top:2px;">Key: <code>{chosen_run.get('source_pk', 'PK')}</code> ➔ <code>{chosen_run.get('target_pk', 'Name')}</code></div>
                </div>
                <div>
                    <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase; letter-spacing:0.5px;">🕒 Execution Timestamp</div>
                    <div style="font-weight:700; color:#032D60; font-size:0.95rem; margin-top:4px;">{chosen_run.get('formatted_date', '')}</div>
                    <div style="font-size:0.78rem; color:#64748B; margin-top:2px;">{chosen_run.get('formatted_time', '')}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 2. KPI Metrics Tiles
    met = chosen_run["metrics"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Rows", met.get("total", "N/A"))
    c2.metric("✅ Updates", met.get("updates", "N/A"))
    c3.metric("🚫 Errors", met.get("errors", "N/A"))
    c4.metric("⏭️ Skipped", met.get("skipped", "N/A"))
    c5.metric("🔀 Duplicates", met.get("duplicates", "N/A"))

    # Cloud Ingestion Telemetry Banner if an upload was performed
    prog_f = r_dir / "ingest_progress.json"
    if prog_f.exists():
        try:
            p_data = json.loads(prog_f.read_text(encoding="utf-8"))
            if p_data.get("status") in ("COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"):
                succ_cnt = p_data.get("successful_records_overall", 0)
                fail_cnt = p_data.get("failed_records_overall", 0)
                tot_cnt = p_data.get("total_records_overall", 0)
                if fail_cnt > 0:
                    st.warning(f"🚀 **Cloud Salesforce Upload**: **{succ_cnt:,}** succeeded, **{fail_cnt:,}** failed out of **{tot_cnt:,}** records in Salesforce.")
                else:
                    st.success(f"🚀 **Cloud Salesforce Upload**: All **{succ_cnt:,} / {tot_cnt:,}** records successfully updated in Salesforce.")
        except Exception:
            pass

    # 3. Output Files Download Center
    st.markdown("##### 📥 Generated Output Files")
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5 = st.columns(5)

    final_f = r_dir / "final_input_file.csv"
    render_download_with_confirmation(
        btn_c1, "📥 Final Input File", final_f,
        download_filename=f"{clean_rep}_final.csv",
        key=f"hist_{key_prefix}_final_{selected_run_id}"
    )

    rb_f = r_dir / "rollback_file.csv"
    render_download_with_confirmation(
        btn_c2, "🔙 Rollback File", rb_f,
        download_filename=f"{clean_rep}_rollback.csv",
        key=f"hist_{key_prefix}_rb_{selected_run_id}"
    )

    err_f = r_dir / "error_records.csv"
    render_download_with_confirmation(
        btn_c3, "🚫 Error Records", err_f,
        download_filename=f"{clean_rep}_errors.csv",
        key=f"hist_{key_prefix}_err_{selected_run_id}"
    )

    succ_f = r_dir / "success_records.csv"
    render_download_with_confirmation(
        btn_c4, "✅ Success Records", succ_f,
        download_filename=f"{clean_rep}_success.csv",
        key=f"hist_{key_prefix}_succ_{selected_run_id}"
    )

    val_f = r_dir / "validation_report.csv"
    render_download_with_confirmation(
        btn_c5, "📋 Validation Audit", val_f,
        download_filename=f"{clean_rep}_validation.csv",
        key=f"hist_{key_prefix}_val_{selected_run_id}"
    )

    # Extra diagnostics, cloud transactions & post-audit files if present
    extra_files = [
        ("salesforce_success_records.csv", "🟢 Cloud Successes"),
        ("salesforce_error_records.csv", "🔴 Cloud Failures"),
        ("post_update_validation_report.csv", "🔍 Post-Audit Report"),
        ("post_update_discrepancies.csv", "⚠️ Discrepancies"),
        ("field_level_changes.csv", "🔍 Field Changes"),
        ("duplicate_primary_keys.csv", "🔀 Source Duplicates"),
        ("duplicate_salesforce_records.csv", "⚠️ SF Duplicates"),
        ("skipped_records.csv", "⏭️ Skipped Records"),
        ("bulk_upload_failures.csv", "💥 Legacy Cloud Failures"),
    ]
    present_extras = [(fn, label, r_dir / fn) for fn, label in extra_files if (r_dir / fn).exists()]
    if present_extras:
        chunk_size = 4
        for row_idx in range(0, len(present_extras), chunk_size):
            chunk = present_extras[row_idx : row_idx + chunk_size]
            extra_cols = st.columns(len(chunk))
            for i, (fn, label, f_path) in enumerate(chunk):
                render_download_with_confirmation(
                    extra_cols[i], label, f_path,
                    download_filename=f"{clean_rep}_{fn}",
                    key=f"hist_{key_prefix}_{fn}_{selected_run_id}"
                )

    # Emergency 1-Click Rollback / Revert Safety Net
    _render_rollback_safety_net(
        r_dir,
        chosen_run.get("report", chosen_run.get("object_name", "Manual")),
        key_prefix,
        selected_run_id,
        target_object=chosen_run.get("target_object") or chosen_run.get("object_name"),
    )

    # Post-Update Live Reconciliation Summary (if available)
    _render_post_audit_summary(r_dir, key_prefix, selected_run_id)

    # 4. Archived Source File
    a_dir = chosen_run.get("archive_dir")
    if a_dir and a_dir.exists():
        arch_files = [f for f in a_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        if arch_files:
            st.markdown("##### 📁 Archived Source Spreadsheet Used for this Run")
            arch_cols = st.columns(max(1, len(arch_files)))
            for i, af in enumerate(arch_files):
                mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if af.suffix == ".xlsx" else "text/csv"
                render_download_with_confirmation(
                    arch_cols[i], f"📄 Download Original Source: {af.name}", af,
                    mime=mime_type,
                    key=f"arch_{key_prefix}_{af.name}_{selected_run_id}"
                )

    # 5. Full Run Summary Log
    sum_f = chosen_run.get("summary_file")
    if sum_f and sum_f.exists():
        with st.expander("📄 View Execution Summary Log", expanded=False):
            with open(sum_f, "r", encoding="utf-8") as f:
                st.text(f.read())

    # 6. Full Audit Log
    audit_f = r_dir / "audit.log"
    if audit_f.exists():
        with st.expander("📜 View Audit & Troubleshooting Log (audit.log)", expanded=True):
            with open(audit_f, "r", encoding="utf-8") as af:
                audit_text = af.read()
            st.code(audit_text, language="text")
            st.download_button(
                "📥 Download Audit Log (.log)",
                audit_text,
                file_name=f"{clean_rep}_{chosen_run['date']}_audit.log",
                mime="text/plain",
                key=f"hist_audit_btn_{key_prefix}_{selected_run_id}",
            )

    st.caption(f"📂 Run Storage Path: `{r_dir}`")


def render(go):
    render_header(
        "📜 Run History & Audit Log",
        "Browse past engine executions, download historical update/rollback files, and audit archived source inputs."
    )

    tab_auto, tab_manual = st.tabs([
        "📥 Automated / Guided Report History",
        "⚡ Manual Dataloader History",
    ])

    # =========================================================================
    # TAB 1: AUTOMATED / GUIDED REPORT HISTORY
    # =========================================================================
    with tab_auto:
        reports = YamlConfigLoader.list_reports()
        report_names = ["All Reports"] + [r.name for r in reports]

        col_f1, _ = st.columns([2, 2])
        with col_f1:
            selected_filter = st.selectbox("Filter Guided Reports", report_names, index=0, key="auto_report_filter")

        auto_runs = scan_guided_runs(selected_filter)

        if not auto_runs:
            st.info("No historical automated runs found for the selected report.")
        else:
            # Top Metrics Banner
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Recorded Runs", len(auto_runs))
            m2.metric("Most Recent Execution", f"{auto_runs[0]['date']} {auto_runs[0]['time']} IST")
            m3.metric("Current Filter", selected_filter)

            st.markdown("---")

            # Run Selector Dropdown
            run_labels = [r["run_id"] for r in auto_runs]
            selected_run_id = st.selectbox("Select a Run to Inspect", run_labels, index=0, key="auto_run_select")
            chosen_run = next(r for r in auto_runs if r["run_id"] == selected_run_id)

            _render_run_details(chosen_run, key_prefix="auto")

    # =========================================================================
    # TAB 2: MANUAL DATALOADER HISTORY
    # =========================================================================
    with tab_manual:
        raw_manual_runs = scan_manual_runs(object_filter="All Objects")

        if not raw_manual_runs:
            st.info("No historical manual dataloader runs found.")
        else:
            # 1. Filters Row
            col_t1, col_t2, col_t3 = st.columns([2, 2, 2])

            with col_t1:
                time_filter = st.selectbox(
                    "📅 Timeframe Filter",
                    ["All Time", "Today", "Yesterday", "Past 7 Days", "This Month", "Past 30 Days"],
                    index=0,
                    key="manual_time_filter"
                )

            with col_t2:
                manual_objects = sorted({r["object_name"] for r in raw_manual_runs if r.get("object_name")})
                obj_filter_options = ["All Objects"] + manual_objects
                selected_obj = st.selectbox(
                    "🎯 Target Salesforce Object",
                    obj_filter_options,
                    index=0,
                    key="manual_obj_filter",
                )

            with col_t3:
                all_operators = sorted({r["user_name"] for r in raw_manual_runs if r.get("user_name")})
                operator_options = ["All Operators"] + all_operators
                selected_operator = st.selectbox(
                    "👤 Operator / User",
                    operator_options,
                    index=0,
                    key="manual_operator_filter"
                )

            # 2. View / Grouping selector
            col_g1, col_g2 = st.columns([3, 2])
            with col_g2:
                group_mode = st.radio(
                    "🗂️ View & Grouping:",
                    ["Group by Day", "Group by Month", "All Runs (Flat List)"],
                    horizontal=True,
                    key="manual_group_mode"
                )

            # Apply Filters
            filtered_runs = raw_manual_runs
            now = datetime.now()

            if time_filter == "Today":
                filtered_runs = [r for r in filtered_runs if r["date"] == now.strftime("%Y-%m-%d")]
            elif time_filter == "Yesterday":
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                filtered_runs = [r for r in filtered_runs if r["date"] == yesterday]
            elif time_filter == "Past 7 Days":
                cutoff = now - timedelta(days=7)
                filtered_runs = [r for r in filtered_runs if r["datetime"] >= cutoff]
            elif time_filter == "This Month":
                this_month = now.strftime("%Y-%m")
                filtered_runs = [r for r in filtered_runs if r["date"].startswith(this_month)]
            elif time_filter == "Past 30 Days":
                cutoff = now - timedelta(days=30)
                filtered_runs = [r for r in filtered_runs if r["datetime"] >= cutoff]

            if selected_obj != "All Objects":
                filtered_runs = [r for r in filtered_runs if r["object_name"] == selected_obj]

            if selected_operator != "All Operators":
                filtered_runs = [r for r in filtered_runs if r["user_name"] == selected_operator]

            if not filtered_runs:
                st.warning(f"No manual runs match the selected filters (`{time_filter}`, `{selected_obj}`, `{selected_operator}`).")
            else:
                # Top Metrics Banner
                m1, m2, m3, m4 = st.columns(4)
                total_runs_count = len(filtered_runs)
                total_rows_processed = sum(int(r["metrics"]["total"]) for r in filtered_runs if str(r["metrics"]["total"]).isdigit())
                total_updates_generated = sum(int(r["metrics"]["updates"]) for r in filtered_runs if str(r["metrics"]["updates"]).isdigit())
                unique_objs_count = len(set(r["object_name"] for r in filtered_runs))

                m1.metric("Total Manual Runs", total_runs_count)
                m2.metric("Total Source Rows", f"{total_rows_processed:,}")
                m3.metric("Total Updates Pushed", f"{total_updates_generated:,}")
                m4.metric("Active Target Objects", unique_objs_count)

                st.markdown("---")

                # Run Selector depending on grouping mode
                if group_mode == "Group by Day":
                    unique_days = []
                    for r in filtered_runs:
                        if r["day_group"] not in unique_days:
                            unique_days.append(r["day_group"])

                    col_sel_day, col_sel_run = st.columns([1, 2])
                    with col_sel_day:
                        chosen_day = st.selectbox("📅 Select Date Group:", unique_days, index=0, key="man_day_sel")
                    day_runs = [r for r in filtered_runs if r["day_group"] == chosen_day]
                    with col_sel_run:
                        chosen_run_id = st.selectbox(
                            f"Select Run from {chosen_day} ({len(day_runs)} available):",
                            [r["run_id"] for r in day_runs],
                            index=0,
                            key="man_run_day_sel"
                        )
                    chosen_run = next(r for r in day_runs if r["run_id"] == chosen_run_id)

                elif group_mode == "Group by Month":
                    unique_months = []
                    for r in filtered_runs:
                        if r["month_group"] not in unique_months:
                            unique_months.append(r["month_group"])

                    col_sel_mo, col_sel_run = st.columns([1, 2])
                    with col_sel_mo:
                        chosen_month = st.selectbox("📆 Select Month Group:", unique_months, index=0, key="man_month_sel")
                    month_runs = [r for r in filtered_runs if r["month_group"] == chosen_month]
                    with col_sel_run:
                        chosen_run_id = st.selectbox(
                            f"Select Run from {chosen_month} ({len(month_runs)} available):",
                            [r["run_id"] for r in month_runs],
                            index=0,
                            key="man_run_mo_sel"
                        )
                    chosen_run = next(r for r in month_runs if r["run_id"] == chosen_run_id)

                else:  # All Runs (Flat List)
                    chosen_run_id = st.selectbox(
                        f"Select a Manual Run to Inspect ({len(filtered_runs)} available):",
                        [r["run_id"] for r in filtered_runs],
                        index=0,
                        key="man_run_flat_sel"
                    )
                    chosen_run = next(r for r in filtered_runs if r["run_id"] == chosen_run_id)

                # Render Detailed Inspection Card
                _render_manual_run_details(chosen_run, key_prefix="manual")

    st.divider()
    render_back_button(go)
    render_footer()
