"""Manual / Ad-Hoc Dataloader UI Module (Dataloader.io Mode).

Allows users to upload any CSV or Excel file, select any Salesforce/Sitetracker object,
configure primary keys, auto-match and customize field mappings, review deltas,
and push updates directly via Salesforce Bulk API 2.0 with 1-click rollback.
"""

from datetime import datetime
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import time
from typing import Any
import pandas as pd
import streamlit as st

from config import settings
from core.exceptions import PrimaryKeyNotFoundError, SalesforceAPIError, SalesforceAuthError
from core.manual_engine import (
    AdhocEngineConfig,
    AdhocFieldMapping,
    AdhocRunResult,
    ManualLoadEngine,
    MappingProfile,
    MappingStatus,
    OperationType,
    detect_salesforce_duplicates,
    detect_source_duplicates,
    detect_target_object,
    detect_unmatched_records,
    normalize_header,
    resolve_pk_from_mapping,
    suggest_field_mappings,
)
from core.normalizer import DataNormalizer
from salesforce.adhoc_fetcher import (
    fetch_adhoc_live_data,
    fetch_all_objects,
    fetch_object_fields,
    is_valid_salesforce_id,
)
from salesforce.auth import check_connection_status, get_active_profile, is_token_valid
from salesforce.job_manager import (
    clear_job_progress,
    get_job_progress,
    is_job_active,
    start_background_ingest,
)
from ui.styles import render_kpi_card, render_pill

logger = logging.getLogger(__name__)


def _format_ist_time(timestamp: float | None = None) -> str:
    """Format a timestamp into UK date + IST time (DD/MM/YYYY HH:MM:SS IST)."""
    if timestamp is None:
        dt = datetime.now()
    else:
        dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%d/%m/%Y %H:%M:%S IST")


def _invalidate_validation_cache():
    """Reset validation state and confirmation when configuration changes."""
    st.session_state.adhoc_unmatched_confirmed = False
    st.session_state.adhoc_live_df = None
    st.session_state.adhoc_run_result = None
    st.session_state.adhoc_bulk_result = None
    st.session_state.adhoc_sf_duplicates_df = None
    st.session_state.adhoc_unmatched_list = []


def _init_manual_state():
    """Ensure session state variables for manual dataloader are initialized."""
    if "adhoc_step" not in st.session_state:
        st.session_state.adhoc_step = 0
    if "adhoc_operation" not in st.session_state:
        st.session_state.adhoc_operation = OperationType.UPDATE
    if "adhoc_source_df" not in st.session_state:
        st.session_state.adhoc_source_df = None
    if "adhoc_source_filename" not in st.session_state:
        st.session_state.adhoc_source_filename = ""
    if "adhoc_objects" not in st.session_state:
        st.session_state.adhoc_objects = []
    if "adhoc_selected_obj" not in st.session_state:
        st.session_state.adhoc_selected_obj = ""
    if "adhoc_source_pk" not in st.session_state:
        st.session_state.adhoc_source_pk = ""
    if "adhoc_target_pk" not in st.session_state:
        st.session_state.adhoc_target_pk = ""
    if "adhoc_fields" not in st.session_state:
        st.session_state.adhoc_fields = []
    if "adhoc_mappings" not in st.session_state:
        st.session_state.adhoc_mappings = []
    if "adhoc_insert_nulls" not in st.session_state:
        st.session_state.adhoc_insert_nulls = False
    if "adhoc_live_df" not in st.session_state:
        st.session_state.adhoc_live_df = None
    if "adhoc_run_result" not in st.session_state:
        st.session_state.adhoc_run_result = None
    if "adhoc_bulk_result" not in st.session_state:
        st.session_state.adhoc_bulk_result = None
    if "adhoc_unmatched_confirmed" not in st.session_state:
        st.session_state.adhoc_unmatched_confirmed = False
    if "adhoc_profile_name" not in st.session_state:
        st.session_state.adhoc_profile_name = ""
    if "adhoc_sf_duplicates_df" not in st.session_state:
        st.session_state.adhoc_sf_duplicates_df = None
    if "adhoc_unmatched_list" not in st.session_state:
        st.session_state.adhoc_unmatched_list = []


def _safe_read_csv(path: Path | str | None, **kwargs) -> pd.DataFrame:
    """Safely read a CSV file, returning an empty DataFrame if empty or missing."""
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        if p.stat().st_size == 0:
            return pd.DataFrame()
    except Exception:
        pass

    csv_kwargs = {
        "dtype": str,
        "keep_default_na": False,
        "encoding": "utf-8",
        "on_bad_lines": "skip",
    }
    csv_kwargs.update(kwargs)

    try:
        return pd.read_csv(p, **csv_kwargs)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except UnicodeDecodeError:
        try:
            csv_kwargs["encoding"] = "latin1"
            csv_kwargs["engine"] = "python"
            return pd.read_csv(p, **csv_kwargs)
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()



def render(go_fn):
    """Main entry point for Manual Dataloader module."""
    _init_manual_state()

    # Top Navigation Bar
    col_nav, col_env = st.columns([3, 1])
    with col_nav:
        st.button("⬅ Back to Home", on_click=go_fn, args=("home",), key="adhoc_btn_home")
        st.title("⚡ Ad-Hoc Object Ingestion & Mapping")
        st.caption("Dynamic Schema Synchronization • Upload custom CSV/Excel, dynamically map Sitetracker object schemas, validate field deltas, and synchronize updates safely.")

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

    with col_env:
        label = "Connected" if status_label in ("Connected", "Connected (Cached)") else status_label
        status_dot = f"● {label}" if is_auth else f"● {status_label}"
        if is_auth:
            status_color = "#04844B"
        elif status_label == "Disconnected":
            status_color = "#64748B"
        elif status_label == "Offline":
            status_color = "#D97706"
        else:
            status_color = "#EA001E"
        st.markdown(
            f"""
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; text-align:right;">
                <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase;">Connected Org</div>
                <div style="font-weight:700; color:#032D60; font-size:0.9rem; display:flex; justify-content:flex-end; align-items:center; gap:6px; margin-top:2px;">
                    {render_pill(env_label, env_color)}
                    <span style="color:{status_color}; font-size:0.8rem; font-weight:600;">{status_dot}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

    # 4-Step Tracker
    steps = [
        "1. Object & Upload",
        "2. Mapping Profile & Match Key",
        "3. Validate & Confirm",
        "4. Results & Downloads",
    ]
    cur_step = st.session_state.adhoc_step

    step_cols = st.columns(4)
    for idx, (col, title) in enumerate(zip(step_cols, steps)):
        with col:
            if idx == cur_step:
                st.markdown(f"**🔷 {title}**")
                st.markdown("<div style='height:4px; background:#0176D3; border-radius:2px;'></div>", unsafe_allow_html=True)
            elif idx < cur_step:
                st.markdown(f"✅ {title}")
                st.markdown("<div style='height:4px; background:#04844B; border-radius:2px;'></div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<span style='color:#94A3B8;'>⚪ {title}</span>", unsafe_allow_html=True)
                st.markdown("<div style='height:4px; background:#E2E8F0; border-radius:2px;'></div>", unsafe_allow_html=True)

    st.markdown("---")

    # 4-Screen Router
    if cur_step == 0:
        _render_screen_1_upload()
    elif cur_step == 1:
        _render_screen_2_mapping()
    elif cur_step == 2:
        _render_screen_3_validation()
    elif cur_step == 3:
        _render_screen_4_results()


# ==============================================================================
# SCREEN 1: TARGET OBJECT & FILE UPLOAD
# ==============================================================================

def _render_screen_1_upload():
    st.markdown("### 1️⃣ Target Object & File Upload")
    st.caption("Select your target Salesforce object and upload your source data spreadsheet (.csv, .xlsx, or .xls).")

    try:
        from pathlib import Path
        from core import job_store
        from salesforce.job_manager import is_job_active
        job_store.init_db()
        for aj in job_store.get_active_jobs():
            if is_job_active(Path(aj["run_dir"])):
                st.info(f"⚡ **Active Ingest in Progress**: A background upload for **{aj['report_name']}** is running on the server.")
                if st.button("👁️ Re-attach to Live Progress ➔", key=f"reattach_ml_{aj['id']}", type="primary"):
                    st.session_state.active_monitor_job_id = aj["id"]
                    st.session_state.page = "live_monitor"
                    st.rerun()
                break
    except Exception:
        pass

    active_prof = get_active_profile()

    if not is_token_valid(profile=active_prof):
        st.error(f"Not authenticated with Salesforce ({active_prof}). Please log in via the Data Export page first.")
        return

    # 1. Discover Objects from Salesforce
    if not st.session_state.adhoc_objects:
        with st.spinner("Connecting to Salesforce and querying available objects..."):
            try:
                st.session_state.adhoc_objects = fetch_all_objects(profile=active_prof)
            except Exception as e:
                st.error(f"Failed to discover Salesforce objects: {e}")
                return

    all_objs = st.session_state.adhoc_objects
    if not all_objs:
        st.error("No updateable objects found in this Salesforce org.")
        return

    # Target Object Selection
    col_cat, col_obj = st.columns([1, 2])
    with col_cat:
        filter_category = st.selectbox(
            "Category Filter:",
            ["All Objects", "Sitetracker (*__c)", "Custom Objects (*__c)", "Standard Objects"],
            key="adhoc_cat_filter",
            help="Filter objects by Salesforce classification",
        )

    if filter_category == "Sitetracker (*__c)":
        filtered_objs = [o for o in all_objs if o["category"] == "Sitetracker"]
    elif filter_category == "Custom Objects (*__c)":
        filtered_objs = [o for o in all_objs if o["category"] in ("Sitetracker", "Custom")]
    elif filter_category == "Standard Objects":
        filtered_objs = [o for o in all_objs if o["category"] == "Standard"]
    else:
        filtered_objs = all_objs

    obj_display_map = {f"{o['label']} ({o['name']})": o["name"] for o in filtered_objs}
    if not obj_display_map:
        filtered_objs = all_objs
        obj_display_map = {f"{o['label']} ({o['name']})": o["name"] for o in filtered_objs}

    default_idx = 0
    if st.session_state.adhoc_selected_obj:
        for idx, (k, v) in enumerate(obj_display_map.items()):
            if v == st.session_state.adhoc_selected_obj:
                default_idx = idx
                break

    with col_obj:
        selected_display = st.selectbox(
            f"Select Target Object ({len(filtered_objs)} available):",
            list(obj_display_map.keys()),
            index=default_idx,
            help="Type to search and select the Salesforce object to update.",
        )
    chosen_obj = obj_display_map[selected_display]
    if chosen_obj != st.session_state.adhoc_selected_obj:
        st.session_state.adhoc_selected_obj = chosen_obj
        st.session_state.adhoc_fields = []
        _invalidate_validation_cache()

    # Discover Fields on the Selected Object
    if not st.session_state.adhoc_fields or st.session_state.get("_last_loaded_obj") != chosen_obj:
        with st.spinner(f"Inspecting fields on '{chosen_obj}'..."):
            try:
                st.session_state.adhoc_fields = fetch_object_fields(chosen_obj, profile=active_prof)
                st.session_state._last_loaded_obj = chosen_obj
            except Exception as e:
                st.error(f"Failed to inspect fields on '{chosen_obj}': {e}")
                return

    # 2. Operation Selection
    st.markdown("#### ⚙️ Operation")
    op_col1, op_col2 = st.columns([1, 2])
    with op_col1:
        st.radio(
            "Select Operation:",
            ["Update (Active)", "Insert (Upcoming)"],
            index=0,
            key="adhoc_op_radio",
            help="Update is currently active. Insert operation will be available in an upcoming release.",
        )
        st.session_state.adhoc_operation = OperationType.UPDATE
    with op_col2:
        st.caption("ℹ️ **Update**: Queries matching records in Salesforce via your designated Match Key, calculates deltas, and updates modified fields using the record's resolved Salesforce `Id`.")

    # 3. File Upload
    st.markdown("#### 📁 Upload Source Spreadsheet")
    st.caption("Supports CSV and Excel files. String identifiers with leading zeroes (e.g. `00120`, `01040`) are preserved strictly.")

    uploaded_file = st.file_uploader(
        "Drop CSV or Excel file here:",
        type=["csv", "xlsx", "xls"],
        key="adhoc_source_file_uploader",
    )

    if uploaded_file is not None:
        if st.session_state.adhoc_source_filename != uploaded_file.name:
            try:
                with st.spinner("Reading spreadsheet..."):
                    df = DataNormalizer.read_spreadsheet(uploaded_file)
                st.session_state.adhoc_source_df = df
                st.session_state.adhoc_source_filename = uploaded_file.name
                _invalidate_validation_cache()
                st.success(f"Loaded `{uploaded_file.name}`: **{len(df):,} rows**, **{len(df.columns)} columns**.")
            except Exception as e:
                st.error(f"Failed to read spreadsheet: {e}")
                st.session_state.adhoc_source_df = None
                return

    src_df = st.session_state.adhoc_source_df
    if src_df is not None:
        st.info("💡 **File Size Guidance**: Recommended file size is up to 200 MB (~100,000 rows) for optimal browser responsiveness. Datasets under 2,000 records execute in 15–30 seconds via REST Collections.")

        with st.expander(f"👁️ Data Preview: `{st.session_state.adhoc_source_filename}` (First 100 rows)", expanded=False):
            st.dataframe(src_df.head(100), use_container_width=True)

        if src_df.empty:
            st.warning("Uploaded file contains no data rows.")
            return

    # Navigation Button
    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    can_proceed = bool(chosen_obj and src_df is not None and not src_df.empty)
    if st.button("Next: Mapping Profile & Match Key ➔", type="primary", use_container_width=True, disabled=not can_proceed):
        st.session_state.adhoc_step = 1
        st.rerun()


# ==============================================================================
# SCREEN 2: MAPPING PROFILE & MATCH KEY SELECTION
# ==============================================================================

def _render_screen_2_mapping():
    st.markdown("### 2️⃣ Mapping Profile & Match Key Selection")
    st.caption("Configure how spreadsheet columns map to Salesforce fields and designate the unique Match Key.")

    src_df = st.session_state.adhoc_source_df
    obj_name = st.session_state.adhoc_selected_obj
    sf_fields = st.session_state.adhoc_fields

    if src_df is None or not obj_name:
        st.warning("Please upload a file and select an object in Step 1 first.")
        if st.button("⬅ Back to Step 1"):
            st.session_state.adhoc_step = 0
            st.rerun()
        return

    src_columns = list(src_df.columns)

    # 1. Profile Management Toolbar
    st.markdown("#### 📋 Profile & Auto-Mapping")
    prof_col1, prof_col2 = st.columns([1, 1])

    with prof_col1:
        if st.button("⚡ Auto-Map from Mapping_file.xlsx", use_container_width=True, help="Load authoritative field definitions and primary key from Mapping_file.xlsx"):
            # Authoritative PK resolution
            pk_res = resolve_pk_from_mapping(obj_name, src_columns)
            if pk_res:
                st.session_state.adhoc_source_pk, st.session_state.adhoc_target_pk = pk_res
                st.toast(f"Authoritatively resolved Match Key: {pk_res[0]} ➔ {pk_res[1]}")
            else:
                st.toast("No authoritative primary key configured for this object in Mapping_file.xlsx. Please select manually below.")

            st.session_state.adhoc_mappings = suggest_field_mappings(
                source_columns=src_columns,
                sf_fields=sf_fields,
                source_pk_col=st.session_state.adhoc_source_pk,
                target_pk_field=st.session_state.adhoc_target_pk,
                object_name=obj_name,
            )
            _invalidate_validation_cache()
            st.rerun()

    with prof_col2:
        # Scan saved profiles in data/mapping_profiles/
        prof_dir = getattr(settings, "MAPPING_PROFILES_DIR", settings.DATA_DIR / "mapping_profiles")
        saved_files = sorted(prof_dir.glob("*.json")) if prof_dir.exists() else []
        prof_options = ["-- Select Saved Profile --"] + [f.stem for f in saved_files]

        sel_saved = st.selectbox("Load Saved Profile:", prof_options, label_visibility="collapsed", key="sel_saved_prof")
        if sel_saved != "-- Select Saved Profile --":
            target_path = prof_dir / f"{sel_saved}.json"
            if target_path.exists():
                try:
                    loaded_prof = MappingProfile.load_from_file(target_path)
                    compat = loaded_prof.check_compatibility(src_columns)
                    if compat["missing"]:
                        st.warning(f"⚠️ Profile expects columns missing from this file: `{', '.join(compat['missing'])}`")
                    if compat["extra"]:
                        st.info(f"ℹ️ File contains columns not defined in profile: `{', '.join(compat['extra'])}`")

                    st.session_state.adhoc_source_pk = loaded_prof.source_pk_col
                    st.session_state.adhoc_target_pk = loaded_prof.target_pk_field
                    st.session_state.adhoc_mappings = loaded_prof.mappings
                    st.session_state.adhoc_insert_nulls = loaded_prof.insert_nulls
                    _invalidate_validation_cache()
                    st.success(f"Loaded profile: `{sel_saved}`")
                except Exception as e:
                    st.error(f"Error loading profile: {e}")

    # Profile Save / Export / Import Accordion
    with st.expander("💾 Save / Export / Import Mapping Profiles", expanded=False):
        save_col, exp_col, imp_col = st.columns(3)
        with save_col:
            new_prof_name = st.text_input("Save Current Profile As:", placeholder="e.g. MasterSite_Update_v1")
            if st.button("Save Profile", disabled=not new_prof_name):
                prof = MappingProfile(
                    profile_name=new_prof_name,
                    object_name=obj_name,
                    operation=st.session_state.adhoc_operation,
                    source_pk_col=st.session_state.adhoc_source_pk,
                    target_pk_field=st.session_state.adhoc_target_pk,
                    mappings=st.session_state.adhoc_mappings,
                    insert_nulls=st.session_state.adhoc_insert_nulls,
                )
                try:
                    saved_p = prof.save_to_file()
                    st.success(f"Saved to `{saved_p.name}`!")
                except Exception as e:
                    st.error(f"Save failed: {e}")

        with exp_col:
            st.write("Export Profile (.json)")
            curr_prof = MappingProfile(
                profile_name=st.session_state.adhoc_profile_name or f"{obj_name}_mapping",
                object_name=obj_name,
                operation=st.session_state.adhoc_operation,
                source_pk_col=st.session_state.adhoc_source_pk,
                target_pk_field=st.session_state.adhoc_target_pk,
                mappings=st.session_state.adhoc_mappings,
                insert_nulls=st.session_state.adhoc_insert_nulls,
            )
            prof_json = json.dumps(curr_prof.to_dict(), indent=2)
            st.download_button("📥 Download JSON", prof_json, file_name=f"{obj_name}_mapping_profile.json", mime="application/json")

        with imp_col:
            st.write("Import Profile (.json)")
            imp_file = st.file_uploader("Upload Profile JSON:", type=["json"], key="adhoc_imp_prof")
            if imp_file is not None:
                try:
                    imp_data = json.loads(imp_file.read().decode("utf-8"))
                    imported = MappingProfile.from_dict(imp_data)
                    st.session_state.adhoc_source_pk = imported.source_pk_col
                    st.session_state.adhoc_target_pk = imported.target_pk_field
                    st.session_state.adhoc_mappings = imported.mappings
                    st.session_state.adhoc_insert_nulls = imported.insert_nulls
                    _invalidate_validation_cache()
                    st.success("Imported profile successfully!")
                except Exception as e:
                    st.error(f"Import failed: {e}")

    # 2. Match Key Selection Section
    st.markdown("---")
    st.markdown("#### 🔑 Match Key Designation (Primary Key)")
    st.caption("Select which spreadsheet column and Salesforce field uniquely identify records. If unmapped, select manually.")

    col_src_pk, col_sf_pk = st.columns(2)

    # Initial resolution if not yet set
    if not st.session_state.adhoc_source_pk or not st.session_state.adhoc_target_pk:
        pk_res = resolve_pk_from_mapping(obj_name, src_columns)
        if pk_res:
            st.session_state.adhoc_source_pk, st.session_state.adhoc_target_pk = pk_res

    src_pk_idx = src_columns.index(st.session_state.adhoc_source_pk) if st.session_state.adhoc_source_pk in src_columns else 0
    with col_src_pk:
        selected_src_pk = st.selectbox(
            "Source Column (Spreadsheet Identifier):",
            src_columns,
            index=src_pk_idx,
            help="Column in your uploaded file that holds unique record keys.",
        )
        if selected_src_pk != st.session_state.adhoc_source_pk:
            st.session_state.adhoc_source_pk = selected_src_pk
            _invalidate_validation_cache()

    # Target SF field selection
    sf_display_map = {
        f"{f['api_name']} ({f['label']})" + (" [External ID]" if f["is_external_id"] else ""): f["api_name"]
        for f in sf_fields
    }
    sf_pk_idx = 0
    if st.session_state.adhoc_target_pk:
        for idx, (disp, api) in enumerate(sf_display_map.items()):
            if api == st.session_state.adhoc_target_pk:
                sf_pk_idx = idx
                break

    with col_sf_pk:
        selected_sf_disp = st.selectbox(
            "Salesforce Match Field:",
            list(sf_display_map.keys()),
            index=sf_pk_idx,
            help="Salesforce field used for matching records (e.g. Name, Site_ID__c, Id).",
        )
        selected_sf_pk = sf_display_map[selected_sf_disp]
        if selected_sf_pk != st.session_state.adhoc_target_pk:
            st.session_state.adhoc_target_pk = selected_sf_pk
            _invalidate_validation_cache()

    # Source Duplicate Check (First Occurrence Wins)
    if selected_src_pk:
        _, dup_source_df = detect_source_duplicates(src_df, selected_src_pk)
        if not dup_source_df.empty:
            st.warning(
                f"⚠️ **Found {len(dup_source_df):,} duplicate row(s)** for Match Key `{selected_src_pk}`.\n\n"
                f"**First Occurrence Wins**: The first row for each key will be updated. The {len(dup_source_df):,} duplicate rows will be quarantined to `duplicate_primary_keys.csv` for audit."
            )
            with st.expander(f"🔍 Inspect {len(dup_source_df):,} Quarantined Duplicate Source Rows", expanded=False):
                st.dataframe(dup_source_df.head(50), use_container_width=True)

    # 3. Interactive Field Mapping Grid
    st.markdown("---")
    st.markdown("#### 🗺️ Field Mappings")

    # Generate initial suggestions if empty
    if not st.session_state.adhoc_mappings:
        st.session_state.adhoc_mappings = suggest_field_mappings(
            source_columns=src_columns,
            sf_fields=sf_fields,
            source_pk_col=selected_src_pk,
            target_pk_field=selected_sf_pk,
            object_name=obj_name,
        )

    mappings = st.session_state.adhoc_mappings

    # Bulk Select / Deselect & Null toggle
    col_bulk, col_null = st.columns([1.5, 1])
    with col_bulk:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("☑️ Select All Mapped", use_container_width=True):
                for m in mappings:
                    if m.source_column != selected_src_pk and m.target_field_api and m.target_field_api.lower() != "id":
                        m.upload_enabled = True
                _invalidate_validation_cache()
                st.rerun()
        with b2:
            if st.button("⬜ Deselect All", use_container_width=True):
                for m in mappings:
                    m.upload_enabled = False
                _invalidate_validation_cache()
                st.rerun()

    with col_null:
        insert_nulls = st.checkbox(
            "Overwrite cloud values with null/blank (#N/A)",
            value=st.session_state.adhoc_insert_nulls,
            help="When checked, blank cells in the spreadsheet will clear existing Salesforce data. Safe default is unchecked (blanks are ignored).",
        )
        if insert_nulls != st.session_state.adhoc_insert_nulls:
            st.session_state.adhoc_insert_nulls = insert_nulls
            _invalidate_validation_cache()

    # Field selector options
    sf_field_options = ["-- Do Not Map --"] + [f"{f['api_name']} ({f['label']})" for f in sf_fields]
    api_lookup = {f"{f['api_name']} ({f['label']})": f["api_name"] for f in sf_fields}
    label_lookup = {f["api_name"]: f["label"] for f in sf_fields}
    dtype_lookup = {f["api_name"]: f["data_type"] for f in sf_fields}

    # Header Row
    st.markdown(
        """
        <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:8px 12px; margin-bottom:8px; font-weight:700; color:#475569; font-size:0.85rem; display:grid; grid-template-columns: 50px 2fr 3fr 1.2fr 1.5fr;">
            <div>Upload</div>
            <div>Source Column</div>
            <div>Target Salesforce Field</div>
            <div>Data Type</div>
            <div>Status</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    for idx, m in enumerate(mappings):
        is_pk = (m.source_column == selected_src_pk or m.target_field_api == selected_sf_pk)
        is_id_field = (m.target_field_api.lower() == "id")

        cols = st.columns([0.5, 2, 3, 1.2, 1.5])

        # 1. Upload Toggle Checkbox
        with cols[0]:
            if is_pk or is_id_field:
                st.markdown("<div style='margin-top:8px; color:#94A3B8;'>🔒</div>", unsafe_allow_html=True)
            else:
                checked = st.checkbox(
                    f"Enable {m.source_column}",
                    value=m.upload_enabled,
                    key=f"chk_en_{idx}_{m.source_column}",
                    label_visibility="collapsed",
                )
                if checked != m.upload_enabled:
                    m.upload_enabled = checked
                    _invalidate_validation_cache()

        # 2. Source Column Name
        with cols[1]:
            st.markdown(f"<div style='margin-top:6px; font-weight:600; color:#032D60;'><code>{m.source_column}</code></div>", unsafe_allow_html=True)

        # 3. Target Salesforce Field Selector
        with cols[2]:
            cur_disp = "-- Do Not Map --"
            if m.target_field_api:
                for opt in sf_field_options:
                    if opt.startswith(f"{m.target_field_api} (") or opt == m.target_field_api:
                        cur_disp = opt
                        break
            default_opt_idx = sf_field_options.index(cur_disp) if cur_disp in sf_field_options else 0
            sel_field = st.selectbox(
                f"SF Field for {m.source_column}",
                sf_field_options,
                index=default_opt_idx,
                key=f"sel_field_{idx}_{m.source_column}",
                label_visibility="collapsed",
            )
            if sel_field != "-- Do Not Map --":
                chosen_api = api_lookup.get(sel_field, sel_field.split(" ")[0])
                if chosen_api != m.target_field_api:
                    m.target_field_api = chosen_api
                    m.target_field_label = label_lookup.get(chosen_api, chosen_api)
                    m.data_type = dtype_lookup.get(chosen_api, "text")
                    if chosen_api.lower() != "id" and not is_pk:
                        m.upload_enabled = True
                    _invalidate_validation_cache()
            else:
                if m.target_field_api:
                    m.target_field_api = ""
                    m.target_field_label = ""
                    m.upload_enabled = False
                    _invalidate_validation_cache()

        # 4. Data Type Badge
        with cols[3]:
            if m.target_field_api:
                actual_dtype = dtype_lookup.get(m.target_field_api, m.data_type or "text")
                dtype_upper = actual_dtype.upper()
                if actual_dtype == "date":
                    st.markdown(f"<div style='margin-top:6px;'><span style='background:#EFF6FF; color:#1D4ED8; border:1px solid #BFDBFE; padding:3px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;'>📅 {dtype_upper}</span></div>", unsafe_allow_html=True)
                elif actual_dtype in ("number", "currency", "percent"):
                    st.markdown(f"<div style='margin-top:6px;'><span style='background:#FFFBEB; color:#B45309; border:1px solid #FDE68A; padding:3px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;'>🔢 {dtype_upper}</span></div>", unsafe_allow_html=True)
                elif actual_dtype == "boolean":
                    st.markdown(f"<div style='margin-top:6px;'><span style='background:#FAF5FF; color:#7E22CE; border:1px solid #E9D5FF; padding:3px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;'>🔘 {dtype_upper}</span></div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='margin-top:6px;'><span style='background:#F1F5F9; color:#475569; border:1px solid #CBD5E1; padding:3px 8px; border-radius:12px; font-size:0.75rem; font-weight:700;'>🔤 {dtype_upper}</span></div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:8px; color:#94A3B8;'>—</div>", unsafe_allow_html=True)

        # 5. Status Badge
        with cols[4]:
            if is_pk:
                st.markdown("<div style='margin-top:6px;'>" + render_pill("Match Key", "blue") + "</div>", unsafe_allow_html=True)
            elif is_id_field:
                st.markdown("<div style='margin-top:6px;'>" + render_pill("Record ID (Read Only)", "gray") + "</div>", unsafe_allow_html=True)
            elif m.target_field_api and m.upload_enabled:
                st.markdown("<div style='margin-top:6px;'>" + render_pill("Mapped", "green") + "</div>", unsafe_allow_html=True)
            elif m.target_field_api and not m.upload_enabled:
                st.markdown("<div style='margin-top:6px;'>" + render_pill("Ignored", "gray") + "</div>", unsafe_allow_html=True)
            else:
                st.markdown("<div style='margin-top:6px;'>" + render_pill("Unmapped", "gray") + "</div>", unsafe_allow_html=True)

    # Navigation Buttons
    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    nav_back, nav_next = st.columns([1, 2])
    with nav_back:
        if st.button("⬅ Back to Object & Upload", use_container_width=True):
            st.session_state.adhoc_step = 0
            st.rerun()

    active_count = sum(1 for m in mappings if m.upload_enabled and m.target_field_api and not (m.source_column == selected_src_pk or m.target_field_api == selected_sf_pk))
    with nav_next:
        if not selected_src_pk or not selected_sf_pk:
            st.error("Please select a valid Source Column and Target Salesforce Field as the Match Key.")
        elif active_count == 0:
            st.warning("Please select at least one field to update before proceeding.")
        else:
            if st.button(f"Next: Validate & Confirm ({active_count} fields) ➔", type="primary", use_container_width=True):
                st.session_state.adhoc_step = 2
                st.rerun()


# ==============================================================================
# SCREEN 3: VALIDATE, PREVIEW CHANGES & CONFIRM
# ==============================================================================

def _render_screen_3_validation():
    st.markdown("### 3️⃣ Live Validation & Delta Preview")
    st.caption("Perform URL-safe live query against Salesforce, inspect ambiguous duplicate matches, confirm unmatched records, and review deltas.")

    src_df = st.session_state.adhoc_source_df
    obj_name = st.session_state.adhoc_selected_obj
    src_pk = st.session_state.adhoc_source_pk
    sf_pk = st.session_state.adhoc_target_pk
    mappings = st.session_state.adhoc_mappings
    active_prof = get_active_profile()

    if src_df is None or not obj_name or not src_pk or not sf_pk:
        st.warning("Missing required configuration. Please return to Step 2.")
        if st.button("⬅ Back to Mapping"):
            st.session_state.adhoc_step = 1
            st.rerun()
        return

    active_fields = [
        m.target_field_api for m in mappings
        if m.upload_enabled and m.target_field_api
        and m.target_field_api.lower() != "id"
        and m.source_column != src_pk
        and m.target_field_api != sf_pk
    ]

    # Target and Key Banner
    st.markdown(
        f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:14px 18px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-weight:700; color:#032D60; font-size:1.05rem;">{obj_name}</span>
                    <span style="color:#64748B; font-size:0.9rem; margin-left:8px;">({len(src_df):,} source records)</span>
                </div>
                <div>
                    <span style="font-size:0.85rem; color:#64748B;">Match Key: </span>
                    <code style="background:#F1F5F9; padding:2px 6px; border-radius:4px;">{src_pk} ➔ {sf_pk}</code>
                    <span style="margin-left:12px; font-size:0.85rem; color:#64748B;">Updating: </span>
                    <b>{len(active_fields)} fields</b>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 1. Trigger Live Fetch & Validation
    if st.session_state.adhoc_live_df is None or st.session_state.adhoc_run_result is None:
        with st.spinner("Executing URL-safe live SOQL query against Salesforce..."):
            try:
                pk_values = [str(v).strip() for v in src_df[src_pk].dropna().tolist() if str(v).strip()]
                live_df = fetch_adhoc_live_data(
                    object_name=obj_name,
                    fields=active_fields,
                    pk_field=sf_pk,
                    pk_values=pk_values,
                    profile=active_prof,
                )
                st.session_state.adhoc_live_df = live_df

                # Run Manual Engine
                cfg = AdhocEngineConfig(
                    object_name=obj_name,
                    source_pk_col=src_pk,
                    target_pk_field=sf_pk,
                    sf_id_field="Id",
                    insert_nulls=st.session_state.adhoc_insert_nulls,
                    mappings=mappings,
                    operation=st.session_state.adhoc_operation,
                    source_filename=st.session_state.adhoc_source_filename or "",
                )
                engine = ManualLoadEngine(cfg)
                res = engine.run(src_df, live_df)
                st.session_state.adhoc_run_result = res

                # Check for SF ambiguous duplicates
                st.session_state.adhoc_sf_duplicates_df = detect_salesforce_duplicates(live_df, sf_pk)

                # Check for unmatched records
                sf_pks = set(live_df[sf_pk].astype(str).str.strip().dropna()) if sf_pk in live_df.columns else set()
                st.session_state.adhoc_unmatched_list = detect_unmatched_records(pk_values, sf_pks)

            except Exception as e:
                st.error(f"Live validation failed: {e}")
                logger.exception("Live validation error")
                if st.button("⬅ Back to Mapping & Match Key"):
                    st.session_state.adhoc_step = 1
                    st.rerun()
                return

    res: AdhocRunResult = st.session_state.adhoc_run_result
    live_df = st.session_state.adhoc_live_df
    sf_dups_df = st.session_state.adhoc_sf_duplicates_df
    unmatched_keys = st.session_state.adhoc_unmatched_list

    # =========================================================================
    # PRE-FLIGHT BLOCKERS & SAFETY GATES
    # =========================================================================

    has_blockers = False

    # A. Ambiguous Salesforce Duplicate Blocker
    if sf_dups_df is not None and not sf_dups_df.empty:
        has_blockers = True
        st.error(
            f"⛔ **EXECUTION BLOCKED: Ambiguous Salesforce Matches Detected ({len(sf_dups_df):,} records)**\n\n"
            f"Salesforce returned multiple records sharing the same `{sf_pk}` key. "
            f"Updating would corrupt duplicate records in Salesforce. Please resolve duplicate keys in Salesforce before uploading."
        )
        with st.expander(f"🔍 View {len(sf_dups_df):,} Ambiguous Duplicate Salesforce Records", expanded=True):
            st.dataframe(sf_dups_df, use_container_width=True)

    # B. Direct Salesforce Id Validation Blocker
    if sf_pk.lower() == "id":
        invalid_ids = [v for v in src_df[src_pk].astype(str).str.strip() if not is_valid_salesforce_id(v)]
        if invalid_ids:
            has_blockers = True
            st.error(
                f"⛔ **EXECUTION BLOCKED: Malformed Salesforce IDs Detected ({len(invalid_ids):,} invalid values)**\n\n"
                f"When matching by Salesforce `Id`, every value must be a valid 15 or 18 character alphanumeric ID. Examples of invalid values: `{invalid_ids[:5]}`"
            )

    # C. Unmatched Records Gate (Default to Exclude + Require Confirmation)
    if unmatched_keys:
        st.warning(
            f"⚠️ **Found {len(unmatched_keys):,} unmatched record(s)** out of {len(src_df):,} total source records.\n\n"
            f"**Default Behavior**: Unmatched records are excluded from the update. Only the **{len(src_df) - len(unmatched_keys):,} matched records** will be updated in Salesforce."
        )
        with st.expander(f"🔍 Inspect {len(unmatched_keys):,} Unmatched Primary Keys (Quarantined to skipped_records.csv)", expanded=False):
            st.write(unmatched_keys[:100])

        confirmed = st.checkbox(
            f"I confirm: Proceed with updating only the {len(src_df) - len(unmatched_keys):,} matched records (exclude {len(unmatched_keys):,} unmatched records)",
            value=st.session_state.adhoc_unmatched_confirmed,
            key="adhoc_chk_unmatched_confirm",
        )
        st.session_state.adhoc_unmatched_confirmed = confirmed

    # Delta Metrics KPI Cards
    st.markdown("#### 📊 Proposed Execution Metrics")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(render_kpi_card("Total Source Rows", f"{res.total_source_rows:,}", "Spreadsheet records", "default"), unsafe_allow_html=True)
    with k2:
        st.markdown(render_kpi_card("Records to Update", f"{res.changed_records:,}", "Deltas identified", "success"), unsafe_allow_html=True)
    with k3:
        st.markdown(render_kpi_card("Unmatched / Skipped", f"{len(unmatched_keys):,}", "Excluded from upload", "default"), unsafe_allow_html=True)
    with k4:
        st.markdown(render_kpi_card("Ambiguous SF Matches", f"{len(sf_dups_df) if sf_dups_df is not None else 0:,}", "Blockers", "error" if (sf_dups_df is not None and not sf_dups_df.empty) else "default"), unsafe_allow_html=True)

    # Field-Level Changes & Audit Table Tabs
    tab_changes, tab_audit = st.tabs([
        f"👁️ Field-Level Changes ({res.changed_records} records)",
        "📋 Full Validation Audit Grid",
    ])

    with tab_changes:
        chg_path = res.artifacts.get("field_level_changes")
        chg_df = _safe_read_csv(chg_path)
        if not chg_df.empty:
            st.dataframe(chg_df, use_container_width=True)
        else:
            st.info("No field-level changes detected between spreadsheet and Salesforce.")

    with tab_audit:
        val_path = res.artifacts.get("validation_report")
        val_df = _safe_read_csv(val_path)
        if not val_df.empty:
            st.dataframe(val_df, use_container_width=True)
        else:
            st.info("Validation grid empty.")

    # Navigation & Run Trigger
    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    col_back, col_run = st.columns([1, 2])

    with col_back:
        if st.button("⬅ Back to Mapping & Key", use_container_width=True):
            st.session_state.adhoc_step = 1
            st.rerun()

    with col_run:
        # Check confirmation requirements
        unmatched_gate_ok = (not unmatched_keys) or st.session_state.adhoc_unmatched_confirmed
        can_run = (not has_blockers) and unmatched_gate_ok and (res.changed_records > 0)

        if has_blockers:
            st.button("⛔ Blocked: Resolve Errors Above", disabled=True, use_container_width=True)
        elif unmatched_keys and not st.session_state.adhoc_unmatched_confirmed:
            st.button("⚠️ Check Confirmation Above to Proceed", disabled=True, use_container_width=True)
        elif res.changed_records == 0:
            st.button("ℹ️ No Deltas to Update", disabled=True, use_container_width=True)
        else:
            if st.button(f"Confirm & Run Ingest ({res.changed_records:,} records) ➔", type="primary", use_container_width=True):
                st.session_state.adhoc_step = 3
                st.rerun()


# ==============================================================================
# SCREEN 4: RUN RESULTS, DOWNLOADS & ROLLBACK
# ==============================================================================

def _render_screen_4_results():
    st.markdown("### 4️⃣ Execution Results & Downloads Hub")
    st.caption("Monitor live progress, download generated audit artifacts, inspect failures, or execute emergency rollback.")

    res: AdhocRunResult = st.session_state.adhoc_run_result
    obj_name = st.session_state.adhoc_selected_obj
    active_prof = get_active_profile()

    if res is None:
        st.warning("No run results found. Please complete Step 3 first.")
        if st.button("⬅ Back to Validation"):
            st.session_state.adhoc_step = 2
            st.rerun()
        return

    # Check background job status
    job_info = get_job_progress(res.run_dir)
    if job_info:
        status = job_info.get("status", "RUNNING")
        if status == "RUNNING":
            is_rb = job_info.get("is_rollback", False)
            eng_name = "Lightning REST Collections" if job_info.get("engine") == "composite" else "Bulk API 2.0"
            title = f"⏪ Rollback in Progress ({eng_name})" if is_rb else f"🚀 Ingest in Progress ({eng_name})"
            st.markdown(f"### {title}")
            st.caption(f"Executing cloud update on **{obj_name}** in **{active_prof.title()}**.")

            tot_recs = job_info.get("total_records_overall", res.changed_records)
            proc_recs = job_info.get("processed_records_overall", 0)
            succ_recs = job_info.get("successful_records_overall", 0)
            fail_recs = job_info.get("failed_records_overall", 0)

            prog_val = min(1.0, max(0.0, proc_recs / tot_recs)) if tot_recs > 0 else 0.0
            st.progress(prog_val, text=f"Progress: {proc_recs:,} of {tot_recs:,} records ({int(prog_val * 100)}%)")

            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("Total Records", f"{tot_recs:,}")
            m_col2.metric("Processed", f"{proc_recs:,}")
            m_col3.metric("Successful", f"{succ_recs:,}")
            if fail_recs > 0:
                m_col4.metric("Failed", f"{fail_recs:,}")
            else:
                try:
                    s_dt = datetime.fromisoformat(job_info["start_time"])
                    el_sec = int((datetime.now() - s_dt).total_seconds())
                    m_col4.metric("Elapsed Time", f"{el_sec}s")
                except Exception:
                    m_col4.metric("Elapsed Time", "N/A")

            col_ref_btn, col_ref_txt = st.columns([1, 3])
            with col_ref_btn:
                if st.button("🔄 Refresh Status", key="btn_adhoc_refresh_running", type="secondary"):
                    st.rerun()
            with col_ref_txt:
                st.caption("ℹ️ Progress updates automatically every 1.5 seconds. Background worker continues even if you switch tabs.")

            time.sleep(1.5)
            st.rerun()
            return

        elif status in ("COMPLETED", "FAILED"):
            is_rb = job_info.get("is_rollback", False)
            if status == "COMPLETED":
                title = "⏪ Rollback Completed" if is_rb else "🎉 Ingest Completed"
                succ = job_info.get("successful_records_overall", 0)
                fail = job_info.get("failed_records_overall", 0)
                if fail == 0:
                    st.success(f"**{title}**! Successfully processed all {succ:,} records on **{obj_name}** with 0 errors! 🚀")
                else:
                    st.warning(f"**{title}** completed with {succ:,} successes and {fail:,} failures on **{obj_name}**.")
                    o_meta = job_info.get("objects", {}).get(obj_name, {})
                    if o_meta.get("failures_file"):
                        fail_path = res.run_dir / o_meta["failures_file"]
                        if fail_path.exists():
                            st.error(f"Failures saved to `{fail_path.name}`:")
                            fail_df = _safe_read_csv(fail_path)
                            st.dataframe(fail_df, use_container_width=True)

                # Dataloader.io Results Downloads
                m_succ_p = res.run_dir / "salesforce_success_records.csv"
                m_err_p = res.run_dir / "salesforce_error_records.csv"
                if m_succ_p.exists() or m_err_p.exists():
                    col_m_s, col_m_e = st.columns(2)
                    with col_m_s:
                        if m_succ_p.exists():
                            with open(m_succ_p, "rb") as msf:
                                st.download_button(
                                    "📥 Download Success Records (.csv)",
                                    msf.read(),
                                    file_name="salesforce_success_records.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="manual_dl_succ",
                                )
                    with col_m_e:
                        if m_err_p.exists():
                            with open(m_err_p, "rb") as mef:
                                st.download_button(
                                    "📥 Download Error Records (.csv)",
                                    mef.read(),
                                    file_name="salesforce_error_records.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="manual_dl_err",
                                )

                # Tier 2: Post-Update Live Verification Report
                m_rep_p = res.run_dir / "post_update_validation_report.csv"
                m_disc_p = res.run_dir / "post_update_discrepancies.csv"
                if m_rep_p.exists():
                    st.markdown("---")
                    st.markdown("### 🔍 Post-Update Live Audit & Reconciliation")
                    st.caption("Verifies whether submitted updates actually persisted or were altered by internal Apex triggers, locked fields, or validation rules.")
                    m_pv_df = _safe_read_csv(m_rep_p, dtype=str)
                    if not m_pv_df.empty:
                        m_tot = len(m_pv_df)
                        m_ver = len(m_pv_df[m_pv_df["Status"] == "VERIFIED_MATCH"])
                        m_mut = len(m_pv_df[m_pv_df["Status"] == "TRIGGER_MUTATION"])
                        m_stale = len(m_pv_df[m_pv_df["Status"].isin(["UNMODIFIED_STALE", "NULL_WIPE_FAILED"])])
                        m_notf = len(m_pv_df[m_pv_df["Status"] == "RECORD_NOT_FOUND"])
                        m_pct = round((m_ver / m_tot * 100), 1) if m_tot > 0 else 100.0

                        mc1, mc2, mc3, mc4 = st.columns(4)
                        mc1.metric("Fields Audited", f"{m_tot:,}")
                        mc2.metric("Verified Match", f"{m_pct}%", delta=f"{m_ver} verified")
                        mc3.metric("Trigger Overwrites", f"{m_mut}", delta="- Alarmed" if m_mut > 0 else None, delta_color="inverse")
                        mc4.metric("Stale / Not Saved", f"{m_stale + m_notf}", delta="- Failed" if (m_stale + m_notf) > 0 else None, delta_color="inverse")

                        if m_disc_p and m_disc_p.exists():
                            m_disc_df = _safe_read_csv(m_disc_p, dtype=str)
                            if not m_disc_df.empty:
                                with st.expander(f"⚠️ View Discrepancies ({len(m_disc_df)} fields mutated or un-saved)", expanded=True):
                                    st.warning("The following fields in Salesforce differ from what was submitted. They may have been overwritten by Sitetracker managed package triggers or validation rules.")
                                    st.dataframe(m_disc_df, use_container_width=True)

                        c_m_pv1, c_m_pv2 = st.columns(2)
                        with c_m_pv1:
                            with open(m_rep_p, "rb") as f_mrep:
                                st.download_button(
                                    "📄 Full Post-Audit Report (.csv)",
                                    f_mrep.read(),
                                    file_name="post_update_validation_report.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="manual_dl_pv_full",
                                )
                        with c_m_pv2:
                            if m_disc_p and m_disc_p.exists():
                                with open(m_disc_p, "rb") as f_mdisc:
                                    st.download_button(
                                        "⚠️ Discrepancies Only (.csv)",
                                        f_mdisc.read(),
                                        file_name="post_update_discrepancies.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                        key="manual_dl_pv_disc",
                                    )
            else:
                title = "Rollback" if is_rb else "Ingest"
                st.error(f"❌ {title} job failed on server: {job_info.get('error_summary', 'Unknown error')}")

    # Start Ingest Controls if not yet running
    if not job_info:
        st.markdown("#### 🚀 Launch Salesforce Ingest Job")
        st.caption(f"Ready to update **{res.changed_records:,} records** on **{obj_name}** in **{active_prof.title()}**.")

        col_eng, col_batch = st.columns([1.5, 1])
        with col_eng:
            sel_engine = st.radio(
                "🚀 Ingest Engine",
                [
                    "⚡ Lightning REST Collections (Fast: ~15-50s - Recommended for <2,500 records)",
                    "📦 Bulk API 2.0 (Asynchronous Queue - For large datasets >2,000 records)"
                ],
                index=0,
                key="adhoc_sel_ingest_engine",
            )
            engine_key = "composite" if "Lightning" in sel_engine else "bulk2"

        with col_batch:
            bulk_batch_size = st.select_slider(
                "⚡ Apex Batch Size (Records per chunk)",
                options=[5, 10, 15, 25, 50],
                value=50 if engine_key == "composite" else 25,
                key="adhoc_sel_batch_size",
                help="Smaller batches stay well below Apex 151 DML limit.",
            )

        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            confirm_phrase = st.text_input(
                "Type CONFIRM to execute update:",
                placeholder="CONFIRM",
                key="adhoc_confirm_push",
            )

        with col_c2:
            st.write("")
            st.write("")
            push_enabled = (confirm_phrase.strip() == "CONFIRM")
            if st.button(f"🚀 Execute Ingest Now", type="primary", disabled=not push_enabled, key="btn_adhoc_execute_push"):
                start_background_ingest(
                    run_dir=res.run_dir,
                    report_name="Ad-Hoc Ingest",
                    is_rollback=False,
                    profile=active_prof,
                    batch_size=bulk_batch_size,
                    target_object=obj_name,
                    engine=engine_key,
                )
                st.rerun()

    # Download Hub
    st.markdown("---")
    st.markdown("#### 📥 Download Generated Artifacts")
    d1, d2, d3, d4 = st.columns(4)

    final_p = res.artifacts.get("final_input_file")
    if final_p and final_p.exists():
        with open(final_p, "rb") as f:
            d1.download_button("📥 Final Input File (.csv)", f.read(), file_name="final_input_file.csv", mime="text/csv", use_container_width=True)

    rollback_p = res.artifacts.get("rollback_file")
    if rollback_p and rollback_p.exists():
        with open(rollback_p, "rb") as f:
            d2.download_button("🔙 Rollback File (.csv)", f.read(), file_name="rollback_file.csv", mime="text/csv", use_container_width=True)

    chg_p = res.artifacts.get("field_level_changes")
    if chg_p and chg_p.exists():
        with open(chg_p, "rb") as f:
            d3.download_button("👁️ Field Changes (.csv)", f.read(), file_name="field_level_changes.csv", mime="text/csv", use_container_width=True)

    dup_src_p = res.artifacts.get("duplicate_primary_keys")
    if dup_src_p and dup_src_p.exists():
        with open(dup_src_p, "rb") as f:
            d4.download_button("⚠️ Source Duplicates (.csv)", f.read(), file_name="duplicate_primary_keys.csv", mime="text/csv", use_container_width=True)

    d5, d6, d7, d8 = st.columns(4)
    skipped_p = res.artifacts.get("skipped_records")
    if skipped_p and skipped_p.exists():
        with open(skipped_p, "rb") as f:
            d5.download_button("⚪ Unmatched Records (.csv)", f.read(), file_name="skipped_records.csv", mime="text/csv", use_container_width=True)

    dup_sf_p = res.artifacts.get("duplicate_salesforce_records")
    if dup_sf_p and dup_sf_p.exists():
        with open(dup_sf_p, "rb") as f:
            d6.download_button("🚫 SF Duplicates (.csv)", f.read(), file_name="duplicate_salesforce_records.csv", mime="text/csv", use_container_width=True)

    err_p = res.artifacts.get("error_records")
    if err_p and err_p.exists():
        with open(err_p, "rb") as f:
            d7.download_button("❌ Error Records (.csv)", f.read(), file_name="error_records.csv", mime="text/csv", use_container_width=True)

    audit_p = res.artifacts.get("audit_log")
    if audit_p and Path(audit_p).exists():
        with open(audit_p, "rb") as f:
            d8.download_button("📄 Audit Log (.log)", f.read(), file_name="audit.log", mime="text/plain", use_container_width=True)

    # Cloud Ingest & Post-Audit Artifacts
    cloud_files = [
        ("salesforce_success_records.csv", "🟢 Cloud Successes (.csv)"),
        ("salesforce_error_records.csv", "🔴 Cloud Failures (.csv)"),
        ("post_update_validation_report.csv", "🔍 Post-Audit Full (.csv)"),
        ("post_update_discrepancies.csv", "⚠️ Discrepancies (.csv)"),
    ]
    present_cloud = [(fn, lbl, res.run_dir / fn) for fn, lbl in cloud_files if (res.run_dir / fn).exists()]
    if present_cloud:
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        c_cols = st.columns(len(present_cloud))
        for i, (fn, lbl, cp) in enumerate(present_cloud):
            with open(cp, "rb") as cf:
                c_cols[i].download_button(lbl, cf.read(), file_name=fn, mime="text/csv", use_container_width=True, key=f"manual_hub_{fn}")

    # 1-Click Rollback Safety Net
    if rollback_p and rollback_p.exists() and job_info and job_info.get("status") == "COMPLETED" and not job_info.get("is_rollback"):
        st.markdown("---")
        st.markdown("### ⏪ Emergency 1-Click Rollback")
        st.warning(f"⚠️ Need to undo this upload? You can restore all {res.changed_records:,} records back to their original Sitetracker values.")

        col_rb_txt, col_rb_btn = st.columns([2, 1])
        with col_rb_txt:
            rb_phrase = st.text_input("Type REVERT to enable rollback:", placeholder="REVERT", key="adhoc_rb_confirm_phrase")
        with col_rb_btn:
            st.write("")
            st.write("")
            if st.button("⏪ Execute Rollback Now", type="secondary", disabled=(rb_phrase.strip() != "REVERT"), key="btn_adhoc_do_rollback"):
                start_background_ingest(
                    run_dir=res.run_dir,
                    report_name="Ad-Hoc Ingest",
                    is_rollback=True,
                    profile=active_prof,
                    batch_size=50,
                    target_object=obj_name,
                    engine=job_info.get("engine", "composite"),
                )
                st.rerun()

    # Reset button for new run
    st.markdown("---")
    if st.button("🔄 Start New Ingestion", key="btn_start_new_ingestion", type="secondary"):
        clear_job_progress(res.run_dir)
        st.session_state.adhoc_step = 0
        st.session_state.adhoc_source_df = None
        st.session_state.adhoc_source_filename = ""
        _invalidate_validation_cache()
        st.rerun()
