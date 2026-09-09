"""HTML web scraper using BeautifulSoup + optional regex."""

from __future__ import annotations

from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.network_utils import clamp_timeout, http_client, validate_url, with_retries
from pixoo.utils.regex_extractor import extract_regex
from pixoo.utils.secrets import resolve_secrets


class WebScraperPlugin(DataSourcePlugin):
    name = "web_scraper"
    description = "Extract values from HTML pages (CSS/XPath + regex)"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "url": {"type": "string", "label": "Page URL", "required": True},
            "selector": {"type": "string", "label": "CSS / XPath", "required": True, "default": "body"},
            "selector_type": {
                "type": "string",
                "label": "Selector type",
                "enum": ["css", "xpath"],
                "default": "css",
            },
            "attribute": {
                "type": "string",
                "label": "Attribute",
                "default": "text",
            },
            "regex": {"type": "string", "label": "Regex (optional)", "default": ""},
            "multiple": {"type": "boolean", "label": "Multiple", "default": False},
            "timeout": {"type": "integer", "label": "Timeout (s)", "default": 10},
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 300},
            "fallback_value": {"type": "string", "label": "Fallback", "default": "N/A"},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        cfg = resolve_secrets(dict(config))
        return validate_url(str(cfg.get("url") or "")) and bool(str(cfg.get("selector") or "").strip())

    def fetch_data(self, config: dict[str, Any]) -> Any:
        from bs4 import BeautifulSoup

        cfg = resolve_secrets(dict(config))
        url = str(cfg["url"])
        selector = str(cfg.get("selector") or "body")
        selector_type = str(cfg.get("selector_type") or "css").lower()
        attribute = str(cfg.get("attribute") or "text")
        regex = str(cfg.get("regex") or "")
        multiple = bool(cfg.get("multiple"))
        timeout = clamp_timeout(cfg.get("timeout"), 10)
        fallback = cfg.get("fallback_value", "N/A")

        def _do() -> str:
            with http_client(timeout=timeout) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text

        html = with_retries(_do, retries=int(cfg.get("retries") or 2))
        texts: list[str] = []

        if selector_type == "xpath":
            from lxml import html as lhtml

            tree = lhtml.fromstring(html)
            nodes = tree.xpath(selector)
            for node in nodes:
                if attribute == "text":
                    texts.append("".join(node.itertext()).strip() if hasattr(node, "itertext") else str(node))
                else:
                    texts.append(str(node.get(attribute) if hasattr(node, "get") else node))
                if not multiple:
                    break
        else:
            soup = BeautifulSoup(html, "lxml")
            nodes = soup.select(selector)
            if not multiple:
                nodes = nodes[:1]
            for node in nodes:
                if attribute == "text":
                    texts.append(node.get_text(" ", strip=True))
                else:
                    texts.append(str(node.get(attribute) or ""))

        if not texts:
            return fallback

        if regex:
            extracted = []
            for t in texts:
                m = extract_regex(t, regex, multiple=False)
                if m is not None:
                    extracted.append(m)
            if not extracted:
                return fallback
            return extracted if multiple else extracted[0]

        return texts if multiple else texts[0]


PLUGIN = WebScraperPlugin()
