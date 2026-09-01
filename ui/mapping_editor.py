"""Streamlit UI page for the Interactive Mapping Editor."""

import logging
import streamlit as st
import pandas as pd

from core.mapping_editor import MappingEditor, EXPECTED_COLUMNS
from ui.components import render_back_button, render_footer, render_header

logger = logging.getLogger(__name__)


def render(go):
    render_header("📝 Interactive Mapping Editor", "View, edit, create, and restore field mappings across reports and Salesforce objects")

    editor = MappingEditor()

    # ==========================================
    # TAB LAYOUT
    # ==========================================
    tab_edit, tab_add, tab_history = st.tabs([
        "✏️ Edit Mappings", "➕ Add New Mapping Row", "📜 Version History & Restore"
    ])

    # ==========================================
    # TAB 1: EDIT EXISTING MAPPINGS
    # ==========================================
    with tab_edit:
        try:
            df = editor.load()
        except FileNotFoundError as e:
            st.error(f"Mapping file not found: {e}")
            render_back_button(go)
            render_footer()
            return
        except Exception as e:
            st.error(f"Failed to load mapping file: {e}")
            render_back_button(go)
            render_footer()
            return

        reports = editor.get_reports()
        selected_report = st.selectbox(
            "Filter by Report",
            ["All Reports"] + reports,
            key="edit_report_filter"
        )

        if selected_report != "All Reports":
            display_df = df[df["Report Name"] == selected_report].copy()
        else:
            display_df = df.copy()

        if display_df.empty:
            st.info("No mappings found for this report.")
        else:
            st.caption("💡 Double click any cell to edit. You can add or delete rows directly in the table below.")

            edited_df = st.data_editor(
                display_df,
                use_container_width=True,
                num_rows="dynamic",
                key="mapping_data_editor",
                column_config={
                    "Data Type": st.column_config.SelectboxColumn(
                        "Data Type",
                        help="Field data type for normalization and validation",
                        options=["text", "date", "number", "boolean"],
                        required=True
                    ),
                    "Primary Key?": st.column_config.SelectboxColumn(
                        "Primary Key?",
                        help="Mark 'Yes' if this field is the unique identifier for delta matching",
                        options=["Yes", "No"],
                        required=True
                    )
                }
            )

            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("💾 Save Changes", type="primary", key="save_mapping_btn"):
                    try:
                        if selected_report != "All Reports":
                            full_df = editor.load()
                            other_reports_df = full_df[full_df["Report Name"] != selected_report]
                            merged_df = pd.concat([other_reports_df, edited_df], ignore_index=True)
                            editor._df = merged_df
                        else:
                            editor._df = edited_df

                        backup = editor.save(reason="ui_edit")
                        st.success(f"✅ Mapping file saved successfully! Backup archived to: `{backup.name}`")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save mapping changes: {e}")

    # ==========================================
    # TAB 2: ADD NEW ROW
    # ==========================================
    with tab_add:
        st.subheader("Add a New Mapping Row")
        st.caption("Add a mapping specification between your source file columns and Sitetracker/Salesforce API fields.")

        with st.form("add_mapping_form"):
            reports = editor.get_reports()

            col_a, col_b = st.columns(2)
            with col_a:
                report_choice = st.selectbox("Report Name", ["— New Report Name —"] + reports, index=1 if reports else 0)
                if report_choice == "— New Report Name —":
                    new_report_name = st.text_input("Enter new Report Name (e.g. 'Apollo 10G')")
                    report_name_val = new_report_name
                else:
                    report_name_val = report_choice

                object_name_val = st.text_input("Object Name (e.g. 'Site', 'Project')", value="Site")
                src_col_val = st.text_input("Source File Column Name (exact header in source Excel)")

            with col_b:
                st_field_val = st.text_input("Sitetracker Field Name (header in Sitetracker CSV)")
                api_name_val = st.text_input("Salesforce API Name (e.g. 'SiteNumber__c', 'Name')")
                data_type_val = st.selectbox("Data Type", ["text", "date", "number", "boolean"])
                primary_key_val = st.selectbox("Is Primary Key?", ["No", "Yes"])

            submitted = st.form_submit_button("➕ Add Mapping Row")

            if submitted:
                if not report_name_val or not src_col_val or not st_field_val or not api_name_val:
                    st.error("Please fill in all required fields (Report, Source Col, Sitetracker Field, API Name).")
                else:
                    try:
                        new_row_data = {
                            "Report Name": report_name_val,
                            "Object Name": object_name_val,
                            "Source File Column Name": src_col_val,
                            "Sitetracker Field Name": st_field_val,
                            "API Name": api_name_val,
                            "Data Type": data_type_val,
                            "Primary Key?": primary_key_val
                        }
                        editor.load()
                        editor.add_row(new_row_data)
                        backup = editor.save(reason=f"add_row_{report_name_val}")
                        st.success(f"✅ Row added for report '{report_name_val}'! Backup created.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to add row: {e}")

    # ==========================================
    # TAB 3: VERSION HISTORY & RESTORE
    # ==========================================
    with tab_history:
        st.subheader("Mapping File Version History")
        st.caption("Every save automatically creates an immutable backup. You can restore previous versions at any time.")

        versions = editor.list_history()

        if not versions:
            st.info("No backup versions found yet. Backups will appear here as soon as you save edits.")
        else:
            for v in versions:
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"📄 **{v['filename']}** ({v['size_kb']} KB)")
                with col2:
                    st.write(f"🕒 {v['modified']}")
                with col3:
                    if st.button("🔄 Restore", key=f"restore_{v['filename']}"):
                        try:
                            editor.restore_version(v["path"])
                            st.success(f"✅ Successfully restored version: {v['filename']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to restore version: {e}")

    # ==========================================
    # FOOTER & BACK
    # ==========================================
    st.divider()
    render_back_button(go)
    render_footer()
