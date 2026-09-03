"""Streamlit UI page for Historical Runs and Audit Log."""

import logging
from pathlib import Path
import streamlit as st
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from ui.components import render_back_button, render_footer, render_header

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
            if "Total source records:" in line_str:
                metrics["total"] = line_str.split(":")[-1].strip()
            elif "SUCCESS (uploaded):" in line_str or "Delta Records:" in line_str:
                metrics["updates"] = line_str.split(":")[-1].strip()
            elif "ERRORS (rejected):" in line_str:
                metrics["errors"] = line_str.split(":")[-1].strip()
            elif "SKIPPED:" in line_str:
                metrics["skipped"] = line_str.split(":")[-1].strip()
            elif "Duplicate keys found:" in line_str or "DUPLICATE PKs:" in line_str:
                metrics["duplicates"] = line_str.split(":")[-1].strip()
    except Exception as e:
        logger.warning("Failed to parse run summary at %s: %e", summary_path, e)

    return metrics


def scan_all_runs(report_filter: str | None = None) -> list[dict]:
    """Scan the data directory and return all runs sorted newest first."""
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
                        "date": date_dir.name,
                        "time": run_dir.name.replace("run_", "").replace("-", ":"),
                        "run_id": f"{r.name} • {date_dir.name} {run_dir.name.replace('run_', '')}",
                        "run_dir": run_dir,
                        "archive_dir": matching_archive if matching_archive.exists() else None,
                        "summary_file": summary_file,
                        "metrics": metrics,
                    })
        except Exception as e:
            logger.warning("Error scanning runs for report %s: %s", r.name, e)

    # Sort newest date and time first
    runs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
    return runs


def render(go):
    render_header(
        "📜 Run History & Audit Log",
        "Browse past engine executions, download historical update/rollback files, and audit archived source inputs."
    )

    # 1. Report Filter
    reports = YamlConfigLoader.list_reports()
    report_names = ["All Reports"] + [r.name for r in reports]

    col_f1, col_f2 = st.columns([2, 2])
    with col_f1:
        selected_filter = st.selectbox("Filter History by Report", report_names, index=0)

    runs = scan_all_runs(selected_filter)

    if not runs:
        st.info("No historical runs found for the selected report.")
        render_back_button(go)
        render_footer()
        return

    # Top Metrics Banner
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Recorded Runs", len(runs))
    m2.metric("Most Recent Execution", f"{runs[0]['date']} {runs[0]['time']}")
    m3.metric("Current Filter", selected_filter)

    st.markdown("---")

    # 2. Run Selector Table / Dropdown
    run_labels = [r["run_id"] for r in runs]
    selected_run_id = st.selectbox("Select a Run to Inspect", run_labels, index=0)

    chosen_run = next(r for r in runs if r["run_id"] == selected_run_id)

    # 3. Selected Run Details
    st.subheader(f"🔍 Details: `{chosen_run['report']}` — {chosen_run['date']} {chosen_run['time']}")

    met = chosen_run["metrics"]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Rows", met["total"])
    c2.metric("✅ Updates", met["updates"])
    c3.metric("🚫 Errors", met["errors"])
    c4.metric("⏭️ Skipped", met["skipped"])
    c5.metric("🔀 Duplicates", met["duplicates"])

    # File Download Center for this Run
    st.markdown("##### 📥 Generated Output Files")
    btn_c1, btn_c2, btn_c3, btn_c4, btn_c5 = st.columns(5)

    r_dir = chosen_run["run_dir"]

    final_f = r_dir / "final_input_file.csv"
    if final_f.exists():
        with open(final_f, "rb") as f:
            btn_c1.download_button("📥 Final Input File", f, file_name=f"{chosen_run['report']}_final.csv", mime="text/csv", key=f"hist_final_{selected_run_id}")

    rb_f = r_dir / "rollback_file.csv"
    if rb_f.exists():
        with open(rb_f, "rb") as f:
            btn_c2.download_button("🔙 Rollback File", f, file_name=f"{chosen_run['report']}_rollback.csv", mime="text/csv", key=f"hist_rb_{selected_run_id}")

    err_f = r_dir / "error_records.csv"
    if err_f.exists():
        with open(err_f, "rb") as f:
            btn_c3.download_button("🚫 Error Records", f, file_name=f"{chosen_run['report']}_errors.csv", mime="text/csv", key=f"hist_err_{selected_run_id}")

    succ_f = r_dir / "success_records.csv"
    if succ_f.exists():
        with open(succ_f, "rb") as f:
            btn_c4.download_button("✅ Success Records", f, file_name=f"{chosen_run['report']}_success.csv", mime="text/csv", key=f"hist_succ_{selected_run_id}")

    val_f = r_dir / "validation_report.csv"
    if val_f.exists():
        with open(val_f, "rb") as f:
            btn_c5.download_button("📋 Validation Audit", f, file_name=f"{chosen_run['report']}_validation.csv", mime="text/csv", key=f"hist_val_{selected_run_id}")

    # Archived Inputs
    a_dir = chosen_run["archive_dir"]
    if a_dir and a_dir.exists():
        st.markdown("##### 📁 Archived Inputs Used for this Run")
        arch_files = [f for f in a_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
        if arch_files:
            arch_cols = st.columns(len(arch_files))
            for i, af in enumerate(arch_files):
                with open(af, "rb") as f:
                    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if af.suffix == ".xlsx" else "text/csv"
                    arch_cols[i].download_button(
                        f"📄 {af.name}",
                        f,
                        file_name=af.name,
                        mime=mime_type,
                        key=f"arch_{af.name}_{selected_run_id}"
                    )

    # Full Run Summary Text
    sum_f = chosen_run["summary_file"]
    if sum_f.exists():
        with st.expander("📄 View Run Summary Log", expanded=True):
            with open(sum_f, "r", encoding="utf-8") as f:
                st.text(f.read())

    st.caption(f"📂 Storage Path: `{r_dir}`")

    st.divider()
    render_back_button(go)
    render_footer()
