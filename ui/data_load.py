"""Streamlit UI page for Data Load / Input File Generation with Dataloader.io guided pipeline."""

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

    from salesforce.auth import get_active_profile, is_token_valid
    active_prof = get_active_profile()
    is_auth = is_token_valid(profile=active_prof)
    env_label = "Developer Sandbox" if active_prof == "sandbox" else "Production Org"
    env_color = "amber" if active_prof == "sandbox" else "blue"

    with col_env:
        st.markdown(
            f"""
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; margin-top:24px;">
                <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase;">Connected Org</div>
                <div style="font-weight:700; color:#032D60; font-size:0.95rem; display:flex; align-items:center; gap:6px; margin-top:2px;">
                    {render_pill(env_label, env_color)}
                    {'<span style="color:#04844B; font-size:0.8rem; font-weight:600;">● Online</span>' if is_auth else '<span style="color:#EA001E; font-size:0.8rem; font-weight:600;">● Disconnected</span>'}
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
        if src_files:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill(f'Found: {src_files[0]}', 'green')}</div>", unsafe_allow_html=True)
            with st.expander(f"👁️ Preview Source Data ({src_files[0]})", expanded=False):
                try:
                    sf_path = src_dir / src_files[0]
                    src_view_df = _read_excel_preview(sf_path) if sf_path.suffix.lower() == ".xlsx" else _read_csv_preview(sf_path)
                    st.caption(f"📁 {len(src_view_df):,} rows • {len(src_view_df.columns)} columns")
                    st.dataframe(src_view_df.head(100), use_container_width=True)
                except Exception as e:
                    st.error(f"Could not load source file: {e}")
        else:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill('Missing source file', 'amber')}</div>", unsafe_allow_html=True)
            st.caption(f"Place input file in: `{src_dir.relative_to(settings.PROJECT_ROOT)}`")
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
        if st_files:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill(f'Found: {st_files[0]}', 'green')}</div>", unsafe_allow_html=True)
            with st.expander(f"👁️ Preview Sitetracker Data ({st_files[0]})", expanded=False):
                try:
                    st_view_df = _read_csv_preview(st_dir / st_files[0])
                    st.caption(f"📁 {len(st_view_df):,} rows • {len(st_view_df.columns)} columns")
                    st.dataframe(st_view_df.head(100), use_container_width=True)
                except Exception as e:
                    st.error(f"Could not load Sitetracker baseline: {e}")
        else:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill('Missing baseline file', 'amber')}</div>", unsafe_allow_html=True)
            st.caption(f"Place file in: `{st_dir.relative_to(settings.PROJECT_ROOT)}`")

        if is_auth:
            if len(report_objects) > 1:
                fetch_obj = st.selectbox(
                    "Target Object for SOQL Query",
                    report_objects,
                    key="sel_fetch_soql_obj",
                    help="Select which Salesforce object to query records from."
                )
                btn_fetch_label = f"🔄 Fetch Live {fetch_obj} Records (SOQL)"
            else:
                fetch_obj = report_objects[0] if report_objects else None
                btn_fetch_label = "🔄 Fetch Live Data from Sitetracker (SOQL)"

            if st.button(btn_fetch_label, key="btn_fetch_live_st", type="primary"):
                with st.spinner(f"Executing SOQL query against {env_label}..."):
                    try:
                        from salesforce.data_fetcher import fetch_sitetracker_data
                        saved_csv = fetch_sitetracker_data(selected_report, st_dir, target_object=fetch_obj)
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
    env_badge = "🧪 Developer Sandbox" if active_prof == "sandbox" else "🏢 Production"

    if not is_token_valid(profile=active_prof):
        st.warning(f"🔒 You must log in to **{env_badge}** via the **Data Export** page before pushing records to Salesforce.")
        return

    st.info(f"Target Salesforce Org: **{env_badge}**")

    # Preview before upload
    if final_file.exists():
        final_push_df = pd.read_csv(final_file, dtype=str, keep_default_na=False)
        with st.expander(f"📥 Preview Payload ({len(final_push_df)} Records to be Ingested)", expanded=False):
            st.dataframe(final_push_df, use_container_width=True)

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

    if len(ingest_objects) > 1:
        target_obj_push = st.selectbox(
            "Target Salesforce Object for Bulk API Ingest",
            ingest_objects,
            key="sel_ingest_object_target",
            help="Select which Salesforce object to update with the delta payload."
        )
    else:
        target_obj_push = default_obj or "Site__c"

    col_c1, col_c2 = st.columns([2, 1])
    with col_c1:
        confirm_phrase = st.text_input(
            "Type CONFIRM to enable Bulk API 2.0 Ingest",
            placeholder="CONFIRM",
            key="input_confirm_bulk_push_v2"
        )

    with col_c2:
        st.write("")
        st.write("")
        push_enabled = (confirm_phrase.strip() == "CONFIRM")
        if st.button("🚀 Ingest Deltas to Sitetracker", type="primary", disabled=not push_enabled, key="btn_execute_bulk_push_v2"):
            with st.spinner(f"Submitting Bulk API 2.0 ingest job to Salesforce for {target_obj_push}..."):
                try:
                    from salesforce.bulk_uploader import push_delta_to_sitetracker
                    bulk_res = push_delta_to_sitetracker(
                        csv_path=final_file,
                        object_name=target_obj_push,
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
    if rb_file.exists():
        with st.expander("⏪ Emergency Rollback Safety Net", expanded=False):
            st.warning("⚠️ **Safety Net**: Revert pre-change values back into Sitetracker to restore records to how they were prior to this run.")
            rb_df = pd.read_csv(rb_file, dtype=str)
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
                if st.button("⏪ Execute Rollback in Sitetracker", type="secondary", disabled=not revert_enabled, key="btn_execute_bulk_revert_v2"):
                    with st.spinner("Submitting Rollback job to Salesforce Bulk API 2.0..."):
                        try:
                            from salesforce.bulk_uploader import push_delta_to_sitetracker
                            yaml_cfg = YamlConfigLoader.load(selected_report)
                            obj_name = yaml_cfg.get("report", {}).get("salesforce_object") or "Site__c"

                            rb_res = push_delta_to_sitetracker(
                                csv_path=rb_file,
                                object_name=obj_name,
                                report_name=selected_report,
                                operation="update"
                            )
                            if rb_res.all_succeeded:
                                st.success(f"⏪ Rollback successful! All {rb_res.successful_records} records reverted to previous state. (Job ID: `{rb_res.job_id}`)")
                            else:
                                st.warning(f"⚠️ Revert processed with {rb_res.failed_records} errors.")
                        except Exception as e:
                            st.error(f"Rollback failed: {e}")


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