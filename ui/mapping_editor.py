"""Streamlit UI page for the Interactive Mapping Editor."""

import logging
import streamlit as st
import pandas as pd
from pathlib import Path

from core.mapping_editor import MappingEditor, EXPECTED_COLUMNS
from ui.components import render_back_button, render_footer, render_header

logger = logging.getLogger(__name__)


def render(go):
    render_header("📝 Interactive Mapping Editor", "Create new report pipelines, edit field mappings, and manage Excel mapping files")

    editor = MappingEditor()

    # ==========================================
    # TAB LAYOUT
    # ==========================================
    tab_create, tab_edit, tab_add, tab_io, tab_history = st.tabs([
        "🚀 Create New Report / Pipeline",
        "✏️ Edit Mappings",
        "➕ Add Single Row",
        "📁 Import / Export Excel",
        "📜 Version History & Restore"
    ])

    # ==========================================
    # TAB 1: CREATE NEW REPORT PIPELINE
    # ==========================================
    with tab_create:
        st.subheader("🚀 Create a Brand New Report Pipeline")
        st.caption("Setup a new report, automatic backend data directories, YAML configuration, and all initial field mappings in one click.")

        col1, col2 = st.columns(2)
        with col1:
            new_pipeline_name = st.text_input("Report Name *", placeholder="e.g. Substation Upgrades", key="new_pipe_name")
            object_name = st.text_input("Salesforce Object Name *", value="Site", key="new_pipe_obj")
        with col2:
            pk_src = st.text_input("Primary Key in Source Excel *", placeholder="e.g. Site ID or Project ID", key="new_pipe_pk_src")
            pk_st = st.text_input("Primary Key in Sitetracker CSV *", placeholder="e.g. Site Number", key="new_pipe_pk_st")
            pk_api = st.text_input("Primary Key Salesforce API Name *", placeholder="e.g. SiteNumber__c", key="new_pipe_pk_api")

        st.markdown("---")
        col_hdr, col_disc = st.columns([3, 2])
        with col_hdr:
            st.markdown("#### Define Additional Field Mappings")
            st.caption("Enter the fields you want to map from your Source Excel to Sitetracker CSV and Salesforce API.")

        with col_disc:
            from salesforce.auth import is_token_valid
            if is_token_valid():
                if st.button("🔍 Auto-Discover Fields from Sitetracker", key="btn_discover_fields"):
                    if not object_name.strip():
                        st.warning("Please enter a Salesforce Object Name first.")
                    else:
                        with st.spinner(f"Fetching fields for {object_name}..."):
                            try:
                                from salesforce.field_discovery import discover_object_fields
                                disc_fields = discover_object_fields(object_name.strip())
                                if disc_fields:
                                    st.session_state.new_pipe_fields = pd.DataFrame(disc_fields)[
                                        ["Source File Column Name", "Sitetracker Field Name", "API Name", "Data Type"]
                                    ]
                                    st.success(f"Discovered {len(disc_fields)} fields from Sitetracker!")
                                    st.rerun()
                                else:
                                    st.warning("No updateable fields found for this object.")
                            except Exception as e:
                                st.error(f"Field discovery failed: {e}")
            else:
                st.caption("🔒 *Log in via 'Data Export' to auto-discover fields from live Sitetracker.*")

        if "new_pipe_fields" not in st.session_state:
            st.session_state.new_pipe_fields = pd.DataFrame([
                {"Source File Column Name": "", "Sitetracker Field Name": "", "API Name": "", "Data Type": "text"},
                {"Source File Column Name": "", "Sitetracker Field Name": "", "API Name": "", "Data Type": "date"},
                {"Source File Column Name": "", "Sitetracker Field Name": "", "API Name": "", "Data Type": "text"},
            ])

        edited_fields = st.data_editor(
            st.session_state.new_pipe_fields,
            num_rows="dynamic",
            use_container_width=True,
            key="new_pipe_fields_editor",
            column_config={
                "Data Type": st.column_config.SelectboxColumn(
                    "Data Type",
                    options=["text", "date", "number", "boolean"],
                    required=True
                )
            }
        )

        if st.button("🚀 Create Report Pipeline & Save Mappings", type="primary", key="btn_create_pipeline"):
            if not new_pipeline_name.strip():
                st.error("❌ Please provide a Report Name.")
            elif not pk_src.strip() or not pk_st.strip() or not pk_api.strip():
                st.error("❌ Please fill in the Primary Key fields for Source, Sitetracker, and Salesforce API.")
            else:
                try:
                    # 1. Scaffold directories and YAML
                    from scripts.scaffold_report import scaffold
                    scaffold(new_pipeline_name.strip())

                    # 2. Build rows for Mapping_file.xlsx
                    rows_to_add = [
                        {
                            "Report Name": new_pipeline_name.strip(),
                            "Object Name": object_name.strip(),
                            "Source File Column Name": pk_src.strip(),
                            "Sitetracker Field Name": pk_st.strip(),
                            "API Name": pk_api.strip(),
                            "Data Type": "text",
                            "Primary Key?": "Yes"
                        }
                    ]

                    # Add non-empty rows from the data editor
                    for _, row in edited_fields.iterrows():
                        src_c = str(row.get("Source File Column Name", "")).strip()
                        st_c = str(row.get("Sitetracker Field Name", "")).strip()
                        api_c = str(row.get("API Name", "")).strip()
                        dtype = str(row.get("Data Type", "text")).strip()

                        if src_c and st_c and api_c:
                            rows_to_add.append({
                                "Report Name": new_pipeline_name.strip(),
                                "Object Name": object_name.strip(),
                                "Source File Column Name": src_c,
                                "Sitetracker Field Name": st_c,
                                "API Name": api_c,
                                "Data Type": dtype,
                                "Primary Key?": "No"
                            })

                    editor.add_rows(rows_to_add)
                    backup = editor.save(reason=f"create_report_{new_pipeline_name.strip()}")

                    st.success(f"🎉 Successfully created new report pipeline **'{new_pipeline_name.strip()}'** with {len(rows_to_add)} mapping fields!")
                    st.info(f"📂 Folders created: `data/{new_pipeline_name.strip().replace(' ', '_')}/input/`\n\n⚙️ Config created: `config/reports/{new_pipeline_name.strip().lower().replace(' ', '_')}.yml`")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creating report pipeline: {e}")

    # ==========================================
    # TAB 2: EDIT EXISTING MAPPINGS
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
    # TAB 3: ADD SINGLE ROW
    # ==========================================
    with tab_add:
        st.subheader("Add a Single Mapping Row")
        st.caption("Add an individual mapping row to an existing report or a new report.")

        reports = editor.get_reports()

        target_type = st.radio(
            "Select Target Report Type",
            ["Existing Report", "New Report Name"],
            horizontal=True,
            key="single_row_target_type"
        )

        col_top1, col_top2 = st.columns(2)
        with col_top1:
            if target_type == "Existing Report":
                if not reports:
                    st.warning("No existing reports found. Please select 'New Report Name'.")
                    selected_rep_name = ""
                else:
                    selected_rep_name = st.selectbox("Select Existing Report *", reports, key="single_row_existing_rep")
            else:
                selected_rep_name = st.text_input("Enter New Report Name *", placeholder="e.g. Substation Upgrades", key="single_row_new_rep")

        with st.form("add_mapping_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                object_name_val = st.text_input("Object Name (e.g. 'Site', 'Project')", value="Site")
                src_col_val = st.text_input("Source File Column Name (exact header in source Excel)")

            with col_b:
                st_field_val = st.text_input("Sitetracker Field Name (header in Sitetracker CSV)")
                api_name_val = st.text_input("Salesforce API Name (e.g. 'SiteNumber__c', 'Name')")
                data_type_val = st.selectbox("Data Type", ["text", "date", "number", "boolean"])
                primary_key_val = st.selectbox("Is Primary Key?", ["No", "Yes"])

            submitted = st.form_submit_button("➕ Add Mapping Row", type="primary")

            if submitted:
                report_name_final = selected_rep_name.strip() if selected_rep_name else ""
                if not report_name_final or not src_col_val.strip() or not st_field_val.strip() or not api_name_val.strip():
                    st.error("Please fill in all required fields (Report Name, Source Col, Sitetracker Field, API Name).")
                else:
                    try:
                        new_row_data = {
                            "Report Name": report_name_final,
                            "Object Name": object_name_val.strip(),
                            "Source File Column Name": src_col_val.strip(),
                            "Sitetracker Field Name": st_field_val.strip(),
                            "API Name": api_name_val.strip(),
                            "Data Type": data_type_val,
                            "Primary Key?": primary_key_val
                        }
                        editor.load()
                        editor.add_row(new_row_data)
                        backup = editor.save(reason=f"add_row_{report_name_final}")

                        # Auto-Scaffold backend folders/yaml if this is a brand new report
                        from scripts.scaffold_report import scaffold
                        from config import settings as app_settings
                        slug = report_name_final.lower().replace(" ", "_")
                        if not (app_settings.CONFIG_DIR / f"{slug}.yml").exists():
                            scaffold(report_name_final)
                            st.success(f"🛠️ Backend data folders and YAML config automatically generated for '{report_name_final}'!")

                        st.success(f"✅ Row added for report '{report_name_final}'! Backup created.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to add row: {e}")

    # ==========================================
    # TAB 4: IMPORT / EXPORT EXCEL
    # ==========================================
    with tab_io:
        st.subheader("📁 Import & Export Excel Mapping File")
        st.caption("Work directly with the central `Mapping_file.xlsx` on your local laptop.")

        col_io1, col_io2 = st.columns(2)
        with col_io1:
            st.markdown("#### 📥 Download Current Mapping File")
            st.write("Download the live `Mapping_file.xlsx` directly to your laptop so you can view or edit it in Microsoft Excel.")
            try:
                with open(editor.file_path, "rb") as f:
                    excel_bytes = f.read()
                st.download_button(
                    label="📥 Download Mapping_file.xlsx",
                    data=excel_bytes,
                    file_name="Mapping_file.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_mapping_file_btn",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error reading mapping file: {e}")

        with col_io2:
            st.markdown("#### 📤 Upload Updated Mapping File")
            st.write("Upload an updated `Mapping_file.xlsx` from your laptop. An automatic backup of the existing file will be preserved.")
            uploaded_map_file = st.file_uploader(
                "Upload Mapping Excel (.xlsx)",
                type=["xlsx"],
                key="upload_mapping_excel"
            )
            if uploaded_map_file is not None:
                if st.button("📤 Apply Uploaded Mapping File", type="primary", key="apply_upload_map_btn", use_container_width=True):
                    try:
                        backup = editor.replace_from_upload(uploaded_map_file)
                        st.success(f"✅ Mapping file successfully replaced! Previous version backed up to `{backup.name}`.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to apply uploaded file: {e}")

    # ==========================================
    # TAB 5: VERSION HISTORY & RESTORE
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
