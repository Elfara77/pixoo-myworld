"""Calendar via iCal URL (Nextcloud / public ICS)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pixoo.plugins.base import DataSourcePlugin
from pixoo.utils.network_utils import clamp_timeout, http_client, validate_url, with_retries
from pixoo.utils.secrets import resolve_secrets


class CalendarPlugin(DataSourcePlugin):
    name = "calendar"
    description = "Upcoming events from an iCal / ICS URL"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "source": {
                "type": "string",
                "label": "Source",
                "enum": ["ical", "nextcloud"],
                "default": "ical",
            },
            "url": {"type": "string", "label": "ICS URL", "required": True},
            "max_events": {"type": "integer", "label": "Max events", "default": 3},
            "field": {
                "type": "string",
                "label": "Field",
                "enum": ["summary", "start_time", "location", "all"],
                "default": "summary",
            },
            "cache_ttl": {"type": "integer", "label": "Cache TTL (s)", "default": 300},
        }

    def validate_config(self, config: dict[str, Any]) -> bool:
        return validate_url(str(config.get("url") or ""))

    def fetch_data(self, config: dict[str, Any]) -> Any:
        cfg = resolve_secrets(dict(config))
        url = str(cfg["url"])
        max_events = int(cfg.get("max_events") or 3)
        field = str(cfg.get("field") or "summary")
        timeout = clamp_timeout(cfg.get("timeout"), 10)

        def _do() -> str:
            with http_client(timeout=timeout) as client:
                r = client.get(url)
                r.raise_for_status()
                return r.text

        ics_text = with_retries(_do, retries=2)
        events = self._parse_ics(ics_text, max_events)
        if field == "all":
            return {"events": events, "summary": events[0]["summary"] if events else None}
        if not events:
            return None
        if field == "summary":
            return events[0].get("summary")
        if field == "start_time":
            return events[0].get("start_time")
        if field == "location":
            return events[0].get("location")
        return events[0].get(field)

    def _parse_ics(self, text: str, max_events: int) -> list[dict[str, Any]]:
        try:
            from icalendar import Calendar
        except ImportError:
            return self._parse_ics_simple(text, max_events)

        cal = Calendar.from_ical(text)
        now = datetime.now(timezone.utc)
        events: list[dict[str, Any]] = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            dt = component.get("dtstart")
            if dt is None:
                continue
            start = dt.dt
            if not isinstance(start, datetime):
                start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            if start < now:
                continue
            events.append(
                {
                    "summary": str(component.get("summary") or ""),
                    "start_time": start.isoformat(),
                    "location": str(component.get("location") or ""),
                }
            )
        events.sort(key=lambda e: e["start_time"])
        return events[:max_events]

    def _parse_ics_simple(self, text: str, max_events: int) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        block: dict[str, str] = {}
        for line in text.splitlines():
            if line.startswith("BEGIN:VEVENT"):
                block = {}
            elif line.startswith("END:VEVENT"):
                if block.get("summary"):
                    events.append(
                        {
                            "summary": block.get("summary", ""),
                            "start_time": block.get("dtstart", ""),
                            "location": block.get("location", ""),
                        }
                    )
                block = {}
            elif line.startswith("SUMMARY:"):
                block["summary"] = line.split(":", 1)[1].strip()
            elif line.startswith("DTSTART"):
                block["dtstart"] = line.split(":", 1)[1].strip()
            elif line.startswith("LOCATION:"):
                block["location"] = line.split(":", 1)[1].strip()
            if len(events) >= max_events:
                break
        return events[:max_events]


PLUGIN = CalendarPlugin()
