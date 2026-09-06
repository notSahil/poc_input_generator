"""Unit tests for Dataloader.io UI styling and pipeline stepper components."""

from unittest.mock import MagicMock, patch
import pytest

from ui.styles import apply_slds_theme, render_kpi_card, render_pill
from ui.components import render_pipeline_stepper, render_step_navigation


def test_render_kpi_card_output():
    """Verify KPI card HTML generation with variants."""
    html = render_kpi_card("Total Rows", 1500, "Scanned records", variant="success")
    assert "Total Rows" in html
    assert "1500" in html
    assert "kpi-success" in html
    assert "Scanned records" in html

    html_default = render_kpi_card("Errors", 0)
    assert "Errors" in html_default
    assert "0" in html_default
    assert "kpi-error" not in html_default


def test_render_pill():
    """Verify status pill badge HTML."""
    pill = render_pill("DATE (UK)", "green")
    assert "slds-pill-green" in pill
    assert "DATE (UK)" in pill


@patch("streamlit.markdown")
def test_apply_slds_theme(mock_markdown):
    """Verify SLDS theme CSS is injected into Streamlit markdown."""
    apply_slds_theme()
    mock_markdown.assert_called_once()
    args, kwargs = mock_markdown.call_args
    assert "--slds-brand: #0176D3" in args[0]
    assert kwargs.get("unsafe_allow_html") is True


@patch("streamlit.columns")
@patch("streamlit.markdown")
def test_render_pipeline_stepper(mock_markdown, mock_columns):
    """Verify native pipeline stepper creates 4 stage columns and renders active step."""
    mock_cols = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    mock_columns.return_value = mock_cols

    selected = render_pipeline_stepper(active_index=1)
    assert selected == 1
    mock_columns.assert_called_once_with(4)


@patch("streamlit.columns")
@patch("streamlit.button")
def test_render_step_navigation_actions(mock_button, mock_columns):
    """Verify navigation buttons trigger prev/next actions."""
    mock_columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
    mock_button.return_value = True

    action = render_step_navigation(current_step=1, total_steps=4, key_prefix="test_nav")
    assert action in ("prev", "next")
