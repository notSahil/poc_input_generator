"""Streamlit UI page for Historical Runs and Audit Log."""

import logging
from pathlib import Path
import streamlit as st
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from ui.components import render_back_button, render_download_with_confirmation, render_footer, render_header

logger = logging.getLogger(__name__)


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

                    runs.append({
                        "report": r.name,
                        "type": "Guided Report",
                        "date": date_dir.name,
                        "time": run_dir.name.replace("run_", "").replace("-", ":"),
                        "run_id": f"📥 {r.name} • {date_dir.name} {run_dir.name.replace('run_', '')}",
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
    """Scan and return all ad-hoc manual dataloader runs sorted newest first."""
    runs = []
    manual_runs_dir = settings.DATA_DIR / "manual_runs"
    if not manual_runs_dir.exists():
        return runs

    for obj_dir in sorted(manual_runs_dir.iterdir()):
        if not obj_dir.is_dir() or obj_dir.name.startswith("."):
            continue

        obj_name = obj_dir.name
        if object_filter and object_filter != "All Objects" and obj_name != object_filter and f"Ad-Hoc: {obj_name}" != object_filter:
            continue

        for date_dir in sorted(obj_dir.iterdir(), reverse=True):
            if not date_dir.is_dir() or date_dir.name.startswith("."):
                continue
            for run_dir in sorted(date_dir.iterdir(), reverse=True):
                if not run_dir.is_dir() or run_dir.name.startswith("."):
                    continue

                summary_file = run_dir / "run_summary.txt"
                metrics = parse_run_summary(summary_file)
                matching_archive = run_dir / "archive"

                runs.append({
                    "report": f"Ad-Hoc: {obj_name}",
                    "object_name": obj_name,
                    "type": "Manual Ingestion",
                    "date": date_dir.name,
                    "time": run_dir.name.replace("run_", "").replace("-", ":"),
                    "run_id": f"⚡ {obj_name} • {date_dir.name} {run_dir.name.replace('run_', '')}",
                    "run_dir": run_dir,
                    "archive_dir": matching_archive if matching_archive.exists() else None,
                    "summary_file": summary_file,
                    "metrics": metrics,
                })

    runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return runs


def scan_all_runs(report_filter: str | None = None) -> list[dict]:
    """Scan the data directory and return all runs (both guided and manual) sorted newest first."""
    all_runs = scan_guided_runs(report_filter) + scan_manual_runs(report_filter)
    all_runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return all_runs


def _render_run_details(chosen_run: dict, key_prefix: str):
    """Render details, KPI metrics, file downloads, and audit logs for a selected run."""
    st.subheader(f"🔍 Details: `{chosen_run['report']}` — {chosen_run['date']} {chosen_run['time']} IST")

    met = chosen_run["metrics"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Rows", met["total"])
    c2.metric("✅ Updates", met["updates"])
    c3.metric("🚫 Errors", met["errors"])
    c4.metric("⏭️ Skipped", met["skipped"])
    c5.metric("🔀 Duplicates", met["duplicates"])

    # File Download Center
    st.markdown("##### 📥 Generated Output Files")
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5 = st.columns(5)

    r_dir = chosen_run["run_dir"]
    clean_rep = chosen_run["report"].replace(":", "_").replace(" ", "_")
    selected_run_id = chosen_run["run_id"]

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

    # Extra diagnostics & duplicate files if present
    extra_files = [
        ("field_level_changes.csv", "🔍 Field Changes"),
        ("duplicate_primary_keys.csv", "🔀 Source Duplicates"),
        ("duplicate_salesforce_records.csv", "⚠️ SF Duplicates"),
        ("skipped_records.csv", "⏭️ Skipped Records"),
    ]
    present_extras = [(fn, label, r_dir / fn) for fn, label in extra_files if (r_dir / fn).exists()]
    if present_extras:
        extra_cols = st.columns(len(present_extras))
        for i, (fn, label, f_path) in enumerate(present_extras):
            render_download_with_confirmation(
                extra_cols[i], label, f_path,
                download_filename=f"{clean_rep}_{fn}",
                key=f"hist_{key_prefix}_{fn}_{selected_run_id}"
            )

    # Archived Inputs
    a_dir = chosen_run["archive_dir"]
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
    sum_f = chosen_run["summary_file"]
    if sum_f.exists():
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
        manual_runs_dir = settings.DATA_DIR / "manual_runs"
        manual_objects = []
        if manual_runs_dir.exists():
            manual_objects = [
                d.name for d in sorted(manual_runs_dir.iterdir())
                if d.is_dir() and not d.name.startswith(".")
            ]

        obj_filter_options = ["All Objects"] + manual_objects

        col_m1, _ = st.columns([2, 2])
        with col_m1:
            selected_obj = st.selectbox(
                "Filter Manual Loads by Target Object",
                obj_filter_options,
                index=0,
                key="manual_obj_filter",
            )

        manual_runs = scan_manual_runs(selected_obj)

        if not manual_runs:
            st.info("No historical manual dataloader runs found for the selected target object.")
        else:
            # Top Metrics Banner
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Manual Runs", len(manual_runs))
            m2.metric("Most Recent Execution", f"{manual_runs[0]['date']} {manual_runs[0]['time']} IST")
            m3.metric("Target Object Filter", selected_obj)

            st.markdown("---")

            # Run Selector Dropdown
            run_labels = [r["run_id"] for r in manual_runs]
            selected_run_id = st.selectbox("Select a Manual Run to Inspect", run_labels, index=0, key="manual_run_select")
            chosen_run = next(r for r in manual_runs if r["run_id"] == selected_run_id)

            _render_run_details(chosen_run, key_prefix="manual")

    st.divider()
    render_back_button(go)
    render_footer()
