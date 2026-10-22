# News Digest Bot

Telegram bot that collects news from Ukrainian RSS feeds (Суспільне, BBC Україна, Українська правда), summarizes them with Google Gemini and delivers a personalized daily digest.

## Features

- RSS ingestion every 30 min into SQLite (WAL) with SHA-256 deduplication
- Gemini-generated digest (5–7 topics, clustered across sources) rendered as Telegram HTML
- Per-user delivery time, timezone-aware (default 21:00 `Europe/Kyiv`) and topic filters
- `/now` — digest for the last 4 hours (cached for 30 min)
- Resilient delivery: flood-wait backoff, blocked users auto-deactivated, Gemini retries/timeouts

## Setup

```bash
cp .env.example .env   # fill in BOT_TOKEN and GEMINI_API_KEY
```

### Docker

```bash
docker compose up -d --build
docker compose logs -f
```

The database lives in the `bot_data` volume mounted at `/app/data`.

### Local

Requires Python 3.11+.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python main.py
```

## Bot commands

| Command | Description |
| --- | --- |
| `/start` | Register and subscribe |
| `/settings` | Delivery time and topics |
| `/now` | Digest for the last 4 hours |
| `/cancel` | Cancel the current action |
| `/help` | Help |

## Development

```bash
.venv/bin/python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the git workflow and commit rules, and [AGENTS.md](AGENTS.md) for the project specification.
