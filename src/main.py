"""Main entrypoint for Daily News Bot."""

import argparse
import json
import logging
import os
import sys

from .config import AppConfig, load_config
from .gemini_summarizer import fallback_summarize, summarize_with_gemini
from .line_notifier import (
    build_fallback_text_message,
    build_flex_message,
    build_flex_messages,
    get_thai_date_string,
    notify_line,
)
from .rss_fetcher import fetch_all_sources

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def safe_print(text: str) -> None:
    """Prints text safely without crashing on non-UTF-8 console encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        except Exception:
            print(text.encode("ascii", errors="replace").decode("ascii"))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_news")


def write_github_step_summary(news_items: list, date_str: str) -> None:
    """Writes a Markdown summary to GitHub Actions step summary if available."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(f"## ☀️ Daily News Summary - {date_str}\n\n")
            f.write(f"Successfully processed and delivered **{len(news_items)}** news items to LINE.\n\n")
            for idx, item in enumerate(news_items, 1):
                f.write(f"### {idx}. [{item.category}] {item.title}\n")
                for bullet in item.summary_bullets:
                    f.write(f"- {bullet}\n")
                if item.importance_reason:
                    f.write(f"\n> 💡 **ทำไมต้องรู้:** {item.importance_reason}\n\n")
                if item.url:
                    f.write(f"[อ่านต่อที่ต้นฉบับ]({item.url})\n\n")
                f.write("---\n")
    except Exception as e:
        logger.warning(f"Could not write to GITHUB_STEP_SUMMARY: {e}")


def run_pipeline(config: AppConfig) -> bool:
    """Executes the full pipeline: Fetch RSS -> Summarize with Gemini -> Push to LINE."""
    thai_date = get_thai_date_string()
    logger.info(f"Starting Daily News Bot for {thai_date}")

    # 1. Fetch RSS candidate news
    logger.info("Fetching news from configured RSS sources...")
    candidates = fetch_all_sources(
        config.sources,
        default_timeout=config.settings.fetch_timeout_seconds,
        default_max_per_source=config.settings.max_items_per_source,
    )
    logger.info(f"Total deduplicated candidate news fetched: {len(candidates)}")

    if not candidates:
        logger.error("No news candidates fetched from any enabled source. Aborting.")
        return False

    # 2. Filter & Summarize with Gemini
    summarized_items = []
    if config.gemini_api_key:
        try:
            logger.info(f"Sending candidates to Gemini ({config.settings.gemini_model}) for selection & summarization...")
            summarized_items = summarize_with_gemini(
                candidates=candidates,
                api_key=config.gemini_api_key,
                model=config.settings.gemini_model,
                min_items=config.settings.min_news_items,
                max_items=config.settings.max_news_items,
            )
            logger.info(f"Gemini selected and summarized {len(summarized_items)} news items.")
            if len(summarized_items) < config.settings.min_news_items:
                logger.warning(
                    f"Gemini returned {len(summarized_items)} items (< {config.settings.min_news_items}). "
                    "Backfilling remaining slots from candidate feeds..."
                )
                from .gemini_summarizer import (
                    SummarizedNewsItem,
                    clean_fallback_summary,
                    normalize_category,
                    sort_items_by_category,
                )
                used_links = {it.url for it in summarized_items if it.url}
                for cand in candidates:
                    if cand.link not in used_links:
                        used_links.add(cand.link)
                        norm_cat = normalize_category(cand.category)
                        bullet = clean_fallback_summary(cand.summary)
                        summarized_items.append(
                            SummarizedNewsItem(
                                title=cand.title,
                                category=norm_cat,
                                summary_bullets=[bullet],
                                importance_reason="ข่าวเด่นประจำเช้าวันนี้",
                                url=cand.link,
                                source_name=cand.source_name,
                            )
                        )
                    if len(summarized_items) >= config.settings.max_news_items:
                        break
                summarized_items = sort_items_by_category(summarized_items[:config.settings.max_news_items])
        except Exception as e:
            logger.error(f"Gemini summarization failed: {e}. Falling back to raw feed selection.")
            summarized_items = fallback_summarize(
                candidates,
                min_items=config.settings.min_news_items,
                max_items=config.settings.max_news_items,
            )
    else:
        logger.warning("No GEMINI_API_KEY provided. Using fallback feed selection.")
        summarized_items = fallback_summarize(
            candidates,
            min_items=config.settings.min_news_items,
            max_items=config.settings.max_news_items,
        )

    if not summarized_items:
        logger.error("No summarized news items available to send.")
        return False

    # 3. Handle Dry Run vs Production Send
    if config.dry_run:
        logger.info("=== DRY RUN MODE ENABLED (No messages sent to LINE) ===")
        text_msg = build_fallback_text_message(summarized_items, thai_date)
        safe_print("\n" + "=" * 50)
        safe_print("PREVIEW OF TEXT MESSAGE:")
        safe_print("=" * 50)
        safe_print(text_msg["text"])
        safe_print("=" * 50 + "\n")

        flex_msgs = build_flex_messages(summarized_items, thai_date)
        safe_print(f"FLEX MESSAGE PAYLOAD ({len(flex_msgs)} carousel message(s)):")
        safe_print(json.dumps(flex_msgs[0] if flex_msgs else {}, ensure_ascii=False, indent=2)[:1000] + "\n...[truncated]...")
        write_github_step_summary(summarized_items, thai_date)
        return True

    # 4. Check LINE credentials
    if not config.line_channel_access_token or not config.line_user_id:
        logger.error(
            "LINE credentials missing! Please configure LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID."
        )
        return False

    # 5. Push to LINE
    logger.info("Delivering news to LINE...")
    success = notify_line(
        news_items=summarized_items,
        channel_access_token=config.line_channel_access_token,
        user_id=config.line_user_id,
        date_str=thai_date,
    )

    if success:
        logger.info("Daily News Bot completed successfully!")
        write_github_step_summary(summarized_items, thai_date)
        return True
    else:
        logger.error("Failed to deliver news to LINE.")
        return False


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Daily News Morning Bot (Serverless)")
    parser.add_argument(
        "--config",
        default=os.getenv("CONFIG_PATH", "config.yaml"),
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and summarize news without sending to LINE",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.dry_run:
        config.dry_run = True

    # Credential warning for normal run
    if not config.dry_run:
        missing = config.validate_credentials()
        if missing:
            logger.error(
                f"Missing required environment variables/secrets: {', '.join(missing)}.\n"
                "Tip: For local testing without LINE credentials, run with --dry-run or DRY_RUN=true"
            )
            sys.exit(1)

    success = run_pipeline(config)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
