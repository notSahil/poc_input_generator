"""Main Streamlit Application Router with Salesforce Lightning Design System styling."""

import streamlit as st
from config.logging_config import setup_logging
from ui.styles import apply_slds_theme, render_pill
from salesforce.auth import check_connection_status, get_active_profile, is_token_valid

# Setup root logging
setup_logging()

# Set global page config once
st.set_page_config(
    page_title="Sitetracker Data Hub",
    page_icon="⚡",
    layout="wide"
)

# Apply global SLDS styling
apply_slds_theme()

# ======================
# SESSION INIT
# ======================

if "page" not in st.session_state:
    st.session_state.page = "home"


# ======================
# PAGE ROUTER
# ======================

def go(page_name: str):
    st.session_state.page = page_name


# ======================
# HOME PAGE
# ======================

def render_home():
    active_prof = get_active_profile()
    is_auth, status_label = check_connection_status(profile=active_prof)
    env_label = "Developer Sandbox" if active_prof == "sandbox" else "Production Org"
    env_color = "amber" if active_prof == "sandbox" else "blue"

    if is_auth:
        status_dot = '<span style="color:#04844B; font-size:0.8rem; font-weight:600;">● Connected</span>'
    elif status_label == "Disconnected":
        status_dot = '<span style="color:#64748B; font-size:0.8rem; font-weight:600;">○ Disconnected</span>'
    else:
        status_dot = f'<span style="color:#EA001E; font-size:0.8rem; font-weight:600;">● {status_label}</span>'

    col_hero, col_status = st.columns([3, 1])
    with col_hero:
        st.title("⚡ Sitetracker Data Hub")
        st.caption("Centralized enterprise workspace for generating Sitetracker input files, mapping schemas, and synchronizing Salesforce records.")

    with col_status:
        st.markdown(
            f"""
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:12px 16px; text-align:right;">
                <div style="font-size:0.75rem; font-weight:700; color:#64748B; text-transform:uppercase;">Active Environment</div>
                <div style="font-weight:700; color:#032D60; font-size:0.95rem; display:flex; justify-content:flex-end; align-items:center; gap:6px; margin-top:4px;">
                    {render_pill(env_label, env_color)}
                    {status_dot}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
    st.subheader("Select Operation Module")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">📥 Data Ingestion Pipeline</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Guided 4-step wizard comparing spreadsheets against Sitetracker exports, validating schemas, and producing validated upload files.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Launch Data Load ➔",
            use_container_width=True,
            type="primary",
            on_click=go,
            args=("data_load",),
            key="btn_nav_dataload"
        )

    with col2:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">📜 Run History & Audit</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Browse past engine executions, re-download historical 5-file output packages, and inspect archived inputs with full audit logs.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "View Run History ➔",
            use_container_width=True,
            on_click=go,
            args=("run_history",),
            key="btn_nav_history"
        )

    with col3:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">📝 Schema & Mapping Editor</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Interactively view and edit Excel column mappings in real time, configure target models, and manage revision history.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Open Mapping Editor ➔",
            use_container_width=True,
            on_click=go,
            args=("mapping_editor",),
            key="btn_nav_mapping"
        )

    with col4:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 220px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">📤 Salesforce Data Export</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Manage multi-environment OAuth sessions, switch between Sandbox and Production, and query live Sitetracker schemas.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Export & Connect ➔",
            use_container_width=True,
            on_click=go,
            args=("export_login",),
            key="btn_nav_export"
        )

    st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
    st.divider()
    st.caption("Sitetracker Input File Generator • Enterprise Data Operations Platform")


# ======================
# ROUTING
# ======================

page = st.session_state.page

if page == "home":
    render_home()

elif page == "data_load":
    from ui.data_load import render
    render(go)

elif page == "run_history":
    from ui.run_history import render
    render(go)

elif page == "mapping_editor":
    from ui.mapping_editor import render
    render(go)

elif page == "export_login":
    from ui.data_export import render
    render(go)

else:
    st.error(f"Unknown page: {page}")
    st.button("⬅ Back to Home", on_click=go, args=("home",))