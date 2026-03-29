"""Configuration loader for GPU Stock Monitor."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import GPUTarget, RetailerConfig


def _find_config() -> Path:
    """Locate config file: env var > cwd/config/config.yaml > repo root."""
    env = os.environ.get("GPU_MONITOR_CONFIG")
    if env:
        p = Path(env)
        if p.exists():
            return p
    candidates = [
        Path("config/config.yaml"),
        Path(__file__).parent.parent.parent.parent / "config" / "config.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("config.yaml not found. Set GPU_MONITOR_CONFIG env var.")


class AppConfig:
    """Parsed and validated application configuration."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

        # Discord
        disc = raw.get("discord", {})
        self.discord_token: str = os.environ.get("DISCORD_TOKEN") or disc.get("token", "")
        self.discord_guild_id: str = str(disc.get("guild_id", ""))
        self.discord_alert_channel: str = disc.get("alert_channel", "gpu-stock-france")
        self.discord_auto_create_channel: bool = disc.get("auto_create_channel", True)
        self.discord_daily_digest: bool = disc.get("daily_digest", False)
        self.discord_digest_time: str = disc.get("digest_time", "07:00")

        # Database
        db = raw.get("database", {})
        self.db_path: str = db.get("path", "data/gpu_monitor.db")

        # Polling
        poll = raw.get("polling", {})
        self.poll_interval_seconds: int = int(poll.get("interval_seconds", 900))
        self.poll_jitter_seconds: int = int(poll.get("jitter_seconds", 120))
        self.cooldown_seconds: int = int(poll.get("cooldown_seconds", 3600))

        # HTTP
        http = raw.get("http", {})
        self.http_timeout: int = int(http.get("timeout_seconds", 30))
        self.http_max_retries: int = int(http.get("max_retries", 3))
        self.http_retry_backoff: float = float(http.get("retry_backoff_base", 2.0))
        self.user_agents: list[str] = http.get("user_agents", [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ])

        # GPU targets
        self.gpu_targets: list[GPUTarget] = [
            GPUTarget(
                family=t["family"],
                display_name=t["display_name"],
                price_ceiling_eur=float(t["price_ceiling_eur"]),
                keywords_include=t.get("keywords_include", []),
                keywords_exclude=t.get("keywords_exclude", []),
            )
            for t in raw.get("gpu_targets", [])
        ]

        # Preferred brands
        self.preferred_brands: list[str] = raw.get("preferred_brands", [])

        # Retailers
        self.retailers: dict[str, RetailerConfig] = {}
        for key, rcfg in raw.get("retailers", {}).items():
            self.retailers[key] = RetailerConfig(
                key=key,
                name=rcfg.get("name", key),
                base_url=rcfg.get("base_url", ""),
                search_urls=rcfg.get("search_urls", []),
                use_browser=rcfg.get("use_browser", False),
                country=rcfg.get("country", "FR"),
                ships_to_france=rcfg.get("ships_to_france", True),
                enabled=rcfg.get("enabled", True),
            )

        # Logging
        log = raw.get("logging", {})
        self.log_level: str = log.get("level", "INFO")
        self.log_format: str = log.get("format", "json")
        self.log_file: str = log.get("file", "logs/gpu_monitor.log")
        self.log_rotate_bytes: int = int(log.get("rotate_bytes", 10 * 1024 * 1024))
        self.log_backup_count: int = int(log.get("backup_count", 5))

    def gpu_target_by_family(self, family: str) -> GPUTarget | None:
        for t in self.gpu_targets:
            if t.family == family:
                return t
        return None


_config_cache: AppConfig | None = None


def load_config(path: Path | None = None) -> AppConfig:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    config_path = path or _find_config()
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    _config_cache = AppConfig(raw)
    return _config_cache


def reload_config(path: Path | None = None) -> AppConfig:
    global _config_cache
    _config_cache = None
    return load_config(path)
