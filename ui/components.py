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
        st.write(f"Do you want to download **`{dl_name}`**?")
        st.caption(f"📁 File size: `{p.stat().st_size:,} bytes`")
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
