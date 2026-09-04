"""Streamlit UI page for Salesforce Data Export & OAuth Authentication."""

import logging
import threading
import webbrowser
import streamlit as st

from config import settings
from salesforce.auth import (
    clear_token,
    exchange_code_for_token,
    get_active_profile,
    get_login_url,
    is_oauth_configured,
    is_token_valid,
    load_token,
    save_env_credentials,
    save_manual_token,
    set_active_profile,
    start_oauth_server,
)
from salesforce.metadata import list_objects
from salesforce.userinfo import get_user_info
from ui.components import render_back_button, render_footer, render_header

logger = logging.getLogger(__name__)


def render(go):
    render_header("📤 Salesforce / Sitetracker Connection & Export", "Authenticate via Salesforce OAuth, inspect objects, and extract live data")

    # ==================================================
    # SESSION STATE INITIALIZATION
    # ==================================================
    if "oauth_server_started" not in st.session_state:
        st.session_state.oauth_server_started = False

    # ==================================================
    # ENVIRONMENT (LOCKED TO DEVELOPER SANDBOX)
    # ==================================================
    active_profile = "sandbox"
    set_active_profile("sandbox")
    env_label = "🧪 Sitetracker Developer Sandbox (developer)"

    curr_tok = load_token(profile=active_profile)
    is_conn = curr_tok is not None and is_token_valid(profile=active_profile)

    col_env, col_badge = st.columns([3, 1])
    with col_env:
        st.markdown(f"**Target Environment:** `{env_label}`")
    with col_badge:
        if is_conn:
            st.success("🟢 Connected")
        else:
            st.warning("⚪ Not Connected")

    # ==================================================
    # AUTH CHECK
    # ==================================================
    token = load_token(profile=active_profile)
    logged_in = token is not None and is_token_valid(profile=active_profile)

    if not logged_in:
        st.info("🔐 Please connect your **Sitetracker Developer Sandbox** to continue.")
        st.subheader("⚡ Connect via Session Token")

        with st.form("sandbox_token_form"):
            default_url = "https://sitetracker-bt--developer.sandbox.my.salesforce.com"
            inp_instance = st.text_input(
                "Salesforce Instance URL",
                value=token.get("instance_url", default_url) if token else default_url,
                placeholder="https://sitetracker-bt--developer.sandbox.my.salesforce.com"
            )
            inp_token = st.text_input(
                "Session Token",
                type="password",
                placeholder="Paste Session ID here"
            )
            sub = st.form_submit_button("🔌 Connect to Sandbox", type="primary")

            if sub:
                if not inp_instance or not inp_token:
                    st.error("Please enter both the Instance URL and Session Token.")
                else:
                    try:
                        save_manual_token(inp_token, inp_instance, profile=active_profile)
                        user_info = get_user_info(profile=active_profile)
                        st.success(f"✅ Successfully connected as **{user_info.get('preferred_username', 'User')}**!")
                        st.rerun()
                    except Exception as err:
                        clear_token(profile=active_profile)
                        st.error(f"❌ Connection failed: {err}. Please check your token.")

        render_back_button(go, key="export_back_home")
        render_footer()
        return

    # ==================================================
    # USER & ORG INFO (CONNECTED STATE)
    # ==================================================
    try:
        user_info = get_user_info(profile=active_profile)
    except Exception as e:
        if "Bad_OAuth_Token" in str(e) or "403" in str(e) or "expired" in str(e).lower() or "not authenticated" in str(e).lower():
            clear_token(profile=active_profile)
            st.error("Session expired or token invalid. Please log in again.")
            st.rerun()
            return
        else:
            st.error(f"Failed to fetch user information from Salesforce: {e}")
            render_back_button(go)
            render_footer()
            return

    # Fetch live sandbox details to verify connection
    user_record = {}
    org_data = {}
    site_cnt = "N/A"
    proj_cnt = "N/A"
    try:
        from salesforce.sf_client import get_sf_connection
        sf = get_sf_connection()

        org_res = sf.query("SELECT Id, Name, OrganizationType, IsSandbox, InstanceName, PrimaryContact FROM Organization LIMIT 1")
        if org_res.get("records"):
            org_data = org_res["records"][0]

        uname = user_info.get("preferred_username", "")
        user_res = sf.query(f"SELECT Id, Name, Email, Username, Profile.Name, UserRole.Name, TimeZoneSidKey, LastLoginDate FROM User WHERE Username = '{uname}' LIMIT 1")
        if user_res.get("records"):
            user_record = user_res["records"][0]

        site_cnt = sf.query("SELECT COUNT() FROM sitetracker__Site__c")["totalSize"]
        proj_cnt = sf.query("SELECT COUNT() FROM BT_Project__c")["totalSize"]
    except Exception as ex:
        logger.warning("Could not query extended sandbox info: %s", ex)

    st.success(f"🟢 Connected to **Sitetracker Developer Sandbox** (`{org_data.get('InstanceName', 'developer')}`)")

    col_u, col_o = st.columns(2)

    with col_u:
        st.markdown("#### 👤 User Information")
        st.markdown(f"**Name:** {user_record.get('Name', 'N/A')}")
        st.markdown(f"**Email:** `{user_record.get('Email', 'N/A')}`")
        st.markdown(f"**Username:** `{user_info.get('preferred_username', 'N/A')}`")
        prof_name = user_record.get("Profile", {}).get("Name", "N/A") if user_record.get("Profile") else "N/A"
        st.markdown(f"**Profile:** `{prof_name}`")
        role_name = user_record.get("UserRole", {}).get("Name", "N/A") if user_record.get("UserRole") else "N/A"
        st.markdown(f"**Role:** `{role_name}`")
        st.markdown(f"**Timezone:** `{user_record.get('TimeZoneSidKey', 'Europe/London')}`")

    with col_o:
        st.markdown("#### 🏢 Developer Sandbox Details")
        st.markdown(f"**Organization:** **{org_data.get('Name', 'Sitetracker BT')}** ({org_data.get('OrganizationType', 'Unlimited Edition')})")
        st.markdown(f"**Is Sandbox:** `{'Yes (Developer Sandbox)' if org_data.get('IsSandbox') else 'No'}`")
        st.markdown(f"**Salesforce Pod / Instance:** `{org_data.get('InstanceName', 'SWE128S')}`")
        st.markdown(f"**Organization ID:** `{user_info.get('organization_id', 'N/A')}`")
        st.markdown(f"**Instance URL:** `{token.get('instance_url', 'N/A')}`")
        st.markdown(f"**Live Sitetracker Sites in Org:** `{site_cnt}` record(s)")
        st.markdown(f"**Live BT Projects in Org:** `{proj_cnt}` record(s)")

    st.write("")
    if st.button("🚪 Logout from Salesforce", type="secondary", key="export_logout"):
        clear_token(profile=active_profile)
        st.session_state.oauth_server_started = False
        st.success("Logged out successfully.")
        st.rerun()

    st.divider()
    render_back_button(go)
    render_footer()