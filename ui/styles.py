"""Salesforce Lightning Design System (SLDS) and Dataloader.io styling tokens for Streamlit."""

import streamlit as st

SLDS_CSS = """
<style>
/* =========================================================
   SALESFORCE LIGHTNING DESIGN SYSTEM (SLDS) TOKENS
   ========================================================= */
:root {
    --slds-brand: #0176D3;
    --slds-brand-dark: #014486;
    --slds-navy: #032D60;
    --slds-bg-canvas: #F4F6F9;
    --slds-bg-surface: #FFFFFF;
    --slds-border-subtle: #DDDBDA;
    --slds-border-focus: #1B96FF;
    --slds-text-default: #181818;
    --slds-text-muted: #514F4D;
    --slds-success-text: #04844B;
    --slds-success-bg: #EBF9F1;
    --slds-warning-text: #B45309;
    --slds-warning-bg: #FEF3C7;
    --slds-error-text: #EA001E;
    --slds-error-bg: #FEE8E6;
}

/* Base Body Spacing & Background */
.stApp {
    background-color: var(--slds-bg-canvas);
    color: var(--slds-text-default);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}

/* Header & Typography */
h1, h2, h3, h4 {
    color: var(--slds-navy) !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em;
}

/* =========================================================
   CARDS & CONTAINERS
   ========================================================= */
.slds-card {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02);
    transition: box-shadow 0.2s ease;
}

.slds-card:hover {
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.07), 0 2px 4px -1px rgba(0, 0, 0, 0.04);
}

.slds-card-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #032D60;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.slds-card-subtitle {
    font-size: 0.875rem;
    color: #64748B;
    margin-bottom: 16px;
}

/* =========================================================
   EXECUTIVE KPI TILES
   ========================================================= */
.kpi-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin: 16px 0 24px 0;
}

.kpi-tile {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    border-top: 4px solid #0176D3;
}

.kpi-tile.kpi-success {
    border-top-color: #04844B;
}

.kpi-tile.kpi-warning {
    border-top-color: #FE9339;
}

.kpi-tile.kpi-error {
    border-top-color: #EA001E;
}

.kpi-label {
    font-size: 0.8rem;
    text-transform: uppercase;
    font-weight: 600;
    color: #64748B;
    letter-spacing: 0.04em;
    margin-bottom: 6px;
}

.kpi-value {
    font-size: 1.8rem;
    font-weight: 800;
    color: #0F172A;
    line-height: 1.1;
}

.kpi-sub {
    font-size: 0.8rem;
    color: #94A3B8;
    margin-top: 4px;
}

/* =========================================================
   STATUS PILLS & BADGES
   ========================================================= */
.slds-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.2;
}

.slds-pill-blue {
    background-color: #EBF3FB;
    color: #0176D3;
    border: 1px solid #B0D5F7;
}

.slds-pill-green {
    background-color: #EBF9F1;
    color: #04844B;
    border: 1px solid #A3E7C3;
}

.slds-pill-amber {
    background-color: #FEF3C7;
    color: #B45309;
    border: 1px solid #FDE68A;
}

.slds-pill-red {
    background-color: #FEE8E6;
    color: #EA001E;
    border: 1px solid #FCA5A5;
}

.slds-pill-purple {
    background-color: #F3E8FF;
    color: #7E22CE;
    border: 1px solid #D8B4FE;
}

/* =========================================================
   VISUAL FIELD MAPPING CONNECTORS (DATALOADER STYLE)
   ========================================================= */
.mapping-header {
    display: grid;
    grid-template-columns: 3fr 1.5fr 3fr;
    padding: 10px 16px;
    background-color: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 700;
    font-size: 0.82rem;
    text-transform: uppercase;
    color: #475569;
    letter-spacing: 0.03em;
}

.mapping-list {
    border: 1px solid #E2E8F0;
    border-top: none;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    overflow: hidden;
    margin-bottom: 20px;
}

.mapping-item {
    display: grid;
    grid-template-columns: 3fr 1.5fr 3fr;
    align-items: center;
    padding: 12px 16px;
    background-color: #FFFFFF;
    border-bottom: 1px solid #F1F5F9;
    transition: background-color 0.15s ease;
}

.mapping-item:last-child {
    border-bottom: none;
}

.mapping-item:hover {
    background-color: #F8FAFC;
}

.mapping-source-col {
    font-weight: 600;
    color: #1E293B;
    font-size: 0.92rem;
}

.mapping-source-sample {
    font-size: 0.78rem;
    color: #64748B;
    margin-top: 2px;
}

.mapping-arrow-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
}

.mapping-target-col {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
}

.mapping-target-field {
    font-weight: 700;
    color: #0176D3;
    font-size: 0.92rem;
}

/* =========================================================
   STREAMLIT NATIVE COMPONENT RE-SKINNING
   ========================================================= */
/* Buttons */
.stButton > button[kind="primary"] {
    background-color: #0176D3 !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
    box-shadow: 0 1px 2px rgba(1, 118, 211, 0.2) !important;
    transition: all 0.15s ease-in-out !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: #014486 !important;
    box-shadow: 0 2px 4px rgba(1, 68, 134, 0.3) !important;
    transform: translateY(-1px);
}

.stButton > button[kind="secondary"] {
    background-color: #FFFFFF !important;
    color: #1E293B !important;
    border: 1px solid #CBD5E1 !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    padding: 8px 18px !important;
}

.stButton > button[kind="secondary"]:hover {
    border-color: #94A3B8 !important;
    background-color: #F8FAFC !important;
}

/* Popover */
div[data-testid="stPopover"] > button {
    border-radius: 6px !important;
    font-weight: 600 !important;
}
</style>
"""


def apply_slds_theme():
    """Injects Salesforce Lightning Design System styling into the active Streamlit view."""
    st.markdown(SLDS_CSS, unsafe_allow_html=True)


def render_kpi_card(label: str, value: str | int, subtext: str = "", variant: str = "default") -> str:
    """Returns HTML for an executive KPI metric tile."""
    variant_class = f"kpi-{variant}" if variant in ("success", "warning", "error") else ""
    sub_html = f'<div class="kpi-sub">{subtext}</div>' if subtext else ""
    return f"""
    <div class="kpi-tile {variant_class}">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {sub_html}
    </div>
    """


def render_pill(label: str, color: str = "blue") -> str:
    """Returns HTML for a status pill badge."""
    return f'<span class="slds-pill slds-pill-{color}">{label}</span>'
