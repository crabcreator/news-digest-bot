"""Extractive fallback digest, used when Gemini stays unavailable after all retries.

No LLM involved: picks the freshest, distinct headlines spread across categories and reuses the
normal renderer, so users still get a useful digest instead of an error.
"""

import re
from collections import defaultdict, deque
from collections.abc import Sequence

from core.categories import ALL_CATEGORY_KEYS
from db.models import NewsItem
from services.summarizer.gemini_client import Topic
from services.summarizer.prompts import MAX_TOPICS

FALLBACK_NOTICE = "⚠️ ШІ-підсумок тимчасово недоступний, тому нижче — найсвіжіші заголовки."
MAX_PER_CATEGORY = 2
MAX_SUMMARY_CHARS = 200
SIMILARITY_THRESHOLD = 0.5

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _tokens(title: str) -> set[str]:
    # 5-char prefixes make the comparison robust to Ukrainian word endings.
    return {w[:5] for w in _WORD_RE.findall(title.lower()) if len(w) > 3}


def _similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= SIMILARITY_THRESHOLD


def _short_summary(item: NewsItem) -> str:
    text = " ".join((item.summary or "").split())
    if len(text) > MAX_SUMMARY_CHARS:
        cut = text[:MAX_SUMMARY_CHARS]
        boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        text = cut[: boundary + 1] if boundary > MAX_SUMMARY_CHARS * 0.4 else cut.rsplit(" ", 1)[0] + "…"
    if not text or text.lower() == " ".join(item.title.lower().split()):
        return "Деталі — за посиланням нижче."
    return text


def build_fallback_topics(items: Sequence[NewsItem], categories: Sequence[str]) -> list[Topic]:
    """Newest-first, round-robin over the selected categories, skipping near-duplicate headlines.

    `items` must be ordered newest first (as returned by the CRUD layer). Items without a
    category are skipped because they cannot be matched to the user's topics reliably.
    """
    allowed = [c for c in ALL_CATEGORY_KEYS if c in set(categories)]
    queues: dict[str, deque[NewsItem]] = defaultdict(deque)
    for item in items:
        if item.category in allowed:
            queues[item.category].append(item)

    picked: list[NewsItem] = []
    picked_tokens: list[set[str]] = []
    per_category: dict[str, int] = defaultdict(int)

    progress = True
    while len(picked) < MAX_TOPICS and progress:
        progress = False
        for category in allowed:
            queue = queues[category]
            while queue and per_category[category] < MAX_PER_CATEGORY:
                item = queue.popleft()
                tokens = _tokens(item.title)
                if any(_similar(tokens, other) for other in picked_tokens):
                    continue
                picked.append(item)
                picked_tokens.append(tokens)
                per_category[category] += 1
                progress = True
                break
            if len(picked) >= MAX_TOPICS:
                break

    return [
        Topic(category=item.category or "", headline=item.title, summary=_short_summary(item), source_id=item.id)
        for item in picked
    ]
