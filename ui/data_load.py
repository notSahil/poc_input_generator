"""Streamlit UI page for Data Load / Input File Generation with Dataloader.io guided pipeline."""

from datetime import datetime, timezone, timedelta
import logging
from pathlib import Path
import shutil
import streamlit as st
import pandas as pd

IST = timezone(timedelta(hours=5, minutes=30))


def _format_ist_time(ts: float | datetime | None, include_tz: bool = True) -> str:
    """Format a POSIX timestamp or datetime into India Standard Time (IST, UTC+05:30)."""
    if ts is None:
        return "N/A"
    try:
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST)
        elif isinstance(ts, datetime):
            if ts.tzinfo is None:
                dt = ts.replace(tzinfo=timezone.utc).astimezone(IST)
            else:
                dt = ts.astimezone(IST)
        else:
            return str(ts)
        suffix = " IST" if include_tz else ""
        return dt.strftime(f"%d/%m/%Y %H:%M{suffix}")
    except Exception:
        return "N/A"

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


def _safe_read_csv(path: Path | str | None, **kwargs) -> pd.DataFrame:
    """Safely read CSV files, returning an empty DataFrame if file is missing, empty (0 bytes), or unparseable."""
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
    try:
        return pd.read_csv(p, **kwargs)
    except (pd.errors.EmptyDataError, UnicodeDecodeError, Exception):
        try:
            return pd.read_csv(p, encoding="latin1", engine="python", on_bad_lines="skip", **kwargs)
        except Exception:
            return pd.DataFrame()


def _read_csv_preview(path: Path) -> pd.DataFrame:
    """Safely read CSV files for UI preview handling both UTF-8 and Latin-1 encodings and casting to str."""
    df = _safe_read_csv(path, dtype=str)
    if df.empty:
        return df
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
        label = "Connected" if status_label in ("Connected", "Connected (Cached)") else status_label
        status_dot = f'<span style="color:#04844B; font-size:0.8rem; font-weight:600;">● {label}</span>'
    elif status_label == "Disconnected":
        status_dot = '<span style="color:#64748B; font-size:0.8rem; font-weight:600;">○ Disconnected</span>'
    elif status_label == "Offline":
        status_dot = '<span style="color:#D97706; font-size:0.8rem; font-weight:600;">● Offline</span>'
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
        st.session_state.last_run_result = None
        st.info("💡 Please select a report model above to inspect data sources.")
        return False

    selected_report = report_options[selected_display]
    if st.session_state.get("selected_report") != selected_report:
        st.session_state.last_run_result = None
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
            st.session_state.last_run_result = None
            st.success(f"✅ Loaded **{uploaded_src.name}** successfully!")

        if src_files:
            st.markdown(f"<div style='margin-bottom:8px;'>{render_pill(f'Active Source: {src_files[0]}', 'green')}</div>", unsafe_allow_html=True)
            # Early Header Check: Detect if uploaded source file is missing required Primary Key or mapped fields
            try:
                sf_path = src_dir / src_files[0]
                sample_src_df = DataNormalizer.read_spreadsheet(sf_path, nrows=5)
                s_cols = list(sample_src_df.columns.astype(str).str.strip())
                m_loader = MappingLoader(settings.MAPPING_FILE, selected_report)
                m_df = m_loader.load()
                pk_src_col, pk_st_col = m_loader.primary_keys()
                field_map = m_loader.field_mapping()

                matched_pk = DataNormalizer.resolve_source_column(s_cols, pk_src_col, pk_st_col, None)
                if not matched_pk:
                    for s_c, s_st, s_api, _ in field_map:
                        if s_c == pk_src_col:
                            matched_pk = DataNormalizer.resolve_source_column(s_cols, s_c, s_st, s_api)
                            if matched_pk:
                                break

                unresolved_fields = [
                    s_c for s_c, s_st, s_api, _ in field_map
                    if not DataNormalizer.resolve_source_column(s_cols, s_c, s_st, s_api)
                ]

                if not matched_pk:
                    st.warning(
                        f"⚠️ **Source File Header Mismatch**: Uploaded file `{src_files[0]}` does not contain the expected Primary Key **`{pk_src_col}`** (or `{pk_st_col}`) for {selected_report}.\n\n"
                        f"• **Found in File ({len(s_cols)} cols)**: `{', '.join(s_cols[:6])}`...\n"
                        f"• **Missing Mapped Fields ({len(unresolved_fields)})**: `{', '.join(unresolved_fields[:6])}`...\n\n"
                        f"👉 *You can proceed to Step 2 to customize mappings / ignore fields, or upload the matching file.*"
                    )
                elif unresolved_fields:
                    st.warning(
                        f"⚠️ **Partial Column Match**: Primary key `{matched_pk}` was found, but {len(unresolved_fields)} mapped fields are missing from `{src_files[0]}`:\n\n"
                        f"• **Missing Fields**: `{', '.join(unresolved_fields[:6])}`...\n\n"
                        f"👉 *You can proceed to Step 2 to map them to other columns or skip them.*"
                    )
                elif matched_pk != pk_src_col:
                    st.info(
                        f"ℹ️ **Sitetracker Export Format Detected**: Headers match Sitetracker field names (e.g. Primary Key **`{matched_pk}`**). All {len(field_map)} mapped fields resolved and auto-aliased seamlessly."
                    )
            except Exception:
                pass

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
            st.session_state.last_run_result = None
            st.success(f"✅ Loaded **{uploaded_st.name}** successfully!")

        if st_files:
            active_st_file = st_files[0]
            st_path = st_dir / active_st_file
            is_live_soql = active_st_file.endswith("_sitetracker_live.csv")
            try:
                st_mtime = _format_ist_time(st_path.stat().st_mtime)
            except Exception:
                st_mtime = "N/A"

            if is_live_soql:
                st.markdown(
                    f"""
                    <div style="background:#F0FDF4; border:1px solid #86EFAC; border-radius:8px; padding:10px 12px; margin-bottom:10px;">
                        <div style="display:flex; align-items:center; justify-content:space-between;">
                            <span style="font-size:0.85rem; font-weight:700; color:#166534;">🌐 LIVE SITETRACKER (SOQL QUERY)</span>
                            <span style="background:#DCFCE7; color:#166534; font-size:0.75rem; font-weight:600; padding:2px 8px; border-radius:10px;">● Live Cloud Data</span>
                        </div>
                        <div style="font-size:0.8rem; color:#15803D; margin-top:4px;">
                            Direct query from <b>{env_label}</b> ({st_mtime})<br>
                            File: <code>{active_st_file}</code>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f"""
                    <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:10px 12px; margin-bottom:10px;">
                        <div style="display:flex; align-items:center; justify-content:space-between;">
                            <span style="font-size:0.85rem; font-weight:700; color:#334155;">📁 OFFLINE SPREADSHEET FILE</span>
                            <span style="background:#F1F5F9; color:#475569; font-size:0.75rem; font-weight:600; padding:2px 8px; border-radius:10px;">📁 Disk File</span>
                        </div>
                        <div style="font-size:0.8rem; color:#475569; margin-top:4px;">
                            Offline file loaded from <code>input/sitetracker/</code> (Modified: {st_mtime})<br>
                            File: <code>{active_st_file}</code>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with st.expander(f"👁️ Preview Sitetracker Data ({active_st_file})", expanded=False):
                try:
                    st_view_df = DataNormalizer.read_spreadsheet(st_path, nrows=100)
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
                        st.session_state.last_run_result = None
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

    custom_map_key = f"custom_mapping_{selected_report}"
    is_customized = custom_map_key in st.session_state and st.session_state[custom_map_key] is not None

    try:
        mapping_loader = MappingLoader(settings.MAPPING_FILE, selected_report)
        template_df = mapping_loader.load()
        report_objects = mapping_loader.objects()
        pks = mapping_loader.all_primary_keys()
    except Exception as e:
        st.warning(f"Could not load mapping for '{selected_report}': {e}")
        template_df = pd.DataFrame()
        report_objects = []
        pks = []

    if template_df.empty:
        st.info("No field mappings defined yet for this report. You can configure them in the Mapping Editor.")
        return

    # Use active custom mapping if present, otherwise template
    mapping_df = st.session_state[custom_map_key] if is_customized else template_df

    # Discover columns in active uploaded source spreadsheet (if available)
    src_cols: list[str] = []
    try:
        cfg = YamlConfigLoader.load(selected_report)
        src_dir = settings.DATA_DIR / cfg["folders"]["work_dir"] / cfg["folders"]["source_dir"]
        src_files = [f.name for f in src_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if src_dir.exists() else []
        if src_files:
            s_df = DataNormalizer.read_spreadsheet(src_dir / src_files[0], nrows=5)
            src_cols = [str(c).strip() for c in s_df.columns]
    except Exception:
        pass

    # Custom mapping active banner with 1-click Reset
    if is_customized:
        c_ban1, c_ban2 = st.columns([3, 1])
        with c_ban1:
            st.info("✏️ **Custom Field Mapping Active (Session Override)**: Using your modified field mappings for this run.")
        with c_ban2:
            if st.button("🔄 Reset to Defaults", key=f"btn_banner_reset_map_{selected_report}", use_container_width=True):
                st.session_state[custom_map_key] = None
                for idx in template_df.index:
                    w_key = f"sel_src_col_{selected_report}_{idx}"
                    if w_key in st.session_state:
                        del st.session_state[w_key]
                st.rerun()

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

    # =========================================================
    # UNIFIED INTERACTIVE FIELD MAPPING TABLE (DATALOADER STYLE)
    # =========================================================
    st.markdown("---")
    st.markdown("#### 🗺️ Interactive Field Mapping & Customization")

    if src_cols:
        src_file_label = f" (`{src_files[0]}`)" if src_files else ""
        st.caption(
            f"Columns from your uploaded spreadsheet{src_file_label} are auto-matched below. "
            "You can customize dropdown mappings or choose `[-- Skip / Do Not Update --]` to exclude fields on the fly."
        )
    else:
        st.caption(
            "ℹ️ *Upload a source spreadsheet in Step 1 to populate the column dropdowns and auto-match headers.*"
        )

    # Top Toolbar: Counts + Action Buttons
    col_tb1, col_tb2, col_tb3 = st.columns([2.6, 1.2, 1.2])
    with col_tb1:
        st.markdown(
            f"<div style='padding-top:6px; font-size:0.9rem; color:#334155;'>"
            f"Configuring <b>{len(filtered_df)}</b> of <b>{len(template_df)}</b> target fields"
            f"</div>",
            unsafe_allow_html=True
        )
    with col_tb2:
        btn_apply = st.button(
            "💾 Apply Mapping",
            key=f"btn_apply_map_{selected_report}",
            type="primary",
            use_container_width=True,
            help="Apply and lock this mapping configuration for this session"
        )
    with col_tb3:
        btn_reset = st.button(
            "🔄 Reset Defaults",
            key=f"btn_toolbar_reset_map_{selected_report}",
            use_container_width=True,
            help="Reset all field mappings back to auto-detected defaults"
        )

    # Handle Reset Defaults action
    if btn_reset:
        st.session_state[custom_map_key] = None
        for idx in template_df.index:
            w_key = f"sel_src_col_{selected_report}_{idx}"
            if w_key in st.session_state:
                del st.session_state[w_key]
        st.rerun()

    # Table Header
    hdr_c1, hdr_c2, hdr_c3, hdr_c4 = st.columns([3.2, 1.1, 3.7, 2.0])
    with hdr_c1:
        st.markdown("<span style='font-size:0.8rem; font-weight:700; color:#475569; text-transform:uppercase;'>Sitetracker Target Field & Object</span>", unsafe_allow_html=True)
    with hdr_c2:
        st.markdown("<span style='font-size:0.8rem; font-weight:700; color:#475569; text-transform:uppercase;'>Data Type</span>", unsafe_allow_html=True)
    with hdr_c3:
        st.markdown("<span style='font-size:0.8rem; font-weight:700; color:#475569; text-transform:uppercase;'>Source Column (Your File)</span>", unsafe_allow_html=True)
    with hdr_c4:
        st.markdown("<span style='font-size:0.8rem; font-weight:700; color:#475569; text-transform:uppercase;'>Match Status</span>", unsafe_allow_html=True)

    st.markdown("<hr style='margin: 4px 0 12px 0; border: none; border-bottom: 2px solid #E2E8F0;'>", unsafe_allow_html=True)

    # Render interactive mapping rows
    for idx, r in filtered_df.iterrows():
        tgt_field = str(r.get("Sitetracker Field Name", "")).strip()
        orig_src = str(r.get("Source File Column Name", "")).strip()
        api_name = str(r.get("API Name", "")).strip() if "API Name" in r and pd.notna(r["API Name"]) else ""
        is_pk = str(r.get("Primary Key?", "")).strip().upper() in ("YES", "Y", "TRUE")
        obj_tag = str(r.get("Object Name", "")).strip() if "Object Name" in r and pd.notna(r["Object Name"]) else ""

        # Data type badge
        dtype_val = r.get("Data Type", "TEXT")
        dtype = str(dtype_val).strip().upper() if pd.notna(dtype_val) and str(dtype_val).strip().upper() != "NAN" else "TEXT"
        badge_color = "green" if "DATE" in dtype else ("blue" if "ID" in dtype or "KEY" in dtype else "purple")
        rule_pill = render_pill(dtype, badge_color)

        pk_badge = f'<span style="margin-left:6px;">{render_pill("🔑 PRIMARY KEY", "amber")}</span>' if is_pk else ""
        obj_pill = f'<span style="color:#64748B; font-size:0.8rem; font-weight:500;">Object: {obj_tag}</span>' if obj_tag else ""

        # Dropdown options for this row
        if is_pk:
            row_options = src_cols if src_cols else [orig_src]
        else:
            row_options = ["-- Skip / Do Not Update --"] + src_cols if src_cols else ["-- Skip / Do Not Update --", orig_src]

        # Determine default / active column choice
        curr_mapped = str(mapping_df.loc[idx, "Source File Column Name"]).strip() if idx in mapping_df.index else orig_src
        matched_choice = DataNormalizer.resolve_source_column(src_cols, curr_mapped, tgt_field, api_name)
        if not matched_choice and curr_mapped != orig_src:
            matched_choice = DataNormalizer.resolve_source_column(src_cols, orig_src, tgt_field, api_name)

        w_key = f"sel_src_col_{selected_report}_{idx}"
        if is_customized and curr_mapped in row_options:
            default_target = curr_mapped
        elif matched_choice and matched_choice in row_options:
            default_target = matched_choice
        elif orig_src in row_options:
            default_target = orig_src
        else:
            default_target = row_options[0]

        sel_idx = row_options.index(default_target) if default_target in row_options else 0

        # Row Layout
        row_c1, row_c2, row_c3, row_c4 = st.columns([3.2, 1.1, 3.7, 2.0])
        with row_c1:
            st.markdown(f"**{tgt_field}**{pk_badge}<br>{obj_pill}", unsafe_allow_html=True)
        with row_c2:
            st.markdown(f"<div style='margin-top:6px;'>{rule_pill}</div>", unsafe_allow_html=True)
        with row_c3:
            chosen_col = st.selectbox(
                f"Map to Column for {tgt_field}",
                options=row_options,
                index=sel_idx,
                key=w_key,
                label_visibility="collapsed"
            )
        with row_c4:
            if chosen_col == "-- Skip / Do Not Update --":
                status_badge = render_pill("⏭ Skipped", "default")
            elif src_cols and chosen_col not in src_cols:
                status_badge = render_pill("⚠️ Missing in File", "amber")
            elif chosen_col == orig_src:
                status_badge = render_pill("✅ Exact Match", "green")
            elif matched_choice and chosen_col == matched_choice:
                status_badge = render_pill("✅ Auto-Matched", "blue")
            else:
                status_badge = render_pill("✏️ Custom Mapped", "purple")
            st.markdown(f"<div style='margin-top:6px;'>{status_badge}</div>", unsafe_allow_html=True)

        st.markdown("<div style='border-bottom: 1px solid #F1F5F9; margin: 4px 0 8px 0;'></div>", unsafe_allow_html=True)

    # Bottom Apply Bar for convenience
    if len(filtered_df) > 5:
        b_col1, b_col2 = st.columns([3.8, 1.2])
        with b_col2:
            btn_apply_bottom = st.button(
                "💾 Apply Mapping",
                key=f"btn_apply_map_bottom_{selected_report}",
                type="primary",
                use_container_width=True,
                help="Apply and lock this mapping configuration for this session"
            )
            if btn_apply_bottom:
                btn_apply = True

    # Handle Apply Mapping action
    if btn_apply:
        custom_rows = []
        pk_missing = False
        for idx, r in template_df.iterrows():
            w_key = f"sel_src_col_{selected_report}_{idx}"
            is_pk = str(r.get("Primary Key?", "")).strip().upper() in ("YES", "Y", "TRUE")

            # If row was rendered in UI, get user selection; otherwise preserve existing mapping
            if w_key in st.session_state:
                chosen = st.session_state[w_key]
            elif idx in mapping_df.index:
                chosen = str(mapping_df.loc[idx, "Source File Column Name"]).strip()
            else:
                chosen = str(r.get("Source File Column Name", "")).strip()

            if chosen == "-- Skip / Do Not Update --":
                if is_pk:
                    pk_missing = True
                continue

            r_copy = r.copy()
            r_copy["Source File Column Name"] = chosen
            custom_rows.append(r_copy)

        if pk_missing:
            st.error("❌ Primary Key column cannot be skipped! Please select a valid source column.")
        elif not custom_rows:
            st.error("❌ Cannot apply empty mapping. At least one field must be mapped.")
        else:
            new_cust_df = pd.DataFrame(custom_rows).reset_index(drop=True)
            st.session_state[custom_map_key] = new_cust_df
            st.success("✅ Custom mapping applied for this session!")
            st.rerun()

    # Detailed Table inspection in expander
    with st.expander("📋 View Complete Mapping Table & Rules", expanded=False):
        st.dataframe(mapping_df, use_container_width=True)

    # Pre-flight Validation
    st.markdown("#### 🔍 Pre-Flight Validation Check")
    if st.button("Run Pre-Flight Validation Check", key="btn_preflight_val"):
        try:
            active_cust_df = st.session_state.get(custom_map_key)
            validator = InputValidator(selected_report, custom_mapping_df=active_cust_df)
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

    # Determine baseline source details for clear visibility
    yaml_cfg = YamlConfigLoader.load(selected_report)
    work_dir = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"]
    st_dir = work_dir / yaml_cfg["folders"]["sitetracker_dir"]
    src_dir = work_dir / yaml_cfg["folders"]["source_dir"]

    st_files = [f.name for f in st_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if st_dir.exists() else []
    src_files = [f.name for f in src_dir.iterdir() if f.is_file() and not f.name.startswith(".")] if src_dir.exists() else []

    if st_files:
        active_st_file = st_files[0]
        st_path = st_dir / active_st_file
        is_live_soql = active_st_file.endswith("_sitetracker_live.csv")
        try:
            st_mtime = _format_ist_time(st_path.stat().st_mtime)
        except Exception:
            st_mtime = "N/A"
        src_label = src_files[0] if src_files else "uploaded spreadsheet"

        if is_live_soql:
            badge_html = f"""
            <div style="background:#F0FDF4; border:1px solid #86EFAC; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-size:0.88rem; font-weight:700; color:#166534;">🌐 BASELINE COMPARISON: LIVE SITETRACKER (SOQL QUERY)</div>
                    <div style="font-size:0.8rem; color:#15803D; margin-top:2px;">
                        Comparing <code>{src_label}</code> against live Salesforce data queried at {st_mtime} (<code>{active_st_file}</code>).
                    </div>
                </div>
                <div><span style="background:#DCFCE7; color:#166534; font-size:0.75rem; font-weight:700; padding:3px 10px; border-radius:12px; border:1px solid #BBF7D0;">● Live Cloud Baseline</span></div>
            </div>
            """
        else:
            badge_html = f"""
            <div style="background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:10px 14px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <div style="font-size:0.88rem; font-weight:700; color:#334155;">📁 BASELINE COMPARISON: OFFLINE SPREADSHEET FILE</div>
                    <div style="font-size:0.8rem; color:#475569; margin-top:2px;">
                        Comparing <code>{src_label}</code> against offline baseline file <code>{active_st_file}</code> (Modified on {st_mtime}).
                    </div>
                </div>
                <div><span style="background:#F1F5F9; color:#475569; font-size:0.75rem; font-weight:700; padding:3px 10px; border-radius:12px; border:1px solid #CBD5E1;">📁 Offline Disk Baseline</span></div>
            </div>
            """
        st.markdown(badge_html, unsafe_allow_html=True)

    with st.expander("⚙️ Ingestion & Blank Overwrite Settings", expanded=False):
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
                custom_map = st.session_state.get(f"custom_mapping_{selected_report}")
                engine = InputFileEngine(
                    selected_report,
                    insert_nulls=st.session_state.insert_nulls_toggle,
                    custom_mapping_df=custom_map,
                )
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

    # Display KPI Metrics & Results if result exists and matches active files
    res = st.session_state.last_run_result
    is_stale = False
    stale_reason = ""
    if res is not None and res.report_name == selected_report:
        curr_src = src_files[0] if src_files else ""
        curr_st = st_files[0] if st_files else ""
        if res.source_file_name and curr_src and res.source_file_name != curr_src:
            is_stale = True
            stale_reason = f"Active source spreadsheet changed from `{res.source_file_name}` to `{curr_src}`."
        elif res.sitetracker_file_name and curr_st and res.sitetracker_file_name != curr_st:
            is_stale = True
            stale_reason = f"Active Sitetracker baseline changed from `{res.sitetracker_file_name}` to `{curr_st}`."

    if is_stale:
        st.warning(f"⚠️ **Deltas Out of Date**: {stale_reason} Please click **'🚀 Run Delta Comparison Engine'** above to compute deltas for your latest active files.")
        has_result = False
    else:
        has_result = res is not None and res.report_name == selected_report
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
                val_df = _safe_read_csv(val_file, dtype=str)
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
                chg_df = _safe_read_csv(chg_file, dtype=str)
                if not chg_df.empty:
                    st.dataframe(chg_df, use_container_width=True)
                else:
                    st.info("No field-level changes detected.")

        with tab_errors:
            if err_file.exists():
                err_df = _safe_read_csv(err_file, dtype=str)
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

    # Verify active files match the generated delta run
    yaml_cfg_s4 = YamlConfigLoader.load(selected_report)
    work_dir_s4 = settings.DATA_DIR / yaml_cfg_s4["folders"]["work_dir"]
    src_dir_s4 = work_dir_s4 / yaml_cfg_s4["folders"]["source_dir"]
    st_dir_s4 = work_dir_s4 / yaml_cfg_s4["folders"]["sitetracker_dir"]
    src_files_s4 = [f.name for f in src_dir_s4.iterdir() if f.is_file() and not f.name.startswith(".")] if src_dir_s4.exists() else []
    st_files_s4 = [f.name for f in st_dir_s4.iterdir() if f.is_file() and not f.name.startswith(".")] if st_dir_s4.exists() else []
    curr_src_s4 = src_files_s4[0] if src_files_s4 else ""
    curr_st_s4 = st_files_s4[0] if st_files_s4 else ""

    if (result.source_file_name and curr_src_s4 and result.source_file_name != curr_src_s4) or \
       (result.sitetracker_file_name and curr_st_s4 and result.sitetracker_file_name != curr_st_s4):
        st.warning("⚠️ **Active files have changed since this delta run was calculated.** Please return to **Step 3 (Delta Comparison)** and re-run the Delta Engine to ensure you are uploading the latest data.")
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

    audit_file = result.run_dir / "audit.log"
    if audit_file.exists():
        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
        with st.expander("📜 View Audit Log (audit.log)", expanded=False):
            st.code(audit_file.read_text(encoding="utf-8"), language="text")
            with open(audit_file, "r", encoding="utf-8") as af:
                st.download_button(
                    "📥 Download Audit Log (.log)",
                    af.read(),
                    file_name=f"{selected_report}_audit.log",
                    mime="text/plain",
                    key="btn_download_audit_log_step4",
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
            is_rb = job_info.get("is_rollback", False)
            if is_rb:
                st.markdown("### ⏪ Revert / Rollback in Progress on Server")
            else:
                st.markdown("### ⏳ Ingestion in Progress on Server")

            proc_overall = job_info.get("processed_records_overall", 0)
            total_overall = max(1, job_info.get("total_records_overall", 1))
            pct = min(1.0, proc_overall / total_overall)
            curr_obj = job_info.get("current_object", "Salesforce Objects")
            eng_lbl = "⚡ Lightning REST" if job_info.get("engine") == "composite" else "📦 Bulk API 2.0"
            if is_rb:
                st.progress(pct, text=f"{eng_lbl}: Reverting {curr_obj} — {proc_overall}/{total_overall} records restored ({int(pct * 100)}%)")
            else:
                st.progress(pct, text=f"{eng_lbl}: Ingesting {curr_obj} — {proc_overall}/{total_overall} records ({int(pct * 100)}%)")

            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            if is_rb:
                m_col1.metric("Reverted Records", f"{proc_overall:,} / {total_overall:,}")
                m_col2.metric("Restored", f"{job_info.get('successful_records_overall', 0):,}")
            else:
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
                if is_rb:
                    st.markdown(
                        f"""
                        <div style="background:#EFF6FF; border:1px solid #93C5FD; border-radius:6px; padding:10px 14px; margin: 12px 0; font-size:0.9rem; color:#1E40AF; display:flex; align-items:center; gap:8px;">
                            <span>⏪</span>
                            <div><b>Active In-Flight Revert:</b> Restoring Chunk <b>{c_chunk} of {t_chunk}</b> (Records {r_start} to {r_end} on <b>{curr_obj}</b>)<br>
                            <span style="font-size:0.8rem; color:#1D4ED8;">Restoring original baseline field values to Sitetracker in cloud...</span></div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                else:
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
                rec_label = "restored" if is_rb else "records"
                st.caption(f"{status_icon} **{obj_name}**: {obj_status} ({o_meta.get('processed_records', 0)}/{o_meta.get('total_records', 0)} {rec_label})")

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
            is_rb = job_info.get("is_rollback", False)
            if status == "COMPLETED":
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
                                fail_df = _safe_read_csv(fail_path, dtype=str)
                                st.dataframe(fail_df, use_container_width=True)

                    # Dataloader.io Results Downloads
                    d_succ_p = result.run_dir / "salesforce_success_records.csv"
                    d_err_p = result.run_dir / "salesforce_error_records.csv"
                    if d_succ_p.exists() or d_err_p.exists():
                        col_dl_s, col_dl_e = st.columns(2)
                        with col_dl_s:
                            if d_succ_p.exists():
                                with open(d_succ_p, "rb") as sf:
                                    st.download_button(
                                        "📥 Download Success Records (.csv)",
                                        sf.read(),
                                        file_name="salesforce_success_records.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                        key=f"dl_succ_{obj_name}",
                                    )
                        with col_dl_e:
                            if d_err_p.exists():
                                with open(d_err_p, "rb") as ef:
                                    st.download_button(
                                        "📥 Download Error Records (.csv)",
                                        ef.read(),
                                        file_name="salesforce_error_records.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                        key=f"dl_err_{obj_name}",
                                    )

                # Tier 2: Post-Update Live Verification Report
                pv_rep_path = result.run_dir / "post_update_validation_report.csv"
                pv_disc_path = result.run_dir / "post_update_discrepancies.csv"
                if pv_rep_path.exists():
                    st.markdown("---")
                    st.markdown("### 🔍 Post-Update Live Audit & Reconciliation")
                    st.caption("Verifies whether submitted updates actually persisted or were altered by internal Apex triggers, locked fields, or workflow rules.")
                    pv_df = _safe_read_csv(pv_rep_path, dtype=str)
                    if not pv_df.empty:
                        tot_fields = len(pv_df)
                        ver_cnt = len(pv_df[pv_df["Status"] == "VERIFIED_MATCH"])
                        mut_cnt = len(pv_df[pv_df["Status"] == "TRIGGER_MUTATION"])
                        stale_cnt = len(pv_df[pv_df["Status"].isin(["UNMODIFIED_STALE", "NULL_WIPE_FAILED"])])
                        not_fnd = len(pv_df[pv_df["Status"] == "RECORD_NOT_FOUND"])
                        pct_ver = round((ver_cnt / tot_fields * 100), 1) if tot_fields > 0 else 100.0

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Fields Audited", f"{tot_fields:,}")
                        m2.metric("Verified Match", f"{pct_ver}%", delta=f"{ver_cnt} verified")
                        m3.metric("Trigger Overwrites", f"{mut_cnt}", delta="- Alarmed" if mut_cnt > 0 else None, delta_color="inverse")
                        m4.metric("Stale / Not Saved", f"{stale_cnt + not_fnd}", delta="- Failed" if (stale_cnt + not_fnd) > 0 else None, delta_color="inverse")

                        if pv_disc_path and pv_disc_path.exists():
                            disc_df = _safe_read_csv(pv_disc_path, dtype=str)
                            if not disc_df.empty:
                                with st.expander(f"⚠️ View Discrepancies ({len(disc_df)} fields mutated or un-saved)", expanded=True):
                                    st.warning("The following fields in Salesforce differ from what was submitted. They may have been overwritten by Sitetracker managed package triggers or validation rules.")
                                    st.dataframe(disc_df, use_container_width=True)

                        col_pv1, col_pv2 = st.columns(2)
                        with col_pv1:
                            with open(pv_rep_path, "rb") as f_rep:
                                st.download_button(
                                    "📄 Full Post-Audit Report (.csv)",
                                    f_rep.read(),
                                    file_name="post_update_validation_report.csv",
                                    mime="text/csv",
                                    use_container_width=True,
                                    key="dl_pv_full",
                                )
                        with col_pv2:
                            if pv_disc_path and pv_disc_path.exists():
                                with open(pv_disc_path, "rb") as f_disc:
                                    st.download_button(
                                        "⚠️ Discrepancies Only (.csv)",
                                        f_disc.read(),
                                        file_name="post_update_discrepancies.csv",
                                        mime="text/csv",
                                        use_container_width=True,
                                        key="dl_pv_disc",
                                    )
            else:
                title = "Rollback" if is_rb else "Ingest"
                st.error(f"❌ {title} job failed on server: {job_info.get('error_summary', 'Unknown error')}")

            if not is_rb:
                completed_objects = list(job_info.get("objects", {}).keys())
                if not completed_objects:
                    try:
                        loader_ingest = MappingLoader(settings.MAPPING_FILE, selected_report)
                        completed_objects = loader_ingest.objects()
                    except Exception:
                        completed_objects = []

                has_multi_obj = len(completed_objects) > 1

                # Check if rollback records exist
                has_completed_rb = False
                if has_multi_obj:
                    for obj in completed_objects:
                        c_target = obj.strip().replace(" ", "_")
                        f_rb = result.run_dir / f"rollback_file_{c_target}.csv"
                        if f_rb.exists() and len(_safe_read_csv(f_rb)) > 0:
                            has_completed_rb = True
                            break
                if not has_completed_rb:
                    f_single = result.run_dir / "rollback_file.csv"
                    has_completed_rb = f_single.exists() and len(_safe_read_csv(f_single)) > 0

                if has_completed_rb:
                    st.markdown("---")
                    st.markdown("### ⏪ Emergency Rollback / Revert Safety Net")
                    st.warning("⚠️ **Need to undo this upload?** You can revert all records back to their original Sitetracker values prior to this run.")

                    with st.expander("🔍 Preview Rollback Records (Values to be restored)", expanded=False):
                        if has_multi_obj:
                            rb_tab_list = st.tabs([f"⏪ {obj}" for obj in completed_objects])
                            for obj, tab in zip(completed_objects, rb_tab_list):
                                with tab:
                                    c_target = obj.strip().replace(" ", "_")
                                    rb_file_obj = result.run_dir / f"rollback_file_{c_target}.csv"
                                    if rb_file_obj.exists():
                                        df_rb = _safe_read_csv(rb_file_obj, dtype=str)
                                        st.caption(f"**{len(df_rb):,}** rollback records ready for **{obj}**")
                                        if not df_rb.empty:
                                            st.dataframe(df_rb, use_container_width=True)
                                        else:
                                            st.info(f"0 rollback records for {obj}.")
                                    else:
                                        st.info(f"No rollback records for {obj}.")
                        else:
                            rb_single = result.run_dir / "rollback_file.csv"
                            if rb_single.exists():
                                df_rb = _safe_read_csv(rb_single, dtype=str)
                                st.caption(f"**{len(df_rb):,}** rollback records ready to restore")
                                if not df_rb.empty:
                                    st.dataframe(df_rb, use_container_width=True)
                                else:
                                    st.info("0 rollback records to restore.")

                    col_rb1, col_rb2 = st.columns([2, 1])
                    with col_rb1:
                        confirm_revert_comp = st.text_input(
                            "Type REVERT to enable rollback",
                            placeholder="REVERT",
                            key="input_confirm_completed_revert"
                        )
                    with col_rb2:
                        st.write("")
                        st.write("")
                        revert_enabled = (confirm_revert_comp.strip() == "REVERT")
                        rb_btn_label = "⏪ Execute Rollback for All Objects" if has_multi_obj else "⏪ Execute Rollback Now"
                        if st.button(rb_btn_label, type="secondary", disabled=not revert_enabled, key="btn_execute_completed_revert"):
                            target_obj = None if has_multi_obj else (completed_objects[0] if completed_objects else None)
                            start_background_ingest(
                                run_dir=result.run_dir,
                                report_name=selected_report,
                                is_rollback=True,
                                profile=active_prof,
                                batch_size=15,
                                target_object=target_obj,
                                engine=job_info.get("engine", "composite"),
                            )
                            st.rerun()

            st.markdown("---")
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

    # Baseline source indicator
    st_dir_step4 = settings.DATA_DIR / yaml_cfg["folders"]["work_dir"] / yaml_cfg["folders"]["sitetracker_dir"]
    st_files_step4 = [f.name for f in st_dir_step4.iterdir() if f.is_file() and not f.name.startswith(".")] if st_dir_step4.exists() else []
    if st_files_step4:
        is_live_soql_s4 = st_files_step4[0].endswith("_sitetracker_live.csv")
        st_p_s4 = st_dir_step4 / st_files_step4[0]
        st_mtime_s4 = _format_ist_time(st_p_s4.stat().st_mtime) if st_p_s4.exists() else ""
        time_str_s4 = f" (Queried: {st_mtime_s4})" if (is_live_soql_s4 and st_mtime_s4) else (f" (Modified: {st_mtime_s4})" if st_mtime_s4 else "")
        lbl_s4 = f"🌐 Live Sitetracker SOQL{time_str_s4}" if is_live_soql_s4 else f"📁 Offline Disk File ({st_files_step4[0]}{time_str_s4})"
        st.caption(f"ℹ️ **Baseline Source Used for Deltas**: `{lbl_s4}`")

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
    total_push_records = 0
    if is_multi_obj_push:
        with st.expander(f"📥 Preview Multi-Object Payloads ({len(ingest_objects)} Objects)", expanded=False):
            tab_list = st.tabs([f"📦 {obj}" for obj in ingest_objects])
            for obj, tab in zip(ingest_objects, tab_list):
                with tab:
                    c_target = obj.strip().replace(" ", "_")
                    obj_file = result.run_dir / f"final_input_file_{c_target}.csv"
                    if obj_file.exists():
                        df_obj = _safe_read_csv(obj_file, dtype=str, keep_default_na=False)
                        total_push_records += len(df_obj)
                        st.caption(f"**{len(df_obj):,}** records ready for **{obj}**")
                        if not df_obj.empty:
                            st.dataframe(df_obj, use_container_width=True)
                        else:
                            st.info(f"0 changed records for {obj}.")
                    else:
                        st.info(f"No dedicated payload file generated for {obj}.")
    elif active_push_file.exists():
        final_push_df = _safe_read_csv(active_push_file, dtype=str, keep_default_na=False)
        total_push_records = len(final_push_df)
        if total_push_records > 0:
            with st.expander(f"📥 Preview Payload for {target_obj_push} ({total_push_records:,} Records to be Ingested)", expanded=False):
                st.dataframe(final_push_df, use_container_width=True)
        else:
            st.info(f"ℹ️ **No changes detected for {target_obj_push}**: All records in your source file already match Sitetracker. 0 delta records to upload.")
    else:
        st.info("ℹ️ No payload file found for this run.")

    if total_push_records == 0:
        st.success("✅ **Sitetracker is already up to date!** There are 0 changed records to push.")

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
            key="input_confirm_bulk_push_v2",
            disabled=(total_push_records == 0)
        )

    with col_c2:
        st.write("")
        st.write("")
        push_enabled = (confirm_phrase.strip() == "CONFIRM") and (total_push_records > 0)
        btn_label = "🚀 Ingest All Deltas to Sitetracker" if is_multi_obj_push else f"🚀 Ingest Deltas to {target_obj_push}"
        if total_push_records == 0:
            st.button(btn_label, type="primary", disabled=True, key="btn_execute_bulk_push_v2", help="No changes to upload. All records match Sitetracker.")
        elif st.button(btn_label, type="primary", disabled=not push_enabled, key="btn_execute_bulk_push_v2"):
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
    has_rb = False
    if is_multi_obj_push:
        for obj in ingest_objects:
            c_target = obj.strip().replace(" ", "_")
            f_rb = result.run_dir / f"rollback_file_{c_target}.csv"
            if f_rb.exists() and len(_safe_read_csv(f_rb)) > 0:
                has_rb = True
                break
    elif active_rb_file.exists() and len(_safe_read_csv(active_rb_file)) > 0:
        has_rb = True

    if has_rb:
        with st.expander("⏪ Emergency Rollback / Revert Safety Net", expanded=False):
            st.warning("⚠️ **Safety Net**: Revert pre-change values back into Sitetracker to restore records to how they were prior to this run.")
            if is_multi_obj_push:
                rb_tab_list = st.tabs([f"⏪ {obj}" for obj in ingest_objects])
                for obj, tab in zip(ingest_objects, rb_tab_list):
                    with tab:
                        c_target = obj.strip().replace(" ", "_")
                        rb_file_obj = result.run_dir / f"rollback_file_{c_target}.csv"
                        if rb_file_obj.exists():
                            df_rb = _safe_read_csv(rb_file_obj, dtype=str)
                            st.caption(f"**{len(df_rb):,}** rollback records ready for **{obj}**")
                            if not df_rb.empty:
                                st.dataframe(df_rb, use_container_width=True)
                            else:
                                st.info(f"0 rollback records for {obj}.")
                        else:
                            st.info(f"No rollback records for {obj}.")
            elif active_rb_file.exists():
                rb_df = _safe_read_csv(active_rb_file, dtype=str)
                if not rb_df.empty:
                    st.dataframe(rb_df, use_container_width=True)
                else:
                    st.info("0 rollback records.")

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

    render_header("⚡ Sitetracker Data Ingestion Pipeline", "Automated delta comparison, schema validation, and intelligent Sitetracker synchronization")

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
        try:
            from pathlib import Path
            from core import job_store
            from salesforce.job_manager import is_job_active
            job_store.init_db()
            for aj in job_store.get_active_jobs():
                if is_job_active(Path(aj["run_dir"])):
                    st.info(f"⚡ **Active Ingest in Progress**: A background upload for **{aj['report_name']}** is currently running on the server.")
                    if st.button("👁️ Re-attach to Live Progress ➔", key=f"reattach_dl_{aj['id']}", type="primary"):
                        st.session_state.active_monitor_job_id = aj["id"]
                        go("live_monitor")
                        st.rerun()
                    break
        except Exception:
            pass

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