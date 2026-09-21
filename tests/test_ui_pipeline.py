"""Unit tests for Dataloader.io UI styling and pipeline stepper components."""

from unittest.mock import MagicMock, patch
import pandas as pd
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


def test_data_load_render_all_steps_no_name_error():
    """Verify data_load.render executes cleanly across all 4 steps without NameError."""
    import ui.data_load

    go_mock = MagicMock()

    class FakeSessionState(dict):
        def __getattr__(self, key):
            return self.get(key)
        def __setattr__(self, key, value):
            self[key] = value

    def mock_cols(spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [MagicMock() for _ in range(count)]

    for step in range(4):
        fake_state = FakeSessionState({
            "data_load_step": step,
            "selected_report": "Apollo 10G",
            "mapping_confirmed": True,
        })

        with patch("streamlit.session_state", fake_state):
            with patch("streamlit.columns", side_effect=mock_cols):
                with patch("streamlit.markdown"):
                    with patch("streamlit.button", return_value=False):
                        with patch("streamlit.info"):
                            with patch("streamlit.caption"):
                                with patch("ui.data_load._render_step_source", return_value=True):
                                    with patch("ui.data_load._render_step_mapping"):
                                        with patch("ui.data_load._render_step_delta", return_value=True):
                                                ui.data_load.render(go_mock)


def test_render_step_mapping_with_custom_mapping_and_badges():
    """Verify _render_step_mapping renders cleanly with custom session mapping."""
    import ui.data_load

    class FakeSessionState(dict):
        def __getattr__(self, key):
            return self.get(key)
        def __setattr__(self, key, value):
            self[key] = value

    custom_df = pd.DataFrame([
        {
            "Report Name": "Apollo 10G",
            "Object Name": "BT Project",
            "Source File Column Name": "Project Ref",
            "Sitetracker Field Name": "Project Reference",
            "API Name": "Project_Reference__c",
            "Data Type": "text",
            "Primary Key?": "YES",
        }
    ])

    fake_state = FakeSessionState({
        "custom_mapping_Apollo 10G": custom_df,
    })

    def mock_cols(spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [MagicMock() for _ in range(count)]

    with patch("streamlit.session_state", fake_state):
        with patch("streamlit.columns", side_effect=mock_cols):
            with patch("streamlit.markdown"):
                with patch("streamlit.button", return_value=False):
                    with patch("streamlit.info"):
                        with patch("streamlit.caption"):
                            with patch("streamlit.radio", return_value="All Objects"):
                                with patch("streamlit.expander", return_value=MagicMock()):
                                    with patch("streamlit.selectbox") as mock_select:
                                        mock_select.return_value = "Project Ref"
                                        ui.data_load._render_step_mapping("Apollo 10G")
                                        # Verify selectbox was rendered for mapping fields
                                        assert mock_select.call_count >= 1


def test_step2_apply_mapping_action():
    """Verify that applying custom mapping persists DataFrame to session state."""
    import ui.data_load

    class FakeSessionState(dict):
        def __getattr__(self, key):
            return self.get(key)
        def __setattr__(self, key, value):
            self[key] = value

    fake_state = FakeSessionState({
        "sel_src_col_Apollo 10G_0": "Project Reference",
    })

    def mock_cols(spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [MagicMock() for _ in range(count)]

    # Simulate clicking "💾 Apply Mapping" button
    def button_side_effect(label, **kwargs):
        return label == "💾 Apply Mapping"

    with patch("streamlit.session_state", fake_state):
        with patch("streamlit.columns", side_effect=mock_cols):
            with patch("streamlit.markdown"):
                with patch("streamlit.button", side_effect=button_side_effect):
                    with patch("streamlit.info"):
                        with patch("streamlit.caption"):
                            with patch("streamlit.radio", return_value="All Objects"):
                                with patch("streamlit.expander", return_value=MagicMock()):
                                    with patch("streamlit.selectbox", return_value="Project Reference"):
                                        with patch("streamlit.rerun"):
                                            with patch("streamlit.success"):
                                                ui.data_load._render_step_mapping("Apollo 10G")

    # Verify custom mapping was saved in session state
    saved = fake_state.get("custom_mapping_Apollo 10G")
    assert saved is not None
    assert isinstance(saved, pd.DataFrame)
    assert len(saved) > 0


def test_step2_customized_renders_without_duplicate_key():
    """Verify that when custom mapping is active, all rendered buttons have unique keys."""
    import ui.data_load

    class FakeSessionState(dict):
        def __getattr__(self, key):
            return self.get(key)
        def __setattr__(self, key, value):
            self[key] = value

    custom_df = pd.DataFrame([
        {
            "Report Name": "Apollo 10G",
            "Object Name": "BT Project",
            "Source File Column Name": "Project Reference",
            "Sitetracker Field Name": "Project Reference",
            "API Name": "Project_Reference__c",
            "Data Type": "text",
            "Primary Key?": "YES",
        }
    ])

    fake_state = FakeSessionState({
        "custom_mapping_Apollo 10G": custom_df,
    })

    def mock_cols(spec, *args, **kwargs):
        count = len(spec) if isinstance(spec, (list, tuple)) else spec
        return [MagicMock() for _ in range(count)]

    rendered_button_keys = []

    def mock_button(label, key=None, **kwargs):
        if key is not None:
            rendered_button_keys.append(key)
        return False

    with patch("streamlit.session_state", fake_state):
        with patch("streamlit.columns", side_effect=mock_cols):
            with patch("streamlit.markdown"):
                with patch("streamlit.button", side_effect=mock_button):
                    with patch("streamlit.info"):
                        with patch("streamlit.caption"):
                            with patch("streamlit.radio", return_value="All Objects"):
                                with patch("streamlit.expander", return_value=MagicMock()):
                                    with patch("streamlit.selectbox", return_value="Project Reference"):
                                        ui.data_load._render_step_mapping("Apollo 10G")

    # Ensure no duplicate keys among all rendered buttons
    assert len(rendered_button_keys) == len(set(rendered_button_keys)), (
        f"Duplicate button keys detected: {rendered_button_keys}"
    )




