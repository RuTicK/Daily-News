"""Unit tests for LINE notifier and message builders."""

import datetime
import unittest
from unittest.mock import MagicMock, patch

from src.gemini_summarizer import SummarizedNewsItem
from src.line_notifier import (
    build_fallback_text_message,
    build_flex_message,
    build_single_bubble,
    get_thai_date_string,
    notify_line,
    sanitize_line_uri,
    send_line_push_message,
)


class TestLineNotifier(unittest.TestCase):
    def setUp(self):
        self.sample_items = [
            SummarizedNewsItem(
                title="หุ้นไทยพุ่ง 15 จุด รับแรงซื้อเทศกาล",
                category="ธุรกิจ",
                summary_bullets=["ตลาดหุ้นเอเชียเขียวสดใส", "นักลงทุนต่างชาติซื้อสุทธิ 3,000 ล้านบาท"],
                importance_reason="โอกาสในการลงทุนหุ้นกลุ่มพลังงาน",
                url="https://thestandard.co/stocks-up",
                source_name="The Standard",
            ),
            SummarizedNewsItem(
                title="เปิดตัวแท็บเล็ตรุ่นใหม่ รองรับปากกา AI",
                category="เทคโนโลยี",
                summary_bullets=["ชิปเร็วขึ้น 20%", "แบตเตอรี่ใช้งานได้ 14 ชม."],
                importance_reason="เป็นอุปกรณ์น่าสนใจสำหรับคนทำงาน",
                url="https://beartai.com/new-tablet",
                source_name="Beartai",
            ),
        ]

    def test_thai_date_formatting(self):
        """Test Buddhist Era and Thai day/month formatting."""
        dt = datetime.datetime(2026, 10, 28, 8, 0, 0)
        date_str = get_thai_date_string(dt)
        self.assertIn("28", date_str)
        self.assertIn("ต.ค.", date_str)
        self.assertIn("2569", date_str)  # 2026 + 543 = 2569

    def test_build_single_bubble(self):
        """Test Flex bubble card generation."""
        bubble = build_single_bubble(self.sample_items[0], 1, 2, "พุธที่ 28 ต.ค. 2569")
        self.assertEqual(bubble["type"], "bubble")
        self.assertEqual(bubble["size"], "mega")
        self.assertIn("header", bubble)
        self.assertIn("body", bubble)
        self.assertIn("footer", bubble)

        # Check button uri
        button_action = bubble["footer"]["contents"][0]["action"]
        self.assertEqual(button_action["type"], "uri")
        self.assertEqual(button_action["uri"], "https://thestandard.co/stocks-up")
        self.assertEqual(button_action["label"], "อ่านต่อ ↗")

    def test_build_flex_message(self):
        """Test Flex carousel message container."""
        flex = build_flex_message(self.sample_items, "28 ต.ค. 2569")
        self.assertEqual(flex["type"], "flex")
        self.assertTrue(flex["altText"].startswith("☀️"))
        self.assertEqual(flex["contents"]["type"], "carousel")
        self.assertEqual(len(flex["contents"]["contents"]), 2)

    def test_build_fallback_text_message(self):
        """Test structured Text message creation."""
        text_msg = build_fallback_text_message(self.sample_items, "28 ต.ค. 2569")
        self.assertEqual(text_msg["type"], "text")
        text = text_msg["text"]
        self.assertIn("☀️ สรุปข่าวเด่นเช้าวันนี้", text)
        self.assertIn("หุ้นไทยพุ่ง 15 จุด", text)
        self.assertIn("https://thestandard.co/stocks-up", text)
        self.assertIn("เปิดตัวแท็บเล็ตรุ่นใหม่", text)
        self.assertIn("💡 ทำไมต้องรู้:", text)

    @patch("src.line_notifier.send_line_push_message")
    def test_notify_line_flex_success(self, mock_send):
        """Test successful Flex message delivery without fallback."""
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_send.return_value = mock_res

        success = notify_line(self.sample_items, "fake-token", "fake-user-id")
        self.assertTrue(success)
        self.assertEqual(mock_send.call_count, 1)

    @patch("src.line_notifier.send_line_push_message")
    def test_notify_line_flex_fails_fallback_to_text(self, mock_send):
        """Test automatic fallback to Text message when Flex returns HTTP 400."""
        # First call (Flex) returns 400 Bad Request
        res_flex_fail = MagicMock()
        res_flex_fail.status_code = 400
        res_flex_fail.text = "Bad Request: Invalid Flex JSON"

        # Second call (Fallback Text) returns 200 OK
        res_text_ok = MagicMock()
        res_text_ok.status_code = 200

        mock_send.side_effect = [res_flex_fail, res_text_ok]

        success = notify_line(self.sample_items, "fake-token", "fake-user-id")
        self.assertTrue(success)
        self.assertEqual(mock_send.call_count, 2)

    def test_notify_line_empty_items(self):
        """Test notify_line with empty items returns False."""
        self.assertFalse(notify_line([], "fake-token", "fake-user-id"))

    def test_sanitize_line_uri(self):
        """Test percent-encoding Thai characters and limiting URL length."""
        raw_thai_url = "https://example.com/news/การเมือง?page=1&query=ข่าว ดี"
        clean = sanitize_line_uri(raw_thai_url)
        self.assertTrue(clean.isascii())
        self.assertIn("%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B9%80%E0%B8%A1%E0%B8%B7%E0%B8%AD%E0%B8%87", clean)

        empty_result = sanitize_line_uri("")
        self.assertEqual(empty_result, "")

        super_long = "https://example.com/" + "a" * 2000
        capped = sanitize_line_uri(super_long)
        self.assertLessEqual(len(capped), 1000)

    def test_build_single_bubble_with_unicode_url(self):
        """Test that bubble button URI is properly sanitized to valid ASCII."""
        item = SummarizedNewsItem(
            title="ข่าวทดสอบลิงก์ภาษาไทย",
            category="ทั่วไป",
            summary_bullets=["เนื้อหา"],
            importance_reason="เหตุผล",
            url="https://thairath.co.th/news/local/ข่าวเช้า",
            source_name="Thairath",
        )
        bubble = build_single_bubble(item, 1, 1, "ศุกร์ที่ 30 ต.ค. 2569")
        btn_uri = bubble["footer"]["contents"][0]["action"]["uri"]
        self.assertTrue(btn_uri.isascii())
        self.assertTrue(btn_uri.startswith("https://thairath.co.th/news/local/"))


if __name__ == "__main__":
    unittest.main()
