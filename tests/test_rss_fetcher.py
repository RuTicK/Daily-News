"""Unit tests for RSS and Atom fetcher."""

import unittest
from unittest.mock import MagicMock, patch

from src.config import SourceConfig
from src.rss_fetcher import (
    CandidateNewsItem,
    clean_html,
    clean_url_for_dedup,
    fetch_all_sources,
    fetch_source_feed,
    normalize_title_for_dedup,
    parse_feed_xml,
)

SAMPLE_RSS_2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Sample News</title>
    <item>
      <title><![CDATA[หุ้นไทยเช้านี้พุ่ง 15 จุด รับแรงซื้อต่างชาติ]]></title>
      <link>https://news.example.com/stocks-up-15-points</link>
      <description><![CDATA[<p>ดัชนีหุ้นไทยปรับตัวขึ้นตามตลาดโลก โดยมี &quot;แรงซื้อ&quot; เด่นในกลุ่มพลังงานและแบงก์</p>]]></description>
      <pubDate>Wed, 28 Oct 2026 08:30:00 +0700</pubDate>
    </item>
    <item>
      <title>ราคาทองคำผันผวน &amp; บาทแข็งค่าต่อเนื่อง</title>
      <link>https://news.example.com/gold-price</link>
      <description>สมาคมค้าทองคำเผยราคาทองวันนี้ปรับตัวลดลงเล็กน้อย</description>
      <pubDate>Wed, 28 Oct 2026 09:00:00 +0700</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sample Tech Blog</title>
  <entry>
    <title>เปิดตัวชิป AI รุ่นใหม่ ประหยัดพลังงานขึ้น 40%</title>
    <link href="https://tech.example.com/new-ai-chip" rel="alternate"/>
    <summary type="html">&lt;p&gt;ชิปรุ่นใหม่มาพร้อม NPU ขั้นสูง เหมาะสำหรับสมาร์ทโฟน&lt;/p&gt;</summary>
    <updated>2026-10-28T07:15:00Z</updated>
  </entry>
</feed>
"""


class TestRssFetcher(unittest.TestCase):
    def test_clean_html(self):
        """Test stripping HTML tags and unescaping entities."""
        raw = "<p>สวัสดี &amp; ยินดีต้อนรับ &quot;ผู้อ่าน&quot; ทุกท่าน &lt;br&gt; <strong>สำคัญ</strong></p>"
        expected = 'สวัสดี & ยินดีต้อนรับ "ผู้อ่าน" ทุกท่าน <br> สำคัญ'
        self.assertEqual(clean_html(raw), expected)
        self.assertEqual(clean_html(""), "")
        self.assertEqual(clean_html(None), "")

    def test_normalize_title_for_dedup(self):
        """Test normalization for duplicate detection."""
        t1 = "หุ้นไทย พุ่ง 10 จุด! (เช้านี้)"
        t2 = "หุ้นไทยพุ่ง 10 จุด - เช้านี้"
        self.assertEqual(normalize_title_for_dedup(t1), normalize_title_for_dedup(t2))

    def test_parse_rss_2(self):
        """Test parsing RSS 2.0 with CDATA and unescaping."""
        items = parse_feed_xml(SAMPLE_RSS_2, "SampleBiz", "ธุรกิจ", max_items=5)
        self.assertEqual(len(items), 2)
        
        first = items[0]
        self.assertEqual(first.title, "หุ้นไทยเช้านี้พุ่ง 15 จุด รับแรงซื้อต่างชาติ")
        self.assertEqual(first.link, "https://news.example.com/stocks-up-15-points")
        self.assertIn('"แรงซื้อ"', first.summary)
        self.assertEqual(first.source_name, "SampleBiz")
        self.assertEqual(first.category, "ธุรกิจ")

        second = items[1]
        self.assertEqual(second.title, "ราคาทองคำผันผวน & บาทแข็งค่าต่อเนื่อง")
        self.assertEqual(second.link, "https://news.example.com/gold-price")

    def test_parse_atom(self):
        """Test parsing Atom 1.0 feed."""
        items = parse_feed_xml(SAMPLE_ATOM, "SampleTech", "ไอที", max_items=5)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.title, "เปิดตัวชิป AI รุ่นใหม่ ประหยัดพลังงานขึ้น 40%")
        self.assertEqual(item.link, "https://tech.example.com/new-ai-chip")
        self.assertIn("NPU ขั้นสูง", item.summary)
        self.assertEqual(item.category, "ไอที")

    def test_parse_malformed_xml_graceful(self):
        """Test that malformed XML returns an empty list without crashing."""
        malformed = "<rss><channel><item><title>Broken<link></channel></rss>"
        items = parse_feed_xml(malformed, "BrokenSource", "ทั่วไป")
        self.assertEqual(items, [])

    @patch("src.rss_fetcher.requests.Session")
    def test_fetch_source_feed_success(self, mock_session_cls):
        """Test fetching a feed via HTTP session."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.content = SAMPLE_RSS_2.encode("utf-8")
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response

        source = SourceConfig(
            name="Test Source",
            category="ธุรกิจ",
            url="https://example.com/rss",
            enabled=True,
            max_items=2,
        )
        items = fetch_source_feed(source, session=mock_session)
        self.assertEqual(len(items), 2)

    def test_fetch_disabled_source(self):
        """Test disabled source immediately returns empty list."""
        source = SourceConfig(name="Off", category="ทั่วไป", url="https://x.com", enabled=False)
        self.assertEqual(fetch_source_feed(source), [])

    @patch("src.rss_fetcher.fetch_source_feed")
    def test_fetch_all_sources_deduplication(self, mock_fetch):
        """Test deduplication across multiple feeds."""
        src1 = SourceConfig(name="S1", category="ทั่วไป", url="https://s1.com", enabled=True)
        src2 = SourceConfig(name="S2", category="ทั่วไป", url="https://s2.com", enabled=True)

        item1 = CandidateNewsItem(
            title="ข่าวด่วน 1",
            link="https://news.com/1?utm_source=rss",
            summary="เนื้อหา 1",
            source_name="S1",
            category="ทั่วไป",
        )
        # Duplicate URL (different query params)
        item2 = CandidateNewsItem(
            title="ข่าวด่วน 1 (เพิ่มเติม)",
            link="https://news.com/1?ref=line",
            summary="เนื้อหา 1",
            source_name="S2",
            category="ทั่วไป",
        )
        # Distinct item
        item3 = CandidateNewsItem(
            title="ข่าวที่สอง",
            link="https://news.com/2",
            summary="เนื้อหา 2",
            source_name="S2",
            category="ทั่วไป",
        )

        mock_fetch.side_effect = [[item1], [item2, item3]]

        results = fetch_all_sources([src1, src2])
        # Only item1 and item3 should remain because item2 shares normalized base URL https://news.com/1
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "ข่าวด่วน 1")
        self.assertEqual(results[1].title, "ข่าวที่สอง")

    def test_clean_url_for_dedup_query_preservation(self):
        """Test that query parameters are preserved while tracking tags and fragments are removed."""
        url_with_utm = "https://example.com/article?id=123&utm_source=twitter#top"
        self.assertEqual(clean_url_for_dedup(url_with_utm), "https://example.com/article?id=123")

        url_diff_id = "https://example.com/article?id=456"
        self.assertNotEqual(clean_url_for_dedup(url_with_utm), clean_url_for_dedup(url_diff_id))

    @patch("src.rss_fetcher.fetch_source_feed")
    def test_fetch_all_sources_preserves_query_param_articles(self, mock_fetch):
        """Test that distinct articles distinguished by query parameters are not falsely dropped."""
        src = SourceConfig(name="ParamNews", category="ทั่วไป", url="https://example.com/feed")
        item1 = CandidateNewsItem("ข่าว 1", "https://example.com/view?id=101", "สรุป 1", "ParamNews", "ทั่วไป")
        item2 = CandidateNewsItem("ข่าว 2", "https://example.com/view?id=102", "สรุป 2", "ParamNews", "ทั่วไป")
        mock_fetch.return_value = [item1, item2]

        results = fetch_all_sources([src])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "ข่าว 1")
        self.assertEqual(results[1].title, "ข่าว 2")

    @patch("src.rss_fetcher.fetch_source_feed")
    def test_fetch_all_sources_interleaving(self, mock_fetch):
        """Test that candidate items are round-robin interleaved across sources."""
        src_a = SourceConfig(name="SourceA", category="ไอที", url="https://a.com")
        src_b = SourceConfig(name="SourceB", category="ธุรกิจ", url="https://b.com")

        items_a = [
            CandidateNewsItem("A1", "https://a.com/1", "", "SourceA", "ไอที"),
            CandidateNewsItem("A2", "https://a.com/2", "", "SourceA", "ไอที"),
        ]
        items_b = [
            CandidateNewsItem("B1", "https://b.com/1", "", "SourceB", "ธุรกิจ"),
            CandidateNewsItem("B2", "https://b.com/2", "", "SourceB", "ธุรกิจ"),
        ]
        mock_fetch.side_effect = [items_a, items_b]

        results = fetch_all_sources([src_a, src_b])
        self.assertEqual(len(results), 4)
        # Interleaved order: A1, B1, A2, B2
        self.assertEqual([r.title for r in results], ["A1", "B1", "A2", "B2"])

    def test_parse_rss_2_link_href_attribute(self):
        """Test parsing RSS 2.0 item where link is an attribute <link href='...'/>."""
        xml = """<rss version="2.0"><channel><item>
            <title>ทดสอบ Link Attribute</title>
            <link href="https://example.com/attr-link"/>
            <description>คำอธิบาย</description>
        </item></channel></rss>"""
        items = parse_feed_xml(xml, "AttrSrc", "ทั่วไป")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].link, "https://example.com/attr-link")


if __name__ == "__main__":
    unittest.main()
