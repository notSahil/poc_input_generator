"""Streamlit UI page for Salesforce Data Export."""

import streamlit as st
from ui.components import render_back_button, render_footer, render_header


def render(go):
    """Render the Export Salesforce Data upcoming feature view."""
    render_header(
        "📤 Export Salesforce Data",
        "Direct Salesforce Data Extraction & Snapshot Utility",
    )

    st.markdown(
        """
        <div class="slds-card" style="padding: 28px; text-align: center; margin-top: 16px; margin-bottom: 24px;">
            <div style="font-size: 44px; margin-bottom: 12px;">📤</div>
            <div class="slds-card-title" style="font-size: 20px; font-weight: 700; color: #002D62; margin-bottom: 8px;">
                Export Salesforce Data
            </div>
            <div style="display: inline-block; background: #e8f4fd; color: #0b5cab; font-size: 12px; font-weight: 600; padding: 4px 14px; border-radius: 12px; margin-bottom: 16px; border: 1px solid #b8daff;">
                Upcoming Feature
            </div>
            <p style="color: #4a5568; max-width: 580px; margin: 0 auto 12px auto; font-size: 14px; line-height: 1.6;">
                Direct Salesforce data export, live SOQL extraction pipelines, and automated snapshot utilities are currently under active development.
            </p>
            <p style="color: #718096; font-size: 12px; margin: 0;">
                All active Salesforce sessions and environment switching remain managed through the profile menu on the Home page.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_back_button(go, key="export_back_home")
    render_footer()