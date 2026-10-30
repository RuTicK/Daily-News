"""Unit tests for configuration loader and models."""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.config import AppConfig, SettingsConfig, SourceConfig, _simple_yaml_parse, load_config, load_yaml


class TestConfig(unittest.TestCase):
    def test_default_config_load(self):
        """Test loading the project's actual config.yaml."""
        cfg = load_config("config.yaml")
        self.assertIsInstance(cfg, AppConfig)
        self.assertGreaterEqual(len(cfg.sources), 5)
        self.assertEqual(cfg.settings.min_news_items, 3)
        self.assertEqual(cfg.settings.max_news_items, 5)

    def test_simple_yaml_parse(self):
        """Test fallback simple YAML parser."""
        yaml_content = """
settings:
  min_news_items: 2
  max_news_items: 4
  gemini_model: "gemini-1.5-flash"
  fetch_timeout_seconds: 20
  max_items_per_source: 3

sources:
  - name: "Feed 1"
    category: "Tech"
    url: "https://example.com/feed1"
    enabled: true
    max_items: 2

  - name: "Feed 2"
    category: "Biz"
    url: "https://example.com/feed2"
    enabled: false
"""
        parsed = _simple_yaml_parse(yaml_content)
        self.assertIn("settings", parsed)
        self.assertEqual(parsed["settings"]["min_news_items"], 2)
        self.assertEqual(parsed["settings"]["max_news_items"], 4)
        self.assertEqual(parsed["settings"]["gemini_model"], "gemini-1.5-flash")
        self.assertIn("sources", parsed)
        self.assertEqual(len(parsed["sources"]), 2)
        self.assertEqual(parsed["sources"][0]["name"], "Feed 1")
        self.assertTrue(parsed["sources"][0]["enabled"])
        self.assertFalse(parsed["sources"][1]["enabled"])

    def test_missing_config_file_uses_defaults(self):
        """Test loading a non-existent file returns default settings."""
        cfg = load_config("non_existent_file.yaml")
        self.assertEqual(cfg.settings.min_news_items, 3)
        self.assertEqual(cfg.settings.max_news_items, 5)
        self.assertEqual(len(cfg.sources), 0)

    def test_validate_credentials(self):
        """Test credential validation method."""
        cfg_empty = AppConfig()
        missing = cfg_empty.validate_credentials()
        self.assertIn("GEMINI_API_KEY", missing)
        self.assertIn("LINE_CHANNEL_ACCESS_TOKEN", missing)
        self.assertIn("LINE_USER_ID", missing)

        cfg_full = AppConfig(
            gemini_api_key="key123",
            line_channel_access_token="tok123",
            line_user_id="user123",
        )
        self.assertEqual(len(cfg_full.validate_credentials()), 0)

    def test_environment_variables_override(self):
        """Test that env vars take precedence."""
        with patch.dict(
            os.environ,
            {
                "GEMINI_MODEL": "custom-gemini-pro",
                "GEMINI_API_KEY": "test-gemini-key",
                "LINE_CHANNEL_ACCESS_TOKEN": "test-line-token",
                "LINE_USER_ID": "test-user-id",
                "DRY_RUN": "true",
            },
        ):
            cfg = load_config("config.yaml")
            self.assertEqual(cfg.settings.gemini_model, "custom-gemini-pro")
            self.assertEqual(cfg.gemini_api_key, "test-gemini-key")
            self.assertEqual(cfg.line_channel_access_token, "test-line-token")
            self.assertEqual(cfg.line_user_id, "test-user-id")
            self.assertTrue(cfg.dry_run)


if __name__ == "__main__":
    unittest.main()
