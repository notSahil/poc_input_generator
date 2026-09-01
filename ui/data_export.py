"""Streamlit UI page for Salesforce Data Export & OAuth Authentication."""

import logging
import threading
import webbrowser
import streamlit as st

from config import settings
from salesforce.auth import (
    clear_token,
    exchange_code_for_token,
    get_login_url,
    is_oauth_configured,
    is_token_valid,
    load_token,
    save_env_credentials,
    save_manual_token,
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
    # AUTH CHECK
    # ==================================================
    token = load_token()
    logged_in = token is not None and is_token_valid()

    if not logged_in:
        st.info("🔐 Please connect your Salesforce / Sitetracker account to continue.")

        tab_oauth, tab_manual_token, tab_config = st.tabs([
            "🔑 Connect via OAuth", "🎟️ Manual Token Input", "⚙️ OAuth Credentials Setup"
        ])

        # --- TAB 1: CONNECT VIA OAUTH ---
        with tab_oauth:
            if not is_oauth_configured():
                st.warning(
                    "⚠️ **OAuth Credentials Missing**: `SF_CLIENT_ID` and `SF_CLIENT_SECRET` are not yet configured.\n\n"
                    "👉 Go to the **⚙️ OAuth Credentials Setup** tab above to enter your Salesforce Connected App credentials."
                )
            else:
                st.write("Click below to log in to your Salesforce / Sitetracker instance:")

                # Ensure callback server is running
                if not st.session_state.oauth_server_started:
                    try:
                        threading.Thread(target=start_oauth_server, daemon=True).start()
                        st.session_state.oauth_server_started = True
                    except Exception as e:
                        logger.warning("Could not start background server: %s", e)

                login_url = get_login_url()

                col_btn, col_refresh = st.columns([1, 1])
                with col_btn:
                    if st.button("🌐 Open Salesforce Login Page", type="primary", key="btn_open_sf"):
                        webbrowser.open(login_url)
                        st.info("Browser window opened. After approving access, click 'Check Login Status' below.")

                with col_refresh:
                    if st.button("🔄 Check Login Status", key="btn_check_login"):
                        st.rerun()

                st.caption(f"Callback redirect URI: `{settings.SF_REDIRECT_URI}`")

                # Manual Auth Code fallback if redirect did not reach server
                with st.expander("Having trouble with the redirect? Enter Auth Code manually"):
                    st.caption("If your browser opened the redirect URL containing `?code=...`, paste the code or full URL below:")
                    auth_input = st.text_input("Paste Authorization Code or Redirect URL", key="manual_auth_code_input")
                    if st.button("Exchange Code", key="btn_exchange_manual"):
                        if auth_input:
                            code = auth_input.strip()
                            if "code=" in code:
                                code = code.split("code=")[1].split("&")[0]
                            try:
                                token_data = exchange_code_for_token(code)
                                from salesforce.auth import save_token
                                save_token(token_data)
                                st.success("✅ Successfully authenticated!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Failed to exchange code: {e}")

        # --- TAB 2: MANUAL TOKEN INPUT ---
        with tab_manual_token:
            st.subheader("Direct Access Token")
            st.caption("If you already have a Bearer token (e.g. from Salesforce CLI `sf org display` or Workbench):")
            with st.form("manual_token_form"):
                inp_instance = st.text_input("Salesforce Instance URL (e.g. https://yourcompany.my.salesforce.com)", value=settings.SF_LOGIN_URL)
                inp_token = st.text_input("Access / Session Token", type="password")
                sub = st.form_submit_button("Save & Connect")
                if sub:
                    if not inp_instance or not inp_token:
                        st.error("Please provide both Instance URL and Access Token.")
                    else:
                        save_manual_token(inp_token, inp_instance)
                        st.success("✅ Token saved!")
                        st.rerun()

        # --- TAB 3: OAUTH CREDENTIALS SETUP ---
        with tab_config:
            st.subheader("Salesforce Connected App Credentials")
            st.caption("Enter your Salesforce Connected App Client ID (Consumer Key) and Client Secret.")

            with st.form("sf_credentials_form"):
                new_client_id = st.text_input("Client ID (Consumer Key)", value=settings.SF_CLIENT_ID)
                new_client_secret = st.text_input("Client Secret (Consumer Secret)", value=settings.SF_CLIENT_SECRET, type="password")
                new_login_url = st.selectbox(
                    "Salesforce Login URL",
                    ["https://login.salesforce.com", "https://test.salesforce.com", "Custom Domain"],
                    index=0 if settings.SF_LOGIN_URL == "https://login.salesforce.com" else (1 if settings.SF_LOGIN_URL == "https://test.salesforce.com" else 2)
                )

                if new_login_url == "Custom Domain":
                    custom_url = st.text_input("Enter Custom Domain (e.g. https://yourcompany.my.salesforce.com)", value=settings.SF_LOGIN_URL)
                    login_url_final = custom_url
                else:
                    login_url_final = new_login_url

                new_redirect_uri = st.text_input("Redirect URI (must match Connected App)", value=settings.SF_REDIRECT_URI)

                submitted = st.form_submit_button("💾 Save Credentials")
                if submitted:
                    if not new_client_id or not new_client_secret:
                        st.error("Please provide both Client ID and Client Secret.")
                    else:
                        save_env_credentials(
                            client_id=new_client_id,
                            client_secret=new_client_secret,
                            login_url=login_url_final,
                            redirect_uri=new_redirect_uri
                        )
                        st.success("✅ Credentials saved to `.env`! You can now log in via the 'Connect via OAuth' tab.")
                        st.rerun()

            st.info(
                "💡 **How to create a Connected App in Salesforce:**\n"
                "1. Go to **Setup** → **App Manager** → **New Connected App**\n"
                "2. Enable **OAuth Settings**\n"
                "3. Set Callback URL to: `http://localhost:1717/oauth/callback`\n"
                "4. Add OAuth Scopes: `Manage user data via APIs (api)`, `Perform requests at any time (refresh_token, offline_access)`\n"
                "5. Save and copy the **Consumer Key** and **Consumer Secret**."
            )

        render_back_button(go, key="export_back_home")
        render_footer()
        return

    # ==================================================
    # USER & ORG INFO (CONNECTED STATE)
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
            st.info("Custom SOQL queries and automated exports can be configured here.")

    with col2:
        if st.button("🚪 Logout from Salesforce", key="export_logout"):
            clear_token()
            st.session_state.oauth_server_started = False
            st.success("Logged out successfully.")
            st.rerun()

    st.divider()
    render_back_button(go)
    render_footer()