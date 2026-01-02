import streamlit as st

def render():
    st.subheader("📤 Data Export")

    # ---------- SESSION INIT ----------
    if "export_logged_in" not in st.session_state:
        st.session_state.export_logged_in = False

    if "sf_instance" not in st.session_state:
        st.session_state.sf_instance = None

    # ---------- LOGIN SCREEN ----------
    if not st.session_state.export_logged_in:
        st.info("Login to Salesforce to continue")

        with st.form("export_login_form"):
            instance = st.selectbox(
                "Select Salesforce Instance",
                ["Partial", "Full Copy", "Production"]
            )

            username = st.text_input("Username")
            password = st.text_input("Password", type="password")

            submit = st.form_submit_button("Login")

        if submit:
            if not username or not password:
                st.error("Username and password are required")
                return

            # ⚠️ PLACEHOLDER: real auth will come later
            # For now we assume credentials are valid
            st.session_state.export_logged_in = True
            st.session_state.sf_instance = instance
            st.session_state.sf_username = username
            st.session_state.sf_password = password

            st.success("Login successful")
            return  # let Streamlit rerun naturally

        return

    # ---------- POST-LOGIN DASHBOARD ----------
    st.success(f"Connected to {st.session_state.sf_instance}")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("⬇️ Export Data from Salesforce"):
            st.info("Export started...")
            # TODO: call export function here
            # export_salesforce_data(...)

    with col2:
        if st.button("⬆️ Run Data Loader Operation"):
            st.info("Data loader triggered...")
            # TODO: reuse your existing engine here

    st.divider()

    if st.button("🚪 Logout"):
        for k in [
            "export_logged_in",
            "sf_instance",
            "sf_username",
            "sf_password"
        ]:
            st.session_state.pop(k, None)

        st.success("Logged out")