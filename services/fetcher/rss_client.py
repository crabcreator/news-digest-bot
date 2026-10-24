"""Async RSS ingestion: fetch feeds concurrently, normalize, enrich and store news items."""

import asyncio
import logging
from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import feedparser
from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException
from sqlalchemy.ext.asyncio import AsyncSession

from db import crud
from db.crud import NewsItemData
from db.models import utcnow
from services.fetcher.categorizer import infer_category
from services.fetcher.extractor import build_summary

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; NewsDigestBot/1.0)"
MAX_FEED_BYTES = 5 * 1024 * 1024
ENRICH_CONCURRENCY = 5


@dataclass(frozen=True, slots=True)
class FeedSource:
    name: str
    url: str
    default_category: str | None = None


DEFAULT_FEEDS: tuple[FeedSource, ...] = (
    FeedSource("Суспільне", "https://suspilne.media/rss/all.rss"),
    FeedSource("BBC Україна", "https://feeds.bbci.co.uk/ukrainian/rss.xml"),
    FeedSource("Українська правда", "https://www.pravda.com.ua/rss/"),
    FeedSource("Mezha.Media", "https://mezha.media/feed/", default_category="technology"),
    FeedSource("AIN.UA", "https://ain.ua/feed/", default_category="technology"),
    FeedSource("DOU", "https://dou.ua/feed/", default_category="technology"),
)


@dataclass(slots=True)
class RawEntry:
    url: str
    title: str
    source: str
    published_at: datetime  # naive UTC
    snippet_html: str | None
    tags: list[str]
    default_category: str | None = None


_TRACKING_PREFIXES = ("utm_", "at_")
_TRACKING_PARAMS = {"fbclid", "gclid", "ref", "ocid"}


def normalize_url(url: str) -> str:
    """Strip tracking query params and fragments so the same article hashes identically."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def entry_published_utc(entry: feedparser.FeedParserDict) -> datetime:
    """Publish date normalized to naive UTC; falls back to now when the feed gives none."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        # feedparser normalizes parsed dates to UTC struct_time
        return datetime.fromtimestamp(timegm(parsed), tz=timezone.utc).replace(tzinfo=None)
    return utcnow()


def parse_feed_bytes(content: bytes, source: FeedSource) -> list[RawEntry]:
    """Validate XML safely (defusedxml), then parse with feedparser."""
    try:
        SafeET.fromstring(content)
    except DefusedXmlException:
        logger.warning("Rejected unsafe XML from %s", source.name)
        return []
    except SafeET.ParseError:
        # Malformed but not malicious: feedparser is tolerant, let it try.
        logger.debug("Strict XML parse failed for %s; falling back to lenient parsing", source.name)

    parsed = feedparser.parse(content)
    entries: list[RawEntry] = []
    for e in parsed.entries:
        link, title = e.get("link"), (e.get("title") or "").strip()
        if not link or not title:
            continue
        content_list = e.get("content") or []
        snippet = e.get("summary") or (content_list[0].get("value") if content_list else None)
        entries.append(
            RawEntry(
                url=normalize_url(link),
                title=title,
                source=source.name,
                published_at=entry_published_utc(e),
                snippet_html=snippet,
                tags=[t.get("term", "") for t in e.get("tags", []) if t.get("term")],
                default_category=source.default_category,
            )
        )
    return entries


async def fetch_feed(http: aiohttp.ClientSession, source: FeedSource) -> list[RawEntry]:
    async with http.get(source.url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        resp.raise_for_status()
        # StreamReader.read(n) may return a partial body, so read chunks until EOF (bounded).
        chunks: list[bytes] = []
        size = 0
        async for chunk in resp.content.iter_chunked(64 * 1024):
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise ValueError(f"Feed {source.name} exceeds {MAX_FEED_BYTES} bytes")
            chunks.append(chunk)
        content = b"".join(chunks)
    return await asyncio.to_thread(parse_feed_bytes, content, source)


async def fetch_all_feeds(http: aiohttp.ClientSession, sources: tuple[FeedSource, ...] | list[FeedSource]) -> list[RawEntry]:
    """Fetch all feeds concurrently; a failing feed never blocks the others."""
    results = await asyncio.gather(*(fetch_feed(http, s) for s in sources), return_exceptions=True)
    entries: list[RawEntry] = []
    for source, result in zip(sources, results):
        if isinstance(result, BaseException):
            logger.error("Feed %s failed: %r", source.name, result)
            continue
        logger.info("Feed %s: %d entries", source.name, len(result))
        entries.extend(result)
    return entries


async def ingest_feeds(
    db: AsyncSession,
    sources: tuple[FeedSource, ...] | list[FeedSource] = DEFAULT_FEEDS,
    http: aiohttp.ClientSession | None = None,
) -> int:
    """Fetch feeds and store unseen entries. Returns the number of newly inserted items."""
    own_http = http is None
    http = http or aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
    try:
        entries = await fetch_all_feeds(http, sources)

        unique: dict[str, RawEntry] = {}
        for entry in entries:
            unique.setdefault(entry.url, entry)
        known = await crud.get_existing_urls(db, list(unique))
        fresh = [e for url, e in unique.items() if url not in known]
        if not fresh:
            logger.info("No new entries")
            return 0

        # Only new entries are enriched, so article pages are fetched at most once.
        semaphore = asyncio.Semaphore(ENRICH_CONCURRENCY)

        async def to_item(entry: RawEntry) -> NewsItemData:
            async with semaphore:
                summary = await build_summary(http, entry.url, entry.snippet_html)
            category = entry.default_category or infer_category(entry.title, summary, entry.tags)
            return NewsItemData(
                url=entry.url,
                title=entry.title,
                source=entry.source,
                published_at=entry.published_at,
                category=category,
                summary=summary or None,
            )

        items = await asyncio.gather(*(to_item(e) for e in fresh))
        inserted = await crud.add_news_items(db, items)
        logger.info("Ingested %d new news items (%d candidates)", inserted, len(fresh))
        return inserted
    finally:
        if own_http:
            await http.close()
