import streamlit as st

# ======================
# SESSION INIT
# ======================

if "page" not in st.session_state:
    st.session_state.page = "home"

# ======================
# PAGE ROUTER
# ======================

def go(page_name: str):
    st.session_state.page = page_name

# ======================
# HOME PAGE
# ======================

def render_home():
    st.set_page_config(
        page_title="Salesforce Data Import & Export",
        layout="wide"
    )

    st.title("Salesforce Data Import and Export Task Handler")
    st.caption("Prototype navigation + pages for Importer and Exporter flows")

    st.subheader("Choose Operation")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.button(
            "📥 Data Load Operation",
            use_container_width=True,
            on_click=go,
            args=("data_load",)
        )

    with col2:
        st.button(
            "📤 Data Export Operation",
            use_container_width=True,
            on_click=go,
            args=("export_login",)
        )

# ======================
# ROUTING
# ======================

page = st.session_state.page

if page == "home":
    render_home()

elif page == "data_load":
    from ui.data_load import render
    render(go)

elif page == "export_login":
    from ui.data_export import render
    render()
    st.button("⬅ Back to Home", on_click=go, args=("home",))

else:
    st.error("Unknown page")