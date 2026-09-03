"""Shared UI components used across pages."""

import streamlit as st


def render_header(title: str, subtitle: str = ""):
    """Render a consistent page header."""
    st.title(title)
    if subtitle:
        st.caption(subtitle)


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


