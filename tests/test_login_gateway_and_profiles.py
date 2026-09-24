"""Unit tests for Salesforce Login Gateway, environment profiles, and session gatekeeping."""

import json
from pathlib import Path
import time
from unittest.mock import MagicMock, patch
import pytest

from config import settings
from salesforce.auth import (
    clear_token,
    get_active_profile,
    get_login_url,
    get_profile_credentials,
    is_authenticated,
    load_profile_credentials,
    load_token,
    save_manual_token,
    save_profile_credentials,
    set_active_profile,
)
from ui.components import flush_workspace_cache


def test_fullcopy_profile_registered():
    """Verify that fullcopy profile is registered with correct label and default login URL."""
    assert "fullcopy" in settings.PROFILES
    assert "Full Copy" in settings.PROFILES["fullcopy"]
    assert "fullcopy" in settings.DEFAULT_LOGIN_URLS
    assert "test.salesforce.com" in settings.DEFAULT_LOGIN_URLS["fullcopy"] or "salesforce.com" in settings.DEFAULT_LOGIN_URLS["fullcopy"]


def test_cascading_credentials_priority(tmp_path, monkeypatch):
    """Test credential resolution order: Env Var > Profile Creds File > Global Settings."""
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "SF_CLIENT_ID", "global_client_id")
    monkeypatch.setattr(settings, "SF_CLIENT_SECRET", "global_client_secret")

    # 1. Fallback to global settings
    cid, csec = get_profile_credentials("sandbox")
    assert cid == "global_client_id"
    assert csec == "global_client_secret"

    # 2. Override with profile creds file
    save_profile_credentials("sandbox", "file_client_id", "file_client_secret")
    cid2, csec2 = get_profile_credentials("sandbox")
    assert cid2 == "file_client_id"
    assert csec2 == "file_client_secret"

    # 3. Override with environment variable
    monkeypatch.setenv("SF_CLIENT_ID_SANDBOX", "env_var_client_id")
    monkeypatch.setenv("SF_CLIENT_SECRET_SANDBOX", "env_var_client_secret")
    cid3, csec3 = get_profile_credentials("sandbox")
    assert cid3 == "env_var_client_id"
    assert csec3 == "env_var_client_secret"


def test_is_authenticated_behavior(tmp_path, monkeypatch):
    """Test is_authenticated under missing, valid, and expired token states."""
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "TOKEN_FILE", tmp_path / ".sf_auth.json")

    # Initially missing
    assert is_authenticated("fullcopy") is False

    # Valid token saved
    save_manual_token("valid_tok_abc", "https://fullcopy.my.salesforce.com", profile="fullcopy")
    assert is_authenticated("fullcopy") is True

    # Expired token
    expired_token = {
        "access_token": "expired_tok",
        "instance_url": "https://fullcopy.my.salesforce.com",
        "saved_at": time.time() - 9000,
    }
    tok_file = tmp_path / ".sf_auth_fullcopy.json"
    with open(tok_file, "w", encoding="utf-8") as f:
        json.dump(expired_token, f)

    assert is_authenticated("fullcopy") is False


def test_flush_workspace_cache(monkeypatch):
    """Test that flush_workspace_cache safely purges cached datasets and previews."""
    import streamlit as st
    st.session_state["source_df"] = "dummy_source"
    st.session_state["preview_df"] = "dummy_preview"
    st.session_state["delta_df"] = "dummy_delta"
    st.session_state["baseline_records"] = [1, 2, 3]
    st.session_state["unrelated_key"] = "keep_me"

    flush_workspace_cache()

    assert "source_df" not in st.session_state
    assert "preview_df" not in st.session_state
    assert "delta_df" not in st.session_state
    assert "baseline_records" not in st.session_state
    assert st.session_state["unrelated_key"] == "keep_me"


def test_login_gateway_renders_without_error(monkeypatch):
    """Test that render_login_gateway executes cleanly against mock Streamlit."""
    from ui.login import render_login_gateway
    mock_go = MagicMock()

    with patch("streamlit.radio", return_value="partial"), \
         patch("streamlit.tabs", return_value=[MagicMock(), MagicMock()]), \
         patch("streamlit.columns", return_value=[MagicMock(), MagicMock()]):
        # Call render_login_gateway with mock go callback
        try:
            render_login_gateway(mock_go, active_profile="partial")
        except Exception as e:
            pytest.fail(f"render_login_gateway raised an exception: {e}")
