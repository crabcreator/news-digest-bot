"""Renders digest topics into the Telegram HTML message template and splits long messages.

The LLM only returns structured topics; markup, links and escaping are produced here so the
output is always valid Telegram HTML (only <b> and <a> are used, all dynamic text is escaped).
"""

import html
import re
from collections.abc import Sequence
from datetime import date

from core.categories import ALL_CATEGORY_KEYS, CATEGORY_BY_KEY
from db.models import NewsItem
from services.summarizer.gemini_client import Topic
from services.summarizer.prompts import MAX_TOPICS

DIVIDER = "───────────────"
FOOTER = "⚙️ Налаштування розкладу й тем: /settings"
TARGET_MAX_CHARS = 3800  # generation budget
TELEGRAM_SAFE_LIMIT = 4000  # split threshold (hard Telegram limit is 4096)
WORDS_PER_MINUTE = 180

_SECTION_SEP = f"\n\n{DIVIDER}\n\n"


def _esc(text: str) -> str:
    """Escape text content for Telegram HTML (&, <, >); quotes only need escaping inside attributes."""
    return html.escape(text, quote=False)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def format_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _header(target_date: date, body_chars: int | None = None) -> str:
    title = f"📰 <b>Головне за день</b> | {format_date(target_date)}"
    if body_chars is None:
        return title
    minutes = max(1, round(body_chars / 6 / WORDS_PER_MINUTE))  # ~6 chars per word incl. space
    return f"{title}\n⏱ Час читання: ~{minutes} хв"


def _render_topic(topic: Topic, item: NewsItem) -> str:
    return (
        f"• <b>{_esc(_one_line(topic.headline))}</b>\n"
        f"{_esc(_one_line(topic.summary))}\n"
        f'🔗 Джерело: <a href="{html.escape(item.url, quote=True)}">{_esc(item.source)}</a>'
    )


def _render_sections(by_category: dict[str, list[str]]) -> list[str]:
    sections = []
    for key in ALL_CATEGORY_KEYS:
        blocks = by_category.get(key)
        if blocks:
            cat = CATEGORY_BY_KEY[key]
            sections.append(f"{cat.emoji} <b>{_esc(cat.title)}</b>\n" + "\n\n".join(blocks))
    return sections


def _assemble(target_date: date, sections: list[str]) -> str:
    body = _SECTION_SEP.join(sections + [FOOTER])
    return f"{_header(target_date, len(body))}\n\n{body}"


def resolve_topics(
    topics: Sequence[Topic], items_by_id: dict[int, NewsItem], allowed_categories: Sequence[str]
) -> list[tuple[str, Topic, NewsItem]]:
    """Validate LLM output: drop hallucinated IDs, duplicates, empty text and disallowed categories."""
    allowed = set(allowed_categories)
    seen_sources: set[int] = set()
    result: list[tuple[str, Topic, NewsItem]] = []
    for topic in topics:
        item = items_by_id.get(topic.source_id)
        if item is None or topic.source_id in seen_sources:
            continue
        if not topic.headline.strip() or not topic.summary.strip():
            continue
        category = topic.category if topic.category in CATEGORY_BY_KEY else (item.category or "")
        if category not in allowed:
            continue
        seen_sources.add(topic.source_id)
        result.append((category, topic, item))
        if len(result) >= MAX_TOPICS:
            break
    return result


def render_digest(
    topics: Sequence[Topic],
    items: Sequence[NewsItem],
    allowed_categories: Sequence[str],
    target_date: date,
    max_chars: int = TARGET_MAX_CHARS,
) -> str | None:
    """Build the final HTML digest, or return None if no valid topic remains after validation.

    If the text exceeds `max_chars`, trailing topics are dropped (the model lists the most
    significant first) until it fits.
    """
    resolved = resolve_topics(topics, {i.id: i for i in items}, allowed_categories)
    while resolved:
        by_category: dict[str, list[str]] = {}
        for category, topic, item in resolved:
            by_category.setdefault(category, []).append(_render_topic(topic, item))
        text = _assemble(target_date, _render_sections(by_category))
        if len(text) <= max_chars or len(resolved) == 1:
            return text
        resolved.pop()
    return None


def render_empty_digest(target_date: date, window_label: str = "") -> str:
    suffix = f" {window_label}" if window_label else ""
    return (
        f"{_header(target_date)}\n\n"
        f"🌿 Поки що нічого значущого{suffix} не сталося — або підходящих новин за обраними темами немає. "
        f"Спробуйте пізніше.\n\n{DIVIDER}\n{FOOTER}"
    )


_TAG_RE = re.compile(r"<[^>]+>")


def split_message(text: str, limit: int = TELEGRAM_SAFE_LIMIT) -> list[str]:
    """Split text into chunks <= limit, preferring category dividers, then blank lines, then lines.

    Digest markup never spans lines (each tag opens and closes on one line), so splitting on
    line boundaries cannot break tags.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for separator in (_SECTION_SEP, "\n\n", "\n"):
        if all(len(part) <= limit for part in text.split(separator)):
            break
    else:
        separator = "\n"

    for part in text.split(separator):
        candidate = f"{current}{separator}{part}" if current else part
        if len(candidate) <= limit:
            current = candidate
            continue
        flush()
        if len(part) <= limit:
            current = part
        else:  # a single line longer than the limit: hard cut at word boundaries (plain text fallback)
            plain = html.unescape(_TAG_RE.sub("", part))
            words, line = plain.split(" "), ""
            for word in words:
                if len(html.escape(line + " " + word)) > limit:
                    chunks.append(html.escape(line))
                    line = word
                else:
                    line = f"{line} {word}".strip()
            current = html.escape(line)
    flush()
    return chunks
