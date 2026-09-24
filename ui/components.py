"""Shared UI components used across pages with Salesforce Lightning Design System styling."""

import streamlit as st


def render_header(title: str, subtitle: str = ""):
    """Render a consistent page header."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def render_pipeline_stepper(active_index: int) -> int:
    """Renders a native, reliable SLDS 4-stage pipeline stepper."""
    steps = [
        ("1. Source & Object", "Select data & fetch"),
        ("2. Field Mapping", "Review column rules"),
        ("3. Delta & Validation", "Compute updates"),
        ("4. Review & Ingest", "Downloads & Bulk API"),
    ]

    selected_step = active_index
    cols = st.columns(4)
    for i, (title, subtitle) in enumerate(steps):
        with cols[i]:
            if i == active_index:
                st.markdown(
                    f"""
                    <div style="background:#EBF3FB; border:2px solid #0176D3; border-radius:8px; padding:10px 12px; text-align:center; min-height:66px;">
                        <div style="font-weight:700; color:#0176D3; font-size:0.9rem;">🔵 {title}</div>
                        <div style="font-size:0.75rem; color:#475569; font-weight:600; margin-top:2px;">Active Step</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            elif i < active_index:
                if st.button(f"✅ {title}", key=f"stepper_jump_{i}", use_container_width=True, help=f"Return to {title}"):
                    selected_step = i
            else:
                st.markdown(
                    f"""
                    <div style="background:#FFFFFF; border:1px solid #CBD5E1; border-radius:8px; padding:10px 12px; text-align:center; min-height:66px; opacity:0.8;">
                        <div style="font-weight:600; color:#64748B; font-size:0.9rem;">⚪ {title}</div>
                        <div style="font-size:0.75rem; color:#94A3B8; margin-top:2px;">{subtitle}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
    st.markdown("<div style='margin-bottom: 18px;'></div>", unsafe_allow_html=True)
    return selected_step


def render_step_navigation(
    current_step: int,
    total_steps: int = 4,
    next_label: str = "Next Step ➔",
    prev_label: str = "⬅ Previous",
    next_disabled: bool = False,
    key_prefix: str = "step_nav"
) -> str | None:
    """
    Renders clean Previous / Next buttons anchored at the bottom of wizard steps.
    Returns 'next' if Next was clicked, 'prev' if Previous was clicked, or None.
    """
    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    st.divider()
    col_prev, col_spacer, col_next = st.columns([1.5, 3, 1.5])

    action = None
    with col_prev:
        if current_step > 0:
            if st.button(prev_label, key=f"{key_prefix}_prev", use_container_width=True):
                action = "prev"

    with col_next:
        if current_step < total_steps - 1:
            if st.button(
                next_label,
                type="primary",
                disabled=next_disabled,
                key=f"{key_prefix}_next",
                use_container_width=True
            ):
                action = "next"

    return action


def render_footer():
    """Render a consistent page footer."""
    st.divider()
    st.caption("Sitetracker Input File Generator • Enterprise Tool")


def render_back_button(go, target: str = "home", label: str = "⬅ Back to Home", key: str | None = None):
    """Render a back navigation button."""
    st.button(label, on_click=go, args=(target,), key=key)


def render_download_with_confirmation(
    container,
    button_label: str,
    file_path,
    download_filename: str = "",
    mime: str = "text/csv",
    help_text: str = "",
    key: str = ""
):
    """
    Renders a rock-solid confirmation popover before allowing file download.
    Guarantees no accidental downloads, no script crashes, and zero screen flicker.
    """
    from pathlib import Path
    p = Path(file_path)
    dl_name = download_filename or p.name

    if not p.exists():
        return

    with container.popover(button_label, use_container_width=True, help=help_text):
        st.markdown("##### 📥 Confirm Download")
        size_bytes = p.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        if size_bytes == 0:
            size_str = "0.00 MB"
        elif size_mb < 0.01:
            size_str = f"{size_mb:.4f} MB"
        else:
            size_str = f"{size_mb:.2f} MB"
        st.caption(f"📁 File size: `{size_str}`")
        with open(p, "rb") as f:
            file_bytes = f.read()
        st.download_button(
            "✅ Yes, Download Now",
            data=file_bytes,
            file_name=dl_name,
            mime=mime,
            type="primary",
            use_container_width=True,
            key=f"dl_btn_{key or dl_name}"
        )


def render_notification_bell(profile: str) -> None:
    """Renders an interactive notification center popover scoped to the active profile."""
    from core import job_store
    job_store.init_db()
    unread_count = job_store.get_unread_count(profile)

    label = f"🔔 ({unread_count})" if unread_count > 0 else "🔔"
    with st.popover(label, help="In-app notification center"):
        st.markdown("##### 🔔 In-App Notifications")
        unreads = job_store.get_unread_notifications(profile, limit=10)

        if not unreads:
            st.caption(f"No unread notifications for {profile} environment.")
        else:
            if st.button("✓ Mark All as Read", key="btn_mark_all_read", use_container_width=True):
                job_store.mark_all_read(profile)
                st.rerun()

            for n in unreads:
                icon = "✅" if n["notification_type"] == "SUCCESS" else ("⚠️" if n["notification_type"] == "WARNING" else ("❌" if n["notification_type"] == "FAILURE" else "ℹ️"))
                created_dt = n["created_at"][:16].replace("T", " ")
                st.markdown(
                    f"""
                    <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:6px; padding:8px 10px; margin-bottom:8px;">
                        <div style="font-weight:700; font-size:0.85rem; color:#032D60;">{icon} {n['title']}</div>
                        <div style="font-size:0.75rem; color:#475569; margin-top:2px;">{n['message']}</div>
                        <div style="font-size:0.7rem; color:#94A3B8; margin-top:4px;">{created_dt} UTC</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def render_active_job_banner(go) -> bool:
    """Renders a prominent SLDS alert banner if a background ingest is currently active.

    Returns True if at least one active job was rendered, False otherwise.
    """
    from datetime import datetime
    from pathlib import Path
    from core import job_store
    from salesforce.job_manager import get_job_progress, is_job_active

    job_store.init_db()
    active_jobs = job_store.get_active_jobs()
    if not active_jobs:
        return False

    rendered_any = False
    for job in active_jobs:
        run_dir_p = Path(job["run_dir"])
        if not is_job_active(run_dir_p):
            continue

        prog = get_job_progress(run_dir_p) or {}
        report_name = job.get("report_name", "Unknown Report")
        profile = job.get("profile", "sandbox")
        is_rb = bool(job.get("is_rollback", False))

        proc = prog.get("processed_records_overall", job.get("processed", 0))
        total = max(1, prog.get("total_records_overall", job.get("total_records", 1)))
        pct = min(100, int((proc / total) * 100))
        c_chunk = prog.get("current_chunk", job.get("current_chunk", 0))
        t_chunk = prog.get("total_chunks", job.get("total_chunks", 0))
        curr_obj = prog.get("current_object", job.get("target_object") or "Salesforce")

        op_name = "Revert / Rollback" if is_rb else "Cloud Ingest"
        chunk_str = f" • Batch {c_chunk}/{t_chunk}" if t_chunk > 0 else ""

        col_text, col_act = st.columns([3.2, 1.2])
        with col_text:
            st.markdown(
                f"""
                <div style="background:#EBF3FB; border:2px solid #0176D3; border-radius:8px; padding:12px 16px; margin-bottom:12px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-size:1.2rem;">⚡</span>
                        <div>
                            <div style="font-weight:700; color:#014486; font-size:0.95rem;">
                                Active {op_name} Running on Server: {report_name} ({profile.title()})
                            </div>
                            <div style="font-size:0.8rem; color:#475569; margin-top:2px;">
                                Target: <b>{curr_obj}</b> • Processed <b>{proc:,} of {total:,}</b> records ({pct}%){chunk_str}
                            </div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with col_act:
            st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)
            if st.button("👁️ View Live Telemetry ➔", key=f"btn_live_telemetry_{job['id']}", type="primary", use_container_width=True):
                st.session_state.active_monitor_job_id = job["id"]
                go("live_monitor")
                st.rerun()

        rendered_any = True

    return rendered_any


def flush_workspace_cache() -> None:
    """Clear transient workspace cache from session_state to prevent cross-environment contamination."""
    keys_to_clear = [
        "preview_df", "source_df", "delta_df", "baseline_records",
        "active_job_run_dir", "cached_soql_records", "step_0_source_df",
        "step_2_diff_df", "step_3_final_df"
    ]
    for k in list(st.session_state.keys()):
        if k in keys_to_clear or k.startswith("cached_user_org_details_"):
            st.session_state.pop(k, None)


def get_cached_profile_details(active_profile: str, force_refresh: bool = False) -> dict:
    """Retrieve and cache extended user & org details in session_state."""
    cache_key = f"cached_user_org_details_{active_profile}"
    if force_refresh or cache_key not in st.session_state:
        from salesforce.userinfo import get_extended_user_and_org_details
        st.session_state[cache_key] = get_extended_user_and_org_details(active_profile)
    return st.session_state[cache_key]


def render_persistent_top_bar(active_profile: str, go: callable) -> None:
    """Renders a persistent top navigation & environment status bar on all authenticated pages."""
    from config import settings
    from salesforce.auth import clear_token, set_active_profile, load_token
    from salesforce.userinfo import get_user_info
    from ui.styles import render_pill

    if active_profile == "partial":
        env_label = "Partial Copy Sandbox"
        env_color = "purple"
    elif active_profile == "sandbox":
        env_label = "Developer Sandbox"
        env_color = "amber"
    elif active_profile == "fullcopy":
        env_label = "Full Copy Sandbox"
        env_color = "teal"
    else:
        env_label = "Production Org"
        env_color = "blue"

    token = load_token(active_profile) or {}
    uname = token.get("username", "")
    if not uname:
        try:
            u_info = get_user_info(active_profile)
            uname = u_info.get("preferred_username", "Salesforce User")
        except Exception:
            uname = "Salesforce User"

    user_display = uname.split("@")[0] if "@" in uname else uname

    col_brand, col_actions = st.columns([1.2, 3.8])
    with col_brand:
        if st.button("⚡ Sitetracker Data Hub", key="top_bar_home_btn", use_container_width=True, help="Return to Home Dashboard"):
            go("home")
            st.rerun()

    with col_actions:
        c_env, c_profile, c_bell, c_switch, c_logout = st.columns([1.5, 1.4, 0.4, 1.0, 0.9])
        with c_env:
            status_dot = '<span style="color:#04844B; font-size:0.75rem; font-weight:700;">● Connected</span>'
            st.markdown(
                f"""
                <div style="display:flex; align-items:center; justify-content:flex-end; gap:6px; margin-top:6px;">
                    {render_pill(env_label, env_color)}
                    {status_dot}
                </div>
                """,
                unsafe_allow_html=True
            )
        with c_profile:
            details = get_cached_profile_details(active_profile)
            user_btn_label = f"👤 {details.get('name', 'User').split()[0]}" if details.get('name') and details.get('name') != "N/A" else f"👤 {user_display}"
            with st.popover(user_btn_label, use_container_width=True, help="Click to view connected Salesforce profile details"):
                st.markdown("##### 👤 Connected User Profile")
                st.markdown(f"**Name:** {details.get('name', 'N/A')}")
                st.markdown(f"**Email:** `{details.get('email', 'N/A')}`")
                st.markdown(f"**Username:** `{details.get('username', 'N/A')}`")
                st.markdown(f"**Profile:** `{details.get('profile_name', 'N/A')}`")
                st.markdown(f"**Role:** `{details.get('role_name', 'N/A')}`")
                st.markdown(f"**Timezone:** `{details.get('timezone', 'Europe/London')}`")
                st.divider()
                st.markdown(f"##### 🏢 {env_label} Details")
                st.markdown(f"**Organization:** **{details.get('org_name', 'Sitetracker BT')}** ({details.get('org_type', 'Enterprise')})")
                st.markdown(f"**Salesforce Pod:** `{details.get('pod', 'N/A')}`")
                st.markdown(f"**Org ID:** `{details.get('org_id', 'N/A')}`")
                st.markdown(f"**Instance URL:** `{details.get('instance_url', 'N/A')}`")
                st.markdown(f"**Auth Method:** `{details.get('auth_method', 'OAuth 2.0')}`")
                st.write("")
                if st.button("🔄 Refresh Details", key="top_bar_refresh_profile_btn", use_container_width=True):
                    get_cached_profile_details(active_profile, force_refresh=True)
                    st.rerun()

        with c_bell:
            render_notification_bell(active_profile)
        with c_switch:
            with st.popover("🔄 Switch Org", use_container_width=True):
                st.markdown("##### 🌐 Switch Salesforce Org")
                profile_keys = list(settings.PROFILES.keys())
                for pk in profile_keys:
                    p_name = settings.PROFILES[pk]
                    is_current = (pk == active_profile)
                    btn_text = f"✓ {p_name}" if is_current else p_name
                    if st.button(btn_text, key=f"top_bar_switch_{pk}", disabled=is_current, use_container_width=True):
                        set_active_profile(pk)
                        flush_workspace_cache()
                        st.rerun()
        with c_logout:
            if st.button("🚪 Logout", key="top_bar_logout_btn", use_container_width=True, help=f"Disconnect from {env_label}"):
                clear_token(profile=active_profile)
                flush_workspace_cache()
                st.rerun()

    st.markdown("<hr style='margin-top:4px; margin-bottom:16px; border:0; border-top:1px solid #E2E8F0;' />", unsafe_allow_html=True)


