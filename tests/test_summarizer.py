import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from core.categories import ALL_CATEGORY_KEYS
from db import crud
from db.models import NewsItem, utcnow
from services.summarizer.digest_service import get_or_generate_digest
from services.summarizer.formatter import DIVIDER, FOOTER, render_digest, render_empty_digest, split_message
from services.summarizer.gemini_client import GeminiSummarizer, SummarizationError, Topic
from services.summarizer.prompts import format_item

ALL = list(ALL_CATEGORY_KEYS)
D = date(2026, 10, 22)


def item(id_, category="war", url=None, source="Суспільне", title="Заголовок", summary="Текст"):
    return NewsItem(id=id_, url=url or f"https://example.com/{id_}", url_hash=str(id_), title=title,
                    source=source, category=category, summary=summary, published_at=utcnow())


# ------------------------------------------------------------------ formatter


def test_render_matches_template_and_escapes():
    items = [item(1, source="A&B", url='https://e.com/a?x=1&y="2"'), item(2, "economy")]
    topics = [
        Topic(category="war", headline="Удар <script>", summary="Перше. Друге.", source_id=1),
        Topic(category="economy", headline="Курс", summary="НБУ тримає курс.", source_id=2),
    ]
    text = render_digest(topics, items, ALL, D)
    assert text.startswith("📰 <b>Головне за день</b> | 22.10.2026\n⏱ Час читання: ~1 хв")
    assert "🪖 <b>Війна та фронт</b>\n• <b>Удар &lt;script&gt;</b>\nПерше. Друге." in text
    assert '🔗 Джерело: <a href="https://e.com/a?x=1&amp;y=&quot;2&quot;">A&amp;B</a>' in text
    assert text.index("Війна") < text.index("Економіка")  # canonical category order
    assert text.endswith(f"{DIVIDER}\n\n{FOOTER}")
    assert "<script>" not in text


def test_render_drops_invalid_topics():
    items = [item(1, "war"), item(2, "culture")]
    topics = [
        Topic(category="war", headline="Ok", summary="s", source_id=1),
        Topic(category="war", headline="Dup source", summary="s", source_id=1),
        Topic(category="war", headline="Hallucinated", summary="s", source_id=999),
        Topic(category="culture", headline="Not allowed", summary="s", source_id=2),
        Topic(category="bogus", headline="Fallback to item category", summary="s", source_id=2),
    ]
    text = render_digest(topics, items, ["war"], D)
    assert "Ok" in text and "Dup source" not in text and "Hallucinated" not in text
    assert "Not allowed" not in text and "Fallback" not in text
    assert render_digest([], items, ALL, D) is None


def test_render_trims_to_budget():
    items = [item(i, "war") for i in range(1, 8)]
    topics = [Topic(category="war", headline=f"H{i}", summary="слово " * 100, source_id=i) for i in range(1, 8)]
    text = render_digest(topics, items, ALL, D, max_chars=3800)
    assert len(text) <= 3800 and "H1" in text and "H7" not in text


def test_empty_digest_notice():
    text = render_empty_digest(D, "за добу")
    assert "за добу" in text and FOOTER in text and "<a" not in text


def test_split_message_at_dividers_and_tag_safe():
    sections = [f"🪖 <b>Cat{i}</b>\n• <b>H</b>\n" + ("слово " * 150) for i in range(6)]
    text = f"\n\n{DIVIDER}\n\n".join(sections)
    chunks = split_message(text, limit=1500)
    assert len(chunks) > 1 and all(len(c) <= 1500 for c in chunks)
    for c in chunks:
        assert c.count("<b>") == c.count("</b>")
    assert split_message("short") == ["short"]


def test_split_message_handles_oversized_line():
    chunks = split_message("слово " * 1000, limit=500)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 1


def test_prompt_item_format():
    line = format_item(item(7, None, title="T", summary="x " * 300))
    assert line.startswith("[7 | Суспільне | ? | T | ") and len(line) < 300


# ------------------------------------------------------------------ gemini client


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    async def generate_content(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return SimpleNamespace(text=outcome)


def make_summarizer(outcomes):
    models = FakeModels(outcomes)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GeminiSummarizer("k", client=client, backoff_base_seconds=0, max_attempts=3, timeout_seconds=5), models


GOOD = json.dumps({"topics": [{"category": "war", "headline": "H", "summary": "S", "source_id": 1}]})


def test_gemini_strips_markdown_fences():
    fenced = f"```json\n{GOOD}\n```"
    topics = GeminiSummarizer._parse(fenced)
    assert len(topics) == 1 and topics[0].headline == "H"


async def test_gemini_retries_transient_errors():
    s, models = make_summarizer([genai_errors.ServerError(503, {"error": {"message": "overloaded"}}), "not json", GOOD])
    topics = await s.generate_topics([item(1)], ALL, 24)
    assert models.calls == 3 and topics[0].source_id == 1


async def test_gemini_gives_up_after_max_attempts():
    err = genai_errors.ClientError(429, {"error": {"message": "quota"}})
    s, models = make_summarizer([err, err, err])
    with pytest.raises(SummarizationError):
        await s.generate_topics([item(1)], ALL, 24)
    assert models.calls == 3


async def test_gemini_does_not_retry_client_errors():
    s, models = make_summarizer([genai_errors.ClientError(400, {"error": {"message": "bad"}})])
    with pytest.raises(SummarizationError):
        await s.generate_topics([item(1)], ALL, 24)
    assert models.calls == 1


async def test_gemini_timeout_is_retried():
    s, models = make_summarizer([asyncio.TimeoutError(), GOOD])
    assert len(await s.generate_topics([item(1)], ALL, 24)) == 1


async def test_gemini_skips_call_without_items():
    s, models = make_summarizer([])
    assert await s.generate_topics([], ALL, 24) == []
    assert models.calls == 0


# ------------------------------------------------------------------ digest service


class FakeSummarizer:
    def __init__(self):
        self.calls = 0

    async def generate_topics(self, items, categories, window_hours):
        self.calls += 1
        return [Topic(category="war", headline="H", summary="S", source_id=items[0].id)]


async def seed(session, hours_ago=1):
    now = utcnow()
    await crud.add_news_items(session, [crud.NewsItemData("https://e.com/1", "T", "Src", now - timedelta(hours=hours_ago), "war", "x")])


async def test_service_generates_then_serves_cache(session):
    await seed(session)
    fake = FakeSummarizer()
    r1 = await get_or_generate_digest(session, fake, ALL, "daily")
    r2 = await get_or_generate_digest(session, fake, ALL, "daily")
    assert fake.calls == 1 and not r1.from_cache and r2.from_cache
    assert r1.digest_id == r2.digest_id and "🔗" in r1.text


async def test_service_now_uses_short_window_and_separate_cache(session):
    await seed(session, hours_ago=10)
    fake = FakeSummarizer()
    now_result = await get_or_generate_digest(session, fake, ALL, "now")
    assert fake.calls == 0 and now_result.digest_id is None and "<a" not in now_result.text  # nothing in last 4h
    daily = await get_or_generate_digest(session, fake, ALL, "daily")
    assert daily.digest_id is not None and fake.calls == 1


async def test_service_separate_cache_per_category_group(session):
    await seed(session)
    fake = FakeSummarizer()
    await get_or_generate_digest(session, fake, ALL, "daily")
    await get_or_generate_digest(session, fake, ["war", "politics"], "daily")
    assert fake.calls == 2


async def test_service_expired_cache_regenerates(session):
    await seed(session)
    fake = FakeSummarizer()
    await get_or_generate_digest(session, fake, ALL, "daily")
    later = utcnow() + timedelta(minutes=61)
    r = await get_or_generate_digest(session, fake, ALL, "daily", now_utc=later)
    # news is 1h old at seed time, still inside the 24h window at +61min
    assert fake.calls == 2 and not r.from_cache


async def test_service_no_categories_returns_notice(session):
    fake = FakeSummarizer()
    r = await get_or_generate_digest(session, fake, [], "daily")
    assert r.digest_id is None and fake.calls == 0


async def test_gemini_rotates_to_fallback_model_on_overload():
    used = []

    class RecordingModels(FakeModels):
        async def generate_content(self, **kwargs):
            used.append(kwargs["model"])
            return await super().generate_content(**kwargs)

    overloaded = genai_errors.ServerError(503, {"error": {"message": "high demand"}})
    models = RecordingModels([overloaded, GOOD])
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    s = GeminiSummarizer("k", model="primary", fallback_model="backup", client=client, backoff_base_seconds=0)
    assert len(await s.generate_topics([item(1)], ALL, 24)) == 1
    assert used == ["primary", "backup"]


def test_render_keeps_apostrophes_readable():
    topics = [Topic(category="war", headline="Прем'єр", summary="Дев'ять днів", source_id=1)]
    text = render_digest(topics, [item(1)], ALL, D)
    assert "Прем'єр" in text and "&#x27;" not in text


def test_empty_fallback_model_env_means_none(monkeypatch):
    from core.config import Settings

    s_default = Settings(bot_token="1:T", gemini_api_key="k", _env_file=None)
    assert s_default.gemini_fallback_model == "gemini-flash-lite-latest"
    assert s_default.gemini_timeout_seconds == 25

    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "")
    s = Settings(bot_token="1:T", gemini_api_key="k", _env_file=None)
    assert s.gemini_fallback_model is None


# ------------------------------------------------------------------ extractive fallback


def test_fallback_topics_are_diverse_and_deduplicated():
    from services.summarizer.fallback import build_fallback_topics

    items = [
        item(1, "war", title="Росія атакувала Київ ракетами вночі", summary="Деталі атаки."),
        item(2, "war", title="Росія атакувала Київ ракетами цієї ночі", summary="Інші деталі."),  # near-duplicate
        item(3, "war", title="ЗСУ звільнили село на Харківщині", summary="Село звільнено."),
        item(4, "war", title="Третя воєнна новина про щось інше", summary="Ще."),
        item(5, "economy", title="НБУ залишив облікову ставку", summary="Ставка 15%."),
        item(6, None, title="Без категорії"),
    ]
    topics = build_fallback_topics(items, ALL)
    ids = [t.source_id for t in topics]
    assert 2 not in ids and 6 not in ids  # duplicate and uncategorised skipped
    assert ids.count(4) == 0  # max 2 per category
    assert {1, 3, 5} == set(ids)
    assert all(t.summary for t in topics)


def test_fallback_respects_category_filter_and_renders_notice():
    from services.summarizer.fallback import FALLBACK_NOTICE, build_fallback_topics

    items = [item(1, "war", title="Новина війни"), item(2, "culture", title="Новина культури")]
    topics = build_fallback_topics(items, ["culture"])
    assert [t.source_id for t in topics] == [2]
    text = render_digest(topics, items, ["culture"], D, notice=FALLBACK_NOTICE)
    assert "⚠️ ШІ-підсумок" in text and "Новина культури" in text and "Новина війни" not in text


async def test_service_serves_fallback_when_gemini_fails_and_does_not_cache(session):
    await seed(session)

    class Failing:
        calls = 0

        async def generate_topics(self, *a):
            Failing.calls += 1
            raise SummarizationError("503")

    r1 = await get_or_generate_digest(session, Failing(), ALL, "now")
    r2 = await get_or_generate_digest(session, Failing(), ALL, "now")
    assert "ШІ-підсумок тимчасово недоступний" in r1.text and r1.digest_id is None
    assert Failing.calls == 2  # not cached: every request retries Gemini


async def test_service_raises_when_fallback_has_nothing(session):
    await crud.add_news_items(
        session, [crud.NewsItemData("https://e.com/u", "T", "Src", utcnow() - timedelta(hours=1), None, "x")]
    )

    class Failing:
        async def generate_topics(self, *a):
            raise SummarizationError("503")

    with pytest.raises(SummarizationError):
        await get_or_generate_digest(session, Failing(), ALL, "now")


def test_build_user_prompt_with_tech_subcategories():
    from services.summarizer.prompts import build_user_prompt

    items = [item(1, "technology", title="OpenAI реліз", summary="Нова модель")]

    # All subcategories -> no restriction
    prompt_all = build_user_prompt(items, ["technology"], 24, tech_subcategories=None)
    assert 'For the "technology" category, only include events' not in prompt_all

    # Subset of subcategories -> restriction added
    prompt_sub = build_user_prompt(items, ["technology"], 24, tech_subcategories=["ai", "cybersec"])
    assert 'For the "technology" category, only include events from these specific fields: ai (Штучний інтелект (AI)), cybersec (Кібербезпека)' in prompt_sub


def test_cache_key_with_tech_subcategories():
    from services.summarizer.digest_service import cache_key

    # all categories and default tech subcategories -> standard key
    k1 = cache_key(ALL, "daily", tech_subcategories=None)
    assert k1 == "all"
    assert "[tech:" not in k1

    # subset of tech subcategories -> suffixed key
    k2 = cache_key(ALL, "daily", tech_subcategories=["ai", "cybersec"])
    assert k2 == "all[tech:ai,cybersec]"


def test_divider_uses_em_dashes():
    assert DIVIDER == "———————————————"
    assert all(ch == "—" for ch in DIVIDER)


def test_system_instruction_topic_limits_and_balancing():
    from services.summarizer.prompts import MAX_TOPICS, MIN_TOPICS, SYSTEM_INSTRUCTION
    from services.summarizer.formatter import resolve_topics

    assert MAX_TOPICS == 8 and MIN_TOPICS == 5
    assert "5-8 most significant events" in SYSTEM_INSTRUCTION
    assert "strive to include at least 1 event from each allowed category" in SYSTEM_INSTRUCTION

    # resolve_topics respects new MAX_TOPICS = 8
    items = [item(i, "war") for i in range(1, 11)]
    topics = [Topic(category="war", headline=f"H{i}", summary=f"S{i}", source_id=i) for i in range(1, 11)]
    resolved = resolve_topics(topics, {i.id: i for i in items}, ["war"])
    assert len(resolved) == 8


def test_world_news_cache_key_and_headers():
    from datetime import date
    from services.summarizer.digest_service import cache_key
    from services.summarizer.formatter import _header, render_empty_digest
    from services.summarizer.prompts import build_user_prompt

    k_ua = cache_key(ALL, "daily", scope="ua")
    assert k_ua == "all"

    k_world = cache_key(ALL, "daily", scope="world")
    assert k_world == "world:all"

    k_world_now = cache_key(ALL, "now", scope="world")
    assert k_world_now == "world:now:all"

    hdr_ua = _header(date(2026, 10, 24), scope="ua")
    assert "📰 <b>Головне за день</b>" in hdr_ua

    hdr_world = _header(date(2026, 10, 24), scope="world")
    assert "🌍 <b>Світові новини</b>" in hdr_world

    empty_world = render_empty_digest(date(2026, 10, 24), scope="world")
    assert "🌍 <b>Світові новини</b>" in empty_world
    assert "у світі" in empty_world

    prompt_world = build_user_prompt([item(1, "war")], ["war"], 24, scope="world")
    assert "WORLD NEWS" in prompt_world
