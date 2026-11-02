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


DEFAULT_CATEGORY_QUOTAS: dict[str, int] = {
    "ข่าวทั่วไทย": 7,
    "ข่าวการเมือง": 3,
    "เทคโนโลยี": 3,
    "หุ้น": 2,
}

CANONICAL_CATEGORY_ORDER: dict[str, int] = {
    "ข่าวทั่วไทย": 0,
    "ข่าวการเมือง": 1,
    "เทคโนโลยี": 2,
    "หุ้น": 3,
}


def normalize_category(category: str) -> str:
    """Normalizes feed category aliases to the 4 canonical categories."""
    cat = (category or "").strip()
    cat_lower = cat.lower()

    # 1. การเมือง (Politics)
    if "การเมือง" in cat or "politic" in cat_lower:
        return "ข่าวการเมือง"

    # 2. เทคโนโลยี (Technology / IT)
    if any(k in cat for k in ["เทคโนโลยี", "ไอที"]) or any(k in cat_lower for k in ["tech", "it", "gadget", "ai", "digital"]):
        return "เทคโนโลยี"

    # 3. หุ้น (Stocks / Finance / Economy / Wealth)
    if any(k in cat for k in ["หุ้น", "ธุรกิจ", "การเงิน", "เศรษฐกิจ"]) or any(k in cat_lower for k in ["wealth", "stock", "finance", "biz", "business", "market", "economy"]):
        return "หุ้น"

    # 4. ข่าวทั่วไทย (General Thai / Local / Society)
    if any(k in cat for k in ["ทั่วไทย", "ทั่วไป", "สังคม", "ข่าวเด่น", "ในประเทศ", "อาชญากรรม"]) or any(k in cat_lower for k in ["thailand", "general", "local"]):
        return "ข่าวทั่วไทย"

    return "ข่าวทั่วไทย" if cat not in CANONICAL_CATEGORY_ORDER else cat


def sort_items_by_category(items: list["SummarizedNewsItem"]) -> list["SummarizedNewsItem"]:
    """Sorts news items according to canonical category order."""
    return sorted(items, key=lambda it: CANONICAL_CATEGORY_ORDER.get(it.category, 99))


@dataclass
class SummarizedNewsItem:
    title: str
    category: str
    summary_bullets: list[str]
    importance_reason: str
    url: str
    source_name: str = ""


SYSTEM_INSTRUCTION = """คุณคือบรรณาธิการข่าวเช้ามืออาชีพ มีหน้าที่คัดเลือกและสรุปข่าวเด่นประจำวันสำหรับคนไทย
เป้าหมายคือช่วยให้ผู้อ่านอัปเดตข่าวสำคัญที่สุดได้ครบถ้วนและรวดเร็ว

เกณฑ์การทำงาน:
1. เลือกข่าวเด่นรวมทั้งหมด 15 ข่าว จากรายการข่าวที่ส่งให้ โดยแบ่งสัดส่วนตามหมวดหมู่ต่อไปนี้อย่างเคร่งครัด:
   - ข่าวทั่วไทย: 7 ข่าว (เหตุการณ์สำคัญ นโยบาย และข่าวสังคมในประเทศ)
   - ข่าวการเมือง: 3 ข่าว (ความเคลื่อนไหวทางการเมือง รัฐบาล และรัฐสภา)
   - เทคโนโลยี: 3 ข่าว (นวัตกรรม เทคโนโลยี ไอที AI และ Gadget)
   - หุ้น: 2 ข่าว (ตลาดหุ้น การลงทุน ภาวะเศรษฐกิจและการเงิน)
2. สรุปเนื้อหาข่าวแต่ละชิ้นเป็น Bullet points ภาษาไทย สั้น กระชับ ตรงประเด็น (1-2 ข้อต่อข่าว เพื่อให้อ่านง่ายและไม่ยาวเกินไป)
3. อธิบายเหตุผลสั้นๆ 1 ประโยค (importance_reason) ว่าทำไมข่าวนี้ถึงสำคัญต่อคนไทยเช้านี้
4. ต้องคง URL ข่าวต้นฉบับให้ตรงกับรายการที่ให้มาอย่างถูกต้อง ห้ามแต่งหรือเปลี่ยน URL
5. ระบุ category ให้ตรงกับ 4 หมวดนี้เท่านั้น: ข่าวทั่วไทย, ข่าวการเมือง, เทคโนโลยี, หุ้น
"""


def build_prompt(
    candidates: list[CandidateNewsItem],
    min_items: int = 15,
    max_items: int = 15,
    category_quotas: Optional[dict[str, int]] = None,
) -> str:
    """Builds the user prompt for Gemini containing candidate news items."""
    quotas = category_quotas or (DEFAULT_CATEGORY_QUOTAS if max_items >= 15 else None)
    if quotas:
        quota_str = ", ".join(f"{cat} {count} ข่าว" for cat, count in quotas.items())
        header = f"โปรดคัดเลือกข่าวเด่นรวม {min_items} ข่าวจากรายการข่าวต่อไปนี้ โดยแบ่งตามหมวดหมู่: {quota_str} และสรุปตามรูปแบบ JSON ที่กำหนด:"
    elif min_items == max_items:
        header = f"โปรดคัดเลือกข่าวเด่น {min_items} ข่าวจากรายการข่าวต่อไปนี้ และสรุปตามรูปแบบ JSON ที่กำหนด:"
    else:
        header = f"โปรดคัดเลือกข่าวเด่น {min_items}-{max_items} ข่าวจากรายการข่าวต่อไปนี้ และสรุปตามรูปแบบ JSON ที่กำหนด:"

    lines = [
        header,
        "",
    ]
    for idx, item in enumerate(candidates, 1):
        norm_cat = normalize_category(item.category)
        lines.append(f"[{idx}] หัวข้อ: {item.title}")
        lines.append(f"    หมวด: {norm_cat} | แหล่งข่าว: {item.source_name}")
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
        '      "category": "หมวดข่าว (ระบุเป็น ข่าวทั่วไทย, ข่าวการเมือง, เทคโนโลยี, หรือ หุ้น)",\n'
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
    seen_urls: set[str] = set()
    for item in items_raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        raw_category = str(item.get("category", "ข่าวทั่วไทย")).strip() or "ข่าวทั่วไทย"
        category = normalize_category(raw_category)
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
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
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
    min_items: int = 15,
    max_items: int = 15,
    category_quotas: Optional[dict[str, int]] = None,
    max_candidate_pool: int = 35,
    timeout: int = 30,
) -> list[SummarizedNewsItem]:
    """
    Calls Gemini API to filter and summarize candidate news items into structured JSON.
    """
    if not candidates:
        logger.warning("No candidate news items provided to Gemini.")
        return []

    url = f"{GEMINI_API_URL_TEMPLATE.format(model=model)}?key={api_key}"
    # Cap candidates sent to Gemini at max_candidate_pool (default 35 items) to ensure ample variety across categories
    effective_candidates = candidates[:max_candidate_pool]
    prompt = build_prompt(
        effective_candidates,
        min_items=min_items,
        max_items=max_items,
        category_quotas=category_quotas,
    )

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
    items = parse_gemini_json(raw_text)
    if not items:
        raise ValueError("Gemini returned no valid summarized news items.")

    return sort_items_by_category(items[:max_items])


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
    min_items: int = 15,
    max_items: int = 15,
    category_quotas: Optional[dict[str, int]] = None,
) -> list[SummarizedNewsItem]:
    """
    Fallback summarizer when Gemini API is unavailable.
    Picks top candidates conforming to category quotas (default: 7 ข่าวทั่วไทย, 3 ข่าวการเมือง, 3 เทคโนโลยี, 2 หุ้น).
    """
    results: list[SummarizedNewsItem] = []
    if not candidates:
        return results

    quotas = category_quotas if category_quotas is not None else (
        DEFAULT_CATEGORY_QUOTAS if max_items >= 15 else None
    )

    if quotas:
        # 1. Bucket candidates by normalized category
        cat_items: dict[str, list[CandidateNewsItem]] = {cat: [] for cat in quotas}
        other_items: list[CandidateNewsItem] = []

        for item in candidates:
            norm_cat = normalize_category(item.category)
            if norm_cat in cat_items:
                cat_items[norm_cat].append(item)
            else:
                other_items.append(item)

        # 2. Pick items according to quota for each category
        used_links: set[str] = set()
        for cat, quota in quotas.items():
            picked = 0
            for item in cat_items.get(cat, []):
                if item.link not in used_links and picked < quota:
                    used_links.add(item.link)
                    picked += 1
                    bullet = clean_fallback_summary(item.summary)
                    results.append(
                        SummarizedNewsItem(
                            title=item.title,
                            category=cat,
                            summary_bullets=[bullet],
                            importance_reason="ข่าวเด่นประจำเช้าวันนี้",
                            url=item.link,
                            source_name=item.source_name,
                        )
                    )

        # 3. If any quota was underfilled, fill remaining slots up to max_items
        if len(results) < max_items:
            for item in candidates:
                if item.link not in used_links:
                    used_links.add(item.link)
                    norm_cat = normalize_category(item.category)
                    bullet = clean_fallback_summary(item.summary)
                    results.append(
                        SummarizedNewsItem(
                            title=item.title,
                            category=norm_cat,
                            summary_bullets=[bullet],
                            importance_reason="ข่าวเด่นประจำเช้าวันนี้",
                            url=item.link,
                            source_name=item.source_name,
                        )
                    )
                if len(results) >= max_items:
                    break

        return sort_items_by_category(results[:max_items])

    # Non-quota fallback (e.g., when small limits like 3-5 items are explicitly requested)
    seen_categories: set[str] = set()
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
