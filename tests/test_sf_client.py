"""Unit tests for simple-salesforce connection bridge."""

from unittest.mock import MagicMock, patch
import pytest

from core.exceptions import SalesforceAuthError
from salesforce.sf_client import get_sf_connection


def test_get_sf_connection_success():
    mock_token = {
        "access_token": "test_access_token_123",
        "instance_url": "https://testorg.my.salesforce.com/"
    }

    with patch("salesforce.sf_client.is_token_valid", return_value=True), \
         patch("salesforce.sf_client.load_token", return_value=mock_token), \
         patch("salesforce.sf_client.Salesforce") as mock_sf_cls:
        
        mock_instance = MagicMock()
        mock_sf_cls.return_value = mock_instance

        sf = get_sf_connection()

        mock_sf_cls.assert_called_once_with(
            instance_url="https://testorg.my.salesforce.com",
            session_id="test_access_token_123"
        )
        assert sf == mock_instance


def test_get_sf_connection_expired_or_invalid():
    mock_token = {"access_token": "expired_tok", "instance_url": "https://test.com"}
    with patch("salesforce.sf_client.load_token", return_value=mock_token), \
         patch("salesforce.sf_client.is_token_valid", return_value=False):
        with pytest.raises(SalesforceAuthError, match="Salesforce session expired or not authenticated"):
            get_sf_connection()


def test_get_sf_connection_missing_token():
    with patch("salesforce.sf_client.is_token_valid", return_value=True), \
         patch("salesforce.sf_client.load_token", return_value=None):
        with pytest.raises(SalesforceAuthError, match="No valid Salesforce token found"):
            get_sf_connection()


def test_get_sf_connection_missing_access_token_key():
    with patch("salesforce.sf_client.is_token_valid", return_value=True), \
         patch("salesforce.sf_client.load_token", return_value={"instance_url": "https://test.com"}):
        with pytest.raises(SalesforceAuthError, match="No valid Salesforce token found"):
            get_sf_connection()


def test_get_sf_connection_missing_instance_url():
    with patch("salesforce.sf_client.is_token_valid", return_value=True), \
         patch("salesforce.sf_client.load_token", return_value={"access_token": "token123"}):
        with pytest.raises(SalesforceAuthError, match="No instance URL found"):
            get_sf_connection()
