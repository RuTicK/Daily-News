"""Unit tests for Gemini summarizer."""

import json
import unittest
from unittest.mock import MagicMock, patch

from src.gemini_summarizer import (
    CandidateNewsItem,
    SummarizedNewsItem,
    build_prompt,
    clean_fallback_summary,
    clean_json_response,
    fallback_summarize,
    parse_gemini_json,
    summarize_with_gemini,
)


class TestGeminiSummarizer(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            CandidateNewsItem(
                title="ข่าวธุรกิจเด่น",
                link="https://biz.com/1",
                summary="สรุปธุรกิจ",
                source_name="BizNews",
                category="ธุรกิจ",
            ),
            CandidateNewsItem(
                title="ข่าวไอทีเด่น",
                link="https://tech.com/2",
                summary="สรุปไอที",
                source_name="TechDaily",
                category="ไอที",
            ),
            CandidateNewsItem(
                title="ข่าวทั่วไปเด่น",
                link="https://general.com/3",
                summary="สรุปทั่วไป",
                source_name="GeneralNews",
                category="ทั่วไป",
            ),
        ]

    def test_build_prompt(self):
        """Test prompt formatting."""
        prompt = build_prompt(self.candidates, min_items=3, max_items=5)
        self.assertIn("ข่าวธุรกิจเด่น", prompt)
        self.assertIn("https://biz.com/1", prompt)
        self.assertIn("ข่าวไอทีเด่น", prompt)
        self.assertIn("3-5 ข่าว", prompt)

    def test_clean_json_response(self):
        """Test stripping backticks, preamble, and conversational wrappers."""
        raw_with_tag = '```json\n{"news": []}\n```'
        self.assertEqual(clean_json_response(raw_with_tag), '{"news": []}')

        raw_without_tag = '```\n{"news": []}\n```'
        self.assertEqual(clean_json_response(raw_without_tag), '{"news": []}')

        clean_raw = '{"news": []}'
        self.assertEqual(clean_json_response(clean_raw), '{"news": []}')

        with_preamble = 'Here is the summary:\n```json\n{"news": []}\n```\nHope it helps!'
        self.assertEqual(clean_json_response(with_preamble), '{"news": []}')

        plain_with_preamble = 'Result:\n{"news": []}\nDone'
        self.assertEqual(clean_json_response(plain_with_preamble), '{"news": []}')

    def test_parse_gemini_json_dict_format(self):
        """Test parsing valid JSON dict format."""
        sample_json = json.dumps({
            "news": [
                {
                    "title": "ข่าวสรุปที่ 1",
                    "category": "ธุรกิจ",
                    "summary_bullets": ["ประเด็น 1", "ประเด็น 2"],
                    "importance_reason": "มีผลต่อค่าเงินบาท",
                    "url": "https://biz.com/1",
                    "source_name": "BizNews",
                }
            ]
        })
        items = parse_gemini_json(sample_json)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "ข่าวสรุปที่ 1")
        self.assertEqual(items[0].category, "ธุรกิจ")
        self.assertEqual(len(items[0].summary_bullets), 2)
        self.assertEqual(items[0].url, "https://biz.com/1")

    def test_parse_gemini_json_list_format(self):
        """Test parsing if Gemini returns direct list."""
        sample_json = json.dumps([
            {
                "title": "ข่าวที่ 1",
                "category": "ไอที",
                "summary_bullets": ["ประเด็น A"],
                "importance_reason": "เทคโนโลยีใหม่",
                "url": "https://tech.com/2",
            }
        ])
        items = parse_gemini_json(sample_json)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "ข่าวที่ 1")

    @patch("src.gemini_summarizer.requests.post")
    def test_summarize_with_gemini_success(self, mock_post):
        """Test successful Gemini API response."""
        gemini_api_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps({
                                    "news": [
                                        {
                                            "title": "ข่าวคัดสรรแล้ว",
                                            "category": "ธุรกิจ",
                                            "summary_bullets": ["สรุปข้อ 1", "สรุปข้อ 2"],
                                            "importance_reason": "สำคัญต่อเศรษฐกิจ",
                                            "url": "https://biz.com/1",
                                            "source_name": "BizNews",
                                        }
                                    ]
                                })
                            }
                        ]
                    }
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = gemini_api_response
        mock_post.return_value = mock_response

        items = summarize_with_gemini(
            self.candidates,
            api_key="fake-gemini-key",
            model="gemini-2.5-flash",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "ข่าวคัดสรรแล้ว")
        self.assertEqual(items[0].url, "https://biz.com/1")

    def test_fallback_summarize(self):
        """Test fallback summarizer produces valid output."""
        items = fallback_summarize(self.candidates, min_items=2, max_items=3)
        self.assertGreaterEqual(len(items), 2)
        self.assertLessEqual(len(items), 3)
        for item in items:
            self.assertTrue(item.title)
            self.assertTrue(item.url)
            self.assertGreaterEqual(len(item.summary_bullets), 1)

    def test_clean_fallback_summary(self):
        """Test stripping WordPress RSS boilerplate and clipping long descriptions."""
        sample_with_footer = "ข่าวล่าสุดวันนี้ The post ข่าวเปิดตัว appeared first on Example Blog ."
        cleaned = clean_fallback_summary(sample_with_footer)
        self.assertNotIn("The post", cleaned)
        self.assertNotIn("appeared first on", cleaned)
        self.assertIn("ข่าวล่าสุดวันนี้", cleaned)

        long_text = "คำ " * 100
        clipped = clean_fallback_summary(long_text, max_len=50)
        self.assertLessEqual(len(clipped), 55)
        self.assertTrue(clipped.endswith("..."))

    @patch("src.gemini_summarizer.requests.post")
    def test_summarize_with_gemini_caps_candidates(self, mock_post):
        """Test that candidate news sent in prompt to Gemini is capped at 15 items."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"news": []}'}]}}]
        }
        mock_post.return_value = mock_response

        # Generate 25 candidates
        many_candidates = [
            CandidateNewsItem(f"Title {i}", f"https://example.com/{i}", f"Summary {i}", "Src", "ทั่วไป")
            for i in range(25)
        ]
        summarize_with_gemini(many_candidates, api_key="fake-key")

        # Verify posted payload
        posted_payload = mock_post.call_args[1]["json"]
        sent_prompt = posted_payload["contents"][0]["parts"][0]["text"]
        self.assertIn("[15] หัวข้อ: Title 14", sent_prompt)
        self.assertNotIn("[16] หัวข้อ: Title 15", sent_prompt)


if __name__ == "__main__":
    unittest.main()
