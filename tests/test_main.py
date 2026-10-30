"""Unit tests for main pipeline execution."""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.config import AppConfig, SettingsConfig, SourceConfig
from src.gemini_summarizer import CandidateNewsItem, SummarizedNewsItem
from src.main import run_pipeline, write_github_step_summary


class TestMainPipeline(unittest.TestCase):
    def setUp(self):
        self.sample_candidate = CandidateNewsItem(
            title="ข่าวตัวอย่าง",
            link="https://example.com/sample",
            summary="เนื้อหาตัวอย่าง",
            source_name="SampleSource",
            category="ทั่วไป",
        )
        self.sample_summary = SummarizedNewsItem(
            title="ข่าวตัวอย่างสรุป",
            category="ทั่วไป",
            summary_bullets=["สรุป 1"],
            importance_reason="เหตุผล",
            url="https://example.com/sample",
            source_name="SampleSource",
        )
        self.config = AppConfig(
            settings=SettingsConfig(min_news_items=1, max_news_items=2),
            sources=[SourceConfig(name="S1", category="ทั่วไป", url="https://s1.com", enabled=True)],
            gemini_api_key="fake-gemini-key",
            line_channel_access_token="fake-line-token",
            line_user_id="fake-line-user-id",
            dry_run=False,
        )

    @patch("src.main.notify_line")
    @patch("src.main.summarize_with_gemini")
    @patch("src.main.fetch_all_sources")
    def test_run_pipeline_success(self, mock_fetch, mock_gemini, mock_line):
        """Test full successful pipeline flow."""
        mock_fetch.return_value = [self.sample_candidate]
        mock_gemini.return_value = [self.sample_summary]
        mock_line.return_value = True

        result = run_pipeline(self.config)
        self.assertTrue(result)
        mock_fetch.assert_called_once()
        mock_gemini.assert_called_once()
        mock_line.assert_called_once()

    @patch("src.main.fetch_all_sources")
    def test_run_pipeline_no_candidates(self, mock_fetch):
        """Test pipeline aborts gracefully if no news could be fetched."""
        mock_fetch.return_value = []
        result = run_pipeline(self.config)
        self.assertFalse(result)

    @patch("src.main.notify_line")
    @patch("src.main.summarize_with_gemini")
    @patch("src.main.fetch_all_sources")
    def test_run_pipeline_dry_run(self, mock_fetch, mock_gemini, mock_line):
        """Test dry run mode does not invoke LINE notifier."""
        self.config.dry_run = True
        mock_fetch.return_value = [self.sample_candidate]
        mock_gemini.return_value = [self.sample_summary]

        result = run_pipeline(self.config)
        self.assertTrue(result)
        mock_line.assert_not_called()

    @patch("src.main.fetch_all_sources")
    def test_run_pipeline_missing_line_credentials(self, mock_fetch):
        """Test error when LINE credentials are missing in non-dry-run mode."""
        self.config.line_channel_access_token = None
        mock_fetch.return_value = [self.sample_candidate]

        result = run_pipeline(self.config)
        self.assertFalse(result)

    def test_write_github_step_summary(self):
        """Test writing markdown summary to step summary file."""
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as tmp:
            tmp_path = tmp.name

        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": tmp_path}):
            write_github_step_summary([self.sample_summary], "28 ต.ค. 2569")

        with open(tmp_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Daily News Summary", content)
        self.assertIn("ข่าวตัวอย่างสรุป", content)


if __name__ == "__main__":
    unittest.main()
