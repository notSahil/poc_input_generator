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
from ui.components import render_back_button, render_download_with_confirmation, render_footer, render_header

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
                st.session_state.last_run_result = result
                st.success("✅ Delta processing completed successfully!")
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

    # ==================================================
    # 5b. RUN RESULTS DASHBOARD (PERSISTENT & SAFE)
    # ==================================================
    if "last_run_result" in st.session_state and st.session_state.last_run_result is not None:
        result = st.session_state.last_run_result
        if result.report_name == selected_report:
            st.markdown("### 📊 Run Results Dashboard")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("✅ Success (Updates)", result.delta_records)
            m_col2.metric("🚫 Errors (Rejected)", result.error_records)
            m_col3.metric("⏭️ Skipped Records", result.skipped_records)
            m_col4.metric("📋 Total Processed", result.total_source_records)

            # Direct Download Buttons Row (with Confirmation Popovers)
            st.markdown("##### 📥 Download Output Files")
            d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)

            final_file = result.run_dir / "final_input_file.csv"
            render_download_with_confirmation(
                d_col1, "📥 Final Input File", final_file,
                help_text="Ready for upload into Sitetracker", key="final_input"
            )

            rb_file = result.run_dir / "rollback_file.csv"
            render_download_with_confirmation(
                d_col2, "🔙 Rollback File", rb_file,
                help_text="Pre-change Sitetracker values to undo this run", key="rollback"
            )

            err_file = result.run_dir / "error_records.csv"
            render_download_with_confirmation(
                d_col3, "🚫 Error Records", err_file,
                help_text="Rejected rows with Salesforce-style error codes", key="errors"
            )

            succ_file = result.run_dir / "success_records.csv"
            render_download_with_confirmation(
                d_col4, "✅ Success Records", succ_file,
                help_text="Rows that passed validation with change summary", key="success"
            )

            val_file = result.run_dir / "validation_report.csv"
            render_download_with_confirmation(
                d_col5, "📋 Validation Report", val_file,
                help_text="Full audit trail per row and check", key="validation"
            )

            # Detailed Inspection Tabs
            tab_grid, tab_err, tab_chg, tab_skip, tab_sum = st.tabs([
                "🎨 Visual Source Grid",
                f"🚫 Errors ({result.error_records})",
                f"👁️ Changes ({result.field_changes_count})",
                f"⏭️ Skipped ({result.skipped_records})",
                "📄 Run Summary"
            ])

            with tab_grid:
                st.caption("Visual breakdown of source data with execution status badges.")
                if val_file.exists():
                    val_df = pd.read_csv(val_file, dtype=str)
                    
                    # Add Status Badge column
                    badge_map = {
                        "SUCCESS": "🟢 UPDATED",
                        "ERROR": "🔴 ERROR (REJECTED)",
                        "SKIPPED": "⚪ UNCHANGED",
                    }
                    status_list = []
                    dup_set = set(str(x) for x in result.duplicate_primary_keys)
                    for _, r in val_df.iterrows():
                        pk = str(r.get("Primary_Key", ""))
                        raw_st = str(r.get("Final_Status", ""))
                        if pk in dup_set:
                            status_list.append("⚠️ DUPLICATE PK")
                        else:
                            status_list.append(badge_map.get(raw_st, f"⚪ {raw_st}"))
                    
                    val_df.insert(0, "Execution Status", status_list)
                    st.dataframe(val_df, use_container_width=True)

            with tab_err:
                if err_file.exists():
                    err_df = pd.read_csv(err_file, dtype=str)
                    if not err_df.empty:
                        st.dataframe(err_df, use_container_width=True)
                    else:
                        st.info("No validation errors found in this run! 🎉")

            with tab_chg:
                chg_file = result.run_dir / "field_level_changes.csv"
                if chg_file.exists():
                    chg_df = pd.read_csv(chg_file, dtype=str)
                    if not chg_df.empty:
                        st.dataframe(chg_df, use_container_width=True)
                    else:
                        st.info("No field-level changes detected.")

            with tab_skip:
                skip_file = result.run_dir / "skipped_records.csv"
                if skip_file.exists():
                    skip_df = pd.read_csv(skip_file, dtype=str)
                    if not skip_df.empty:
                        st.dataframe(skip_df, use_container_width=True)
                    else:
                        st.info("No records were skipped in this run.")

            with tab_sum:
                summary_file = result.run_dir / "run_summary.txt"
                if summary_file.exists():
                    with open(summary_file, "r", encoding="utf-8") as f:
                        st.text(f.read())

            st.caption(f"📂 Run Output Directory: `{result.run_dir}`")


    # ======================
    # 6. PUSH TO SITETRACKER (BULK API 2.0)
    # ======================
    if "last_run_result" in st.session_state and st.session_state.last_run_result is not None:
        last_res = st.session_state.last_run_result
        if last_res.report_name == selected_report and last_res.delta_records > 0:
            st.markdown("---")
            st.subheader("6️⃣ Push to Sitetracker (Bulk API 2.0)")
            st.caption("Safely upload the generated delta records directly to Sitetracker asynchronously.")

            # Show changes preview
            changes_file = last_res.run_dir / "field_level_changes.csv"
            if changes_file.exists():
                changes_df = pd.read_csv(changes_file, dtype=str)
                with st.expander(f"👁️ Preview {len(changes_df)} Field-Level Changes to be Pushed", expanded=False):
                    st.dataframe(changes_df, use_container_width=True)

            from salesforce.auth import is_token_valid
            if not is_token_valid():
                st.warning("🔒 You must log in via the **Data Export** page before pushing records to Salesforce.")
            else:
                col_c1, col_c2 = st.columns([2, 1])
                with col_c1:
                    confirm_phrase = st.text_input(
                        "Type CONFIRM to enable upload",
                        placeholder="CONFIRM",
                        key="input_confirm_bulk_push"
                    )

                with col_c2:
                    st.write("")
                    st.write("")
                    push_enabled = (confirm_phrase.strip() == "CONFIRM")
                    if st.button("🚀 Push Deltas to Sitetracker", type="primary", disabled=not push_enabled, key="btn_execute_bulk_push"):
                        with st.spinner("Submitting Bulk API 2.0 ingest job to Salesforce..."):
                            try:
                                from salesforce.bulk_uploader import push_delta_to_sitetracker
                                final_csv = last_res.run_dir / "final_input_file.csv"

                                # Determine target object
                                yaml_cfg = YamlConfigLoader.load(selected_report)
                                obj_name = yaml_cfg.get("report", {}).get("salesforce_object") or "Site__c"
                                if not obj_name and not mapping_df.empty and "Object Name" in mapping_df.columns:
                                    obj_name = mapping_df["Object Name"].dropna().iloc[0]

                                bulk_res = push_delta_to_sitetracker(
                                    csv_path=final_csv,
                                    object_name=obj_name,
                                    report_name=selected_report,
                                    operation="update"
                                )

                                if bulk_res.all_succeeded:
                                    st.success(f"🎉 Successfully updated all {bulk_res.successful_records} records in Sitetracker! (Job ID: `{bulk_res.job_id}`)")
                                else:
                                    st.warning(f"⚠️ Processed {bulk_res.total_records} records: {bulk_res.successful_records} succeeded, {bulk_res.failed_records} failed. (Job ID: `{bulk_res.job_id}`)")
                                    if bulk_res.failures_csv_path and bulk_res.failures_csv_path.exists():
                                        st.error(f"Failure details saved to: `{bulk_res.failures_csv_path.name}`")
                                        fail_df = pd.DataFrame(bulk_res.failures)
                                        st.dataframe(fail_df, use_container_width=True)
                            except Exception as e:
                                st.error(f"Bulk API upload failed: {e}")

                # Emergency Rollback / Revert Safety Net
                rb_csv = last_res.run_dir / "rollback_file.csv"
                if rb_csv.exists():
                    st.write("")
                    with st.expander("⏪ Emergency Rollback / Revert to Previous Sitetracker State", expanded=False):
                        st.warning("⚠️ **Safety Net**: This will push the pre-change values back into Sitetracker to restore records to how they were before this run.")
                        rb_df = pd.read_csv(rb_csv, dtype=str)
                        st.dataframe(rb_df, use_container_width=True)

                        col_rb1, col_rb2 = st.columns([2, 1])
                        with col_rb1:
                            confirm_revert = st.text_input(
                                "Type REVERT to enable rollback",
                                placeholder="REVERT",
                                key="input_confirm_bulk_revert"
                            )
                        with col_rb2:
                            st.write("")
                            st.write("")
                            revert_enabled = (confirm_revert.strip() == "REVERT")
                            if st.button("⏪ Execute Rollback in Sitetracker", type="secondary", disabled=not revert_enabled, key="btn_execute_bulk_revert"):
                                with st.spinner("Submitting Rollback job to Salesforce Bulk API 2.0..."):
                                    try:
                                        from salesforce.bulk_uploader import push_delta_to_sitetracker
                                        yaml_cfg = YamlConfigLoader.load(selected_report)
                                        obj_name = yaml_cfg.get("report", {}).get("salesforce_object") or "Site__c"
                                        if not obj_name and not mapping_df.empty and "Object Name" in mapping_df.columns:
                                            obj_name = mapping_df["Object Name"].dropna().iloc[0]

                                        rb_res = push_delta_to_sitetracker(
                                            csv_path=rb_csv,
                                            object_name=obj_name,
                                            report_name=selected_report,
                                            operation="update"
                                        )
                                        if rb_res.all_succeeded:
                                            st.success(f"⏪ Rollback successful! All {rb_res.successful_records} records reverted to their previous state in Sitetracker. (Job ID: `{rb_res.job_id}`)")
                                        else:
                                            st.warning(f"⚠️ Revert processed with {rb_res.failed_records} errors.")
                                    except Exception as e:
                                        st.error(f"Rollback failed: {e}")

    # ======================
    # NAVIGATION & FOOTER
    # ======================
    st.divider()
    col_nav1, _ = st.columns([1, 4])
    with col_nav1:
        render_back_button(go)
    render_footer()