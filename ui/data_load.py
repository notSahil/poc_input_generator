import streamlit as st
import pandas as pd
import subprocess
import os
import sys
import re

# ======================
# CONFIG
# ======================
def render(go):
    #st.title("📁 Data Loader")
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MAPPING_FILE = os.path.join(BASE_DIR, "Common", "Mapping_file.xlsx")
    ENGINE_SCRIPT = os.path.join(BASE_DIR, "engine", "input_file_engine.py")
    OBJECT_COLUMN = "Object Name"

    # BASIC VALIDATION
    
    if not os.path.exists(ENGINE_SCRIPT):
        st.error(f"Engine script not found:\n{ENGINE_SCRIPT}")
        st.stop()

    try:
        full_mapping_df = pd.read_excel(MAPPING_FILE, dtype=str)
    except Exception as e:
        st.error(f"Failed to load mapping file: {e}")
        st.stop()

    available_reports = (
        full_mapping_df["Report Name"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    if not available_reports:
        st.error("No reports found in Mapping_file.xlsx")
        st.stop()

    # ======================
    # BUILD REPORT CONFIG
    # ======================

    REPORTS = {}

    for report in available_reports:
        folder_name = report.replace(" ", "_")
        work_dir = os.path.join(BASE_DIR, folder_name)

        if not os.path.isdir(work_dir):
            st.warning(f"Report folder missing for '{report}': {work_dir}")
            continue

        REPORTS[report] = {
            "work_dir": work_dir,
            "runs_dir": os.path.join(work_dir, "runs")
        }

    if not REPORTS:
        st.error("No valid report folders found.")
        st.stop()

    # ======================
    # PAGE SETUP
    # ======================

    st.set_page_config(page_title="Input File Portal", layout="wide")
    st.title("📁 Input File Portal")
    st.caption("UI for Input File Generation")

    # ======================
    # REPORT SELECTION
    # ======================

    st.subheader("1️⃣ Select Report")

    selected_report = st.selectbox(
        "Choose report",
        ["-- Select Report --"] + sorted(REPORTS.keys()),
        index=0
    )

    if selected_report == "-- Select Report --":
        st.info("Please select a report to continue.")
        st.stop()

    # ======================
    # LOAD MAPPING (REPORT-SPECIFIC)
    # ======================

    mapping_df = full_mapping_df[
        full_mapping_df["Report Name"] == selected_report
    ]

    if mapping_df.empty:
        st.warning("No mapping found for this report.")
        st.stop()

    # ======================
    # OBJECT SELECTION
    # ======================

    st.subheader("2️⃣ Select Object")

    if OBJECT_COLUMN not in mapping_df.columns:
        st.error(f"'{OBJECT_COLUMN}' column not found in mapping file.")
        st.stop()

    object_list = (
        mapping_df[OBJECT_COLUMN]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    selected_object = st.selectbox(
        "Choose object to preview mapping",
        ["-- Select Object --"] + sorted(object_list),
        index=0
    )

    # ======================
    # MAPPING PREVIEW
    # ======================

    st.subheader("3️⃣ Mapping File Preview")

    if selected_object == "-- Select Object --":
        st.warning("Please select an object to preview mapping.")
        st.stop()

    preview_df = mapping_df[mapping_df[OBJECT_COLUMN] == selected_object]

    if preview_df.empty:
        st.warning("No mapping rows found for selected object.")
    else:
        st.dataframe(preview_df, use_container_width=True)

    # ======================
    # CONFIRMATION
    # ======================

    st.subheader("4️⃣ Confirmation")

    confirm_mapping = st.checkbox(
        "I have reviewed the mapping and confirm it is correct"
    )

    # ======================
    # EXECUTION
    # ======================

    st.subheader("5️⃣ Run")

    if st.button("🚀 Generate Input File", type="primary"):
        if not confirm_mapping:
            st.error("You must confirm the mapping before running.")
            st.stop()

        st.info("Running engine… please wait")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "engine.cli",
                "--report",
                selected_report
            ],
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        st.subheader("🖥 Engine Output")
        st.code(stdout if stdout else "No output", language="text")

        if stderr:
            st.subheader("⚠️ Engine Errors")
            st.code(stderr, language="text")

        if result.returncode != 0:
            st.error("❌ Engine execution failed.")
            st.stop()

        if "skip" in stdout.lower():
            st.warning("⚠️ Execution skipped (input files missing).")
            st.stop()

        st.success("✅ Execution completed successfully")

        # ======================
        # LOAD SUMMARY
        # ======================

        match = re.search(r"Output written to (.+)", stdout)

        if not match:
            st.warning("Could not determine output location from engine output.")
            st.stop()

        run_path = match.group(1).strip()
        summary_path = os.path.join(run_path, "run_summary.txt")

        st.subheader("📊 Run Summary")

        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                st.text(f.read())
        else:
            st.warning("Run summary file not found.")

        st.subheader("📂 Output Location")
        st.code(run_path)

    # ======================
    # FOOTER
    # ======================

    st.divider()
    st.caption("Internal Tool • Streamlit UI")