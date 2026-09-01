"""Streamlit UI page for Salesforce Data Export."""

import logging
import threading
import webbrowser
import streamlit as st

from config import settings
from salesforce.auth import clear_token, is_token_valid, load_token, start_oauth_server
from salesforce.metadata import list_objects
from salesforce.userinfo import get_user_info
from ui.components import render_back_button, render_footer, render_header

logger = logging.getLogger(__name__)


def render(go):
    render_header("📤 Salesforce Data Export", "Connect to Salesforce/Sitetracker, explore metadata, and extract data")

    # ==================================================
    # SESSION STATE INITIALIZATION
    # ==================================================
    if "oauth_server_started" not in st.session_state:
        st.session_state.oauth_server_started = False

    # ==================================================
    # AUTH CHECK
    # ==================================================
    token = load_token()

    if not token or not is_token_valid():
        st.info("Please log in with your Salesforce / Sitetracker account to continue.")

        if not settings.SF_CLIENT_ID or not settings.SF_CLIENT_SECRET:
            st.warning("⚠️ Salesforce OAuth credentials are not set in `.env`. Please configure `SF_CLIENT_ID` and `SF_CLIENT_SECRET`.")

        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔐 Login with Salesforce", key="sf_login"):
                if not st.session_state.oauth_server_started:
                    threading.Thread(
                        target=start_oauth_server,
                        daemon=True
                    ).start()
                    st.session_state.oauth_server_started = True

                login_url = (
                    f"{settings.SF_LOGIN_URL}/services/oauth2/authorize"
                    f"?response_type=code"
                    f"&client_id={settings.SF_CLIENT_ID}"
                    f"&redirect_uri={settings.SF_REDIRECT_URI}"
                )

                webbrowser.open(login_url)
                st.warning("Complete login in your browser window, then refresh this page.")
                st.stop()

        render_back_button(go, key="export_back_home")
        render_footer()
        return

    # ==================================================
    # USER & ORG INFO
    # ==================================================
    try:
        user_info = get_user_info()
    except Exception as e:
        if "Bad_OAuth_Token" in str(e) or "403" in str(e) or "expired" in str(e).lower():
            clear_token()
            st.error("Session expired or token invalid. Please log in again.")
            st.rerun()
            return
        else:
            st.error(f"Failed to fetch user information from Salesforce: {e}")
            render_back_button(go)
            render_footer()
            return

    st.subheader("🔐 Connected Salesforce User")
    col1, col2 = st.columns(2)

    with col1:
        st.text(f"Username: {user_info.get('preferred_username', 'N/A')}")
        st.text(f"User ID: {user_info.get('user_id', 'N/A')}")

    with col2:
        st.text(f"Org ID: {user_info.get('organization_id', 'N/A')}")
        st.text(f"Instance: {token.get('instance_url', 'N/A')}")

    # ==================================================
    # SALESFORCE OBJECTS
    # ==================================================
    st.subheader("📦 Available Salesforce Objects")

    try:
        objects = list_objects()
        object_df = [
            {
                "API Name": obj.get("name", ""),
                "Label": obj.get("label", ""),
                "Custom": obj.get("custom", False),
                "Queryable": obj.get("queryable", False)
            }
            for obj in objects
        ]
        st.dataframe(object_df, use_container_width=True)
    except Exception as e:
        st.error(f"Failed to load Salesforce objects: {e}")

    # ==================================================
    # ACTIONS
    # ==================================================
    st.subheader("⚡ Data Actions")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("⬇️ Export Data from Object", key="export_data"):
            st.info("Custom SOQL queries and automated exports can be run here.")

    with col2:
        if st.button("🚪 Logout from Salesforce", key="export_logout"):
            clear_token()
            st.session_state.oauth_server_started = False
            st.success("Logged out successfully.")
            st.rerun()

    st.divider()
    render_back_button(go)
    render_footer()