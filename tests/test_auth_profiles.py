"""Unit tests for multi-environment profile switcher and token management."""

import json
from pathlib import Path
import pytest

from config import settings
from salesforce.auth import (
    clear_token,
    get_active_profile,
    get_token_file,
    is_token_valid,
    load_token,
    sanitize_session_token,
    save_manual_token,
    set_active_profile,
)


def test_sanitize_session_token():
    # Test stripping MY_TOKEN: prefix and ### separator
    raw = "MY_TOKEN: 00Dds00000359wz###!AQEAQLURT88LE3S.ajYG5rxx"
    expected = "00Dds00000359wz!AQEAQLURT88LE3S.ajYG5rxx"
    assert sanitize_session_token(raw) == expected

    # Test whitespace and quotes
    raw2 = '  "00Dds00000359wz!AQEAQLURT"  '
    assert sanitize_session_token(raw2) == "00Dds00000359wz!AQEAQLURT"

    # Test empty
    assert sanitize_session_token("") == ""


def test_profile_switching(tmp_path, monkeypatch):
    test_profile_file = tmp_path / ".sf_profile.json"
    monkeypatch.setattr(settings, "PROFILE_FILE", test_profile_file)

    # Defaults to sandbox
    assert get_active_profile() == "sandbox"

    # Switch to prod
    set_active_profile("prod")
    assert get_active_profile() == "prod"

    # Switch back to sandbox
    set_active_profile("sandbox")
    assert get_active_profile() == "sandbox"

    # Invalid profile raises ValueError
    with pytest.raises(ValueError):
        set_active_profile("invalid_env")


def test_profile_token_isolation(tmp_path, monkeypatch):
    test_profile_file = tmp_path / ".sf_profile.json"
    monkeypatch.setattr(settings, "PROFILE_FILE", test_profile_file)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "TOKEN_FILE", tmp_path / ".sf_auth.json")

    set_active_profile("sandbox")
    save_manual_token("tok_sandbox_123", "https://sandbox.my.salesforce.com", profile="sandbox")

    set_active_profile("prod")
    save_manual_token("tok_prod_456", "https://prod.my.salesforce.com", profile="prod")

    # Verify isolation
    sb_token = load_token(profile="sandbox")
    assert sb_token["access_token"] == "tok_sandbox_123"
    assert sb_token["instance_url"] == "https://sandbox.my.salesforce.com"

    prod_token = load_token(profile="prod")
    assert prod_token["access_token"] == "tok_prod_456"
    assert prod_token["instance_url"] == "https://prod.my.salesforce.com"

    # Clear sandbox only
    clear_token(profile="sandbox")
    assert load_token(profile="sandbox") is None
    assert load_token(profile="prod") is not None


def test_oauth_login_url(monkeypatch):
    from salesforce.auth import get_login_url
    monkeypatch.setattr(settings, "SF_CLIENT_ID", "test_client_id")
    monkeypatch.setattr(settings, "SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")

    sb_url = get_login_url(profile="sandbox")
    assert "test.salesforce.com" in sb_url
    assert "client_id=test_client_id" in sb_url

    prod_url = get_login_url(profile="prod")
    assert "login.salesforce.com" in prod_url


def test_exchange_code_for_token(tmp_path, monkeypatch):
    from unittest.mock import MagicMock, patch
    from salesforce.auth import exchange_code_for_token

    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "SF_CLIENT_ID", "mock_id")
    monkeypatch.setattr(settings, "SF_CLIENT_SECRET", "mock_secret")
    monkeypatch.setattr(settings, "SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "mock_access_token_123",
        "refresh_token": "mock_refresh_token_456",
        "instance_url": "https://sitetracker-bt--developer.sandbox.my.salesforce.com"
    }

    with patch("requests.post", return_value=mock_resp):
        res = exchange_code_for_token("auth_code_xyz", profile="sandbox")
        assert res["access_token"] == "mock_access_token_123"
        assert res["refresh_token"] == "mock_refresh_token_456"
        assert res["profile"] == "sandbox"

        # Verify saved to sandbox token file
        saved = load_token(profile="sandbox")
        assert saved["access_token"] == "mock_access_token_123"
        assert saved["refresh_token"] == "mock_refresh_token_456"


def test_pkce_generation_and_challenge(monkeypatch, tmp_path):
    from salesforce.auth import get_login_url, generate_pkce_pair
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "SF_CLIENT_ID", "pkce_test_client")
    monkeypatch.setattr(settings, "SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")

    verifier, challenge = generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43

    login_url = get_login_url(profile="sandbox")
    assert "code_challenge=" in login_url
    assert "code_challenge_method=S256" in login_url


