"""
CLI entry point for GPU Stock Monitor.

Commands:
    check-once              Run all retailers once and exit
    run-daemon              Start continuous polling loop
    test-retailer <name>    Scrape a single retailer and print results
    send-test-alert         Send a test message to Discord
    ensure-discord-channel  Create/verify the alert channel
    list-products           List all tracked products from DB
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from .alerting import Alerter
from .browser import BrowserClient
from .config import load_config
from .db import Database, open_db
from .discord_client import DiscordClient
from .http_client import HttpClient
from .retailers import RETAILER_MAP
from .scheduler import Scheduler, run_all_retailers, run_single_retailer
from .setup_logging import setup_logging


def _get_context(config_path: str | None):
    """Load config and return a dict with shared setup."""
    from pathlib import Path as P
    p = P(config_path) if config_path else None
    cfg = load_config(p)
    setup_logging(cfg)
    return cfg


@click.group()
@click.option("--config", "-c", default=None, help="Path to config.yaml")
@click.pass_context
def cli(ctx, config):
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command("check-once")
@click.pass_context
def check_once(ctx):
    """Run all enabled retailers once, emit alerts, and exit."""
    asyncio.run(_check_once(ctx.obj["config_path"]))


async def _check_once(config_path: str | None) -> None:
    cfg = _get_context(config_path)
    logger = logging.getLogger(__name__)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)

    async with HttpClient(cfg) as http:
        browser = None
        needs_browser = any(
            r.enabled and r.use_browser for r in cfg.retailers.values()
        )
        if needs_browser:
            browser = BrowserClient(
                user_agents=cfg.user_agents,
                screenshot_dir="logs/screenshots",
            )
            await browser.start()

        try:
            async with open_db(cfg.db_path) as db:
                discord = DiscordClient(cfg)
                alerter = Alerter(db, discord, cfg)
                await run_all_retailers(db, alerter, cfg, http, browser)
        finally:
            if browser:
                await browser.stop()

    logger.info("check-once complete")


@cli.command("run-daemon")
@click.pass_context
def run_daemon(ctx):
    """Start the continuous polling scheduler."""
    asyncio.run(_run_daemon(ctx.obj["config_path"]))


async def _run_daemon(config_path: str | None) -> None:
    cfg = _get_context(config_path)
    logger = logging.getLogger(__name__)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    async with HttpClient(cfg) as http:
        browser = None
        needs_browser = any(
            r.enabled and r.use_browser for r in cfg.retailers.values()
        )
        if needs_browser:
            browser = BrowserClient(
                user_agents=cfg.user_agents,
                screenshot_dir="logs/screenshots",
            )
            await browser.start()

        try:
            async with open_db(cfg.db_path) as db:
                discord = DiscordClient(cfg)
                alerter = Alerter(db, discord, cfg)

                # Ensure the Discord channel exists on startup
                try:
                    ch_id = await discord.ensure_channel()
                    logger.info("Discord channel ready: #%s (id=%s)", cfg.discord_alert_channel, ch_id)
                except Exception as e:
                    logger.warning("Discord channel setup failed: %s", e)

                scheduler = Scheduler(db, alerter, cfg, http, browser)
                try:
                    await scheduler.run()
                except KeyboardInterrupt:
                    logger.info("Interrupted")
                    scheduler.stop()
        finally:
            if browser:
                await browser.stop()


@cli.command("test-retailer")
@click.argument("retailer_name")
@click.pass_context
def test_retailer(ctx, retailer_name):
    """Scrape a single retailer and print results (no DB writes, no alerts)."""
    asyncio.run(_test_retailer(ctx.obj["config_path"], retailer_name))


async def _test_retailer(config_path: str | None, retailer_name: str) -> None:
    cfg = _get_context(config_path)
    logger = logging.getLogger(__name__)

    cls = RETAILER_MAP.get(retailer_name.lower())
    if cls is None:
        known = ", ".join(RETAILER_MAP.keys())
        click.echo(f"Unknown retailer '{retailer_name}'. Known: {known}", err=True)
        sys.exit(1)

    retailer_cfg = cfg.retailers.get(retailer_name.lower())
    if retailer_cfg is None or not retailer_cfg.enabled:
        click.echo(f"Retailer '{retailer_name}' is disabled in config.", err=True)
        sys.exit(1)

    async with HttpClient(cfg) as http:
        browser = None
        if retailer_cfg.use_browser:
            browser = BrowserClient(user_agents=cfg.user_agents)
            await browser.start()
        try:
            retailer = cls(cfg, http, browser)
            products = await retailer.scrape()
        finally:
            if browser:
                await browser.stop()

    if not products:
        click.echo(f"No matching products found at {retailer_name}")
        return

    click.echo(f"\nFound {len(products)} products from {retailer_name}:\n")
    for p in products:
        price_str = f"{p.price_eur:.2f}€" if p.price_eur else "N/A"
        click.echo(f"  [{p.status.value:12s}] {p.name[:60]:60s} {price_str:10s}  {p.url}")


@cli.command("send-test-alert")
@click.pass_context
def send_test_alert(ctx):
    """Send a test alert to the configured Discord channel."""
    asyncio.run(_send_test_alert(ctx.obj["config_path"]))


async def _send_test_alert(config_path: str | None) -> None:
    cfg = _get_context(config_path)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)

    async with open_db(cfg.db_path) as db:
        discord = DiscordClient(cfg)
        alerter = Alerter(db, discord, cfg)
        await alerter.send_test_alert()

    click.echo("Test alert sent. Check your Discord channel.")


@cli.command("ensure-discord-channel")
@click.pass_context
def ensure_discord_channel(ctx):
    """Create or verify the GPU alert Discord channel."""
    asyncio.run(_ensure_discord_channel(ctx.obj["config_path"]))


async def _ensure_discord_channel(config_path: str | None) -> None:
    cfg = _get_context(config_path)
    discord = DiscordClient(cfg)
    try:
        ch_id = await discord.ensure_channel()
        click.echo(f"Channel #{cfg.discord_alert_channel} ready (id={ch_id})")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("list-products")
@click.option("--family", "-f", default=None, help="Filter by GPU family (e.g. RTX_5080)")
@click.option("--retailer", "-r", default=None, help="Filter by retailer name")
@click.option("--status", "-s", default=None, help="Filter by status (IN_STOCK, etc.)")
@click.pass_context
def list_products(ctx, family, retailer, status):
    """List all tracked products from the database."""
    asyncio.run(_list_products(ctx.obj["config_path"], family, retailer, status))


async def _list_products(
    config_path: str | None,
    family: str | None,
    retailer: str | None,
    status: str | None,
) -> None:
    from .models import StockStatus
    cfg = _get_context(config_path)
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)

    status_enum = StockStatus(status) if status else None

    async with open_db(cfg.db_path) as db:
        products = await db.list_products(gpu_family=family, retailer=retailer, status=status_enum)

    if not products:
        click.echo("No products found.")
        return

    click.echo(f"\n{'ID':12} {'Retailer':15} {'Family':12} {'Status':12} {'Price':8}  {'Name'}")
    click.echo("-" * 100)
    for p in products:
        price_str = f"{p.price_eur:.0f}€" if p.price_eur else "N/A"
        click.echo(
            f"{p.product_id:12} {p.retailer:15} {p.gpu_family:12} "
            f"{p.status.value:12} {price_str:8}  {p.name[:50]}"
        )
    click.echo(f"\nTotal: {len(products)} products")


def main():
    cli(obj={})


if __name__ == "__main__":
    main()
