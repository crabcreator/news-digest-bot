"""Article text extraction and cleaning with trafilatura."""

import asyncio
import logging
import re
from html import unescape

import aiohttp
import trafilatura

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 700
MIN_USEFUL_CHARS = 150  # feed snippets shorter than this are considered truncated
MAX_PARAGRAPHS = 3
MAX_ARTICLE_BYTES = 2 * 1024 * 1024  # 2 MB limit for article page download

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v\u00a0]+")


def clean_text(text: str) -> str:
    """Collapse whitespace, keeping paragraph breaks."""
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def truncate_paragraphs(text: str, max_paragraphs: int = MAX_PARAGRAPHS, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    """Keep the first few paragraphs and cut at a sentence/word boundary under max_chars."""
    paragraphs = [p for p in text.split("\n") if p.strip()][:max_paragraphs]
    result = "\n".join(paragraphs)
    if len(result) <= max_chars:
        return result
    cut = result[:max_chars]
    boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if boundary > max_chars * 0.5:
        return cut[: boundary + 1]
    return cut.rsplit(" ", 1)[0] + "…"


def extract_from_html_snippet(html: str | None) -> str:
    """Clean the HTML fragment that comes with the feed entry (summary/content)."""
    if not html:
        return ""
    extracted = None
    if "<" in html:
        try:
            extracted = trafilatura.extract(
                f"<html><body>{html}</body></html>", include_comments=False, include_tables=False, favor_recall=True
            )
        except Exception:  # noqa: BLE001 - extraction must never break ingestion
            logger.debug("trafilatura failed on snippet", exc_info=True)
    if not extracted:
        extracted = _TAG_RE.sub(" ", unescape(html))
    return truncate_paragraphs(clean_text(extracted))


def extract_from_page_html(page_html: str, url: str | None = None) -> str:
    try:
        extracted = trafilatura.extract(
            page_html, url=url, include_comments=False, include_tables=False, favor_precision=True
        )
    except Exception:  # noqa: BLE001
        logger.debug("trafilatura failed on page %s", url, exc_info=True)
        return ""
    return truncate_paragraphs(clean_text(extracted)) if extracted else ""


async def fetch_article_text(session: aiohttp.ClientSession, url: str) -> str:
    """Download an article page and extract its leading paragraphs. Returns '' on any failure."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return ""
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.content.iter_chunked(64 * 1024):
                size += len(chunk)
                chunks.append(chunk)
                if size >= MAX_ARTICLE_BYTES:
                    break
            page = b"".join(chunks).decode("utf-8", errors="replace")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.debug("Could not download article %s", url)
        return ""
    # trafilatura is CPU-bound and synchronous: keep the event loop free.
    return await asyncio.to_thread(extract_from_page_html, page, url)


async def build_summary(session: aiohttp.ClientSession, url: str, snippet_html: str | None) -> str:
    """Feed snippet if it is long enough, otherwise try to enrich it from the article page."""
    snippet = await asyncio.to_thread(extract_from_html_snippet, snippet_html)
    if len(snippet) >= MIN_USEFUL_CHARS:
        return snippet
    full = await fetch_article_text(session, url)
    return full if len(full) > len(snippet) else snippet
