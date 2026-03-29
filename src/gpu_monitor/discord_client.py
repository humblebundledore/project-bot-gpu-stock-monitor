"""
Discord client using the Bot API directly.
Uses the configured bot token to post to the alert channel.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from .config import AppConfig

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


class DiscordClient:
    """
    Thin async Discord Bot API client.
    Handles channel lookup/creation and message posting.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._token = config.discord_token
        self._guild_id = config.discord_guild_id
        self._channel_name = config.discord_alert_channel
        self._channel_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "GPUMonitor/0.1 (gpu-stock-monitor)",
        }

    async def _api_get(self, client: httpx.AsyncClient, path: str) -> dict:
        resp = await client.get(f"{DISCORD_API}{path}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    async def _api_post(self, client: httpx.AsyncClient, path: str, payload: dict) -> dict:
        resp = await client.post(
            f"{DISCORD_API}{path}", headers=self._headers(), json=payload
        )
        resp.raise_for_status()
        return resp.json()

    async def ensure_channel(self) -> str:
        """
        Return the channel ID for the alert channel, creating it if necessary.
        Caches the result.
        """
        if self._channel_id:
            return self._channel_id

        async with httpx.AsyncClient(timeout=15) as client:
            channels = await self._api_get(client, f"/guilds/{self._guild_id}/channels")
            for ch in channels:
                if ch.get("name") == self._channel_name and ch.get("type") == 0:
                    self._channel_id = str(ch["id"])
                    logger.info("Found existing Discord channel #%s (id=%s)", self._channel_name, self._channel_id)
                    return self._channel_id

            if self._config.discord_auto_create_channel:
                logger.info("Creating Discord channel #%s", self._channel_name)
                ch = await self._api_post(
                    client,
                    f"/guilds/{self._guild_id}/channels",
                    {
                        "name": self._channel_name,
                        "type": 0,  # GUILD_TEXT
                        "topic": "🖥️ GPU stock alerts — France — RTX 5080, RX 9070 XT, RTX 5070 Ti",
                        "rate_limit_per_user": 5,
                    },
                )
                self._channel_id = str(ch["id"])
                logger.info("Created Discord channel #%s (id=%s)", self._channel_name, self._channel_id)
                return self._channel_id

        raise RuntimeError(
            f"Discord channel #{self._channel_name} not found and auto-create is disabled"
        )

    async def send_message(self, content: str) -> dict:
        """Post a plain-text message to the alert channel."""
        channel_id = await self.ensure_channel()
        async with httpx.AsyncClient(timeout=15) as client:
            result = await self._api_post(
                client,
                f"/channels/{channel_id}/messages",
                {"content": content},
            )
        logger.info("Discord message sent (id=%s)", result.get("id"))
        return result

    async def send_embed(
        self,
        title: str,
        description: str,
        color: int,
        url: str | None = None,
        fields: list[dict] | None = None,
        footer: str | None = None,
    ) -> dict:
        """Post an embed to the alert channel."""
        channel_id = await self.ensure_channel()
        embed: dict = {
            "title": title,
            "description": description,
            "color": color,
        }
        if url:
            embed["url"] = url
        if fields:
            embed["fields"] = fields
        if footer:
            embed["footer"] = {"text": footer}

        async with httpx.AsyncClient(timeout=15) as client:
            result = await self._api_post(
                client,
                f"/channels/{channel_id}/messages",
                {"embeds": [embed]},
            )
        logger.info("Discord embed sent (id=%s)", result.get("id"))
        return result
