"""Dedicated Enterprise Login Gateway for Sitetracker Data Hub with Salesforce Lightning Design System styling."""

import logging
import threading
from urllib.parse import parse_qs, urlparse
import streamlit as st

from config import settings
from salesforce.auth import (
    check_connection_status,
    clear_token,
    exchange_code_for_token,
    get_active_profile,
    get_login_url,
    get_profile_credentials,
    is_token_valid,
    load_profile_credentials,
    load_token,
    pop_pkce_session,
    sanitize_consumer_key,
    save_env_credentials,
    save_manual_token,
    save_profile_credentials,
    set_active_profile,
    start_oauth_server,
)
from salesforce.userinfo import get_user_info
from ui.styles import render_pill

logger = logging.getLogger(__name__)


def render_login_gateway(go: callable, active_profile: str | None = None) -> None:
    """
    Renders the dedicated, enterprise-grade Salesforce Authentication Gateway.
    Zero details or internal operational modules are displayed prior to authentication.
    Pre-populates backend credentials automatically to eliminate manual key entry for users.
    """
    # Initialize background OAuth local listener once
    if "oauth_server_started" not in st.session_state:
        st.session_state.oauth_server_started = False

    current_prof = active_profile or get_active_profile()
    if current_prof not in settings.PROFILES:
        current_prof = settings.DEFAULT_PROFILE

    # Header / Hero Branding
    col_brand, col_status = st.columns([3, 1.2])
    with col_brand:
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 4px;">
                <span style="font-size: 2.2rem;">⚡</span>
                <div>
                    <h1 style="margin: 0; font-size: 1.8rem; color: #032D60;">Sitetracker Data Hub</h1>
                    <div style="font-size: 0.85rem; color: #64748B; font-weight: 500;">Enterprise Salesforce Authentication Gateway</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col_status:
        st.markdown(
            """
            <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:10px 14px; text-align:right;">
                <div style="font-size:0.7rem; font-weight:700; color:#64748B; text-transform:uppercase;">Access Control</div>
                <div style="font-weight:700; color:#EA001E; font-size:0.85rem; margin-top:2px;">
                    🔒 Unauthenticated
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)

    # ==================================================
    # STEP 1: ENVIRONMENT SELECTION
    # ==================================================
    st.markdown("#### 1️⃣ Select Target Salesforce Environment")
    profile_options = list(settings.PROFILES.keys())

    selected_prof = st.radio(
        "Target Salesforce Environment",
        options=profile_options,
        index=profile_options.index(current_prof),
        format_func=lambda p: settings.PROFILES.get(p, p),
        horizontal=True,
        key="login_gateway_env_selector",
        label_visibility="collapsed"
    )

    if selected_prof != current_prof:
        set_active_profile(selected_prof)
        st.rerun()

    env_label = settings.PROFILES.get(selected_prof, selected_prof)
    
    # Determine default login & instance URLs
    default_url = getattr(settings, "DEFAULT_LOGIN_URLS", {}).get(selected_prof, settings.SF_LOGIN_URL)
    prof_creds = load_profile_credentials(selected_prof)
    login_url = prof_creds.get("login_url") or default_url

    # Check backend credentials
    cid, csec = get_profile_credentials(selected_prof)
    clean_cid = sanitize_consumer_key(cid)
    clean_csec = (csec or "").strip().strip("'\"")
    has_backend_creds = bool(clean_cid and clean_csec)

    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)

    # ==================================================
    # STEP 2: AUTHENTICATION METHODS
    # ==================================================
    st.markdown(f"#### 2️⃣ Authenticate to **{env_label}**")

    tab_oauth, tab_workbench = st.tabs([
        "🚀 1-Click Salesforce OAuth (External Client App)",
        "⚡ Session Token (Workbench)"
    ])

    # --------------------------------------------------
    # TAB 1: 1-CLICK OAUTH 2.0
    # --------------------------------------------------
    with tab_oauth:
        if has_backend_creds:
            # Auto-detected credentials: zero typing required!
            st.markdown(
                f"""
                <div style="background:#F0FDF4; border:1px solid #86EFAC; border-radius:8px; padding:12px 16px; margin-bottom:14px;">
                    <div style="color:#166534; font-weight:700; font-size:0.9rem; display:flex; align-items:center; gap:8px;">
                        <span>✅</span> Connected App Pre-configured for {env_label}
                    </div>
                    <div style="color:#15803D; font-size:0.78rem; margin-top:2px;">
                        Login URL: <code>{login_url}</code> • Client ID: <code>{clean_cid[:8]}...{clean_cid[-6:]}</code>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # Start local OAuth listener thread
            if not st.session_state.oauth_server_started:
                t = threading.Thread(target=start_oauth_server, args=(settings.OAUTH_CALLBACK_PORT,), daemon=True)
                t.start()
                st.session_state.oauth_server_started = True

            # Generate or reuse OAuth URL
            creds_key = (clean_cid, clean_csec, login_url, selected_prof)
            if st.session_state.get("oauth_creds_key") != creds_key or "oauth_url" not in st.session_state:
                st.session_state["oauth_creds_key"] = creds_key
                new_url = get_login_url(
                    client_id=clean_cid,
                    client_secret=clean_csec,
                    login_url=login_url,
                    profile=selected_prof
                )
                st.session_state["oauth_url"] = new_url
                parsed_u = urlparse(new_url)
                qp_u = parse_qs(parsed_u.query)
                st.session_state["active_oauth_state"] = qp_u.get("state", [""])[0]

            oauth_url = st.session_state["oauth_url"]

            col_btn, col_check = st.columns([2, 1.2])
            with col_btn:
                st.link_button(
                    "🚀 Login with Salesforce (OAuth 2.0)",
                    oauth_url,
                    type="primary",
                    use_container_width=True
                )
            with col_check:
                if st.button("🔄 Check Connection", key=f"btn_check_oauth_{selected_prof}", use_container_width=True):
                    is_conn, status_msg = check_connection_status(profile=selected_prof, force_check=True)
                    if is_conn:
                        st.success(f"Connected to {env_label}!")
                        st.rerun()
                    else:
                        st.info("Waiting for login authorization to complete in browser...")

            # Remote / Mobile Browser Exchange Box
            with st.expander("📱 Logging in from remote server or mobile? Click here for redirect URL paste", expanded=False):
                st.caption(
                    "1. Click **🚀 Login with Salesforce** above and authorize.\n"
                    "2. If your browser redirects to `http://localhost:1717/...` and says *'Cannot connect'* (normal on remote servers), **copy the full address bar URL**.\n"
                    "3. Paste the URL below and click **Complete Login**:"
                )
                manual_code = st.text_input(
                    "Paste Redirected URL or Code",
                    placeholder="http://localhost:1717/oauth/callback?code=...",
                    key=f"inp_manual_auth_code_{selected_prof}"
                )
                if st.button("🔌 Complete Login", key=f"btn_exchange_auth_{selected_prof}", type="primary"):
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
                            sess = pop_pkce_session(state=state_val, profile=selected_prof)
                            ver = sess.get("verifier")
                            cid_val = clean_cid or sess.get("client_id", "")
                            csec_val = clean_csec or sess.get("client_secret", "")
                            url_val = login_url or sess.get("login_url", "")
                            exchange_code_for_token(
                                code_val,
                                client_id=cid_val,
                                client_secret=csec_val,
                                login_url=url_val,
                                code_verifier=ver,
                                profile=selected_prof
                            )
                            u_info = get_user_info(profile=selected_prof)
                            st.success(f"✅ Successfully authenticated as **{u_info.get('preferred_username', 'User')}**!")
                            st.session_state.pop("oauth_url", None)
                            st.session_state.pop("active_oauth_state", None)
                            st.session_state.pop("oauth_creds_key", None)
                            st.rerun()
                        except Exception as e:
                            logger.error("OAuth exchange failed: %s", e, exc_info=True)
                            clear_token(profile=selected_prof)
                            st.error(f"❌ OAuth exchange failed: {e}")

        else:
            # No credentials pre-configured for this environment: prompt admin setup
            st.info(f"ℹ️ Connected App credentials for **{env_label}** have not been configured yet. Enter them below once to save permanently.")

        # Collapsed expander for updating keys (optional/admin)
        with st.expander("⚙️ Advanced: Configure / Update Connected App Keys", expanded=not has_backend_creds):
            st.caption(f"Update OAuth Consumer Key & Secret for **{env_label}**. Saved securely on this server.")
            inp_cid = st.text_input(
                "Consumer Key (Client ID)",
                value=clean_cid,
                placeholder="Paste Consumer Key (e.g. 3MVG93Bty...)",
                key=f"gateway_inp_cid_{selected_prof}"
            )
            inp_csec = st.text_input(
                "Consumer Secret",
                value=clean_csec,
                type="password",
                placeholder="Paste Consumer Secret",
                key=f"gateway_inp_csec_{selected_prof}"
            )
            inp_url = st.text_input(
                "Salesforce Login URL",
                value=login_url,
                key=f"gateway_inp_url_{selected_prof}"
            )
            remember = st.checkbox(
                "💾 Save credentials permanently on this server",
                value=True,
                key=f"gateway_remember_{selected_prof}"
            )

            if st.button("💾 Save Credentials & Refresh", key=f"btn_save_creds_{selected_prof}", type="secondary"):
                clean_in_cid = sanitize_consumer_key(inp_cid)
                clean_in_csec = (inp_csec or "").strip().strip("'\"")
                clean_in_url = (inp_url or "").strip() or default_url
                if clean_in_cid and clean_in_csec:
                    save_profile_credentials(selected_prof, clean_in_cid, clean_in_csec, login_url=clean_in_url)
                    if selected_prof == "sandbox":
                        save_env_credentials(clean_in_cid, clean_in_csec, login_url=clean_in_url)
                    st.success("✅ Credentials saved! Reloading gateway...")
                    st.rerun()
                else:
                    st.error("Please enter both Client ID and Client Secret.")

    # --------------------------------------------------
    # TAB 2: SESSION TOKEN (WORKBENCH)
    # --------------------------------------------------
    with tab_workbench:
        st.markdown(f"Connect using a temporary session token generated from Salesforce Workbench for **{env_label}**.")
        with st.form(f"gateway_token_form_{selected_prof}"):
            inp_instance = st.text_input(
                "Salesforce Instance URL",
                value=login_url if "salesforce.com" in login_url else default_url,
                placeholder="https://sitetracker-bt--partial.sandbox.my.salesforce.com"
            )
            inp_token = st.text_input(
                "Session Token",
                type="password",
                placeholder="Paste Session ID here"
            )
            sub = st.form_submit_button(f"🔌 Connect to {env_label}", type="primary", use_container_width=True)

            if sub:
                if not inp_instance or not inp_token:
                    st.error("Please enter both the Instance URL and Session Token.")
                else:
                    try:
                        save_manual_token(inp_token, inp_instance, profile=selected_prof)
                        u_info = get_user_info(profile=selected_prof)
                        st.success(f"✅ Successfully connected as **{u_info.get('preferred_username', 'User')}**!")
                        st.rerun()
                    except Exception as err:
                        clear_token(profile=selected_prof)
                        st.error(f"❌ Connection failed: {err}. Please check your token.")

    st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
    st.divider()
    st.caption("Sitetracker Input File Generator • Enterprise Data Operations Platform")
