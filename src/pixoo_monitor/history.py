"""Historique métriques — ring buffer fichier + agrégation en buckets pour sparklines."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import project_root

# Presets courants (setup propose aussi une durée libre)
PERIOD_PRESETS: dict[str, int] = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "24h": 24 * 60 * 60,
}
PERIOD_PRESET_CHOICES = tuple(PERIOD_PRESETS.keys())

# Métriques numériques pouvant avoir un graphe d'historique
HISTORY_METRIC_KEYS: tuple[str, ...] = (
    "cpu",
    "ram",
    "swap",
    "disk",
    "network",
    "net_up",
    "temperature",
    "load_avg",
    "nc_disk",
    "php_fpm_workers",
)

HISTORY_METRIC_LABELS: dict[str, str] = {
    "cpu": "CPU %",
    "ram": "RAM %",
    "swap": "Swap %",
    "disk": "Disque %",
    "network": "Réseau ↓ (kbps)",
    "net_up": "Réseau ↑ (kbps)",
    "temperature": "Température °C",
    "load_avg": "Load 1m",
    "nc_disk": "Disque Nextcloud %",
    "php_fpm_workers": "php-fpm busy %",
}

DEFAULT_BUCKETS = 56
MAX_BUCKETS = 60
MIN_PERIOD_SEC = 10  # 10 s mini (graphes très courts)
MAX_PERIOD_SEC = 366 * 24 * 3600  # ~1 an max
MAX_SAMPLES_PER_METRIC = 8640  # ~24h @ 10s ou fenêtre longue plus grossière
# Mois / année approximatifs pour l'historique local
SEC_PER_MONTH = 30 * 86400
SEC_PER_YEAR = 365 * 86400

# Unités: s, m, h, j (jour), M (mois — sensible à la casse), a (année)
# Note: 'm' = minutes, 'M' = mois ; en entrée bas-de-casse 'mo'/'mois' aussi.
_PERIOD_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*"
    r"(s|sec|secs|m|min|mins|h|hr|hrs|j|d|day|days|mo|mois|M|a|an|ans|y|yr|year|years)?\s*$",
)


def parse_period(value: Any, default: str = "15m") -> tuple[str, int]:
    """
    Parse une durée humaine → (label normalisé, secondes).

    Unités: s | m | h | j (jour) | M/mo (mois) | a (année)
    Exemples: 30s, 5m, 15m, 1h, 12h, 1j, 7j, 1M, 1a, 90 (= minutes)
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return normalize_period_label(default)

    if isinstance(value, (int, float)):
        # Nombre nu = minutes
        secs = int(float(value) * 60)
        secs = max(MIN_PERIOD_SEC, min(MAX_PERIOD_SEC, secs))
        return format_period(secs), secs

    raw = str(value).strip()
    # Alias presets (minuscule)
    low = raw.lower()
    aliases = {"5": "5m", "15": "15m", "60": "1h", "24": "24h", "1": "1h"}
    if low in aliases:
        raw = aliases[low]
        low = raw.lower()
    if low in PERIOD_PRESETS:
        return low, PERIOD_PRESETS[low]
    # 1j / 7j aliases → jours
    if low in ("1j", "1d"):
        return "1j", 86400
    if low in ("7j", "7d"):
        return "7j", 7 * 86400

    m = _PERIOD_RE.match(raw)
    if not m:
        return normalize_period_label(default)

    amount = float(m.group(1))
    unit_raw = m.group(2)
    if unit_raw is None:
        unit = "m"
    elif unit_raw == "M":
        unit = "M"  # mois
    else:
        unit = unit_raw.lower()

    if unit in ("s", "sec", "secs"):
        secs = int(amount)
    elif unit in ("m", "min", "mins"):
        secs = int(amount * 60)
    elif unit in ("h", "hr", "hrs"):
        secs = int(amount * 3600)
    elif unit in ("j", "d", "day", "days"):
        secs = int(amount * 86400)
    elif unit in ("M", "mo", "mois"):
        secs = int(amount * SEC_PER_MONTH)
    elif unit in ("a", "an", "ans", "y", "yr", "year", "years"):
        secs = int(amount * SEC_PER_YEAR)
    else:
        secs = int(amount * 60)

    secs = max(MIN_PERIOD_SEC, min(MAX_PERIOD_SEC, secs))
    return format_period(secs), secs


def format_period(seconds: int) -> str:
    """Label compact stable (ex. 30s, 15m, 2h, 1j, 1M, 1a)."""
    seconds = int(seconds)
    if seconds % SEC_PER_YEAR == 0 and seconds >= SEC_PER_YEAR:
        return f"{seconds // SEC_PER_YEAR}a"
    if seconds % SEC_PER_MONTH == 0 and seconds >= SEC_PER_MONTH:
        return f"{seconds // SEC_PER_MONTH}M"
    if seconds % 86400 == 0 and seconds >= 86400:
        return f"{seconds // 86400}j"
    if seconds % 3600 == 0 and seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def normalize_period_label(value: Any, default: str = "15m") -> tuple[str, int]:
    return parse_period(value, default)


def period_seconds(value: Any, default: str = "15m") -> int:
    return parse_period(value, default)[1]


def history_dir() -> Path:
    return project_root() / "data" / "history"


def _metric_path(metric: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in metric)
    return history_dir() / f"{safe}.json"


def parse_history_config(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """
    Retourne {metric: {enabled, period, period_seconds, buckets}}.

      [history]
      default_period = "15m"   # ou "30m", "2h", …
      buckets = 56

      [history.metrics.cpu]
      enabled = true
      period = "1h"            # preset ou durée libre
    """
    hist = cfg.get("history") or {}
    if not isinstance(hist, dict):
        return {}
    default_label, _ = parse_period(hist.get("default_period", "15m"))
    buckets = int(hist.get("buckets", DEFAULT_BUCKETS))
    buckets = max(8, min(MAX_BUCKETS, buckets))

    metrics_section = hist.get("metrics") or {}
    if not isinstance(metrics_section, dict):
        metrics_section = {}

    out: dict[str, dict[str, Any]] = {}
    for key in HISTORY_METRIC_KEYS:
        section = metrics_section.get(key)
        if section is None:
            section = hist.get(key)
        if not isinstance(section, dict):
            continue
        if not bool(section.get("enabled", False)):
            continue
        label, secs = parse_period(section.get("period", default_label), default_label)
        n = int(section.get("buckets", buckets))
        out[key] = {
            "enabled": True,
            "period": label,
            "period_seconds": secs,
            "buckets": max(8, min(MAX_BUCKETS, n)),
        }
    return out


class HistoryStore:
    """Ring buffer JSON par métrique + agrégation moyenne par bucket."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        self.enabled = parse_history_config(self.cfg)
        history_dir().mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[tuple[float, float]]] = {}
        # Rétention fichiers = max(périodes configurées, 24h)
        self._retain_sec = max(
            [PERIOD_PRESETS["24h"]]
            + [int(c["period_seconds"]) for c in self.enabled.values()],
            default=PERIOD_PRESETS["24h"],
        )

    def _load(self, metric: str) -> list[tuple[float, float]]:
        if metric in self._cache:
            return self._cache[metric]
        path = _metric_path(metric)
        samples: list[tuple[float, float]] = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for pair in raw.get("samples") or []:
                    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                        samples.append((float(pair[0]), float(pair[1])))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                samples = []
        self._cache[metric] = samples
        return samples

    def _save(self, metric: str, samples: list[tuple[float, float]]) -> None:
        path = _metric_path(metric)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "metric": metric,
            "samples": [[round(t, 3), round(v, 4)] for t, v in samples[-MAX_SAMPLES_PER_METRIC:]],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)
        self._cache[metric] = samples[-MAX_SAMPLES_PER_METRIC:]

    def record(self, metric: str, value: float | None, ts: float | None = None) -> None:
        if value is None or metric not in self.enabled:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:
            return
        now = float(ts if ts is not None else time.time())
        samples = self._load(metric)
        samples.append((now, v))
        cutoff = now - self._retain_sec - 60
        samples = [(t, x) for t, x in samples if t >= cutoff][-MAX_SAMPLES_PER_METRIC:]
        self._save(metric, samples)

    def record_snapshot_values(self, values: dict[str, float | None], ts: float | None = None) -> None:
        now = float(ts if ts is not None else time.time())
        for metric, val in values.items():
            self.record(metric, val, ts=now)

    def buckets(
        self,
        metric: str,
        *,
        period: str | None = None,
        n_buckets: int | None = None,
        now: float | None = None,
    ) -> tuple[list[float | None], float, str]:
        """
        Retourne (bucket_means, fill_progress 0..1, period_label).
        fill_progress = min(1, âge depuis 1er échantillon / période).
        """
        conf = self.enabled.get(metric) or {}
        label, window = parse_period(period or conf.get("period", "15m"))
        n = int(n_buckets or conf.get("buckets", DEFAULT_BUCKETS))
        n = max(8, min(MAX_BUCKETS, n))
        now_ts = float(now if now is not None else time.time())
        start = now_ts - window

        samples = [(t, v) for t, v in self._load(metric) if start <= t <= now_ts]
        result: list[float | None] = [None] * n
        if not samples:
            return result, 0.0, label

        first_ts = samples[0][0]
        fill = min(1.0, max(0.0, (now_ts - first_ts) / window))

        width = window / n
        sums = [0.0] * n
        counts = [0] * n
        for t, v in samples:
            idx = int((t - start) / width)
            if idx < 0:
                continue
            if idx >= n:
                idx = n - 1
            sums[idx] += v
            counts[idx] += 1
        for i in range(n):
            if counts[i]:
                result[i] = sums[i] / counts[i]
        return result, fill, label


def extract_history_values(snap: Any) -> dict[str, float | None]:
    """Extrait les valeurs numériques d'un Snapshot pour l'historique."""
    out: dict[str, float | None] = {
        "cpu": getattr(snap, "cpu_percent", None),
        "ram": getattr(snap, "ram_percent", None),
        "swap": getattr(snap, "swap_percent", None),
        "disk": getattr(snap, "disk_percent", None),
        "network": getattr(snap, "net_down_kbps", None),
        "net_up": getattr(snap, "net_up_kbps", None),
        "load_avg": None,
        "temperature": None,
        "nc_disk": None,
        "php_fpm_workers": None,
    }
    load = getattr(snap, "load_avg", None)
    if load:
        out["load_avg"] = float(load[0])
    temps = getattr(snap, "temperatures", None) or []
    if temps:
        out["temperature"] = float(temps[0][1])
    nc = getattr(snap, "nc", None)
    if nc is not None:
        out["nc_disk"] = getattr(nc, "nc_disk_percent", None)
        a = getattr(nc, "php_fpm_active", None)
        t = getattr(nc, "php_fpm_total", None)
        if a is not None and t is not None and t > 0:
            out["php_fpm_workers"] = 100.0 * float(a) / float(t)
    return out
