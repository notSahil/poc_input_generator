"""Streamlit UI page for Data Load / Input File Generation with Dataloader.io guided pipeline."""

from datetime import datetime
import logging
from pathlib import Path
import shutil
import streamlit as st
import pandas as pd

from config import settings
from core.config_loader import YamlConfigLoader
from core.engine import InputFileEngine
from core.exceptions import EngineSkipError, InputGeneratorError, MappingError, ValidationError
from core.mapping_loader import MappingLoader
from core.normalizer import DataNormalizer
from core.validator import InputValidator
from ui.components import (
    render_back_button,
    render_download_with_confirmation,
    render_footer,
    render_header,
    render_pipeline_stepper,
    render_step_navigation,
)
from ui.styles import apply_slds_theme, render_kpi_card, render_pill

logger = logging.getLogger(__name__)


def _read_csv_preview(path: Path) -> pd.DataFrame:
    """Safely read CSV files for UI preview handling both UTF-8 and Latin-1 encodings and casting to str."""
    try:
        df = pd.read_csv(path, dtype=str, encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv(path, dtype=str, encoding="latin1", engine="python", on_bad_lines="skip")
    return df.fillna("").astype(str)


def _read_excel_preview(path: Path) -> pd.DataFrame:
    """Safely read Excel files for UI preview with all columns cast to strings to prevent Arrow serialization errors."""
    try:
        df = pd.read_excel(path, dtype=str)
    except Exception:
        df = pd.read_excel(path)
    return df.fillna("").astype(str)


def _init_wizard_state():
    """Ensure wizard session state variables are initialized."""
    if "data_load_step" not in st.session_state:
        st.session_state.data_load_step = 0
    if "selected_report" not in st.session_state:
        st.session_state.selected_report = None
    if "last_run_result" not in st.session_state:
        st.session_state.last_run_result = None
    if "mapping_confirmed" not in st.session_state:
        st.session_state.mapping_confirmed = True  # Default to True so user is not blocked
    if "insert_nulls_toggle" not in st.session_state:
        st.session_state.insert_nulls_toggle = False


# =========================================================
# STEP 1: SOURCE & OBJECT SELECTION
# =========================================================

def _render_step_source(reports: list) -> bool:
    st.markdown("### 1️⃣ Source Data & Salesforce Object")
    st.caption("Select the configured report model and verify input spreadsheets or trigger a live Sitetracker fetch.")

    # Map display names with readiness indicator
    report_options = {}
    for r in reports:
        badges = []
        if not r.has_source:
            badges.append("no source")
        if not r.has_sitetracker:
            badges.append("no sitetracker")
        status_suffix = f" ⚠️ ({', '.join(badges)})" if badges else " ✅ (ready)"
        report_options[f"{r.name}{status_suffix}"] = r.name

    current_idx = 0
    keys = ["-- Select Report --"] + sorted(report_options.keys())
    if st.session_state.selected_report:
        for idx, k in enumerate(keys):
            if k != "-- Select Report --" and report_options[k] == st.session_state.selected_report:
                current_idx = idx
                break

    col_sel, col_env = st.columns([2.5, 1.5])
    with col_sel:
        selected_display = st.selectbox(
            "Target Report Model",
            keys,
            index=current_idx,
            help="Select the data load configuration model defining Primary Keys and target fields."
        )

    from salesforce.auth import check_connection_status, get_active_profile
    active_prof = get_active_profile()
    is_auth, status_label = check_connection_status(profile=active_prof)
    if active_prof == "partial":
        env_label = "Partial Copy Sandbox"
        env_color = "purple"
    elif active_prof == "sandbox":
        env_label = "Developer Sandbox"
        env_color = "amber"
    else:
        env_label = "Production Org"
        env_color = "blue"

    if is_auth:
        status_dot = '<span style="color:#04844B; font-size:0.8rem; font-weight:600;">● Connected</span>'
    elif status_label == "Disconnected":
        status_dot = '<span style="color:#64748B; font-size:0.8rem; font-weight:600;">○ Disconnected</span>'
    else:
        status_dot = f'<span style="color:#EA001E; font-size:0.8rem; font-weight:600;">● {status_label}</span>'

    with col_env:
        st.markdown(
            f"""
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; margin-top:24px;">
                <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase;">Connected Org</div>
                <div style="font-weight:700; color:#032D60; font-size:0.95rem; display:flex; align-items:center; gap:6px; margin-top:2px;">
                    {render_pill(env_label, env_color)}
                    {status_dot}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    if selected_display == "-- Select Report --":
        st.session_state.selected_report = None
        st.info("💡 Please select a report model above to inspect data sources.")
        return False

    selected_report = report_options[selected_display]
    st.session_state.selected_report = selected_report

    yaml_cfg = YamlConfigLoader.load(selected_report)
    work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
    src_dir = work_dir / yaml_cfg["folders"]["source_dir"]
    st_dir = work_dir / yaml_cfg["folders"]["sitetracker_dir"]

    src_files = [f.name for f in src_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if src_dir.exists() else []
    st_files = [f.name for f in st_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if st_dir.exists() else []

    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

    # Dynamically discover objects and primary keys
    try:
        loader = MappingLoader(settings.MAPPING_FILE, selected_report)
        report_objects = loader.objects()
        report_pks = loader.all_primary_keys()
    except Exception:
        report_objects = []
        report_pks = []

    if report_objects:
        obj_pills = " ".join(render_pill(o, "blue") for o in report_objects)
        st.markdown(
            f"""
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; align-items:center; justify-content:space-between;">
                <div style="font-size:0.85rem; font-weight:600; color:#475569;">Registered Salesforce Objects:</div>
                <div>{obj_pills}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    col_src_card, col_st_card = st.columns(2)

    with col_src_card:
        st.markdown(
            f"""
            <div class="slds-card">
                <div class="slds-card-title">📄 Source Excel / CSV Input</div>
                <div class="slds-card-subtitle">Spreadsheet containing site updates to push into Sitetracker.</div>
            """,
            unsafe_allow_html=True
        )

        uploaded_src = st.file_uploader(
            "Upload Source Spreadsheet (CSV or Excel)",
            type=["csv", "xlsx", "xls"],
            key=f"uploader_src_{selected_report}",
            help="Upload an updated data file (.csv, .xlsx, .xls) containing records to process."
        )
        if uploaded_src is not None:
            src_dir.mkdir(parents=True, exist_ok=True)
            save_dest = src_dir / uploaded_src.name
            archive_src = src_dir / "archive"
            archive_src.mkdir(parents=True, exist_ok=True)
            for old_f in src_dir.iterdir():
                if old_f.is_file() and not old_f.name.startswith(".") and old_f.name != uploaded_src.name:
                    try:
                        shutil.move(str(old_f), str(archive_src / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{old_f.name}"))
                    except Exception:
                        pass
            with open(save_dest, "wb") as f_out:
                f_out.write(uploaded_src.getbuffer())
            src_files = [uploaded_src.name]
            st.success(f"✅ Loaded **{uploaded_src.name}** successfully!")

        if src_files:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill(f'Active Source: {src_files[0]}', 'green')}</div>", unsafe_allow_html=True)
            with st.expander(f"👁️ Preview Source Data ({src_files[0]})", expanded=False):
                try:
                    sf_path = src_dir / src_files[0]
                    src_view_df = DataNormalizer.read_spreadsheet(sf_path, nrows=100)
                    st.caption(f"📁 Previewing top {len(src_view_df):,} rows • {len(src_view_df.columns)} columns")
                    st.dataframe(src_view_df, use_container_width=True)
                except Exception as e:
                    st.error(f"Could not load source file: {e}")
        else:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill('Missing source file', 'amber')}</div>", unsafe_allow_html=True)
            st.caption(f"Upload above or place input file in: `{src_dir.relative_to(settings.PROJECT_ROOT)}`")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_st_card:
        st.markdown(
            f"""
            <div class="slds-card">
                <div class="slds-card-title">🔄 Sitetracker Baseline Data</div>
                <div class="slds-card-subtitle">Current records from Sitetracker used to compute deltas.</div>
            """,
            unsafe_allow_html=True
        )

        uploaded_st = st.file_uploader(
            "Upload Sitetracker Baseline (CSV or Excel)",
            type=["csv", "xlsx", "xls"],
            key=f"uploader_st_{selected_report}",
            help="Optional: Upload an offline baseline export file if not fetching live via SOQL."
        )
        if uploaded_st is not None:
            st_dir.mkdir(parents=True, exist_ok=True)
            save_dest = st_dir / uploaded_st.name
            archive_st = st_dir / "archive"
            archive_st.mkdir(parents=True, exist_ok=True)
            for old_f in st_dir.iterdir():
                if old_f.is_file() and not old_f.name.startswith(".") and old_f.name != uploaded_st.name:
                    try:
                        shutil.move(str(old_f), str(archive_st / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{old_f.name}"))
                    except Exception:
                        pass
            with open(save_dest, "wb") as f_out:
                f_out.write(uploaded_st.getbuffer())
            st_files = [uploaded_st.name]
            st.success(f"✅ Loaded **{uploaded_st.name}** successfully!")

        if st_files:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill(f'Active Baseline: {st_files[0]}', 'green')}</div>", unsafe_allow_html=True)
            with st.expander(f"👁️ Preview Sitetracker Data ({st_files[0]})", expanded=False):
                try:
                    st_view_df = DataNormalizer.read_spreadsheet(st_dir / st_files[0], nrows=100)
                    st.caption(f"📁 Previewing top {len(st_view_df):,} rows • {len(st_view_df.columns)} columns")
                    st.dataframe(st_view_df, use_container_width=True)
                except Exception as e:
                    st.error(f"Could not load Sitetracker baseline: {e}")
        else:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill('Missing baseline file', 'amber')}</div>", unsafe_allow_html=True)
            st.caption(f"Upload above, place file in: `{st_dir.relative_to(settings.PROJECT_ROOT)}`, or fetch live.")

        if is_auth:
            if report_objects:
                obj_refs = " & ".join(f"**{o}**" for o in report_objects)
                st.caption(f"ℹ️ Queries mapped fields across: {obj_refs}")

            if st.button("🔄 Fetch Live Data from Sitetracker (SOQL)", key="btn_fetch_live_st", type="primary"):
                with st.spinner(f"Executing SOQL query against {env_label}..."):
                    try:
                        from salesforce.data_fetcher import fetch_sitetracker_data
                        src_path = (src_dir / src_files[0]) if src_files else None
                        saved_csv = fetch_sitetracker_data(
                            selected_report,
                            st_dir,
                            source_file=src_path,
                            profile=active_prof,
                        )
                        st.success(f"✅ Fetched live records to `{saved_csv.name}`!")
                        st.rerun()
                    except MappingError as e:
                        st.error(f"⚠️ **Field Mapping Error**:\n\n{e}")
                    except Exception as e:
                        st.error(f"Failed to fetch live data: {e}")
        else:
            st.caption("🔒 *Org is disconnected. Log in via 'Data Export' to enable 1-click live SOQL fetching.*")
        st.markdown("</div>", unsafe_allow_html=True)

    return True


# =========================================================
# STEP 2: FIELD MAPPING CANVAS (DATALOADER.IO STYLE)
# =========================================================

def _render_step_mapping(selected_report: str):
    st.markdown("### 2️⃣ Visual Field Mapping & Schema Validation")
    st.caption("Verify how source spreadsheet columns map to Sitetracker API fields and data types.")

    try:
        mapping_loader = MappingLoader(settings.MAPPING_FILE, selected_report)
        mapping_df = mapping_loader.load()
        report_objects = mapping_loader.objects()
        pks = mapping_loader.all_primary_keys()
    except Exception as e:
        st.warning(f"Could not load mapping for '{selected_report}': {e}")
        mapping_df = pd.DataFrame()
        report_objects = []
        pks = []

    if mapping_df.empty:
        st.info("No field mappings defined yet for this report. You can configure them in the Mapping Editor.")
        return

    # High level mapping health metrics
    total_fields = len(mapping_df)

    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown(
            render_kpi_card(
                "Mapped Fields",
                f"{total_fields}",
                f"{len(report_objects)} Target Object{'s' if len(report_objects) != 1 else ''}",
                "success"
            ),
            unsafe_allow_html=True
        )
    with col_m2:
        if len(pks) == 1:
            pk_title = pks[0]["source"]
            pk_sub = f"Object: {pks[0]['object']}" if pks[0]["object"] else "Primary Deduplication Key"
        elif len(pks) > 1:
            pk_title = f"{len(pks)} Primary Keys"
            pk_sub = " • ".join(f"{p['source']} ({p['object']})" for p in pks)
        else:
            pk_title = "None Detected"
            pk_sub = "⚠️ Check Primary Key? column"
        st.markdown(render_kpi_card("Primary Key(s)", pk_title, pk_sub, "default"), unsafe_allow_html=True)

    with col_m3:
        obj_display = ", ".join(report_objects) if report_objects else "Default"
        st.markdown(
            render_kpi_card(
                "Salesforce Object(s)",
                obj_display,
                f"{len(report_objects)} Registered Object{'s' if len(report_objects) != 1 else ''}",
                "default"
            ),
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)

    # Object Filter (if multiple objects exist)
    filtered_df = mapping_df
    if len(report_objects) > 1:
        f_col1, f_col2 = st.columns([3, 1])
        with f_col1:
            selected_filter = st.radio(
                "Filter Fields by Salesforce Object:",
                ["All Objects"] + report_objects,
                horizontal=True,
                key="radio_filter_obj"
            )
        with f_col2:
            if selected_filter != "All Objects":
                filtered_df = mapping_df[mapping_df["Object Name"].astype(str).str.strip().str.lower() == selected_filter.strip().lower()]
            st.markdown(f"<div style='margin-top:28px; font-size:0.85rem; color:#64748B;'>Showing <b>{len(filtered_df)}</b> of <b>{len(mapping_df)}</b> fields</div>", unsafe_allow_html=True)

    # Dataloader-style Visual Mapping List
    st.markdown(
        """
        <div class="mapping-header">
            <div>Source Column (Spreadsheet)</div>
            <div style="text-align: center;">Mapping & Rule</div>
            <div style="text-align: right;">Sitetracker Target Field & Object</div>
        </div>
        <div class="mapping-list">
        """,
        unsafe_allow_html=True
    )

    src_col_name = "Source File Column Name" if "Source File Column Name" in mapping_df.columns else mapping_df.columns[0]
    st_col_name = "Sitetracker Field Name" if "Sitetracker Field Name" in mapping_df.columns else (mapping_df.columns[1] if len(mapping_df.columns) > 1 else src_col_name)
    type_col_name = "Data Type" if "Data Type" in mapping_df.columns else None

    for _, row in filtered_df.iterrows():
        src_val = str(row.get(src_col_name, ""))
        tgt_val = str(row.get(st_col_name, ""))
        row_obj = str(row.get("Object Name", "")).strip() if "Object Name" in row and pd.notna(row["Object Name"]) else ""
        is_pk = str(row.get("Primary Key?", "")).strip().upper() in ("YES", "Y", "TRUE")
        dtype = str(row.get(type_col_name, "TEXT")).upper() if type_col_name else "TEXT"

        badge_color = "green" if "DATE" in dtype else ("blue" if "ID" in dtype or "KEY" in dtype else "purple")
        rule_pill = render_pill(dtype, badge_color)

        pk_badge = f'<span style="margin-right:6px;">{render_pill("🔑 PRIMARY KEY", "amber")}</span>' if is_pk else ""
        obj_badge = f'<span style="margin-left:6px;">{render_pill(row_obj, "blue")}</span>' if row_obj else ""

        st.markdown(
            f"""
            <div class="mapping-item">
                <div>
                    <div class="mapping-source-col">{pk_badge}{src_val}</div>
                    <div class="mapping-source-sample">Source Input Header</div>
                </div>
                <div class="mapping-arrow-col">
                    <div>{rule_pill}</div>
                    <div style="font-size:0.75rem; color:#94A3B8;">➔</div>
                </div>
                <div class="mapping-target-col">
                    <div class="mapping-target-field">{tgt_val}{obj_badge}</div>
                    <div style="font-size:0.75rem; color:#64748B;">API Target Field</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("</div>", unsafe_allow_html=True)

    # Detailed Table inspection in expander
    with st.expander("📋 View Complete Mapping Table & Rules", expanded=False):
        st.dataframe(mapping_df, use_container_width=True)

    # Pre-flight Validation
    st.markdown("#### 🔍 Pre-Flight Validation Check")
    if st.button("Run Pre-Flight Validation Check", key="btn_preflight_val"):
        try:
            validator = InputValidator(selected_report)
            val_res = validator.validate_all()

            if val_res.is_valid:
                st.success("✅ All pre-flight validation checks passed! Ready for delta computation.")
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

    st.session_state.mapping_confirmed = st.checkbox(
        "I have verified the field mappings and source column schemas.",
        value=st.session_state.mapping_confirmed,
        key="chk_confirm_mapping"
    )


# =========================================================
# STEP 3: DELTA GENERATION & AUDIT ENGINE
# =========================================================

def _render_step_delta(selected_report: str) -> bool:
    st.markdown("### 3️⃣ Delta Engine & Validation Audit")
    st.caption("Execute row-by-row comparison against baseline Sitetracker data to compute strict updates.")

    with st.expander("⚙️ Dataloader Execution Settings", expanded=False):
        st.session_state.insert_nulls_toggle = st.checkbox(
            "⚠️ Overwrite with Blanks (Insert Nulls)",
            value=st.session_state.insert_nulls_toggle,
            help="If enabled, empty cells in the source file will wipe existing values in Sitetracker with #N/A. If disabled (safe default), empty cells are ignored and existing values are preserved."
        )

    col_btn, col_info = st.columns([1.5, 3])
    with col_btn:
        run_delta = st.button("🚀 Run Delta Comparison Engine", type="primary", use_container_width=True, key="btn_run_delta_engine")
    with col_info:
        st.caption("Compares source input vs Sitetracker baseline, enforces Primary Key integrity, and isolates field modifications.")

    if run_delta:
        with st.spinner("Executing comparison engine & validating rows..."):
            try:
                engine = InputFileEngine(selected_report, insert_nulls=st.session_state.insert_nulls_toggle)
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

    # Display KPI Metrics & Results if result exists
    has_result = st.session_state.last_run_result is not None and st.session_state.last_run_result.report_name == selected_report
    if has_result:
        result = st.session_state.last_run_result
        st.markdown("<div style='margin-top: 18px;'></div>", unsafe_allow_html=True)
        st.markdown("#### 📊 Execution Results & Audit Metrics")

        k_col1, k_col2, k_col3, k_col4 = st.columns(4)
        with k_col1:
            st.markdown(render_kpi_card("Total Source Rows", f"{result.total_source_records:,}", "Processed records", "default"), unsafe_allow_html=True)
        with k_col2:
            st.markdown(render_kpi_card("Updates (Deltas)", f"{result.delta_records:,}", "Target updates", "success"), unsafe_allow_html=True)
        with k_col3:
            st.markdown(render_kpi_card("Errors / Rejected", f"{result.error_records:,}", "Quarantined rows", "error" if result.error_records > 0 else "default"), unsafe_allow_html=True)
        with k_col4:
            st.markdown(render_kpi_card("Unchanged / Skipped", f"{result.skipped_records:,}", "No action needed", "default"), unsafe_allow_html=True)

        # Tab inspection
        val_file = result.run_dir / "validation_report.csv"
        final_file = result.run_dir / "final_input_file.csv"
        err_file = result.run_dir / "error_records.csv"
        chg_file = result.run_dir / "field_level_changes.csv"

        tab_grid, tab_changes, tab_errors, tab_summary = st.tabs([
            "🎨 Visual Source Grid",
            f"👁️ Field-Level Changes ({result.field_changes_count})",
            f"🚫 Error Diagnostics ({result.error_records})",
            "📄 Run Summary"
        ])

        with tab_grid:
            if val_file.exists():
                val_df = pd.read_csv(val_file, dtype=str)
                badge_map = {
                    "SUCCESS": "🟢 UPDATED",
                    "ERROR": "🔴 ERROR (REJECTED)",
                    "SKIPPED": "⚪ UNCHANGED",
                    "DUPLICATE_SKIPPED": "⚠️ DUPLICATE (SKIPPED)",
                }
                status_list = [badge_map.get(str(r.get("Final_Status", "")), f"⚪ {r.get('Final_Status', '')}") for _, r in val_df.iterrows()]
                val_df.insert(0, "Execution Status", status_list)
                st.dataframe(val_df, use_container_width=True)

        with tab_changes:
            if chg_file.exists():
                chg_df = pd.read_csv(chg_file, dtype=str)
                if not chg_df.empty:
                    st.dataframe(chg_df, use_container_width=True)
                else:
                    st.info("No field-level changes detected.")

        with tab_errors:
            if err_file.exists():
                err_df = pd.read_csv(err_file, dtype=str)
                if not err_df.empty:
                    st.dataframe(err_df, use_container_width=True)
                else:
                    st.info("No validation errors found in this run! 🎉")

        with tab_summary:
            sum_file = result.run_dir / "run_summary.txt"
            if sum_file.exists():
                with open(sum_file, "r", encoding="utf-8") as f:
                    st.text(f.read())

    return has_result


# =========================================================
# STEP 4: REVIEW & INGEST (DOWNLOADS & BULK API 2.0)
# =========================================================

def _render_step_ingest(selected_report: str):
    st.markdown("### 4️⃣ Review, Downloads & Sitetracker Ingest")
    st.caption("Download the strict 5-file output suite or push updates directly to Sitetracker via Bulk API 2.0.")

    result = st.session_state.last_run_result
    if result is None or result.report_name != selected_report:
        st.info("💡 Please execute the Delta Engine in Step 3 before reviewing and downloading output files.")
        return

    # Direct Download Hub
    st.markdown("#### 📥 Standard Output Files Hub")
    st.caption("All files generated following strict Sitetracker data contracts.")

    d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)
    final_file = result.run_dir / "final_input_file.csv"
    render_download_with_confirmation(
        d_col1, "📥 Final Input File", final_file,
        help_text="Ready for upload into Sitetracker", key="ingest_final"
    )

    rb_file = result.run_dir / "rollback_file.csv"
    render_download_with_confirmation(
        d_col2, "🔙 Rollback File", rb_file,
        help_text="Pre-change Sitetracker values to undo this run", key="ingest_rb"
    )

    err_file = result.run_dir / "error_records.csv"
    render_download_with_confirmation(
        d_col3, "🚫 Error Records", err_file,
        help_text="Rejected rows with Salesforce-style error codes", key="ingest_err"
    )

    succ_file = result.run_dir / "success_records.csv"
    render_download_with_confirmation(
        d_col4, "✅ Success Records", succ_file,
        help_text="Rows that passed validation with change summary", key="ingest_succ"
    )

    val_file = result.run_dir / "validation_report.csv"
    render_download_with_confirmation(
        d_col5, "📋 Validation Report", val_file,
        help_text="Full audit trail per row and check", key="ingest_val"
    )

    # Bulk API 2.0 Ingest Gate
    st.markdown("---")
    st.markdown("#### 🚀 Push to Sitetracker (Bulk API 2.0)")
    st.caption("Safely upload the generated delta records directly to Sitetracker asynchronously.")

    from salesforce.auth import get_active_profile, is_token_valid
    active_prof = get_active_profile()
    env_badge = settings.PROFILES.get(active_prof, active_prof)

    if not is_token_valid(profile=active_prof):
        st.warning(f"🔒 You must log in to **{env_badge}** via the **Data Export** page before pushing records to Salesforce.")
        return

    st.info(f"Target Salesforce Org: **{env_badge}**")

    from salesforce.job_manager import (
        get_job_progress,
        clear_job_progress,
        is_job_active,
        start_background_ingest,
    )

    job_info = get_job_progress(result.run_dir)

    if job_info:
        status = job_info.get("status")
        if status == "RUNNING":
            st.markdown("### ⏳ Ingestion in Progress on Server")
            st.info(
                "📱 **Phone Disconnect Safe**: The upload is executing in a detached background worker on the Oracle server. "
                "You can safely close this browser tab, switch apps, or lock your phone. The upload will continue uninterrupted."
            )
            proc_overall = job_info.get("processed_records_overall", 0)
            total_overall = max(1, job_info.get("total_records_overall", 1))
            pct = min(1.0, proc_overall / total_overall)
            curr_obj = job_info.get("current_object", "Salesforce Objects")
            eng_lbl = "⚡ Lightning REST" if job_info.get("engine") == "composite" else "📦 Bulk API 2.0"
            st.progress(pct, text=f"{eng_lbl}: Ingesting {curr_obj} — {proc_overall}/{total_overall} records ({int(pct * 100)}%)")

            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("Processed Records", f"{proc_overall:,} / {total_overall:,}")
            m_col2.metric("Succeeded", f"{job_info.get('successful_records_overall', 0):,}")
            m_col3.metric("Failed", f"{job_info.get('failed_records_overall', 0):,}")
            start_str = job_info.get("start_time")
            if start_str:
                try:
                    s_dt = datetime.fromisoformat(start_str)
                    el_sec = int((datetime.now() - s_dt).total_seconds())
                    m_col4.metric("Elapsed Time", f"{el_sec}s")
                except Exception:
                    m_col4.metric("Elapsed Time", "N/A")

            # Show in-flight chunk evaluation detail if available
            stage = job_info.get("stage", "completed_chunk")
            c_chunk = job_info.get("current_chunk", 0)
            t_chunk = job_info.get("total_chunks", 0)
            r_start = job_info.get("chunk_start", 0)
            r_end = job_info.get("chunk_end", 0)

            if stage == "in_flight" and t_chunk > 0:
                st.markdown(
                    f"""
                    <div style="background:#F0FDF4; border:1px solid #86EFAC; border-radius:6px; padding:10px 14px; margin: 12px 0; font-size:0.9rem; color:#166534; display:flex; align-items:center; gap:8px;">
                        <span>⏳</span>
                        <div><b>Active In-Flight Request:</b> Evaluating Chunk <b>{c_chunk} of {t_chunk}</b> (Records {r_start} to {r_end} on <b>{curr_obj}</b>)<br>
                        <span style="font-size:0.8rem; color:#15803D;">Salesforce Apex triggers & Sitetracker validation rules are evaluating in cloud (~20–40s per chunk)...</span></div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            # Show per-object status badges
            st.markdown("##### 📦 Object Breakdown")
            for obj_name, o_meta in job_info.get("objects", {}).items():
                obj_status = o_meta.get("status", "PENDING")
                status_icon = "⏳" if obj_status == "RUNNING" else ("✅" if "COMPLETED" in obj_status else "○")
                st.caption(f"{status_icon} **{obj_name}**: {obj_status} ({o_meta.get('processed_records', 0)}/{o_meta.get('total_records', 0)} records)")

            col_ref_btn, col_ref_txt = st.columns([1, 3])
            with col_ref_btn:
                if st.button("🔄 Refresh Status", key="btn_manual_refresh_running", type="secondary"):
                    st.rerun()
            with col_ref_txt:
                st.caption("ℹ️ Progress updates automatically every few seconds. Tap Refresh anytime to force a live sync.")

            import time
            time.sleep(3)
            st.rerun()
            return

        elif status in ("COMPLETED", "FAILED"):
            if status == "COMPLETED":
                is_rb = job_info.get("is_rollback", False)
                title = "⏪ Rollback Completed" if is_rb else "🎉 Ingest Completed"
                st.success(f"**{title}**! Processed {job_info.get('processed_records_overall', 0):,} records across {job_info.get('total_objects', 1)} objects.")
                for obj_name, o_meta in job_info.get("objects", {}).items():
                    succ = o_meta.get("successful_records", 0)
                    fail = o_meta.get("failed_records", 0)
                    tot = o_meta.get("total_records", 0)
                    j_id = o_meta.get("job_id") or "N/A"
                    if fail == 0:
                        st.success(f"✅ **{obj_name}**: Successfully processed all {succ:,}/{tot:,} records! (Job: `{j_id}`)")
                    else:
                        st.warning(f"⚠️ **{obj_name}**: {succ:,} succeeded, {fail:,} failed out of {tot:,} records. (Job: `{j_id}`)")
                        if o_meta.get("failures_file"):
                            fail_path = result.run_dir / o_meta["failures_file"]
                            if fail_path.exists():
                                st.error(f"[{obj_name}] Failures saved to `{fail_path.name}`:")
                                fail_df = pd.read_csv(fail_path, dtype=str)
                                st.dataframe(fail_df, use_container_width=True)
            else:
                st.error(f"❌ Ingest job failed on server: {job_info.get('error_summary', 'Unknown error')}")

            if st.button("🔄 Dismiss & Reset for New Ingest", key="btn_clear_job_state", type="primary"):
                clear_job_progress(result.run_dir)
                st.rerun()
            return

    # Allow selecting target object if report has multiple objects
    try:
        loader_ingest = MappingLoader(settings.MAPPING_FILE, selected_report)
        ingest_objects = loader_ingest.objects()
    except Exception:
        ingest_objects = []

    yaml_cfg = YamlConfigLoader.load(selected_report)
    default_obj = yaml_cfg.get("report", {}).get("salesforce_object")
    if not default_obj and ingest_objects:
        default_obj = ingest_objects[0]

    ALL_OBJECTS_OPTION = f"⚡ All Objects (Sequential Ingest: {', '.join(ingest_objects)})"
    if len(ingest_objects) > 1:
        target_options = [ALL_OBJECTS_OPTION] + ingest_objects
        target_obj_push = st.selectbox(
            "Target Salesforce Object for Ingest",
            target_options,
            index=0,
            key="sel_ingest_object_target",
            help="Choose 'All Objects' to upload deltas to both objects automatically, or choose a specific object."
        )
    else:
        target_obj_push = default_obj or "Site__c"

    is_multi_obj_push = (target_obj_push == ALL_OBJECTS_OPTION)

    # Select appropriate payload file for target object
    clean_target = target_obj_push.strip().replace(" ", "_")
    obj_specific_file = result.run_dir / f"final_input_file_{clean_target}.csv"
    active_push_file = obj_specific_file if obj_specific_file.exists() else final_file

    obj_specific_rb = result.run_dir / f"rollback_file_{clean_target}.csv"
    active_rb_file = obj_specific_rb if obj_specific_rb.exists() else rb_file

    # Preview before upload
    if is_multi_obj_push:
        with st.expander(f"📥 Preview Multi-Object Payloads ({len(ingest_objects)} Objects)", expanded=False):
            tab_list = st.tabs([f"📦 {obj}" for obj in ingest_objects])
            for obj, tab in zip(ingest_objects, tab_list):
                with tab:
                    c_target = obj.strip().replace(" ", "_")
                    obj_file = result.run_dir / f"final_input_file_{c_target}.csv"
                    if obj_file.exists():
                        df_obj = pd.read_csv(obj_file, dtype=str, keep_default_na=False)
                        st.caption(f"**{len(df_obj):,}** records ready for **{obj}**")
                        st.dataframe(df_obj, use_container_width=True)
                    else:
                        st.info(f"No dedicated payload file generated for {obj}.")
    elif active_push_file.exists():
        final_push_df = pd.read_csv(active_push_file, dtype=str, keep_default_na=False)
        with st.expander(f"📥 Preview Payload for {target_obj_push} ({len(final_push_df)} Records to be Ingested)", expanded=False):
            st.dataframe(final_push_df, use_container_width=True)

    col_eng, col_batch = st.columns([1.5, 1])
    with col_eng:
        sel_engine = st.radio(
            "🚀 Ingest Engine",
            [
                "⚡ Lightning REST Collections (Fast: ~15s - Recommended for <2,000 records)",
                "📦 Bulk API 2.0 (Asynchronous Queue - For large datasets >2,000 records)"
            ],
            index=0,
            key="sel_ingest_engine",
            help="Lightning REST Collections processes batches in 1-2 seconds per 50 records without queue delay. Bulk API 2.0 uses Salesforce cloud queues."
        )
        engine_key = "composite" if "Lightning" in sel_engine else "bulk2"

    with col_batch:
        bulk_batch_size = st.select_slider(
            "⚡ Apex Batch Size (Records per chunk)",
            options=[5, 10, 15, 25, 50],
            value=15,
            key="sel_bulk_batch_size",
            help="Micro-batching prevents Apex 151 DML limit. Smaller batches (10-15) update progress every 20-30s. Larger batches (50) take ~2 mins per chunk."
        )
        st.caption("ℹ️ **Recommended**: 15 records/chunk provides smooth progress updates every ~30s.")

    col_c1, col_c2 = st.columns([2, 1])
    with col_c1:
        confirm_phrase = st.text_input(
            "Type CONFIRM to enable Ingest",
            placeholder="CONFIRM",
            key="input_confirm_bulk_push_v2"
        )

    with col_c2:
        st.write("")
        st.write("")
        push_enabled = (confirm_phrase.strip() == "CONFIRM")
        btn_label = "🚀 Ingest All Deltas to Sitetracker" if is_multi_obj_push else f"🚀 Ingest Deltas to {target_obj_push}"
        if st.button(btn_label, type="primary", disabled=not push_enabled, key="btn_execute_bulk_push_v2"):
            start_background_ingest(
                run_dir=result.run_dir,
                report_name=selected_report,
                is_rollback=False,
                profile=active_prof,
                batch_size=bulk_batch_size,
                target_object=None if is_multi_obj_push else target_obj_push,
                engine=engine_key,
            )
            st.rerun()

    # Emergency Rollback / Revert Safety Net
    has_rb = is_multi_obj_push or active_rb_file.exists()
    if has_rb:
        with st.expander("⏪ Emergency Rollback Safety Net", expanded=False):
            st.warning("⚠️ **Safety Net**: Revert pre-change values back into Sitetracker to restore records to how they were prior to this run.")
            if is_multi_obj_push:
                rb_tab_list = st.tabs([f"⏪ {obj}" for obj in ingest_objects])
                for obj, tab in zip(ingest_objects, rb_tab_list):
                    with tab:
                        c_target = obj.strip().replace(" ", "_")
                        rb_file_obj = result.run_dir / f"rollback_file_{c_target}.csv"
                        if rb_file_obj.exists():
                            df_rb = pd.read_csv(rb_file_obj, dtype=str)
                            st.caption(f"**{len(df_rb):,}** rollback records ready for **{obj}**")
                            st.dataframe(df_rb, use_container_width=True)
                        else:
                            st.info(f"No rollback records for {obj}.")
            elif active_rb_file.exists():
                rb_df = pd.read_csv(active_rb_file, dtype=str)
                st.dataframe(rb_df, use_container_width=True)

            col_rb1, col_rb2 = st.columns([2, 1])
            with col_rb1:
                confirm_revert = st.text_input(
                    "Type REVERT to enable rollback",
                    placeholder="REVERT",
                    key="input_confirm_bulk_revert_v2"
                )
            with col_rb2:
                st.write("")
                st.write("")
                revert_enabled = (confirm_revert.strip() == "REVERT")
                rb_btn_label = "⏪ Execute Rollback for All Objects" if is_multi_obj_push else f"⏪ Execute Rollback for {target_obj_push}"
                if st.button(rb_btn_label, type="secondary", disabled=not revert_enabled, key="btn_execute_bulk_revert_v2"):
                    start_background_ingest(
                        run_dir=result.run_dir,
                        report_name=selected_report,
                        is_rollback=True,
                        profile=active_prof,
                        batch_size=bulk_batch_size,
                        target_object=None if is_multi_obj_push else target_obj_push,
                        engine=engine_key,
                    )
                    st.rerun()


# =========================================================
# MAIN RENDER FUNCTION
# =========================================================

def render(go):
    apply_slds_theme()
    _init_wizard_state()

    render_header("⚡ Sitetracker Data Ingestion Pipeline", "Dataloader-style guided workflow for field mapping, validation, and Bulk updates")

    reports = YamlConfigLoader.list_reports()
    if not reports:
        st.error(f"No reports configured in `{settings.CONFIG_DIR}`.")
        render_back_button(go)
        render_footer()
        return

    # Render Native Pipeline Stepper
    new_step = render_pipeline_stepper(st.session_state.data_load_step)
    if new_step != st.session_state.data_load_step:
        st.session_state.data_load_step = new_step
        st.rerun()

    current_step = st.session_state.data_load_step

    if current_step == 0:
        has_selection = _render_step_source(reports)
        nav = render_step_navigation(
            current_step=0,
            total_steps=4,
            next_label="Next: Field Mapping ➔",
            next_disabled=not has_selection,
            key_prefix="step0_nav"
        )
        if nav == "next":
            st.session_state.data_load_step = 1
            st.rerun()

    elif current_step == 1:
        if not st.session_state.selected_report:
            st.session_state.data_load_step = 0
            st.rerun()
        _render_step_mapping(st.session_state.selected_report)
        nav = render_step_navigation(
            current_step=1,
            total_steps=4,
            prev_label="⬅ Back: Source Data",
            next_label="Next: Delta Engine ➔",
            next_disabled=not st.session_state.mapping_confirmed,
            key_prefix="step1_nav"
        )
        if nav == "prev":
            st.session_state.data_load_step = 0
            st.rerun()
        elif nav == "next":
            st.session_state.data_load_step = 2
            st.rerun()

    elif current_step == 2:
        if not st.session_state.selected_report:
            st.session_state.data_load_step = 0
            st.rerun()
        has_result = _render_step_delta(st.session_state.selected_report)
        nav = render_step_navigation(
            current_step=2,
            total_steps=4,
            prev_label="⬅ Back: Field Mapping",
            next_label="Next: Review & Ingest ➔",
            next_disabled=not has_result,
            key_prefix="step2_nav"
        )
        if nav == "prev":
            st.session_state.data_load_step = 1
            st.rerun()
        elif nav == "next":
            st.session_state.data_load_step = 3
            st.rerun()

    elif current_step == 3:
        if not st.session_state.selected_report:
            st.session_state.data_load_step = 0
            st.rerun()
        _render_step_ingest(st.session_state.selected_report)
        nav = render_step_navigation(
            current_step=3,
            total_steps=4,
            prev_label="⬅ Back: Delta Engine",
            key_prefix="step3_nav"
        )
        if nav == "prev":
            st.session_state.data_load_step = 2
            st.rerun()

    # Home Navigation & Footer
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    render_back_button(go, label="🏠 Return to Home Hub")
    render_footer()