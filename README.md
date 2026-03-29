# gpu-stock-monitor

Monitors French retailers for GPU availability and posts Discord alerts when target cards come in stock.

## Target GPUs

| Priority | Model | Ceiling |
|----------|-------|---------|
| 1 | NVIDIA GeForce RTX 5080 16GB | 1500 € |
| 2 | AMD Radeon RX 9070 XT 16GB | 850 € |
| 3 | NVIDIA GeForce RTX 5070 Ti 16GB | 950 € |

## Retailers

**Primary:** LDLC, TopAchat, Materiel.net, Alternate France, Rue du Commerce  
**Stretch:** Amazon FR, Cdiscount, Fnac/Darty (add as experimental adapters)

## Quick Start

### Local with Docker Compose

```bash
cp config/config.yaml config/config.local.yaml
# Edit config/config.local.yaml — set discord.guild_id and discord.bot_token
docker-compose up --build
```

### Local without Docker

```bash
pip install -e ".[dev]"
playwright install chromium

# Ensure the Discord channel exists
gpu-monitor ensure-discord-channel

# Run one check cycle
gpu-monitor check-once

# Start the daemon
gpu-monitor run-daemon
```

### GitHub Actions

Set these repository secrets:
- `DISCORD_BOT_TOKEN` — your OpenClaw Discord bot token
- `DISCORD_GUILD_ID` — your Discord server/guild ID

The workflow runs every 15 minutes and uploads SQLite as an artifact for state persistence.

## CLI Commands

```bash
gpu-monitor check-once              # Run one full check cycle and exit
gpu-monitor run-daemon              # Run continuously (asyncio scheduler)
gpu-monitor test-retailer ldlc     # Test a single retailer adapter
gpu-monitor send-test-alert        # Post a test message to Discord
gpu-monitor ensure-discord-channel # Create gpu-stock-france channel if missing
gpu-monitor list-products          # List all products seen in the DB
```

## Configuration

Edit `config/config.yaml`:

```yaml
discord:
  bot_token: "YOUR_BOT_TOKEN"
  guild_id: "YOUR_GUILD_ID"
  channel_name: "gpu-stock-france"
  auto_create_channel: true

polling:
  interval_seconds: 900   # 15 minutes
  jitter_seconds: 120     # ±2 minutes per retailer

targets:
  - family: RTX_5080
    keywords: ["RTX 5080", "GeForce RTX 5080"]
    price_ceiling: 1500.0
  - family: RX_9070_XT
    keywords: ["RX 9070 XT", "Radeon RX 9070 XT"]
    price_ceiling: 850.0
  - family: RTX_5070_TI
    keywords: ["RTX 5070 Ti", "GeForce RTX 5070 Ti"]
    price_ceiling: 950.0
```

## Adding a New Retailer

1. Create `src/gpu_monitor/retailers/myretailer.py`
2. Subclass `BaseRetailer` and implement `fetch()`, `parse_products()`, `normalize()`
3. Decide: static HTML (use `http_client`) or JS-heavy (use `browser` Playwright wrapper)
4. Register in `src/gpu_monitor/retailers/__init__.py`
5. Add retailer URLs and selectors to `config/config.yaml`
6. Add fixture HTML and parser test in `tests/`

## Daemon vs GitHub Actions

| | Daemon | GitHub Actions |
|--|--------|---------------|
| Latency | Near-realtime | ~15min |
| Cost | Server/machine required | Free (within limits) |
| State | Persistent SQLite | Artifact upload/download |
| Setup | Docker Compose | Just repo secrets |
| Reliability | Needs uptime | GitHub-managed |

**Recommendation:** Use GitHub Actions for low-effort monitoring, daemon if you have a home server running OpenClaw anyway.

## Known Limitations

- **Anti-bot detection:** Rue du Commerce and Cdiscount are aggressive. The Playwright fallback helps but may still get blocked. Mark adapters as `experimental=True` if unreliable.
- **Price parsing:** Prices with unusual formatting (spaces, non-breaking chars) may parse incorrectly — check logs if prices look wrong.
- **Marketplace sellers:** Third-party sellers on Amazon/Fnac are hard to reliably distinguish from first-party stock. Config has `exclude_marketplace` flag but it's best-effort.
- **GitHub Actions SQLite:** State is ephemeral between runs unless artifact is properly restored. First run after a gap will re-alert on everything in stock.
- **robots.txt:** Respected for unauthenticated crawling but retailers may update their policies — review periodically.
