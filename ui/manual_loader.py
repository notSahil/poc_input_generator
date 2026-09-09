"""Manual / Ad-Hoc Dataloader UI Module (Dataloader.io Mode).

Allows users to upload any CSV or Excel file, select any Salesforce/Sitetracker object,
configure primary keys, auto-match and customize field mappings, review deltas,
and push updates directly via Salesforce Bulk API 2.0 with 1-click rollback.
"""

from io import BytesIO
import logging
from pathlib import Path
import re
from typing import Any
import pandas as pd
import streamlit as st

from config import settings
from core.exceptions import SalesforceAPIError, SalesforceAuthError
from core.manual_engine import (
    AdhocEngineConfig,
    AdhocFieldMapping,
    AdhocRunResult,
    ManualLoadEngine,
    detect_target_object,
    suggest_field_mappings,
)
from salesforce.adhoc_fetcher import (
    fetch_adhoc_live_data,
    fetch_all_objects,
    fetch_object_fields,
)
from salesforce.auth import check_connection_status, get_active_profile, is_token_valid
from salesforce.bulk_uploader import push_delta_to_sitetracker
from ui.styles import render_kpi_card, render_pill

logger = logging.getLogger(__name__)


def _init_manual_state():
    """Ensure session state variables for manual dataloader are initialized."""
    if "adhoc_step" not in st.session_state:
        st.session_state.adhoc_step = 0
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
        st.session_state.adhoc_insert_nulls = True
    if "adhoc_run_result" not in st.session_state:
        st.session_state.adhoc_run_result = None
    if "adhoc_bulk_result" not in st.session_state:
        st.session_state.adhoc_bulk_result = None
    if "adhoc_rollback_result" not in st.session_state:
        st.session_state.adhoc_rollback_result = None


def _safe_read_csv(path: Path | None) -> pd.DataFrame:
    """Safely read a CSV file, returning an empty DataFrame if empty or missing."""
    if not path:
        return pd.DataFrame()
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8", on_bad_lines="skip")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except UnicodeDecodeError:
        try:
            return pd.read_csv(p, dtype=str, keep_default_na=False, encoding="latin1", engine="python", on_bad_lines="skip")
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
        st.title("⚡ Ad-Hoc Data Loader")
        st.caption("Dataloader.io Mode • Upload custom CSV/Excel, map any Salesforce object dynamically, validate deltas, and upload.")

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
        status_dot = "● Connected" if is_auth else f"● {status_label}"
        status_color = "#04844B" if is_auth else "#EA001E"
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

    # Step Tracker
    steps = [
        "1. Upload Source Data",
        "2. Select Object & Key",
        "3. Field Mapping",
        "4. Review, Diff & Upload",
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

    # Step Router
    if cur_step == 0:
        _render_step_1_upload()
    elif cur_step == 1:
        _render_step_2_object()
    elif cur_step == 2:
        _render_step_3_mapping()
    elif cur_step == 3:
        _render_step_4_execution()


# ==============================================================================
# STEP 1: UPLOAD SOURCE DATA
# ==============================================================================

def _render_step_1_upload():
    st.markdown("### 1️⃣ Upload Source Spreadsheet")
    st.caption("Upload any CSV or Excel file containing the records you want to insert or update in Salesforce.")

    uploaded_file = st.file_uploader(
        "Choose a file (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        key="adhoc_file_input",
    )

    if uploaded_file is not None:
        try:
            filename = uploaded_file.name
            if filename.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(uploaded_file, dtype=str)
            else:
                try:
                    df = pd.read_csv(uploaded_file, dtype=str, encoding="utf-8")
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, dtype=str, encoding="latin1", engine="python", on_bad_lines="skip")

            df = df.fillna("").astype(str)
            st.session_state.adhoc_source_df = df
            st.session_state.adhoc_source_filename = filename

            # Auto-detect target Salesforce object from columns
            detected_obj = detect_target_object(list(df.columns))
            if detected_obj:
                st.session_state.adhoc_selected_obj = detected_obj
                st.session_state._adhoc_detected_obj = detected_obj

            st.success(f"Loaded **{filename}** successfully ({len(df):,} rows, {len(df.columns)} columns)")

            if st.session_state.get("_adhoc_detected_obj"):
                st.info(f"💡 Auto-detected target object: **{st.session_state._adhoc_detected_obj}** based on spreadsheet columns.")

            # Preview
            with st.expander("👁️ Preview First 10 Rows", expanded=True):
                st.dataframe(df.head(10), use_container_width=True)

            st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
            if st.button("Next: Select Object & Identifier ➔", type="primary", use_container_width=True):
                st.session_state.adhoc_step = 1
                st.rerun()

        except Exception as e:
            st.error(f"Failed to read uploaded file: {e}")
    else:
        if st.session_state.adhoc_source_df is not None:
            st.info(f"Using previously uploaded file: **{st.session_state.adhoc_source_filename}** ({len(st.session_state.adhoc_source_df):,} rows)")
            with st.expander("👁️ Preview Current Data", expanded=False):
                st.dataframe(st.session_state.adhoc_source_df.head(5), use_container_width=True)
            if st.button("Next: Select Object & Identifier ➔", type="primary", use_container_width=True):
                st.session_state.adhoc_step = 1
                st.rerun()


# ==============================================================================
# STEP 2: SELECT OBJECT & IDENTIFIER
# ==============================================================================

def _render_step_2_object():
    st.markdown("### 2️⃣ Select Target Salesforce Object & Primary Key")
    st.caption("Choose which Salesforce object to update and which field uniquely identifies records.")

    src_df = st.session_state.adhoc_source_df
    if src_df is None:
        st.warning("Please upload a source file in Step 1 first.")
        if st.button("⬅ Back to Upload"):
            st.session_state.adhoc_step = 0
            st.rerun()
        return

    # Discover Objects from Salesforce
    active_prof = get_active_profile()
    if not is_token_valid(profile=active_prof):
        st.error(f"Not authenticated with Salesforce ({active_prof}). Please log in via the Data Export page first.")
        return

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

    # Quick Select Core Objects
    st.markdown("**⚡ Quick Select Common Sitetracker Objects:**")
    qcols = st.columns(5)
    core_shortcuts = [
        ("🏢 Site", "sitetracker__Site__c"),
        ("📂 BT Project", "BT_Project__c"),
        ("📋 Project", "sitetracker__Project__c"),
        ("🔧 Work Order", "sitetracker__Work_Order__c"),
        ("🚩 Milestone", "sitetracker__Milestone__c"),
    ]
    for c, (btn_label, obj_api) in zip(qcols, core_shortcuts):
        is_active = (st.session_state.adhoc_selected_obj == obj_api)
        if c.button(
            f"{'👉 ' if is_active else ''}{btn_label}",
            key=f"quick_btn_{obj_api}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state.adhoc_selected_obj = obj_api
            st.session_state.adhoc_fields = []
            st.rerun()

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

    # Search & Category Filters
    col_filter1, col_filter2 = st.columns([2, 1])
    with col_filter1:
        search_query = st.text_input(
            "🔍 Search Objects by Name or Label:",
            "",
            placeholder="e.g. Site, Project, Work Order, Account...",
            key="adhoc_obj_search",
        )
    with col_filter2:
        filter_category = st.selectbox(
            "Category Filter:",
            ["All Objects", "Sitetracker (*__c)", "Custom Objects (*__c)", "Standard Objects"],
            key="adhoc_cat_filter",
        )

    if filter_category == "Sitetracker (*__c)":
        filtered_objs = [o for o in all_objs if o["category"] == "Sitetracker"]
    elif filter_category == "Custom Objects (*__c)":
        filtered_objs = [o for o in all_objs if o["category"] in ("Sitetracker", "Custom")]
    elif filter_category == "Standard Objects":
        filtered_objs = [o for o in all_objs if o["category"] == "Standard"]
    else:
        filtered_objs = all_objs

    if search_query.strip():
        q = search_query.strip().lower()
        filtered_objs = [
            o for o in filtered_objs
            if q in o["label"].lower() or q in o["name"].replace("sitetracker__", "").replace("__c", "").lower()
        ]

    # Format object choices: "Site (sitetracker__Site__c)"
    obj_display_map = {
        f"{o['label']} ({o['name']})": o["name"]
        for o in filtered_objs
    }

    if not obj_display_map:
        st.warning("No objects matched your search. Showing all available objects.")
        filtered_objs = all_objs
        obj_display_map = {
            f"{o['label']} ({o['name']})": o["name"]
            for o in filtered_objs
        }

    # Find default index
    default_idx = 0
    if st.session_state.adhoc_selected_obj:
        for idx, (k, v) in enumerate(obj_display_map.items()):
            if v == st.session_state.adhoc_selected_obj:
                default_idx = idx
                break

    selected_display = st.selectbox(
        f"Select Target Object ({len(filtered_objs)} available):",
        list(obj_display_map.keys()),
        index=default_idx,
        help="Select the Salesforce object you want to upload data to.",
    )
    selected_obj = obj_display_map[selected_display]
    st.session_state.adhoc_selected_obj = selected_obj

    # Discover Fields on the Selected Object
    if not st.session_state.adhoc_fields or st.session_state.get("_last_loaded_obj") != selected_obj:
        with st.spinner(f"Inspecting fields on '{selected_obj}'..."):
            try:
                st.session_state.adhoc_fields = fetch_object_fields(selected_obj, profile=active_prof)
                st.session_state._last_loaded_obj = selected_obj
            except Exception as e:
                st.error(f"Failed to inspect fields on '{selected_obj}': {e}")
                return

    sf_fields = st.session_state.adhoc_fields

    # Primary Key Selection
    st.markdown("#### 🔑 Record Matching Key (Primary Key)")
    st.caption("Select how records in your spreadsheet will match existing records in Salesforce.")

    col_src_pk, col_sf_pk = st.columns(2)

    src_columns = list(src_df.columns)

    # Check if Mapping_file.xlsx specifies a primary key for this object
    rec_src_pk = None
    rec_sf_pk = None
    mapping_file = Path(settings.DATA_DIR) / "common" / "Mapping_file.xlsx"
    if not mapping_file.exists():
        mapping_file = Path("data/common/Mapping_file.xlsx")
    if mapping_file.exists():
        try:
            mf = pd.read_excel(mapping_file)
            for _, row in mf.iterrows():
                if str(row.get("Primary Key?", "")).strip().lower() in ("yes", "y", "true"):
                    obj = str(row.get("Object Name", "")).strip().lower()
                    src_c = str(row.get("Source File Column Name", "")).strip()
                    sf_api = str(row.get("API Name", "")).strip()

                    applies = False
                    if "site" in selected_obj.lower() and "site" in obj:
                        applies = True
                    elif "bt_project" in selected_obj.lower() and "bt" in obj:
                        applies = True
                    elif "project" in selected_obj.lower() and ("bt" not in obj and "project" in obj):
                        applies = True

                    if applies and src_c in src_columns:
                        rec_src_pk = src_c
                        rec_sf_pk = sf_api
                        break
        except Exception:
            pass

    # Determine default source PK index
    src_pk_default_idx = 0
    if rec_src_pk and rec_src_pk in src_columns:
        src_pk_default_idx = src_columns.index(rec_src_pk)
    else:
        for idx, c in enumerate(src_columns):
            if any(term in c.lower() for term in ("id", "site_id", "project", "wes", "code", "ref")):
                src_pk_default_idx = idx
                break

    with col_src_pk:
        selected_src_pk = st.selectbox(
            "Source Column (Spreadsheet Identifier)",
            src_columns,
            index=src_pk_default_idx,
            help="Column in your uploaded file that holds unique record keys.",
        )
        st.session_state.adhoc_source_pk = selected_src_pk

    # Determine default target SF PK index
    sf_pk_default_idx = 0
    if rec_sf_pk and any(f["api_name"] == rec_sf_pk for f in sf_fields):
        for idx, f in enumerate(sf_fields):
            if f["api_name"] == rec_sf_pk:
                sf_pk_default_idx = idx
                break
    else:
        for idx, f in enumerate(sf_fields):
            if f["is_external_id"] or f["api_name"] == "Id" or "id" in f["api_name"].lower():
                sf_pk_default_idx = idx
                break

    with col_sf_pk:
        sf_display_map = {
            f"{f['api_name']} ({f['label']})" + (" [External ID]" if f["is_external_id"] else ""): f["api_name"]
            for f in sf_fields
        }
        selected_sf_pk_display = st.selectbox(
            "Salesforce Target Field (Identifier)",
            list(sf_display_map.keys()),
            index=sf_pk_default_idx,
            help="Salesforce field matching your spreadsheet identifier (e.g. Id, External ID).",
        )
        selected_sf_pk = sf_display_map[selected_sf_pk_display]
        st.session_state.adhoc_target_pk = selected_sf_pk

    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    col_back, col_next = st.columns([1, 2])
    with col_back:
        if st.button("⬅ Back to Upload", use_container_width=True):
            st.session_state.adhoc_step = 0
            st.rerun()

    with col_next:
        if st.button("Next: Field Mapping & Selection ➔", type="primary", use_container_width=True):
            # Generate auto-match suggestions
            st.session_state.adhoc_mappings = suggest_field_mappings(
                source_columns=src_columns,
                sf_fields=sf_fields,
                source_pk_col=selected_src_pk,
                target_pk_field=selected_sf_pk,
                object_name=selected_obj,
            )
            st.session_state.adhoc_step = 2
            st.rerun()


# ==============================================================================
# STEP 3: FIELD MAPPING & SELECTION
# ==============================================================================

def _render_step_3_mapping():
    st.markdown("### 3️⃣ Field Mapping & Selection")
    st.caption("Check the fields you want to update in Salesforce and verify data types.")

    obj_name = st.session_state.adhoc_selected_obj
    src_pk = st.session_state.adhoc_source_pk
    sf_pk = st.session_state.adhoc_target_pk
    sf_fields = st.session_state.adhoc_fields

    col_hdr_info, col_hdr_btn = st.columns([3, 1])
    with col_hdr_info:
        st.markdown(
            f"""
            <div style="background:#F0F4F8; border-left:4px solid #0176D3; border-radius:4px; padding:10px 16px; margin-bottom:12px;">
                <div style="font-size:0.9rem; color:#032D60;">
                    <b>Target Object:</b> <code>{obj_name}</code> &nbsp;|&nbsp;
                    <b>Identifier Mapping:</b> <code>{src_pk}</code> ➔ <code>{sf_pk}</code>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col_hdr_btn:
        if st.button("🔄 Change Object / Key", use_container_width=True, help="Go back to Step 2 to select a different Salesforce object or matching key"):
            st.session_state.adhoc_step = 1
            st.rerun()

    mappings = st.session_state.adhoc_mappings
    if not mappings:
        st.warning("No mappings configured. Please go back to Step 2.")
        if st.button("⬅ Back to Object Selection"):
            st.session_state.adhoc_step = 1
            st.rerun()
        return

    # Check if ANY non-key field was matched
    mapped_non_pk = [m for m in mappings if m.source_column != src_pk and m.target_field_api]
    if not mapped_non_pk and len(mappings) > 1:
        st.warning(
            f"⚠️ **Notice**: None of your spreadsheet columns matched fields on **`{obj_name}`**.\n\n"
            f"Please verify if **`{obj_name}`** is the correct Salesforce object for this file."
        )
        if st.session_state.adhoc_source_df is not None:
            detected_alt = detect_target_object(list(st.session_state.adhoc_source_df.columns))
            if detected_alt and detected_alt != obj_name:
                if st.button(f"⚡ Switch Target Object to detected: '{detected_alt}'", type="primary"):
                    st.session_state.adhoc_selected_obj = detected_alt
                    st.session_state.adhoc_fields = []
                    st.session_state.adhoc_step = 1
                    st.rerun()

    # Build options for target field selector
    sf_field_options = ["-- Do Not Map --"] + [f"{f['api_name']} ({f['label']})" for f in sf_fields]
    api_lookup = {f"{f['api_name']} ({f['label']})": f["api_name"] for f in sf_fields}
    label_lookup = {f["api_name"]: f["label"] for f in sf_fields}
    dtype_lookup = {f["api_name"]: f["data_type"] for f in sf_fields}

    # Bulk Select / Deselect
    col_actions, col_opt = st.columns([2, 2])
    with col_actions:
        b_col1, b_col2 = st.columns(2)
        with b_col1:
            if st.button("☑️ Select All Fields", use_container_width=True):
                for m in mappings:
                    if m.source_column != src_pk and m.target_field_api and m.target_field_api.lower() != "id":
                        m.upload_enabled = True
                st.rerun()
        with b_col2:
            if st.button("⬜ Deselect All", use_container_width=True):
                for m in mappings:
                    m.upload_enabled = False
                st.rerun()

    with col_opt:
        st.session_state.adhoc_insert_nulls = st.checkbox(
            "Clear field in Salesforce if spreadsheet cell is blank (#N/A)",
            value=st.session_state.adhoc_insert_nulls,
            help="When enabled, blank values in your file will wipe existing values in Salesforce. When unchecked, blanks are safely ignored.",
        )

    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

    # Interactive Mapping Editor Rows
    st.markdown("#### 📋 Field Mapping Configuration")
    header_cols = st.columns([1, 3, 4, 2, 2])
    header_cols[0].markdown("**Upload?**")
    header_cols[1].markdown("**Source Column**")
    header_cols[2].markdown("**Salesforce Target Field**")
    header_cols[3].markdown("**Data Type**")
    header_cols[4].markdown("**Match Status**")

    st.markdown("<hr style='margin: 4px 0 12px 0;'>", unsafe_allow_html=True)

    data_types = ["text", "date", "number", "boolean"]

    for idx, m in enumerate(mappings):
        cols = st.columns([1, 3, 4, 2, 2])
        is_pk = bool(m.source_column == src_pk or (sf_pk and m.target_field_api == sf_pk))
        is_id_field = bool(m.target_field_api and m.target_field_api.lower() == "id")

        # 1. Upload Checkbox (Record ID and Primary Keys are strictly lookup-only)
        if is_pk:
            cols[0].markdown("🔑 *Key*")
            m.upload_enabled = False
        elif is_id_field:
            cols[0].markdown("🔒 *ID*")
            m.upload_enabled = False
        else:
            m.upload_enabled = cols[0].checkbox(
                f"Upload {m.source_column}",
                value=m.upload_enabled,
                key=f"chk_upload_{idx}",
                label_visibility="collapsed",
            )

        # 2. Source Column Name
        cols[1].markdown(f"`{m.source_column}`")

        # 3. Target Salesforce Field Selector
        cur_display = "-- Do Not Map --"
        if m.target_field_api:
            for opt in sf_field_options:
                if opt.startswith(f"{m.target_field_api} (") or opt == m.target_field_api:
                    cur_display = opt
                    break

        default_idx = sf_field_options.index(cur_display) if cur_display in sf_field_options else 0
        selected_opt = cols[2].selectbox(
            f"Salesforce Field for {m.source_column}",
            sf_field_options,
            index=default_idx,
            key=f"sel_sf_{idx}",
            label_visibility="collapsed",
        )

        if selected_opt != "-- Do Not Map --":
            chosen_api = api_lookup.get(selected_opt, selected_opt.split(" ")[0])
            m.target_field_api = chosen_api
            m.target_field_label = label_lookup.get(chosen_api, chosen_api)
            # Record ID and PK fields can never be updated
            if chosen_api.lower() == "id" or is_pk:
                m.upload_enabled = False
            # Auto-assign type if not manually modified
            if not m.data_type or m.data_type == "text":
                m.data_type = dtype_lookup.get(chosen_api, "text")
        else:
            m.target_field_api = ""
            m.target_field_label = ""
            m.upload_enabled = False

        # 4. Data Type Selector
        dt_idx = data_types.index(m.data_type) if m.data_type in data_types else 0
        m.data_type = cols[3].selectbox(
            f"Data Type for {m.source_column}",
            data_types,
            index=dt_idx,
            key=f"sel_dt_{idx}",
            label_visibility="collapsed",
        )

        # 5. Match Status Pill
        if is_pk:
            cols[4].markdown(render_pill("Primary Key", "blue"), unsafe_allow_html=True)
        elif is_id_field:
            cols[4].markdown(render_pill("Record ID (Read Only)", "gray"), unsafe_allow_html=True)
        elif m.target_field_api:
            cols[4].markdown(render_pill(m.match_confidence or "Matched", "green"), unsafe_allow_html=True)
        else:
            cols[4].markdown(render_pill("Unmapped", "gray"), unsafe_allow_html=True)

    # Validation check
    active_count = sum(1 for m in mappings if m.upload_enabled and m.target_field_api)

    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    col_back, col_next = st.columns([1, 2])
    with col_back:
        if st.button("⬅ Back to Object Selection", use_container_width=True):
            st.session_state.adhoc_step = 1
            st.rerun()

    with col_next:
        if active_count == 0:
            st.warning("⚠️ Please select at least one field to upload before proceeding.")
        else:
            btn_label = f"Next: Fetch Live Data & Review Deltas ({active_count} fields selected) ➔"
            if st.button(btn_label, type="primary", use_container_width=True):
                st.session_state.adhoc_step = 3
                st.rerun()


# ==============================================================================
# STEP 4: REVIEW, LIVE FETCH, DIFF & UPLOAD
# ==============================================================================

def _render_step_4_execution():
    st.markdown("### 4️⃣ Live Sitetracker Fetch, Delta Review & Upload")
    st.caption("Query live records matching your primary keys, validate deltas, and upload directly via Bulk API 2.0.")

    src_df = st.session_state.adhoc_source_df
    obj_name = st.session_state.adhoc_selected_obj
    src_pk = st.session_state.adhoc_source_pk
    sf_pk = st.session_state.adhoc_target_pk
    mappings = st.session_state.adhoc_mappings
    active_prof = get_active_profile()

    active_fields = [
        m.target_field_api for m in mappings
        if m.upload_enabled and m.target_field_api
        and m.target_field_api.lower() != "id"
        and m.source_column != src_pk
        and m.target_field_api != sf_pk
    ]

    st.markdown(
        f"""
        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:14px 18px; margin-bottom:16px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-weight:700; color:#032D60; font-size:1.05rem;">{obj_name}</span>
                    <span style="color:#64748B; font-size:0.9rem; margin-left:8px;">({len(src_df):,} source records)</span>
                </div>
                <div>
                    <span style="font-size:0.85rem; color:#64748B;">Identifier: </span>
                    <code style="background:#F1F5F9; padding:2px 6px; border-radius:4px;">{src_pk} ➔ {sf_pk}</code>
                    <span style="margin-left:12px; font-size:0.85rem; color:#64748B;">Updating: </span>
                    <b>{len(active_fields)} fields</b>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # 1. Trigger Live Fetch & Delta Calculation
    col_trigger, col_back = st.columns([3, 1])
    with col_trigger:
        btn_calc = st.button(
            "⚡ 1-Click: Fetch Live Sitetracker Data & Compute Deltas",
            type="primary",
            use_container_width=True,
            key="btn_run_adhoc_engine",
        )
    with col_back:
        if st.button("⬅ Adjust Mappings", use_container_width=True):
            st.session_state.adhoc_step = 2
            st.rerun()

    if btn_calc:
        with st.spinner("Executing URL-safe live SOQL query against Salesforce..."):
            try:
                pk_values = src_df[src_pk].dropna().tolist()
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
                )
                engine = ManualLoadEngine(cfg)
                res = engine.run(src_df, live_df)
                st.session_state.adhoc_run_result = res
                changes_count = len(_safe_read_csv(res.artifacts.get("field_level_changes")))
                st.success(f"Completed! Found {res.changed_records} records with updates ({changes_count} field changes).")

            except Exception as e:
                st.error(f"Execution failed: {e}")
                logger.exception("Ad-hoc engine execution error")
                return

    # Display Results if Available
    res: AdhocRunResult = st.session_state.adhoc_run_result
    if res is not None and res.object_name == obj_name:
        st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
        st.markdown("#### 📊 Execution Delta Metrics")

        k_col1, k_col2, k_col3, k_col4 = st.columns(4)
        with k_col1:
            st.markdown(render_kpi_card("Total Source Rows", f"{res.total_source_rows:,}", "Processed records", "default"), unsafe_allow_html=True)
        with k_col2:
            st.markdown(render_kpi_card("Records to Update", f"{res.changed_records:,}", "Deltas identified", "success"), unsafe_allow_html=True)
        with k_col3:
            st.markdown(render_kpi_card("Validation Errors", f"{res.error_rows:,}", "Quarantined rows", "error" if res.error_rows > 0 else "default"), unsafe_allow_html=True)
        with k_col4:
            st.markdown(render_kpi_card("Unchanged / Skipped", f"{res.unchanged_records + res.skipped_pks:,}", "No update required", "default"), unsafe_allow_html=True)

        # Tabs for Visual Review
        tab_changes, tab_grid, tab_errors, tab_summary = st.tabs([
            f"👁️ Field-Level Changes ({res.changed_records} records)",
            "📋 Validation Audit Grid",
            f"🚫 Error Diagnostics ({res.error_rows})",
            "📄 Run Summary",
        ])

        with tab_changes:
            chg_path = res.artifacts.get("field_level_changes")
            chg_df = _safe_read_csv(chg_path)
            if not chg_df.empty:
                st.dataframe(chg_df, use_container_width=True)
            else:
                st.info("No field-level changes detected between spreadsheet and Salesforce.")

        with tab_grid:
            val_path = res.artifacts.get("validation_report")
            val_df = _safe_read_csv(val_path)
            if not val_df.empty:
                badge_map = {
                    "READY_FOR_UPLOAD": "🟢 UPDATE DETECTED",
                    "REJECTED_ERRORS": "🔴 ERROR (REJECTED)",
                    "UNCHANGED": "⚪ UNCHANGED",
                    "DUPLICATE_SKIPPED": "⚠️ DUPLICATE",
                    "SKIPPED": "⚪ NOT IN SALESFORCE",
                }
                status_list = [badge_map.get(str(r.get("Final_Status", "")), f"⚪ {r.get('Final_Status', '')}") for _, r in val_df.iterrows()]
                val_df.insert(0, "Status", status_list)
                st.dataframe(val_df, use_container_width=True)
            else:
                st.info("Validation audit grid is empty.")

        with tab_errors:
            err_path = res.artifacts.get("error_records")
            err_df = _safe_read_csv(err_path)
            if not err_df.empty:
                st.dataframe(err_df, use_container_width=True)
            else:
                st.info("No validation errors found in this run! 🎉")

        with tab_summary:
            sum_path = res.artifacts.get("run_summary")
            if sum_path and sum_path.exists():
                st.code(sum_path.read_text(encoding="utf-8"))

        # Download Hub
        st.markdown("---")
        st.markdown("#### 📥 Download Generated Artifacts")
        d_col1, d_col2, d_col3, d_col4 = st.columns(4)

        final_path = res.artifacts.get("final_input_file")
        if final_path and final_path.exists():
            with open(final_path, "rb") as f:
                d_col1.download_button("📥 Final Input File (.csv)", f.read(), file_name="final_input_file.csv", mime="text/csv", use_container_width=True)

        rollback_path = res.artifacts.get("rollback_file")
        if rollback_path and rollback_path.exists():
            with open(rollback_path, "rb") as f:
                d_col2.download_button("🔙 Rollback File (.csv)", f.read(), file_name="rollback_file.csv", mime="text/csv", use_container_width=True)

        if chg_path and chg_path.exists():
            with open(chg_path, "rb") as f:
                d_col3.download_button("👁️ Field Changes (.csv)", f.read(), file_name="field_level_changes.csv", mime="text/csv", use_container_width=True)

        val_path = res.artifacts.get("validation_report")
        if val_path and val_path.exists():
            with open(val_path, "rb") as f:
                d_col4.download_button("📋 Validation Report (.csv)", f.read(), file_name="validation_report.csv", mime="text/csv", use_container_width=True)

        # Push to Salesforce (Bulk API 2.0)
        st.markdown("---")
        st.markdown("#### 🚀 Push to Sitetracker (Salesforce Bulk API 2.0)")
        st.caption(f"Direct asynchronous upload to **{obj_name}** in **{active_prof.title()}**.")

        if res.changed_records == 0:
            st.info("No changes to upload. All spreadsheet records already match Salesforce.")
        else:
            col_up, col_rb = st.columns([2, 1])

            with col_up:
                if st.button("🚀 Upload Changes to Sitetracker (Bulk API 2.0)", type="primary", use_container_width=True):
                    with st.spinner(f"Uploading {res.changed_records} records to {obj_name}..."):
                        try:
                            upload_res = push_delta_to_sitetracker(
                                csv_path=final_path,
                                object_name=obj_name,
                                is_rollback=False,
                            )
                            st.session_state.adhoc_bulk_result = upload_res

                            if upload_res.all_succeeded:
                                st.success(f"🎉 Successfully uploaded all {upload_res.successful_records} records to Salesforce! (Job ID: {upload_res.job_id})")
                            else:
                                st.warning(f"⚠️ Upload completed with {upload_res.successful_records} successes and {upload_res.failed_records} failures. (Job ID: {upload_res.job_id})")
                                if upload_res.failures:
                                    st.dataframe(pd.DataFrame(upload_res.failures), use_container_width=True)

                        except Exception as e:
                            st.error(f"Bulk upload failed: {e}")

            with col_rb:
                if st.button("🔙 1-Click Rollback / Revert", use_container_width=True, help="Reverts uploaded records back to their original Sitetracker values using the rollback file."):
                    if not rollback_path or not rollback_path.exists():
                        st.error("No rollback file available for this run.")
                    else:
                        with st.spinner("Executing 1-click rollback via Bulk API 2.0..."):
                            try:
                                rb_res = push_delta_to_sitetracker(
                                    csv_path=rollback_path,
                                    object_name=obj_name,
                                    is_rollback=True,
                                )
                                st.session_state.adhoc_rollback_result = rb_res
                                if rb_res.all_succeeded:
                                    st.success(f"✅ Successfully rolled back all {rb_res.successful_records} records! Original values restored.")
                                else:
                                    st.warning(f"Rollback completed with {rb_res.failed_records} errors.")
                            except Exception as e:
                                st.error(f"Rollback failed: {e}")
