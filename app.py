"""Main Streamlit Application Router."""

import streamlit as st
from config.logging_config import setup_logging

# Setup root logging
setup_logging()

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
    st.set_page_config(
        page_title="Sitetracker Data Hub",
        page_icon="⚡",
        layout="wide"
    )

    st.title("⚡ Sitetracker Data Hub")
    st.caption("Centralized tool for generating Sitetracker input files, mapping fields, and exporting Salesforce data")

    st.subheader("Select Operation")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.info("### 📥 Data Load Operation\nCompare source spreadsheets with Sitetracker data, compute deltas, and produce validated upload files.")
        st.button(
            "Go to Data Load →",
            use_container_width=True,
            type="primary",
            on_click=go,
            args=("data_load",)
        )

    with col2:
        st.info("### 📜 Run History & Audit\nBrowse past engine executions, re-download historical files, and inspect archived inputs.")
        st.button(
            "Go to Run History →",
            use_container_width=True,
            on_click=go,
            args=("run_history",)
        )

    with col3:
        st.info("### 📝 Mapping Editor\nInteractively edit column mappings, define new data models, and track version history with backups.")
        st.button(
            "Go to Mapping Editor →",
            use_container_width=True,
            on_click=go,
            args=("mapping_editor",)
        )

    with col4:
        st.info("### 📤 Data Export Operation\nAuthenticate with Salesforce OAuth, inspect objects, and extract live Sitetracker records.")
        st.button(
            "Go to Data Export →",
            use_container_width=True,
            on_click=go,
            args=("export_login",)
        )

    st.divider()
    st.caption("Sitetracker Input File Generator • Internal Engineering Tool")


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