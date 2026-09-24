"""Main Streamlit Application Router with Salesforce Lightning Design System styling."""

import streamlit as st
from config.logging_config import setup_logging
from ui.components import render_active_job_banner, render_notification_bell, render_persistent_top_bar
from ui.styles import apply_slds_theme, render_pill
from salesforce.auth import check_connection_status, get_active_profile, is_token_valid

from core import job_store

# Setup root logging
setup_logging()

# Initialize persistent job queue & recover interrupted jobs strictly ONCE per server process
@st.cache_resource
def _server_startup_recovery() -> bool:
    job_store.init_db()
    job_store.mark_interrupted_on_startup()
    return True

_server_startup_recovery()

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
# AUTHENTICATION GATEKEEPER
# ======================

active_prof = get_active_profile()
is_auth, status_label = check_connection_status(profile=active_prof)

if not is_auth:
    from ui.login import render_login_gateway
    render_login_gateway(go, active_profile=active_prof)
    st.stop()


# ======================
# HOME PAGE
# ======================

def render_home():
    # Top bar is only shown on the home dashboard
    render_persistent_top_bar(active_prof, go)

    st.title("⚡ Sitetracker Data Hub")
    st.caption("Centralized enterprise workspace for generating Sitetracker input files, mapping schemas, and synchronizing Salesforce records.")

    st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
    # Render in-flight active upload banner if any background jobs are running on server
    render_active_job_banner(go)

    st.subheader("Select Operation Module")


    # Primary Operation Modes
    col_primary1, col_primary2 = st.columns(2)

    with col_primary1:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 200px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">📥 Guided Report Pipeline</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        End-to-end automated pipeline for pre-configured templates (e.g. Apollo 10G, Master Site Listing). Performs smart delta comparison, schema normalization, and validated Sitetracker updates.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Launch Guided Pipeline ➔",
            use_container_width=True,
            type="primary",
            on_click=go,
            args=("data_load",),
            key="btn_nav_dataload"
        )

    with col_primary2:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 200px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">⚡ Ad-Hoc Object Ingestion & Mapping</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Dynamic Schema Synchronization • Upload custom CSV or Excel files, dynamically map to any Sitetracker object, validate field deltas, and synchronize updates with 1-click rollback safety.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Launch Ad-Hoc Ingestion ➔",
            use_container_width=True,
            type="primary",
            on_click=go,
            args=("manual_load",),
            key="btn_nav_adhoc_loader"
        )

    st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
    st.caption("Administrative & Management Utilities")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 190px; display: flex; flex-direction: column; justify-content: space-between;">
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

    with col2:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 190px; display: flex; flex-direction: column; justify-content: space-between;">
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

    with col3:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 190px; display: flex; flex-direction: column; justify-content: space-between;">
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

    with col4:
        st.markdown(
            """
            <div class="slds-card" style="min-height: 190px; display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="slds-card-title">⏰ Task Scheduler</div>
                    <div class="slds-card-subtitle" style="margin-top: 8px;">
                        Automate scheduled delta runs and recurring Salesforce updates with timezone precision and multi-channel notifications.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.button(
            "Open Scheduler ➔",
            use_container_width=True,
            on_click=go,
            args=("task_scheduler",),
            key="btn_nav_scheduler"
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

elif page == "manual_load":
    from ui.manual_loader import render
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

elif page == "task_scheduler":
    from ui.task_scheduler import render
    render(go)

elif page == "live_monitor":
    from ui.live_monitor import render
    render(go)



else:
    st.error(f"Unknown page: {page}")
    st.button("⬅ Back to Home", on_click=go, args=("home",))