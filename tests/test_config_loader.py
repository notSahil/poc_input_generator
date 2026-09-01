"""Unit tests for YamlConfigLoader."""

import pytest
from core.config_loader import YamlConfigLoader
from core.exceptions import ConfigNotFoundError


class TestConfigLoader:
    def test_load_existing_config(self, mock_environment):
        cfg = YamlConfigLoader.load("Test Report")
        assert cfg["report"]["name"] == "Test Report"
        assert cfg["folders"]["work_dir"] == "Test_Report"

    def test_load_non_existent_config(self, mock_environment):
        with pytest.raises(ConfigNotFoundError):
            YamlConfigLoader.load("Non Existent Report")

    def test_list_reports(self, mock_environment):
        reports = YamlConfigLoader.list_reports()
        assert len(reports) == 1
        assert reports[0].name == "Test Report"
        assert reports[0].has_source is True
        assert reports[0].has_sitetracker is True
