"""Streamlit UI page for Salesforce Data Export & OAuth Authentication."""

import logging
import threading
import webbrowser
from urllib.parse import parse_qs, urlparse
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
    load_profile_credentials,
    pop_pkce_session,
    sanitize_consumer_key,
    save_env_credentials,
    save_profile_credentials,
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
    # ENVIRONMENT PROFILE SELECTOR
    # ==================================================
    curr_active = get_active_profile()
    if curr_active not in settings.PROFILES:
        curr_active = settings.DEFAULT_PROFILE

    profile_options = list(settings.PROFILES.keys())

    st.markdown("### 🌐 Active Salesforce Environment")
    col_env_sel, col_env_stat = st.columns([3, 2])
    with col_env_sel:
        selected_prof = st.radio(
            "Target Environment",
            options=profile_options,
            index=profile_options.index(curr_active),
            format_func=lambda p: settings.PROFILES.get(p, p),
            horizontal=True,
            key="radio_active_env_profile",
            label_visibility="collapsed"
        )

    if selected_prof != curr_active:
        set_active_profile(selected_prof)
        active_profile = selected_prof
        st.rerun()
    else:
        active_profile = curr_active

    env_label = settings.PROFILES.get(active_profile, active_profile)
    curr_tok = load_token(profile=active_profile)
    is_conn = curr_tok is not None and is_token_valid(profile=active_profile)

    with col_env_stat:
        if is_conn:
            st.success(f"🟢 Connected: {env_label}")
        else:
            st.warning(f"⚪ Not Connected: {env_label}")

    # ==================================================
    # AUTH CHECK
    # ==================================================
    token = load_token(profile=active_profile)
    logged_in = token is not None and is_token_valid(profile=active_profile)

    if not logged_in:
        st.info(f"🔐 Please connect your **{env_label}** to continue.")

        tab_oauth, tab_token = st.tabs(["🔑 1-Click OAuth (Connected App)", "⚡ Session Token (Workbench)"])

        # --------------------------------------------------
        # TAB 1: EXTERNAL CLIENT APP OAUTH 2.0
        # --------------------------------------------------
        with tab_oauth:
            st.markdown(f"Enter your **External Client App** credentials to authenticate with **{env_label}**.")

            # Load profile-specific credentials if available
            prof_creds = load_profile_credentials(active_profile)
            saved_remember = st.session_state.get(f"ui_inp_remember_{active_profile}", bool(prof_creds))
            
            default_cid = prof_creds.get("client_id", "")
            if not default_cid and active_profile == "sandbox" and saved_remember:
                default_cid = settings.SF_CLIENT_ID

            default_csec = prof_creds.get("client_secret", "")
            if not default_csec and active_profile == "sandbox" and saved_remember:
                default_csec = settings.SF_CLIENT_SECRET

            if active_profile == "partial":
                default_url = prof_creds.get("login_url", "https://sitetracker-bt--partial.sandbox.my.salesforce.com")
            elif active_profile == "sandbox":
                default_url = prof_creds.get("login_url", "https://test.salesforce.com")
            else:
                default_url = prof_creds.get("login_url", "https://login.salesforce.com")

            inp_cid = st.text_input(
                "Consumer Key (Client ID)",
                value=default_cid,
                placeholder="Paste Consumer Key (e.g. 3MVG93Bty...)",
                key=f"ui_inp_cid_{active_profile}",
                help="Found in Salesforce Setup > External Client App Manager > OAuth Settings"
            )
            inp_csec = st.text_input(
                "Consumer Secret",
                value=default_csec,
                type="password",
                placeholder="Paste Consumer Secret",
                key=f"ui_inp_csec_{active_profile}",
                help="Found in Salesforce Setup > Manage Consumer Details"
            )
            inp_url = st.text_input(
                "Salesforce Login URL",
                value=default_url,
                key=f"ui_inp_url_{active_profile}",
                help="https://test.salesforce.com for Sandboxes or your MyDomain URL"
            )
            remember = st.checkbox(
                "💾 Remember credentials for this environment on this machine",
                value=saved_remember or bool(prof_creds),
                key=f"ui_inp_remember_{active_profile}"
            )

            clean_cid = sanitize_consumer_key(inp_cid)
            clean_csec = (inp_csec or "").strip().strip("'\"")
            clean_url = (inp_url or "").strip() or default_url

            if inp_cid.strip() and clean_cid != inp_cid.strip():
                st.caption("ℹ️ Auto-corrected Consumer Key format (e.g. leading '3').")

            has_creds = bool(clean_cid and clean_csec)

            if has_creds:
                if remember:
                    save_profile_credentials(active_profile, clean_cid, clean_csec, login_url=clean_url)
                    if active_profile == "sandbox":
                        save_env_credentials(clean_cid, clean_csec, login_url=clean_url)

                # Start local callback server in background thread if not already running
                if not st.session_state.oauth_server_started:
                    t = threading.Thread(target=start_oauth_server, args=(settings.OAUTH_CALLBACK_PORT,), daemon=True)
                    t.start()
                    st.session_state.oauth_server_started = True

                # Stabilize OAuth URL: do not generate a new PKCE pair on every Streamlit rerun
                creds_key = (clean_cid, clean_csec, clean_url, active_profile)
                if st.session_state.get("oauth_creds_key") != creds_key or "oauth_url" not in st.session_state:
                    st.session_state["oauth_creds_key"] = creds_key
                    new_url = get_login_url(
                        client_id=clean_cid,
                        client_secret=clean_csec,
                        login_url=clean_url,
                        profile=active_profile
                    )
                    st.session_state["oauth_url"] = new_url
                    parsed_u = urlparse(new_url)
                    qp_u = parse_qs(parsed_u.query)
                    st.session_state["active_oauth_state"] = qp_u.get("state", [""])[0]

                oauth_url = st.session_state["oauth_url"]

                st.divider()
                st.markdown("##### 🚀 Step 2: Authorize & Connect")
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

                # Mobile & Remote Browser Authorization Box
                st.info(
                    "📱 **Logging in from your phone or remote browser? Follow these 3 steps:**\n\n"
                    "1. Tap **🚀 Login with Salesforce** above. Log in and tap **Allow**.\n"
                    "2. Your browser will redirect to `http://localhost:1717/...` and show *'Cannot connect to server'* (or *'This site can't be reached'*). **This is completely normal on mobile or remote servers!**\n"
                    "3. **Tap your phone's address bar, copy that full URL**, switch back here, paste it below, and tap **Complete Login**:"
                )

                manual_code = st.text_input("Paste Redirected URL or Code here", placeholder="http://localhost:1717/oauth/callback?code=...", key="inp_manual_auth_code")
                if st.button("🔌 Complete Login", key="btn_exchange_auth_code", type="primary"):
                    if not manual_code.strip():
                        st.error("Please paste the callback URL or authorization code.")
                    else:
                        raw_input = manual_code.strip().strip("'\"")
                        code_val = raw_input
                        state_val = st.session_state.get("active_oauth_state")
                        if "?" in raw_input:
                            parsed = urlparse(raw_input)
                            qp = parse_qs(parsed.query)
                            code_val = qp.get("code", [raw_input])[0]
                            extracted_state = qp.get("state", [None])[0]
                            if extracted_state:
                                state_val = extracted_state

                        try:
                            sess = pop_pkce_session(state=state_val, profile=active_profile)
                            ver = sess.get("verifier")
                            cid_val = clean_cid or sess.get("client_id", "")
                            csec_val = clean_csec or sess.get("client_secret", "")
                            url_val = clean_url or sess.get("login_url", "") or "https://test.salesforce.com"
                            token_data = exchange_code_for_token(
                                code_val,
                                client_id=cid_val,
                                client_secret=csec_val,
                                login_url=url_val,
                                code_verifier=ver,
                                profile=active_profile
                            )
                            user_info = get_user_info(profile=active_profile)
                            st.success(f"✅ Successfully connected via OAuth 2.0 as **{user_info.get('preferred_username', 'User')}**!")
                            st.session_state.pop("oauth_url", None)
                            st.session_state.pop("active_oauth_state", None)
                            st.session_state.pop("oauth_creds_key", None)
                            st.rerun()
                        except Exception as e:
                            logger.error("OAuth exchange failed: %s", e, exc_info=True)
                            clear_token(profile=active_profile)
                            st.error(f"❌ OAuth exchange failed: {e}")
            else:
                st.info("👆 Please enter your Consumer Key and Consumer Secret above to begin.")

        # --------------------------------------------------
        # TAB 2: WORKBENCH SESSION TOKEN
        # --------------------------------------------------
        with tab_token:
            st.markdown(f"Connect using a temporary session token generated from Salesforce Workbench for **{env_label}**.")
            with st.form(f"env_token_form_{active_profile}"):
                if active_profile == "partial":
                    default_instance_url = "https://sitetracker-bt--partial.sandbox.my.salesforce.com"
                elif active_profile == "sandbox":
                    default_instance_url = "https://sitetracker-bt--developer.sandbox.my.salesforce.com"
                else:
                    default_instance_url = "https://login.salesforce.com"

                inp_instance = st.text_input(
                    "Salesforce Instance URL",
                    value=token.get("instance_url", default_instance_url) if token else default_instance_url,
                    placeholder=default_instance_url
                )
                inp_token = st.text_input(
                    "Session Token",
                    type="password",
                    placeholder="Paste Session ID here"
                )
                sub = st.form_submit_button(f"🔌 Connect to {env_label.split()[1] if len(env_label.split()) > 1 else env_label}", type="primary")

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
    # CONNECTED STATE VIEW
    # ==================================================
    try:
        user_info = get_user_info(profile=active_profile)
    except Exception as e_auth:
        logger.warning("Salesforce session expired or invalid token (%s). Auto-clearing token...", e_auth)
        clear_token(profile=active_profile)
        st.warning("⚠️ Salesforce session has expired or the token is invalid. Please connect again.")
        st.rerun()

    org_data = {}
    user_record = {}
    site_cnt = 0
    proj_cnt = 0

    try:
        from salesforce.sf_client import get_sf_connection
        sf = get_sf_connection(profile=active_profile)
        org_res = sf.query("SELECT Id, Name, OrganizationType, IsSandbox, InstanceName FROM Organization LIMIT 1")
        if org_res.get("records"):
            org_data = org_res["records"][0]

        uname = user_info.get("preferred_username", "").replace("'", "\\'")
        if uname:
            user_res = sf.query(f"SELECT Id, Name, Email, Username, Profile.Name, UserRole.Name, TimeZoneSidKey, LastLoginDate FROM User WHERE Username = '{uname}' LIMIT 1")
            if user_res.get("records"):
                user_record = user_res["records"][0]

        try:
            site_cnt = sf.query("SELECT COUNT() FROM sitetracker__Site__c")["totalSize"]
        except Exception as e_site:
            logger.debug("Could not query sitetracker__Site__c count: %s", e_site)
            site_cnt = 0

        try:
            proj_cnt = sf.query("SELECT COUNT() FROM BT_Project__c")["totalSize"]
        except Exception as e_proj:
            logger.debug("Could not query BT_Project__c count: %s", e_proj)
            proj_cnt = 0
    except Exception as ex:
        logger.warning("Could not query extended sandbox info: %s", ex)

    st.success(f"🟢 Connected to **{env_label}** (`{org_data.get('InstanceName', active_profile)}`)")

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
        st.markdown(f"#### 🏢 {env_label.split()[1] if len(env_label.split()) > 1 else env_label} Details")
        st.markdown(f"**Organization:** **{org_data.get('Name', 'Sitetracker BT')}** ({org_data.get('OrganizationType', 'Unlimited Edition')})")
        st.markdown(f"**Is Sandbox:** `{'Yes (Sandbox)' if org_data.get('IsSandbox') else 'No'}`")
        st.markdown(f"**Salesforce Pod / Instance:** `{org_data.get('InstanceName', 'N/A')}`")
        st.markdown(f"**Organization ID:** `{user_info.get('organization_id', 'N/A')}`")
        st.markdown(f"**Instance URL:** `{token.get('instance_url', 'N/A')}`")
        auth_type = "OAuth 2.0 (Auto-Refresh Active 🔄)" if token.get("refresh_token") else "Session Token (Workbench)"
        st.markdown(f"**Auth Method:** `{auth_type}`")
        st.markdown(f"**Live Sitetracker Sites in Org:** `{site_cnt}` record(s)")
        st.markdown(f"**Live BT Projects in Org:** `{proj_cnt}` record(s)")

    st.write("")
    if st.button(f"🚪 Logout from {env_label.split()[1] if len(env_label.split()) > 1 else env_label}", type="secondary", key=f"export_logout_{active_profile}"):
        clear_token(profile=active_profile)
        st.session_state.oauth_server_started = False
        st.success(f"Logged out from {env_label} successfully.")
        st.rerun()

    st.divider()
    render_back_button(go)
    render_footer()