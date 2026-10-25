# Daily News Digest Telegram Bot

An asynchronous, production-ready Telegram bot in Python that periodically aggregates news articles from official Ukrainian and international RSS feeds, stores and deduplicates them in an SQLite database, periodically generates high-quality structured daily digests using Google Gemini AI, and delivers personalized digests to registered Telegram users based on their individual time, timezone, and topic preferences.

---

## Features

- **Multi-Scope News (Ukraine & World):**
  - 🇺🇦 **Ukrainian News:** Curated Ukrainian sources covering frontline events, politics, economy, culture, and tech.
  - 🌍 **World News:** Major English-language media (BBC World, The Guardian, CNBC, Nature, Variety, TechCrunch, etc.) automatically translated and summarized directly into fluent Ukrainian. Delivered as an optional second message.
- **Smart Summarization (Google Gemini):**
  - Clusters related items across sources and discards clickbait/duplicates.
  - Selects 5–8 key events balanced across user-selected categories.
  - Fast response times: automatic failover between primary (`gemini-3.5-flash`) and ultra-fast fallback (`gemini-flash-lite-latest`) with aggressive timeouts (25s) to prevent queue hangs.
  - Safe Telegram HTML formatting with em-dash dividers (`———————————————`) and automatic message chunking for messages exceeding Telegram's 4096-character limit.
- **Comprehensive Topic Categorization:**
  - **8 Main Categories:**
    - 🪖 War & Frontline (`war`)
    - 🏛 Politics (`politics`)
    - 💰 Economy (`economy`)
    - 💻 Technology (`technology`)
    - 🔬 Science (`science`)
    - 🎭 Culture (`culture`)
    - 🌟 Showbiz (`showbiz`)
    - 👥 Society (`society`)
  - **Technology Subcategories:** Fine-grained selection under Technology:
    - 🤖 Artificial Intelligence (AI)
    - 🛡 Cyber Security
    - 📱 Gadgets & Hardware
    - 💼 IT Business & Startups
    - 💻 Software & Development
- **Interactive `/settings` UI:**
  - Quick delivery time presets (`08:00`, `13:00`, `19:00`, `20:00`, `21:00`, `22:00`) or custom time (`07:30`).
  - Timezone picker (Kyiv, Warsaw, London, Berlin, Prague, New York).
  - Independent topic selections for Ukrainian and World news.
  - Category selection guards (prevents deselecting all topics).
- **On-Demand Digest (`/now`):**
  - Instant digest for the last 4 hours, served with live typing indicators and cached for 30 minutes to minimize API quota usage.
- **Automated Data Retention & Maintenance:**
  - Daily cleanup job (03:00 UTC) automatically purges news older than 14 days, digests older than 30 days, and delivery logs older than 30 days.
  - Executes `PRAGMA optimize;` daily to keep SQLite performance peak.
- **Resilient Delivery & DevOps:**
  - Handles Telegram `FloodWait` with exponential backoff.
  - Automatically deactivates users who blocked the bot (`TelegramForbiddenError`).
  - Multi-stage Docker build with non-root user and native Docker `HEALTHCHECK` with scheduler heartbeat monitoring.

---

## Default RSS Sources (23 Curated Feeds)

### 🇺🇦 Ukrainian News (11 Feeds)
| Source | Category / Focus | Default Category |
| --- | --- | --- |
| **Суспільне** | General, Frontline, Society | Dynamic |
| **BBC Україна** | General, Politics | Dynamic |
| **Українська правда** | General, Politics, War | Dynamic |
| **Економічна правда** | Macroeconomics, Business, Finance | `economy` |
| **Наука.ua** | Science, Space, Biology | `science` |
| **Читомо** | Literature, Books, Publishing | `culture` |
| **Vertigo** | Cinema, TV Series, Arts | `culture` |
| **ТаблоID** | Celebrities, Eurovision, Showbiz | `showbiz` |
| **Mezha.Media** | Hardware, Gadgets, Tech Industry | `technology` |
| **AIN.UA** | IT Business, Startups, Investments | `technology` |
| **DOU** | Software Development, Tech Careers | `technology` |

### 🌍 World News (12 Feeds)
| Source | Category / Focus | Default Category |
| --- | --- | --- |
| **BBC World** | Global News, Politics, Conflict | Dynamic |
| **The Guardian World** | World News, International Politics | Dynamic |
| **DW World** | Global Affairs, Europe, Diplomacy | Dynamic |
| **CNBC Economy** | Global Markets, Central Banks, Economy | `economy` |
| **Nature News** | Groundbreaking Science & Research | `science` |
| **Phys.org** | Physics, Astronomy, Lab Research | `science` |
| **BBC Culture** | Global Arts, Theater, Cinema | `culture` |
| **Variety** | Hollywood, Entertainment, Oscars/Grammys | `showbiz` |
| **The Verge** | Big Tech, Consumer Electronics, AI | `technology` |
| **TechCrunch** | Venture Capital, Startups, AI | `technology` |
| **Ars Technica** | Cyber Security, Linux, Tech Policy | `technology` |
| **Wired** | Global Tech Trends, Future Tech | `technology` |

> Additional feeds can be configured dynamically without code changes using the `RSS_FEEDS` environment variable.

---

## Bot Commands

| Command | Description | Access |
| --- | --- | --- |
| `/start` | Register user and activate daily digest subscription | All users |
| `/settings` | Open interactive menu (schedule, timezone, UA/World topics) | All users |
| `/now` | Generate and deliver an immediate digest for the past 4 hours | All users |
| `/cancel` | Cancel custom time input in FSM | All users |
| `/help` | Display command usage and features guide | All users |
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
| `FETCH_INTERVAL_MINUTES`| No | Periodic RSS fetch interval in minutes | `30` |
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

All 103 unit and integration tests cover:
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
