"""Streamlit UI page for Data Load / Input File Generation."""

import logging
from pathlib import Path
import streamlit as st
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.engine import InputFileEngine
from core.exceptions import EngineSkipError, InputGeneratorError, MappingError, ValidationError
from core.mapping_loader import MappingLoader
from core.validator import InputValidator
from ui.components import render_back_button, render_footer, render_header

logger = logging.getLogger(__name__)


def render(go):
    render_header("📥 Data Load & Input File Generator", "Generate Sitetracker-ready update files by comparing source data against current exports")

    # ======================
    # 1. REPORT SELECTION
    # ======================
    reports = YamlConfigLoader.list_reports()

    if not reports:
        st.error(f"No reports configured in `{settings.CONFIG_DIR}`.")
        st.info("You can scaffold a new report via CLI: `python cli.py scaffold <report_name>`")
        render_back_button(go)
        render_footer()
        return

    st.subheader("1️⃣ Select Report")

    # Map display name with status indicator
    report_options = {}
    for r in reports:
        badges = []
        if not r.has_source:
            badges.append("no source")
        if not r.has_sitetracker:
            badges.append("no sitetracker")
        
        status_suffix = f" ⚠️ ({', '.join(badges)})" if badges else " ✅ (ready)"
        report_options[f"{r.name}{status_suffix}"] = r.name

    selected_display = st.selectbox(
        "Choose configured report",
        ["-- Select Report --"] + sorted(report_options.keys()),
        index=0
    )

    if selected_display == "-- Select Report --":
        st.info("Please select a report to continue.")
        render_back_button(go)
        render_footer()
        return

    selected_report = report_options[selected_display]

    # ======================
    # 2. DATA SOURCE STATUS & LIVE FETCH
    # ======================
    st.subheader("2️⃣ Input Data Files & Live Fetch")

    yaml_cfg = YamlConfigLoader.load(selected_report)
    work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
    src_dir = work_dir / yaml_cfg["folders"]["source_dir"]
    st_dir = work_dir / yaml_cfg["folders"]["sitetracker_dir"]

    src_files = [f.name for f in src_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if src_dir.exists() else []
    st_files = [f.name for f in st_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if st_dir.exists() else []

    col_src_card, col_st_card = st.columns(2)

    with col_src_card:
        st.markdown("#### 📄 Source Excel File")
        if src_files:
            st.success(f"✅ Found: **`{src_files[0]}`**")
        else:
            st.warning(f"⚠️ Missing source file. Place Excel in: `{src_dir.relative_to(settings.PROJECT_ROOT)}`")

    with col_st_card:
        st.markdown("#### 🔄 Sitetracker Data")
        if st_files:
            st.success(f"✅ Found: **`{st_files[0]}`**")
        else:
            st.warning(f"⚠️ Missing file in `{st_dir.relative_to(settings.PROJECT_ROOT)}`")

        from salesforce.auth import is_token_valid
        if is_token_valid():
            if st.button("🔄 Fetch Live Data from Sitetracker", key="btn_fetch_live_st", type="primary"):
                with st.spinner("Executing SOQL query against Sitetracker..."):
                    try:
                        from salesforce.data_fetcher import fetch_sitetracker_data
                        saved_csv = fetch_sitetracker_data(selected_report, st_dir)
                        st.success(f"✅ Fetched live records to `{saved_csv.name}`!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to fetch live data: {e}")
        else:
            st.caption("🔒 *Log in via 'Data Export' to enable 1-click live SOQL fetching directly from Sitetracker.*")

    # ======================
    # 3. MAPPING PREVIEW
    # ======================
    st.subheader("3️⃣ Field Mapping Details")

    try:
        mapping_loader = MappingLoader(settings.MAPPING_FILE, selected_report)
        mapping_df = mapping_loader.load()
    except Exception as e:
        st.warning(f"Could not load mapping for '{selected_report}': {e}")
        mapping_df = pd.DataFrame()

    if not mapping_df.empty:
        # Object selection filter
        if "Object Name" in mapping_df.columns:
            objects = ["All Objects"] + sorted(mapping_df["Object Name"].dropna().unique().tolist())
            selected_object = st.selectbox("Filter preview by Object", objects, index=0)
            if selected_object != "All Objects":
                preview_df = mapping_df[mapping_df["Object Name"] == selected_object]
            else:
                preview_df = mapping_df
        else:
            preview_df = mapping_df

        st.dataframe(preview_df, use_container_width=True)
    else:
        st.info("No field mappings defined yet for this report. You can edit them in the Mapping Editor.")

    # ======================
    # 4. VALIDATION
    # ======================
    st.subheader("4️⃣ Validation & Readiness")

    col_val1, col_val2 = st.columns([1, 3])
    with col_val1:
        run_validation = st.button("🔍 Validate Inputs First")

    if run_validation:
        try:
            validator = InputValidator(selected_report)
            val_res = validator.validate_all()

            if val_res.is_valid:
                st.success("✅ All validation checks passed!")
            else:
                st.error("❌ Validation errors found:")
                for err in val_res.errors:
                    st.write(f"- {err}")

            if val_res.warnings:
                st.warning("⚠️ Validation warnings:")
                for warn in val_res.warnings:
                    st.write(f"- {warn}")
        except Exception as e:
            st.error(f"Validation execution failed: {e}")

    # ======================
    # 5. CONFIRMATION & EXECUTION
    # ======================
    st.subheader("5️⃣ Execution")

    confirm_mapping = st.checkbox(
        "I have reviewed the field mappings and input data and confirm they are correct."
    )

    if st.button("🚀 Generate Input File", type="primary"):
        if not confirm_mapping:
            st.error("Please confirm the mapping before running.")
            st.stop()

        with st.spinner("Running comparison engine…"):
            try:
                engine = InputFileEngine(selected_report)
                result = engine.run()

                st.success("✅ Delta processing completed successfully!")

                # Key Metrics
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Source Records", result.total_source_records)
                col2.metric("Valid Source Records", result.valid_source_records)
                col3.metric("Delta Updates", result.delta_records)
                col4.metric("Field Changes", result.field_changes_count)

                # Quality warnings
                if result.has_warnings:
                    if result.invalid_primary_keys:
                        st.warning(f"⚠️ {len(result.invalid_primary_keys)} invalid primary keys found.")
                    if result.duplicate_primary_keys:
                        st.warning(f"⚠️ {len(result.duplicate_primary_keys)} duplicate primary key values found: {result.duplicate_primary_keys}")
                    if result.invalid_dates:
                        st.warning(f"⚠️ {len(result.invalid_dates)} invalid date values encountered.")

                # Output Location
                st.subheader("📂 Output Directory")
                st.code(str(result.run_dir))

                # Display summary file if exists
                summary_file = result.run_dir / "run_summary.txt"
                if summary_file.exists():
                    with st.expander("📄 View Run Summary", expanded=True):
                        with open(summary_file, "r", encoding="utf-8") as f:
                            st.text(f.read())

            except EngineSkipError as e:
                st.warning(f"⏭ Execution skipped: {e}")
            except ValidationError as e:
                st.error(f"❌ Input validation failed: {e}")
                if hasattr(e, "errors"):
                    for err in e.errors:
                        st.write(f"- {err}")
            except MappingError as e:
                st.error(f"❌ Mapping configuration error: {e}")
            except InputGeneratorError as e:
                st.error(f"❌ Error: {e}")
            except Exception as e:
                st.error(f"❌ Unexpected engine failure: {e}")
                logger.exception("Engine failed unexpectedly")

    # ======================
    # NAVIGATION & FOOTER
    # ======================
    st.divider()
    col_nav1, _ = st.columns([1, 4])
    with col_nav1:
        render_back_button(go)
    render_footer()