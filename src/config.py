"""Configuration loader and validator for Daily News Bot."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class SourceConfig:
    name: str
    category: str
    url: str
    enabled: bool = True
    max_items: Optional[int] = None


@dataclass
class SettingsConfig:
    min_news_items: int = 3
    max_news_items: int = 5
    gemini_model: str = "gemini-2.5-flash"
    fetch_timeout_seconds: int = 15
    max_items_per_source: int = 5


@dataclass
class AppConfig:
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    sources: list[SourceConfig] = field(default_factory=list)
    gemini_api_key: Optional[str] = None
    line_channel_access_token: Optional[str] = None
    line_user_id: Optional[str] = None
    dry_run: bool = False

    def validate_credentials(self) -> list[str]:
        """Check for missing credentials. Returns a list of missing variable names."""
        missing = []
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.line_channel_access_token:
            missing.append("LINE_CHANNEL_ACCESS_TOKEN")
        if not self.line_user_id:
            missing.append("LINE_USER_ID")
        return missing


def _simple_yaml_parse(text: str) -> dict[str, Any]:
    """
    Fallback parser for basic YAML if PyYAML is not installed.
    Supports top-level dicts, sub-dicts, and lists of dicts.
    """
    result: dict[str, Any] = {}
    current_key: Optional[str] = None
    current_list: Optional[list[Any]] = None
    current_list_item: Optional[dict[str, Any]] = None

    lines = text.splitlines()
    for raw_line in lines:
        # Strip comments
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # Top-level key: e.g. "settings:" or "sources:"
        if indent == 0 and stripped.endswith(":"):
            current_key = stripped[:-1].strip()
            current_list = None
            current_list_item = None
            if current_key == "sources":
                result[current_key] = []
                current_list = result[current_key]
            else:
                result[current_key] = {}
            continue

        # Inside settings dict (indent 2)
        if current_key == "settings" and indent >= 2 and ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v.isdigit():
                val: Any = int(v)
            elif v.lower() == "true":
                val = True
            elif v.lower() == "false":
                val = False
            else:
                val = v
            result["settings"][k] = val
            continue

        # Inside sources list (indent 2 with "- " or indent 4 with fields)
        if current_key == "sources" and current_list is not None:
            if stripped.startswith("- "):
                current_list_item = {}
                current_list.append(current_list_item)
                item_content = stripped[2:].strip()
                if ":" in item_content:
                    k, v = item_content.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    current_list_item[k] = v
            elif current_list_item is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v.isdigit():
                    val = int(v)
                elif v.lower() == "true":
                    val = True
                elif v.lower() == "false":
                    val = False
                else:
                    val = v
                current_list_item[k] = val

    return result


def load_yaml(path_or_content: str | Path) -> dict[str, Any]:
    """Loads YAML using PyYAML if available, or fallback parser."""
    text: str
    if isinstance(path_or_content, Path) or (isinstance(path_or_content, str) and os.path.exists(path_or_content)):
        with open(path_or_content, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = str(path_or_content)

    try:
        import yaml
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            return parsed
        return {}
    except ImportError:
        return _simple_yaml_parse(text)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Loads configuration from YAML file and merges environment variables."""
    cfg_data: dict[str, Any] = {}
    path = Path(config_path)
    if path.is_file():
        cfg_data = load_yaml(path)

    # Parse settings
    settings_data = cfg_data.get("settings", {})
    settings = SettingsConfig(
        min_news_items=int(settings_data.get("min_news_items", 3)),
        max_news_items=int(settings_data.get("max_news_items", 5)),
        gemini_model=os.getenv("GEMINI_MODEL") or str(settings_data.get("gemini_model", "gemini-2.5-flash")),
        fetch_timeout_seconds=int(settings_data.get("fetch_timeout_seconds", 15)),
        max_items_per_source=int(settings_data.get("max_items_per_source", 5)),
    )

    # Parse sources
    sources_data = cfg_data.get("sources", [])
    sources: list[SourceConfig] = []
    for s in sources_data:
        if isinstance(s, dict) and "name" in s and "url" in s:
            sources.append(
                SourceConfig(
                    name=str(s["name"]),
                    category=str(s.get("category", "ทั่วไป")),
                    url=str(s["url"]),
                    enabled=bool(s.get("enabled", True)),
                    max_items=int(s["max_items"]) if "max_items" in s and s["max_items"] is not None else None,
                )
            )

    dry_run_env = os.getenv("DRY_RUN", "").strip().lower()
    dry_run = dry_run_env in ("true", "1", "yes")

    return AppConfig(
        settings=settings,
        sources=sources,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        line_channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"),
        line_user_id=os.getenv("LINE_USER_ID"),
        dry_run=dry_run,
    )
