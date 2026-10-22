# **AGENTS.md: Daily News Digest Telegram Bot**

## **Project Specification & AI Agent Implementation Guide**

---

# **1\. Project Overview and Objective**

Build an asynchronous, production-ready Telegram bot in Python that periodically aggregates news articles from official Ukrainian RSS feeds, stores and deduplicates them in an SQLite database, periodically generates high-quality structured daily digests using the Google Gemini API, and delivers personalized digests to registered Telegram users based on their individual time and topic preferences.

---

# **2\. Technology Stack and Key Libraries**

* **Language:** Python 3.11+  
* **Telegram Bot Framework:** `aiogram` (v3.x) with async routers, filters, FSM (Finite State Machine).  
* **RSS Parsing and Extraction:**  
  * `aiohttp` and `feedparser` for fetching feeds asynchronously.  
  * `trafilatura` for extracting article body text and stripping boilerplate or ads.  
  * `defusedxml` for secure XML and RSS parsing.  
* **Database and Storage:**  
  * SQLite with Write-Ahead Logging (WAL mode enabled).  
  * `SQLAlchemy` (v2.0 async engine with `aiosqlite`) or raw `aiosqlite`.  
* **LLM Integration:**  
  * `google-genai` SDK (Google Gemini API).  
  * Target model: `gemini-3.5-flash` (or `gemini-3.8-flash`).  
* **Task Scheduling:**  
  * `APScheduler` (`AsyncIOScheduler`) integrated into the asyncio event loop.  
* **Configuration and Validation:**  
  * `pydantic-settings` for strongly typed environment configuration via `.env`.  
* **Deployment and Containerization:**  
  * Docker and docker-compose.

---

# **3\. Architecture and Data Flow**

## **A. Data Collection Pipeline (News Fetcher)**

1. **Periodic Poll:** Every 30 to 60 minutes, the scheduler triggers the RSS fetcher.  
2. **Sources (Default Feeds):**  
   * Suspilne News RSS  
   * BBC News Ukraine RSS  
   * Ukrainska Pravda RSS  
3. **Deduplication:**  
   * Normalize feed entries.  
   * Compute SHA-256 hash of URL and title.  
   * Insert into `news_items` with `ON CONFLICT DO NOTHING` on the unique `url_hash` constraint.  
4. **Content Extraction:**  
   * Use `trafilatura` to extract 2 to 3 key paragraphs or full summary if feed content is truncated.

## **B. Summarization Engine (Gemini AI Pipeline)**

1. **Input Selection:** Fetch unsummarized news items published within the target window (e.g., past 24 hours).  
2. **Context Compression:** Limit context size by sending structured items: `[ID | Source | Category | Title | Summary]`.  
   |---|---|---|  
   * **System instruction:** Professional Ukrainian news editor.  
   * **Tasks:** Cluster identical events from different sources, filter out noise and clickbait, produce 5 to 7 key news topics.  
   * **Format:** Markdown-formatted Telegram post with bold topic titles, 2-3 concise summary sentences, and source links.  
   * **Constraint:** Must not exceed 3800 characters to fit Telegram 4096-character limit safely.

## **C. Multi-User Delivery and Interaction**

1. **User Settings Management:**  
   * Default delivery time: 21:00 (Kyiv time, `Europe/Kyiv`).  
   * Timezone: `Europe/Kyiv`.  
   * Category filters: Politics, War and Frontline, Economy, Technology, Culture, Society.  
   * Enable or Disable each Category.  
   * Enable or Disable daily digest toggle.  
2. **Scheduler Execution:**  
   * Check registered users whose scheduled time matches the current minute.  
   * Generate or retrieve cached daily digest matching the user category preferences.  
   * Send message with retry and error handling (handling user blocks, rate limits).  
3. **On-Demand Command:**  
   * `/now`: Triggers instant digest generation for the current user for the last 4 hours.

---

# **4\. Database Schema (SQLite)**

## **Table: `users`**

| Column | Type | Constraints / Default | Description |
| :---- | :---- | :---- | :---- |
| `id` | INTEGER | PRIMARY KEY | Telegram User ID |
| `username` | TEXT | NULLABLE | Telegram handle |
| `first_name` | TEXT | NULLABLE | User's first name |
| `delivery_hour` | INTEGER | DEFAULT: 20 | Hour of delivery (0-23) |
| `delivery_minute` | INTEGER | DEFAULT: 0 | Minute of delivery (0-59) |
| `timezone` | TEXT | DEFAULT: Europe/Kyiv | User timezone |
| `categories` | TEXT | DEFAULT: all | Comma-separated or JSON list of selected categories |
| `is_active` | BOOLEAN | DEFAULT: 1 | Active subscriber status |
| `created_at` | TIMESTAMP | DEFAULT: CURRENT\_TIMESTAMP | Registration timestamp |

## **Table: `news_items`**

| Column | Type | Constraints / Default | Description |
| :---- | :---- | :---- | :---- |
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Internal record identifier |
| `url` | TEXT | UNIQUE, NOT NULL | Canonical article URL |
| `url_hash` | TEXT | UNIQUE, NOT NULL | SHA-256 hash for deduplication |
| `title` | TEXT | NOT NULL | Article title |
| `source` | TEXT | NOT NULL | Source name (e.g., Suspilne, BBC Ukraine, Pravda) |
| `category` | TEXT | NULLABLE | Extracted or inferred category |
| `summary` | TEXT | NULLABLE | Extracted text snippet |
| `published_at` | TIMESTAMP | NOT NULL | Original publication timestamp |
| `created_at` | TIMESTAMP | DEFAULT: CURRENT\_TIMESTAMP | Ingestion timestamp |

## **Table: `digests`**

| Column | Type | Constraints / Default | Description |
| :---- | :---- | :---- | :---- |
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Internal digest identifier |
| `target_date` | DATE | NOT NULL | Date for which digest was created |
| `category_group` | TEXT | DEFAULT: all | Target category combination |
| `content` | TEXT | NOT NULL | Generated Telegram markdown text |
| `created_at` | TIMESTAMP | DEFAULT: CURRENT\_TIMESTAMP | Generation timestamp |

## **Table: `user_delivery_logs`**

| Column | Type | Constraints / Default | Description |
| :---- | :---- | :---- | :---- |
| `id` | INTEGER | PRIMARY KEY, AUTOINCREMENT | Log entry ID |
| `user_id` | INTEGER | FOREIGN KEY \-\> users.id | Recipient user ID |
| `digest_id` | INTEGER | FOREIGN KEY \-\> digests.id | Delivered digest ID |
| `status` | TEXT | \- | Status flag: `sent`, `failed`, `blocked` |
| `sent_at` | TIMESTAMP | DEFAULT: CURRENT\_TIMESTAMP | Delivery execution timestamp |

---

# **5\. Directory Structure**

news-digest-bot/

├── bot/

│   ├── handlers/

│   │   ├── \_\_init\_\_.py

│   │   ├── common.py          \# /start, /help, /cancel

│   │   ├── settings.py        \# Delivery time picker, categories toggle

│   │   └── digest.py          \# /now command handler

│   ├── keyboards/

│   │   ├── inline.py          \# Time selector, category toggles

│   │   └── reply.py

│   ├── middlewares/

│   │   └── db\_session.py      \# Injects async DB session into handlers

│   └── bot\_instance.py        \# Bot and Dispatcher setup

├── core/

│   ├── config.py              \# Pydantic Settings (.env validator)

│   └── database.py            \# SQLite async engine and Base declarative model

├── db/

│   ├── models.py              \# SQLAlchemy ORM models

│   └── crud.py                \# CRUD queries for users, news, and digests

├── services/

│   ├── fetcher/

│   │   ├── rss\_client.py      \# Async RSS feed parser

│   │   └── extractor.py       \# Trafilatura cleaner

│   ├── summarizer/

│   │   ├── gemini\_client.py   \# Google Gemini API integration

│   │   └── prompts.py         \# System prompt and formatting rules

│   └── scheduler/

│       ├── jobs.py            \# Aggregation and delivery tasks

│       └── scheduler\_mgr.py   \# APScheduler initialization

├── .env.example

├── Dockerfile

├── docker-compose.yml

├── requirements.txt

└── main.py                    \# Application entry point

---

# **6\. Implementation Instructions for the AI Agent**

## **Step 1: Environment and Configuration**

* Create `core/config.py` using `pydantic-settings`.  
* Required environment variables in `.env`:  
  * `BOT_TOKEN`: Telegram Bot API token from `@BotFather`.  
  * `GEMINI_API_KEY`: API key from Google AI Studio.  
  * `DATABASE_URL`: `sqlite+aiosqlite:///./data/news_bot.db`.  
  * `LOG_LEVEL`: `INFO` or `DEBUG`.

## **Step 2: Database Layer**

* Implement SQLAlchemy async engine in `core/database.py`.  
* Ensure SQLite executes `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;` on connection.  
* Implement ORM models in `db/models.py` and repository methods in `db/crud.py`.

## **Step 3: RSS Feed Ingestion Service**

* Implement `services/fetcher/rss_client.py`.  
* Loop over configured RSS feed URLs concurrently using `asyncio.gather` with an `aiohttp.ClientSession`.  
* Normalize publish dates to UTC.  
* Save unseen entries to `news_items` with conflict-safe deduplication.

## **Step 4: Gemini Summarizer Service**

* Implement `services/summarizer/gemini_client.py`.  
* Query `news_items` published in the past 24 hours.  
* Construct the prompt:  
  * **System instruction:** You are an objective, professional Ukrainian news editor.  
  * **Output format:** Telegram MarkdownV2 or HTML.  
  * **Maximum 7 items:** bullet points with event title, 2 sentences explaining context and impact, with an embedded hyperlink to the original source.  
* **Fallback strategy:** If content exceeds 4000 characters, automatically split into multiple Telegram messages without breaking tags.

## **Step 5: Telegram Bot UI and User Settings**

* Handlers in `bot/handlers/settings.py`:  
  * Allow users to select delivery hour (e.g., 08:00, 13:00, 19:00, 20:00, 22:00) using inline keyboard.  
  * Allow users to toggle categories on or off.  
* Handler in `bot/handlers/digest.py`:  
  * `/now`: Immediate digest generation or serving cached today's digest.

## **Step 6: APScheduler Integration**

* In `main.py`, attach `AsyncIOScheduler`.  
* **Job 1:** Every 30 minutes — run `fetch_and_store_rss_news()`.  
* **Job 2:** Every minute — run `check_and_send_scheduled_digests()`, which queries active users whose `delivery_hour` and `delivery_minute` match current Kyiv time.

## **Step 7: Dockerization and Deployment**

* Write multi-stage `Dockerfile` (`Python 3.11-slim`, non-root user).  
* Write `docker-compose.yml` with a volume mounted at `/app/data` to persist `news_bot.db`.  
* Configure `restart: unless-stopped`.

---

# **7\. Edge Cases and Resilience Rules**

1. **Telegram API Rate Limiting (`FloodWait`):** Wrap outgoing send operations with exponential backoff handling `TelegramRetryAfter`.  
2. **Blocked Users:** If `TelegramForbiddenError` is raised, set `user.is_active = False` in the database.  
3. **Empty News Window:** If no significant news occurred in the period, reply with a calm informative notice rather than failing.  
4. **LLM API Quotas and Timeouts:** Implement retry logic (up to 3 attempts) and timeout handling for Gemini API requests.

---

# **8\. Telegram Message Format and Delivery Rules**

## **Visual Message Template**

The AI summarizer must format the final Telegram post following this exact visual layout:

```
📰 Головне за день | {date}
⏱ Час читання: ~2 хв

```

```
{Category_Emoji} {Category_Title}
• {Bold_Event_Headline}
{Concise summary: 2-3 sentences explaining what happened, context, and impact.}
🔗 Джерело: <a href="{source_url}">{Source_Name}</a>

```

```
... (repeated for 5-7 key topics across relevant user-selected categories) ...

```

```
───────────────
⚙️ Налаштування розкладу й тем: /settings
```

## **Critical Formatting and Delivery Rules**

5. **HTML Parse Mode:**  
   * Always use `ParseMode.HTML` (`parse_mode="HTML"`) instead of `MarkdownV2`.  
   * MarkdownV2 requires escaping 18 reserved characters (e.g. dots, hyphens, exclamation marks) which frequently causes unhandled parsing exceptions when generated by LLMs.  
   * For HTML, only allow valid tags (`<b>`, `<i>`, `<a>`, `<code>`) and escape all dynamic user/feed strings using `html.escape()`.  
6. **Disable Link Previews:**  
   * When sending digests containing 5-7 source URLs, always disable web page previews to keep the message clean and readable.  
   * In `aiogram 3`, pass `link_preview_options=LinkPreviewOptions(is_disabled=True)` to `bot.send_message()`.  
7. **Message Length Budget:**  
   * Target optimal length: 1,200 to 2,200 characters.  
   * This ensures the digest fits on a single mobile screen without requiring scrolling, while remaining well below Telegram's 4,096-character limit.  
   * If a digest unexpectedly exceeds 4,000 characters, split logically at category boundary dividers (`───────────────`).  
8. **Periodic RSS Polling Rationale:**  
   * Do NOT attempt to fetch RSS feeds on-demand right before digest delivery.  
   * Ukrainian media RSS feeds maintain a shallow rolling window (typically only the latest 15 to 30 articles). Polling once in the evening would lose all morning and afternoon news.  
   * The background scheduler MUST continuously ingest feeds every 30-60 minutes into the SQLite database. The summarizer then queries the database for the relevant 24-hour window.