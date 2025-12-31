import streamlit as st

def render():
    #st.title("📤 Data Export")

    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False

    if not st.session_state.logged_in:
        with st.form("login_form"):
            instance = st.selectbox(
                "Select Salesforce Instance",
                ["Partial", "Full Copy", "Production"]
            )

            username = st.text_input("Username")
            password = st.text_input("Password", type="password")

            submitted = st.form_submit_button("Login")

        if submitted:
            if username and password:
                st.session_state.logged_in = True
                st.session_state.instance = instance
                st.success("Login successful")
                st.rerun()
            else:
                st.error("Enter credentials")

        return

    # AFTER LOGIN
    st.success(f"Logged into {st.session_state.instance}")
    st.write("Data export operations will go here")