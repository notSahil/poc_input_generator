"""Streamlit UI page for Salesforce Data Export & OAuth Authentication."""

import logging
import threading
import webbrowser
import streamlit as st

from config import settings
from salesforce.auth import (
    clear_saved_credentials,
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

        tab_oauth, tab_token = st.tabs(["🔑 1-Click OAuth (Connected App)", "⚡ Session Token (Workbench)"])

        # --------------------------------------------------
        # TAB 1: EXTERNAL CLIENT APP OAUTH 2.0
        # --------------------------------------------------
        with tab_oauth:
            st.markdown("Enter your **External Client App** credentials to authenticate with your Sitetracker Sandbox.")

            # Upfront Credentials Input Form
            with st.form("oauth_login_form"):
                st.markdown("##### 🔑 External Client App Credentials")

                default_cid = st.session_state.get("inp_client_id", settings.SF_CLIENT_ID)
                default_csec = st.session_state.get("inp_client_secret", settings.SF_CLIENT_SECRET)
                default_url = st.session_state.get("inp_login_url", settings.SF_LOGIN_URL)

                inp_cid = st.text_input(
                    "Consumer Key (Client ID)",
                    value=default_cid,
                    placeholder="Enter Consumer Key (e.g. 3MVG93Bty...)",
                    help="Found in Salesforce Setup > External Client App Manager > OAuth Settings"
                )
                inp_csec = st.text_input(
                    "Consumer Secret",
                    value=default_csec,
                    type="password",
                    placeholder="Enter Consumer Secret",
                    help="Found in Salesforce Setup > Manage Consumer Details"
                )
                inp_url = st.text_input(
                    "Salesforce Login URL",
                    value=default_url or "https://test.salesforce.com",
                    help="https://test.salesforce.com for Sandboxes or your MyDomain URL"
                )
                remember = st.checkbox("💾 Remember credentials on this machine", value=False)

                submit_prep = st.form_submit_button("⚡ Prepare Salesforce Login", type="primary")

                if submit_prep:
                    if not inp_cid.strip() or not inp_csec.strip():
                        st.error("Please enter both the Consumer Key and Consumer Secret.")
                    else:
                        st.session_state["inp_client_id"] = inp_cid.strip()
                        st.session_state["inp_client_secret"] = inp_csec.strip()
                        st.session_state["inp_login_url"] = inp_url.strip()
                        st.session_state["remember_creds"] = remember

                        settings.SF_CLIENT_ID = inp_cid.strip()
                        settings.SF_CLIENT_SECRET = inp_csec.strip()
                        settings.SF_LOGIN_URL = inp_url.strip()

                        if remember:
                            save_env_credentials(inp_cid, inp_csec, login_url=inp_url)
                        else:
                            clear_saved_credentials()
                            settings.SF_CLIENT_ID = inp_cid.strip()
                            settings.SF_CLIENT_SECRET = inp_csec.strip()
                            settings.SF_LOGIN_URL = inp_url.strip()

                        st.session_state["oauth_ready"] = True
                        st.session_state["oauth_url"] = get_login_url(
                            client_id=inp_cid.strip(),
                            login_url=inp_url.strip(),
                            profile=active_profile
                        )
                        st.success("Credentials ready! Click the button below to authorize.")
                        st.rerun()

            active_cid = st.session_state.get("inp_client_id", settings.SF_CLIENT_ID)
            active_csec = st.session_state.get("inp_client_secret", settings.SF_CLIENT_SECRET)

            if active_cid and active_csec:
                # Start local callback server in background thread if not already running
                if not st.session_state.oauth_server_started:
                    t = threading.Thread(target=start_oauth_server, args=(settings.OAUTH_CALLBACK_PORT,), daemon=True)
                    t.start()
                    st.session_state.oauth_server_started = True

                oauth_url = st.session_state.get("oauth_url") or get_login_url(
                    client_id=active_cid,
                    login_url=st.session_state.get("inp_login_url", settings.SF_LOGIN_URL),
                    profile=active_profile
                )

                st.divider()
                st.markdown("##### 🚀 Step 2: Authorize in Salesforce")
                col_btn, col_check = st.columns([2, 1])
                with col_btn:
                    st.link_button(
                        "🚀 Login with Salesforce (OAuth 2.0)",
                        oauth_url,
                        type="primary",
                        use_container_width=True
                    )
                with col_check:
                    if st.button("🔄 Check Connection", key="btn_check_oauth", use_container_width=True):
                        tok = load_token(profile=active_profile)
                        if tok and is_token_valid(profile=active_profile):
                            st.success("Connected!")
                            st.rerun()
                        else:
                            st.info("Waiting for login to complete in your browser...")

                # Manual Code Fallback (for corporate proxy / firewall environments)
                with st.expander("📋 Manual Authorization Code (If browser didn't redirect automatically)", expanded=False):
                    st.caption("If your browser redirected to a URL starting with `http://localhost:1717/oauth/callback?code=...`, paste the `code` value here:")
                    manual_code = st.text_input("Authorization Code", placeholder="Paste code parameter from URL", key="inp_manual_auth_code")
                    if st.button("🔌 Exchange Code & Connect", key="btn_exchange_auth_code"):
                        if not manual_code.strip():
                            st.error("Please enter the authorization code.")
                        else:
                            try:
                                token_data = exchange_code_for_token(
                                    manual_code.strip(),
                                    client_id=active_cid,
                                    client_secret=active_csec,
                                    login_url=st.session_state.get("inp_login_url", settings.SF_LOGIN_URL),
                                    profile=active_profile
                                )
                                user_info = get_user_info(profile=active_profile)
                                st.success(f"✅ Successfully connected via OAuth 2.0 as **{user_info.get('preferred_username', 'User')}**!")
                                st.rerun()
                            except Exception as e:
                                clear_token(profile=active_profile)
                                st.error(f"❌ OAuth exchange failed: {e}")

        # --------------------------------------------------
        # TAB 2: WORKBENCH SESSION TOKEN
        # --------------------------------------------------
        with tab_token:
            st.markdown("Connect using a temporary session token generated from Salesforce Workbench.")
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
        auth_type = "OAuth 2.0 (Auto-Refresh Active 🔄)" if token.get("refresh_token") else "Session Token (Workbench)"
        st.markdown(f"**Auth Method:** `{auth_type}`")
        st.markdown(f"**Live Sitetracker Sites in Org:** `{site_cnt}` record(s)")
        st.markdown(f"**Live BT Projects in Org:** `{proj_cnt}` record(s)")

    st.write("")
    if st.button("🚪 Logout from Salesforce", type="secondary", key="export_logout"):
        clear_token(profile=active_profile)
        if not st.session_state.get("remember_creds", False):
            clear_saved_credentials()
            st.session_state.pop("inp_client_id", None)
            st.session_state.pop("inp_client_secret", None)
            st.session_state.pop("oauth_url", None)
        st.session_state.oauth_server_started = False
        st.success("Logged out successfully.")
        st.rerun()

    st.divider()
    render_back_button(go)
    render_footer()