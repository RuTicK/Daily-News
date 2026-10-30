"""RSS and Atom news feed fetcher and parser."""

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .config import SourceConfig

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 DailyNewsBot/1.0"
)


@dataclass
class CandidateNewsItem:
    title: str
    link: str
    summary: str
    source_name: str
    category: str
    published: Optional[str] = None


def clean_html(text: Optional[str]) -> str:
    """Removes HTML tags and unescapes HTML entities."""
    if not text:
        return ""
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", text)
    # Unescape HTML entities (&amp;, &lt;, &gt;, &quot;, &#39;, etc.)
    cleaned = html.unescape(cleaned)
    # Normalize multiple whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_title_for_dedup(title: str) -> str:
    """Creates a normalized string for title deduplication."""
    cleaned = clean_html(title).lower()
    # Remove common punctuation and whitespace
    cleaned = re.sub(r"[\s\-_—|–\.,;:!?'\"“”‘’\(\)\[\]{}]+", "", cleaned)
    return cleaned


TRACKING_QUERY_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "oc",
}


def clean_url_for_dedup(raw_url: str) -> str:
    """
    Removes fragments and common marketing tracking parameters while preserving
    meaningful query parameters that distinguish separate articles.
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        filtered_query = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k.lower() not in TRACKING_QUERY_PARAMS
        ]
        filtered_query.sort()
        new_query = urlencode(filtered_query)
        path = parsed.path.rstrip("/") if len(parsed.path) > 1 else parsed.path
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", new_query, ""))
    except Exception:
        return raw_url.strip()


def find_first_child(elem: ET.Element, tags: list[str]) -> Optional[ET.Element]:
    """Finds the first matching child element without relying on truthiness."""
    for tag in tags:
        child = elem.find(tag)
        if child is not None:
            return child
    return None


def parse_feed_xml(
    xml_text_or_bytes: str | bytes,
    source_name: str,
    category: str,
    max_items: int = 5,
) -> list[CandidateNewsItem]:
    """
    Parses RSS 2.0 or Atom 1.0 XML content.
    Returns up to max_items candidate items.
    """
    items: list[CandidateNewsItem] = []
    
    if isinstance(xml_text_or_bytes, str):
        # Strip potential BOM or leading whitespace
        xml_bytes = xml_text_or_bytes.strip().encode("utf-8")
    else:
        xml_bytes = xml_text_or_bytes.strip()

    if not xml_bytes:
        return items

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.warning(f"XML parse error for source '{source_name}': {e}")
        # Try a relaxed fallback cleanup if possible
        try:
            cleaned_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", xml_bytes.decode("utf-8", errors="replace"))
            root = ET.fromstring(cleaned_text.encode("utf-8"))
        except Exception:
            return items

    # Check for Atom feed (<feed xmlns="http://www.w3.org/2005/Atom">)
    atom_ns = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{atom_ns}entry") or root.findall("entry")
    if entries:
        for entry in entries[:max_items]:
            title_elem = find_first_child(entry, [f"{atom_ns}title", "title"])
            title = clean_html(title_elem.text if title_elem is not None else "")
            
            # Find alternate link
            link = ""
            for l in entry.findall(f"{atom_ns}link") + entry.findall("link"):
                rel = l.attrib.get("rel", "alternate")
                if rel == "alternate" and "href" in l.attrib:
                    link = l.attrib["href"]
                    break
                elif "href" in l.attrib and not link:
                    link = l.attrib["href"]

            summary_elem = find_first_child(
                entry,
                [f"{atom_ns}summary", "summary", f"{atom_ns}content", "content"]
            )
            summary = clean_html(summary_elem.text if summary_elem is not None else "")
            
            pub_elem = find_first_child(
                entry,
                [f"{atom_ns}published", "published", f"{atom_ns}updated", "updated"]
            )
            published = pub_elem.text.strip() if (pub_elem is not None and pub_elem.text) else None

            if title and link:
                items.append(
                    CandidateNewsItem(
                        title=title,
                        link=link.strip(),
                        summary=summary,
                        source_name=source_name,
                        category=category,
                        published=published,
                    )
                )
        return items

    # Check for RSS 2.0 (<rss><channel><item>)
    channel = root.find("channel")
    item_nodes = channel.findall("item") if channel is not None else root.findall(".//item")
    for item in item_nodes[:max_items]:
        title_elem = item.find("title")
        title = clean_html(title_elem.text if title_elem is not None else "")

        link_elem = item.find("link")
        link = link_elem.text.strip() if (link_elem is not None and link_elem.text) else ""
        if not link and link_elem is not None and "href" in link_elem.attrib:
            link = link_elem.attrib["href"].strip()
        if not link:
            guid_elem = item.find("guid")
            if guid_elem is not None and guid_elem.text and guid_elem.text.startswith("http"):
                link = guid_elem.text.strip()

        desc_elem = item.find("description")
        desc = clean_html(desc_elem.text if desc_elem is not None else "")

        pub_elem = item.find("pubDate")
        published = pub_elem.text.strip() if (pub_elem is not None and pub_elem.text) else None

        if title and link:
            items.append(
                CandidateNewsItem(
                    title=title,
                    link=link,
                    summary=desc,
                    source_name=source_name,
                    category=category,
                    published=published,
                )
            )

    return items


def fetch_source_feed(
    source: SourceConfig,
    timeout: int = 15,
    session: Optional[requests.Session] = None,
) -> list[CandidateNewsItem]:
    """Fetches and parses a single RSS source."""
    if not source.enabled:
        return []

    sess = session or requests.Session()
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }

    try:
        response = sess.get(source.url, headers=headers, timeout=timeout)
        response.raise_for_status()
        max_items = source.max_items if source.max_items else 5
        return parse_feed_xml(response.content, source.name, source.category, max_items=max_items)
    except Exception as e:
        logger.warning(f"Failed to fetch feed '{source.name}' from {source.url}: {e}")
        return []


def fetch_all_sources(
    sources: list[SourceConfig],
    default_timeout: int = 15,
    default_max_per_source: int = 5,
) -> list[CandidateNewsItem]:
    """
    Fetches news from all enabled sources, deduplicates, and returns candidates
    interleaved across sources for optimal category and source diversity.
    """
    session = requests.Session()
    source_results: list[list[CandidateNewsItem]] = []

    for src in sources:
        if not src.enabled:
            continue
        max_items = src.max_items or default_max_per_source
        src_items = fetch_source_feed(src, timeout=default_timeout, session=session)
        logger.info(f"Fetched {len(src_items)} items from '{src.name}' ({src.category})")
        if src_items:
            source_results.append(src_items[:max_items])

    # Round-robin interleave across sources to balance news categories
    all_candidates: list[CandidateNewsItem] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    max_depth = max((len(items) for items in source_results), default=0)
    for depth in range(max_depth):
        for items in source_results:
            if depth < len(items):
                item = items[depth]
                clean_url = clean_url_for_dedup(item.link)
                norm_title = normalize_title_for_dedup(item.title)
                if not norm_title or norm_title in seen_titles or clean_url in seen_urls:
                    continue

                seen_titles.add(norm_title)
                seen_urls.add(clean_url)
                all_candidates.append(item)

    return all_candidates
