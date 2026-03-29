# GPU Stock Monitor

Discord bot that alerts when specific GPUs become available at MSRP from official sources.

## Monitored cards

| Card | Retailer | MSRP (France) |
|------|----------|--------------|
| GeForce RTX 5080 Founders Edition | NVIDIA France | €1,119 |
| GeForce RTX 5090 Founders Edition | NVIDIA France | €2,059 |
| Sapphire Pure Radeon RX 9070 XT Gaming OC 16GB | LDLC, TopAchat | €649 |

NVIDIA FE cards are monitored via the official NVIDIA inventory API (`store.nvidia.com/fr-fr`).
The Sapphire Pure is tracked on French authorized retailers — only this exact model is matched
(Sapphire PULSE and other AIB variants are ignored).

## Setup

### 1. Discord bot

Create a bot at [discord.com/developers](https://discord.com/developers/applications), enable
the **Message Content** and **Server Members** intents, invite it to your server, and copy the token.

### 2. Configuration

```bash
cp config/config.yaml config/config.local.yaml
# edit config.local.yaml — set guild_id and alert_channel
export DISCORD_TOKEN="your-bot-token"
export GPU_MONITOR_CONFIG="config/config.local.yaml"
```

### 3. Run

**Docker Compose (recommended):**

```bash
DISCORD_TOKEN=your-token docker compose up -d
```

**Local:**

```bash
pip install -e ".[dev]"
gpu-monitor run-daemon
```

## CLI

```bash
gpu-monitor check-once          # single poll, print results
gpu-monitor test-retailer ldlc  # debug a specific retailer
gpu-monitor send-test-alert     # verify Discord webhook
gpu-monitor list-products       # show database contents
```

## Architecture

```
scheduler → retailer.scrape() → parse_products() → normalizer → db → alerting → Discord
```

- **NVIDIA France** — polls the FE inventory JSON API, no browser needed
- **LDLC / TopAchat** — static HTML scraping with JSON-LD fallback
- All status text is normalized to `IN_STOCK / PREORDER / BACKORDER / OUT_OF_STOCK`
- Alerts fire on transitions into alertable states, with a 1h cooldown per product
- Daily digest summarizes current availability at a configured time (UTC)

## Dev

```bash
pip install -e ".[dev]"
pytest
```
