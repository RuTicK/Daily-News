"""Gemini AI news filter and summarizer."""

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

from .rss_fetcher import CandidateNewsItem

logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class SummarizedNewsItem:
    title: str
    category: str
    summary_bullets: list[str]
    importance_reason: str
    url: str
    source_name: str = ""


SYSTEM_INSTRUCTION = """คุณคือบรรณาธิการข่าวเช้ามืออาชีพ มีหน้าที่คัดเลือกและสรุปข่าวเด่นประจำวันสำหรับคนไทย
เป้าหมายคือช่วยให้ผู้อ่านอัปเดตข่าวสำคัญที่สุดได้ครบถ้วนภายในเวลา 1 นาที

เกณฑ์การทำงาน:
1. เลือกข่าวเด่นเพียง 3-5 ข่าว จากรายการข่าวที่ส่งให้ โดยเน้นข่าวที่มีผลกระทบสำคัญต่อชีวิตประจำวัน เศรษฐกิจ การเงิน สังคม หรือเทคโนโลยี
2. พยายามกระจายหมวดหมู่ให้หลากหลาย (เช่น ทั่วไป, ธุรกิจ, การเงิน, ไอที, เทคโนโลยี)
3. สรุปเนื้อหาข่าวแต่ละชิ้นเป็น Bullet points ภาษาไทย สั้น กระชับ ตรงประเด็น (2-3 ข้อต่อข่าว)
4. อธิบายเหตุผลสั้นๆ 1 ประโยค (importance_reason) ว่าทำไมข่าวนี้ถึงสำคัญต่อคนไทยเช้านี้
5. ต้องคง URL ข่าวต้นฉบับให้ตรงกับรายการที่ให้มาอย่างถูกต้อง ห้ามแต่งหรือเปลี่ยน URL
"""


def build_prompt(candidates: list[CandidateNewsItem], min_items: int = 3, max_items: int = 5) -> str:
    """Builds the user prompt for Gemini containing candidate news items."""
    lines = [
        f"โปรดคัดเลือกข่าวเด่น {min_items}-{max_items} ข่าวจากรายการข่าวต่อไปนี้ และสรุปตามรูปแบบ JSON ที่กำหนด:",
        "",
    ]
    for idx, item in enumerate(candidates, 1):
        lines.append(f"[{idx}] หัวข้อ: {item.title}")
        lines.append(f"    หมวด: {item.category} | แหล่งข่าว: {item.source_name}")
        lines.append(f"    URL: {item.link}")
        if item.summary:
            # Clip summary snippet
            snippet = item.summary[:300] + ("..." if len(item.summary) > 300 else "")
            lines.append(f"    เนื้อหาย่อ: {snippet}")
        lines.append("")

    lines.append(
        "ตอบกลับด้วยรูปแบบ JSON ตามโครงสร้างนี้เท่านั้น:\n"
        "{\n"
        '  "news": [\n'
        "    {\n"
        '      "title": "พาดหัวข่าวที่กระชับและน่าสนใจ",\n'
        '      "category": "หมวดข่าว (เช่น ธุรกิจ, ทั่วไป, ไอที)",\n'
        '      "summary_bullets": [\n'
        '        "ประเด็นสำคัญข้อที่ 1",\n'
        '        "ประเด็นสำคัญข้อที่ 2"\n'
        "      ],\n"
        '      "importance_reason": "ทำไมเรื่องนี้ถึงสำคัญต่อคนไทยเช้านี้",\n'
        '      "url": "URL ข่าวต้นฉบับที่ตรงกัน",\n'
        '      "source_name": "ชื่อสำนักข่าวต้นทาง"\n'
        "    }\n"
        "  ]\n"
        "}"
    )
    return "\n".join(lines)


def clean_json_response(raw_text: str) -> str:
    """Strips Markdown backticks, code fences, and surrounding conversational text from JSON response."""
    cleaned = raw_text.strip()
    # 1. Search for markdown code fences anywhere in the response
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, flags=re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    # 2. Search for top-level JSON object {...} or array [...]
    json_block = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", cleaned)
    if json_block:
        return json_block.group(1).strip()

    return cleaned


def parse_gemini_json(raw_json_text: str) -> list[SummarizedNewsItem]:
    """Parses JSON text into a list of SummarizedNewsItem."""
    cleaned = clean_json_response(raw_json_text)
    data = json.loads(cleaned)

    # Could be {"news": [...]} or directly [...]
    items_raw = data.get("news") if isinstance(data, dict) else data
    if not isinstance(items_raw, list):
        raise ValueError("Gemini output does not contain a list of news items.")

    results: list[SummarizedNewsItem] = []
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        category = str(item.get("category", "ทั่วไป")).strip()
        importance = str(item.get("importance_reason", "")).strip()
        source_name = str(item.get("source_name", "")).strip()

        bullets_raw = item.get("summary_bullets", [])
        if isinstance(bullets_raw, list):
            bullets = [str(b).strip() for b in bullets_raw if str(b).strip()]
        elif isinstance(bullets_raw, str):
            bullets = [bullets_raw.strip()]
        else:
            bullets = []

        if title and (url or bullets):
            results.append(
                SummarizedNewsItem(
                    title=title,
                    category=category,
                    summary_bullets=bullets,
                    importance_reason=importance,
                    url=url,
                    source_name=source_name,
                )
            )
    return results


def summarize_with_gemini(
    candidates: list[CandidateNewsItem],
    api_key: str,
    model: str = "gemini-2.5-flash",
    min_items: int = 3,
    max_items: int = 5,
    timeout: int = 30,
) -> list[SummarizedNewsItem]:
    """
    Calls Gemini API to filter and summarize candidate news items into structured JSON.
    """
    if not candidates:
        logger.warning("No candidate news items provided to Gemini.")
        return []

    url = f"{GEMINI_API_URL_TEMPLATE.format(model=model)}?key={api_key}"
    # Cap candidates sent to Gemini at 15 items to comply with prompt specification
    effective_candidates = candidates[:15]
    prompt = build_prompt(effective_candidates, min_items=min_items, max_items=max_items)

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "systemInstruction": {
            "parts": [{"text": SYSTEM_INSTRUCTION}],
        },
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.8,
            "responseMimeType": "application/json",
        },
    }

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()

    res_data = response.json()
    candidates_res = res_data.get("candidates", [])
    if not candidates_res:
        raise ValueError(f"No response candidate returned by Gemini: {res_data}")

    first_candidate = candidates_res[0]
    content = first_candidate.get("content", {})
    parts = content.get("parts", [])
    if not parts or "text" not in parts[0]:
        raise ValueError(f"Empty text in Gemini response: {first_candidate}")

    raw_text = parts[0]["text"]
    return parse_gemini_json(raw_text)


def clean_fallback_summary(raw: Optional[str], max_len: int = 180) -> str:
    """Cleans RSS summary snippet by stripping footers and truncating cleanly."""
    if not raw:
        return "อ่านรายละเอียดเพิ่มเติมได้ที่ลิงก์ข่าวต้นฉบับ"
    # Remove common promotional footers (e.g. 'The post ... appeared first on ...')
    cleaned = re.sub(r"The post .* appeared first on .*", "", raw, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\[\u2026\]|\.\.\.", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_len:
        snippet = cleaned[:max_len]
        if " " in snippet:
            cleaned = snippet.rsplit(" ", 1)[0] + "..."
        else:
            cleaned = snippet + "..."
    return cleaned if cleaned else "อ่านรายละเอียดเพิ่มเติมได้ที่ลิงก์ข่าวต้นฉบับ"


def fallback_summarize(
    candidates: list[CandidateNewsItem],
    min_items: int = 3,
    max_items: int = 5,
) -> list[SummarizedNewsItem]:
    """
    Fallback summarizer when Gemini API is unavailable.
    Picks top diverse candidates directly from raw RSS feeds.
    """
    results: list[SummarizedNewsItem] = []
    seen_categories: set[str] = set()

    # First pass: try to pick 1 per category
    for item in candidates:
        if item.category not in seen_categories:
            seen_categories.add(item.category)
            bullet = clean_fallback_summary(item.summary)
            results.append(
                SummarizedNewsItem(
                    title=item.title,
                    category=item.category,
                    summary_bullets=[bullet],
                    importance_reason="ข่าวเด่นประจำเช้าวันนี้",
                    url=item.link,
                    source_name=item.source_name,
                )
            )
        if len(results) >= max_items:
            break

    # Second pass: fill up to min_items if needed
    if len(results) < min_items:
        for item in candidates:
            if not any(r.url == item.link for r in results):
                bullet = clean_fallback_summary(item.summary)
                results.append(
                    SummarizedNewsItem(
                        title=item.title,
                        category=item.category,
                        summary_bullets=[bullet],
                        importance_reason="ข่าวเด่นประจำเช้าวันนี้",
                        url=item.link,
                        source_name=item.source_name,
                    )
                )
            if len(results) >= max_items:
                break

    return results
