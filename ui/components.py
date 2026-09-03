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


@st.dialog("📥 Download Confirmation")
def confirm_download_dialog(file_path, friendly_name: str = "", mime: str = "text/csv"):
    """Modal dialog asking user to confirm before downloading a file."""
    from pathlib import Path
    p = Path(file_path)
    display_name = friendly_name or p.name

    st.write(f"Are you sure you want to download **`{display_name}`**?")
    if p.exists():
        st.caption(f"📄 File: `{p.name}` • Size: `{p.stat().st_size:,} bytes`")
        with open(p, "rb") as f:
            file_bytes = f.read()

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "✅ Yes, Download",
                file_bytes,
                file_name=p.name,
                mime=mime,
                type="primary",
                use_container_width=True
            )
        with c2:
            if st.button("Cancel", use_container_width=True):
                st.rerun()
    else:
        st.error(f"File does not exist: {p}")

