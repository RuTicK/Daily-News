"""LINE Messaging API notifier with Flex Message and structured Text fallback."""

import datetime
import logging
from typing import Any, Optional
from urllib.parse import quote, urlparse, urlunparse

import requests

from .gemini_summarizer import SummarizedNewsItem

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
THAI_MONTHS_SHORT = [
    "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
    "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."
]
THAI_MONTHS_FULL = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
]

CATEGORY_THEMES: dict[str, dict[str, str]] = {
    "ธุรกิจ": {"header_bg": "#065F46", "badge_bg": "#10B981", "badge_text": "#FFFFFF", "icon": "📈"},
    "การเงิน": {"header_bg": "#065F46", "badge_bg": "#10B981", "badge_text": "#FFFFFF", "icon": "💰"},
    "ไอที": {"header_bg": "#1E3A8A", "badge_bg": "#3B82F6", "badge_text": "#FFFFFF", "icon": "💻"},
    "เทคโนโลยี": {"header_bg": "#312E81", "badge_bg": "#6366F1", "badge_text": "#FFFFFF", "icon": "🚀"},
    "ทั่วไป": {"header_bg": "#0C4A6E", "badge_bg": "#0284C7", "badge_text": "#FFFFFF", "icon": "📰"},
    "สังคม": {"header_bg": "#0C4A6E", "badge_bg": "#0284C7", "badge_text": "#FFFFFF", "icon": "👥"},
    "การเมือง": {"header_bg": "#881337", "badge_bg": "#E11D48", "badge_text": "#FFFFFF", "icon": "🏛️"},
    "ข่าวเด่น": {"header_bg": "#78350F", "badge_bg": "#F59E0B", "badge_text": "#FFFFFF", "icon": "⭐"},
}

DEFAULT_THEME = {"header_bg": "#1E293B", "badge_bg": "#475569", "badge_text": "#FFFFFF", "icon": "📌"}


def get_thai_date_string(dt: Optional[datetime.datetime] = None) -> str:
    """Returns formatted Thai date string, e.g., 'พุธที่ 28 ต.ค. 2569'."""
    now = dt or datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=7)))
    day_name = THAI_DAYS[now.weekday()]
    day_num = now.day
    month_name = THAI_MONTHS_SHORT[now.month - 1]
    be_year = now.year + 543
    return f"{day_name}ที่ {day_num} {month_name} {be_year}"


def get_theme_for_category(category: str) -> dict[str, str]:
    """Finds theme colors for a category."""
    for key, theme in CATEGORY_THEMES.items():
        if key in category:
            return theme
    return DEFAULT_THEME


def sanitize_line_uri(raw_url: str) -> str:
    """
    Ensures a URL is properly percent-encoded and within LINE Messaging API
    1000-character limit for URI actions. Handles Thai characters and spaces.
    """
    if not raw_url:
        return ""
    try:
        parts = urlparse(raw_url.strip())
        path = quote(parts.path, safe="/:@&=+$,-_.!~*'()")
        query = quote(parts.query, safe="/:@&=+$,-_.!~*'()?=")
        fragment = quote(parts.fragment, safe="/:@&=+$,-_.!~*'()")
        clean = urlunparse((parts.scheme, parts.netloc, path, parts.params, query, fragment))
        return clean[:1000]
    except Exception:
        return raw_url.strip()[:1000]


def build_single_bubble(
    item: SummarizedNewsItem,
    index: int,
    total_count: int,
    date_str: str,
) -> dict[str, Any]:
    """Builds a single modern Flex bubble card for a news item."""
    theme = get_theme_for_category(item.category)
    badge_label = f"{theme['icon']} {item.category}"
    counter_label = f"ข่าวที่ {index}/{total_count}"

    # Header section
    header = {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": theme["header_bg"],
        "paddingTop": "14px",
        "paddingBottom": "14px",
        "paddingStart": "16px",
        "paddingEnd": "16px",
        "contents": [
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [
                            {
                                "type": "text",
                                "text": badge_label,
                                "color": theme["badge_text"],
                                "size": "xs",
                                "weight": "bold",
                                "align": "center",
                            }
                        ],
                        "backgroundColor": theme["badge_bg"],
                        "cornerRadius": "10px",
                        "paddingStart": "8px",
                        "paddingEnd": "8px",
                        "paddingTop": "3px",
                        "paddingBottom": "3px",
                        "flex": 0,
                    },
                    {
                        "type": "text",
                        "text": counter_label,
                        "color": "#94A3B8",
                        "size": "xs",
                        "align": "end",
                        "gravity": "center",
                    },
                ],
            },
            {
                "type": "text",
                "text": f"☀️ ข่าวเช้า • {date_str}",
                "color": "#CBD5E1",
                "size": "xxs",
                "margin": "xs",
            },
        ],
    }

    # Body bullet points
    bullet_boxes: list[dict[str, Any]] = []
    for bullet in item.summary_bullets:
        bullet_boxes.append(
            {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": "•",
                        "color": theme["badge_bg"],
                        "size": "sm",
                        "flex": 0,
                        "weight": "bold",
                    },
                    {
                        "type": "text",
                        "text": bullet,
                        "size": "sm",
                        "color": "#334155",
                        "wrap": True,
                        "flex": 1,
                    },
                ],
            }
        )

    body_contents: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": item.title,
            "weight": "bold",
            "size": "md",
            "wrap": True,
            "color": "#0F172A",
        },
        {
            "type": "separator",
            "margin": "md",
            "color": "#E2E8F0",
        },
        {
            "type": "box",
            "layout": "vertical",
            "margin": "md",
            "spacing": "sm",
            "contents": bullet_boxes,
        },
    ]

    # Importance reason callout
    if item.importance_reason:
        body_contents.append(
            {
                "type": "box",
                "layout": "vertical",
                "margin": "lg",
                "backgroundColor": "#F8FAFC",
                "cornerRadius": "8px",
                "paddingAll": "10px",
                "borderColor": "#E2E8F0",
                "borderWidth": "1px",
                "contents": [
                    {
                        "type": "text",
                        "text": f"💡 ทำไมต้องรู้: {item.importance_reason}",
                        "size": "xs",
                        "color": "#475569",
                        "wrap": True,
                    }
                ],
            }
        )

    # Source name note if present
    if item.source_name:
        body_contents.append(
            {
                "type": "text",
                "text": f"ที่มา: {item.source_name}",
                "size": "xxs",
                "color": "#94A3B8",
                "margin": "sm",
            }
        )

    body = {
        "type": "box",
        "layout": "vertical",
        "paddingAll": "16px",
        "contents": body_contents,
    }

    # Footer button
    footer_contents: list[dict[str, Any]] = []
    link_url = sanitize_line_uri(item.url)
    if link_url.startswith(("http://", "https://")):
        footer_contents.append(
            {
                "type": "button",
                "style": "primary",
                "height": "sm",
                "color": "#06C755",  # LINE Green
                "action": {
                    "type": "uri",
                    "label": "อ่านต่อ ↗",
                    "uri": link_url,
                },
            }
        )

    bubble: dict[str, Any] = {
        "type": "bubble",
        "size": "mega",
        "header": header,
        "body": body,
    }
    if footer_contents:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "paddingTop": "0px",
            "paddingBottom": "14px",
            "paddingStart": "16px",
            "paddingEnd": "16px",
            "contents": footer_contents,
        }

    return bubble


def build_flex_message(
    news_items: list[SummarizedNewsItem],
    date_str: Optional[str] = None,
) -> dict[str, Any]:
    """
    Builds a LINE Flex Carousel message with a card per news item.
    """
    formatted_date = date_str or get_thai_date_string()
    total_count = len(news_items)
    alt_text = f"☀️ สรุปข่าวเด่นเช้าวันนี้ ({total_count} ข่าว) • {formatted_date}"[:400]

    bubbles = [
        build_single_bubble(item, idx, total_count, formatted_date)
        for idx, item in enumerate(news_items, 1)
    ]

    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def build_fallback_text_message(
    news_items: list[SummarizedNewsItem],
    date_str: Optional[str] = None,
) -> dict[str, Any]:
    """
    Builds a structured Thai Text message as a reliable fallback.
    """
    formatted_date = date_str or get_thai_date_string()
    total_count = len(news_items)

    lines = [
        f"☀️ สรุปข่าวเด่นเช้าวันนี้ • {formatted_date}",
        f"คัดสรร {total_count} ข่าวสำคัญ อ่านจบได้ใน 1 นาที",
        "━" * 22,
        "",
    ]

    for idx, item in enumerate(news_items, 1):
        theme = get_theme_for_category(item.category)
        lines.append(f"[{idx}] {theme['icon']} {item.category}: {item.title}")
        for bullet in item.summary_bullets:
            lines.append(f"  • {bullet}")
        if item.importance_reason:
            lines.append(f"  💡 ทำไมต้องรู้: {item.importance_reason}")
        if item.url:
            lines.append(f"  🔗 อ่านต่อ: {item.url}")
        lines.append("")

    lines.append("━" * 22)
    lines.append("🤖 สรุปอัตโนมัติด้วย Gemini AI • Daily News Bot")

    return {
        "type": "text",
        "text": "\n".join(lines).strip(),
    }


def send_line_push_message(
    channel_access_token: str,
    user_id: str,
    messages: list[dict[str, Any]],
    timeout: int = 15,
) -> requests.Response:
    """Direct push message call to LINE Messaging API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {channel_access_token}",
    }
    payload = {
        "to": user_id,
        "messages": messages,
    }
    response = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=timeout)
    return response


def notify_line(
    news_items: list[SummarizedNewsItem],
    channel_access_token: str,
    user_id: str,
    date_str: Optional[str] = None,
    timeout: int = 15,
) -> bool:
    """
    Sends news items to LINE as a Flex Message.
    If Flex message fails, automatically falls back to a structured Text message.
    """
    if not news_items:
        logger.warning("No news items to send to LINE.")
        return False

    formatted_date = date_str or get_thai_date_string()

    # 1. Try sending Flex Message
    flex_msg = build_flex_message(news_items, formatted_date)
    try:
        res = send_line_push_message(channel_access_token, user_id, [flex_msg], timeout=timeout)
        if res.status_code == 200:
            logger.info("Successfully sent LINE Flex Message.")
            return True
        else:
            logger.warning(
                f"LINE Flex message rejected with HTTP {res.status_code}: {res.text}. "
                "Attempting fallback to structured Text message..."
            )
    except Exception as e:
        logger.warning(f"Error sending LINE Flex message: {e}. Attempting fallback to Text message...")

    # 2. Automatic Fallback to Text Message
    fallback_text_msg = build_fallback_text_message(news_items, formatted_date)
    try:
        res_text = send_line_push_message(channel_access_token, user_id, [fallback_text_msg], timeout=timeout)
        if res_text.status_code == 200:
            logger.info("Successfully sent fallback structured Text message to LINE.")
            return True
        else:
            logger.error(f"Fallback Text message also failed with HTTP {res_text.status_code}: {res_text.text}")
            res_text.raise_for_status()
            return False
    except Exception as e:
        logger.error(f"Fatal error sending fallback Text message to LINE: {e}")
        raise
