# Daily News Digest Telegram Bot

An asynchronous Telegram bot that aggregates news from official Ukrainian and international RSS feeds, summarizes key events using Google Gemini AI, and delivers personalized daily digests based on individual user schedules and topic preferences.

---

## Features

- **Dual-Scope Coverage (Ukraine & World):** Aggregates 23 curated Ukrainian and global media outlets, automatically translating and summarizing international news into fluent Ukrainian.
- **Smart AI Summarization:** Leverages Google Gemini to cluster related stories, eliminate clickbait, and produce 5–8 balanced topics with direct source links. Includes automatic failover to fallback models to prevent timeouts.
- **Topic Personalization:** Supports 8 core categories (War, Politics, Economy, Technology, Science, Culture, Showbiz, Society) along with specialized technology subcategories.
- **Custom Scheduling & Timezones:** Delivers digests according to each user's chosen local time and timezone, alongside instant on-demand updates.
- **Data Retention & Maintenance:** Automated background jobs clean up expired news and logs daily to keep the SQLite database lightweight and fast.
- **Production-Ready Reliability:** Built-in Telegram rate-limit handling (`FloodWait`), automatic deactivation of inactive/blocked users, and healthcheck monitoring.

---

## Curated RSS Sources

- **🇺🇦 Ukrainian (11 feeds):** Суспільне, BBC Україна, Українська правда, Економічна правда, Наука.ua, Читомо, Vertigo, ТаблоID, Mezha.Media, AIN.UA, DOU.
- **🌍 World (12 feeds):** BBC World, The Guardian, DW, CNBC, Nature, Phys.org, BBC Culture, Variety, The Verge, TechCrunch, Ars Technica, Wired.

> Feeds can be customized or extended without code changes via the `RSS_FEEDS` environment variable.

---

## Bot Commands

| Command | Description | Access |
| --- | --- | --- |
| `/start` | Register user and activate daily digest subscription | All users |
| `/settings` | Configure delivery time, timezone, and UA/World topics | All users |
| `/now` | Immediate digest for the past 4 hours | All users |
| `/cancel` | Cancel active time or custom input | All users |
| `/help` | Usage instructions and bot information | All users |
| `/stats` | View subscriber count, news volume, and delivery health | Admins only (`ADMIN_IDS`) |

---

## Technology Stack

- **Language:** Python 3.11+
- **Telegram Bot Framework:** `aiogram` (v3.x) with async routers, filters, and FSM.
- **RSS Ingestion & Cleaning:** `aiohttp`, `feedparser`, `trafilatura`, `defusedxml`.
- **Database:** SQLite with Write-Ahead Logging (`WAL` mode) via `SQLAlchemy 2.0` (async with `aiosqlite`).
- **AI Summarization:** `google-genai` SDK with Gemini models (`gemini-3.5-flash`, `gemini-flash-lite-latest`).
- **Scheduling:** `APScheduler` (`AsyncIOScheduler`) attached to the asyncio event loop.
- **Configuration:** `pydantic-settings` with `.env` validation.
- **Deployment:** Docker, Docker Compose, Multi-stage builds, non-root user.

---

## Getting Started

### 1. Configuration

Copy `.env.example` to `.env` and fill in your API tokens:

```bash
cp .env.example .env
```

| Variable | Required | Description | Default |
| --- | --- | --- | --- |
| `BOT_TOKEN` | **Yes** | Telegram Bot API token from [@BotFather](https://t.me/BotFather) | — |
| `GEMINI_API_KEY` | **Yes** | Google Gemini API key from [Google AI Studio](https://aistudio.google.com/) | — |
| `GEMINI_MODEL` | No | Primary Gemini model for summarization | `gemini-3.5-flash` |
| `GEMINI_FALLBACK_MODEL` | No | Failover model used when primary is overloaded (503/504) | `gemini-flash-lite-latest` |
| `GEMINI_TIMEOUT_SECONDS`| No | Timeout per generation attempt (seconds) | `25` |
| `DATABASE_URL` | No | SQLite database URL with async driver | `sqlite+aiosqlite:///./data/news_bot.db` |
| `LOG_LEVEL` | No | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `FETCH_INTERVAL_MINUTES`| No | Periodic RSS fetch interval in minutes | `60` |
| `ADMIN_IDS` | No | Comma-separated Telegram User IDs for `/stats` access | `""` |
| `RSS_FEEDS` | No | Optional JSON list of custom feed sources | Defaults to all 23 feeds |

---

### 2. Run with Docker (Recommended)

```bash
# Build and run container in detached mode
docker compose up -d --build

# View logs
docker compose logs -f

# Check health status
docker compose ps
```

The SQLite database and WAL logs are persisted inside the `bot_data` volume mounted at `/app/data`.

---

### 3. Run Locally

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development dependencies
pip install -r requirements-dev.txt

# Start the bot
python main.py
```

---

## Testing & Quality Assurance

Run the test suite using `pytest`:

```bash
.venv/bin/python -m pytest
```

All 104 unit and integration tests cover:
- Pydantic configuration & environment parsing.
- Async database CRUD, indexes, and automated SQLite schema migrations.
- Feed ingestion, SHA-256 deduplication, and XML security (XXE defense).
- English and Ukrainian category classifiers and keyword inference.
- Gemini prompt formatting, topic limits (5–8), and balanced distribution.
- Interactive inline keyboards, FSM time parsing, and settings navigation.
- Delivery logic, rate-limit retries, blocked user deactivation, and Docker healthchecks.

---

## Contributing & License

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming (`feature/*`, `fix/*`, `docs/*`), conventional commit guidelines, and PR workflow. Project specification details can be found in [AGENTS.md](AGENTS.md).
