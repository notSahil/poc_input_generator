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
