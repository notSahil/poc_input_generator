"""Shared UI components used across pages."""

import streamlit as st


def render_header(title: str, subtitle: str = ""):
    """Render a consistent page header."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def render_pipeline_stepper(active_index: int, key: str = "pipeline_stepper") -> int:
    """Renders the Dataloader.io 4-stage pipeline stepper."""
    try:
        import streamlit_antd_components as sac
        items = [
            sac.StepsItem(title="1. Source & Object", description="Select data & live fetch"),
            sac.StepsItem(title="2. Field Mapping", description="Review mapping & schema"),
            sac.StepsItem(title="3. Delta & Validation", description="Run comparison engine"),
            sac.StepsItem(title="4. Review & Ingest", description="5 output files & Bulk API"),
        ]
        selected = sac.steps(
            items=items,
            index=active_index,
            variant="navigation",
            color="blue",
            return_index=True,
            key=key
        )
        return selected if selected is not None else active_index
    except Exception:
        # Fallback to basic HTML stepper if sac cannot render
        step_labels = ["1. Source & Object", "2. Field Mapping", "3. Delta & Validation", "4. Review & Ingest"]
        cols = st.columns(4)
        for i, col in enumerate(cols):
            with col:
                badge = "🔵" if i == active_index else ("✅" if i < active_index else "⚪")
                st.markdown(f"**{badge} {step_labels[i]}**")
        return active_index


def render_step_navigation(
    current_step: int,
    total_steps: int = 4,
    on_prev=None,
    on_next=None,
    next_label: str = "Next Step ➔",
    prev_label: str = "⬅ Previous",
    next_disabled: bool = False,
    key_prefix: str = "step_nav"
):
    """Renders clean Previous / Next buttons anchored at the bottom of wizard steps."""
    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)
    st.divider()
    col_prev, col_spacer, col_next = st.columns([1.5, 3, 1.5])

    with col_prev:
        if current_step > 0 and on_prev:
            st.button(prev_label, on_click=on_prev, key=f"{key_prefix}_prev", use_container_width=True)

    with col_next:
        if current_step < total_steps - 1 and on_next:
            st.button(
                next_label,
                on_click=on_next,
                type="primary",
                disabled=next_disabled,
                key=f"{key_prefix}_next",
                use_container_width=True
            )


def render_footer():
    """Render a consistent page footer."""
    st.divider()
    st.caption("Sitetracker Input File Generator • Internal Tool")


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


