from datetime import datetime

from services.fetcher.categorizer import infer_category
from services.fetcher.extractor import extract_from_html_snippet, truncate_paragraphs
from services.fetcher.rss_client import FeedSource, ingest_feeds, normalize_url, parse_feed_bytes

SRC = FeedSource("Test", "https://example.com/rss")

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Росія атакувала Київ ракетами</title>
<link>https://example.com/a?at_medium=RSS&amp;id=5#frag</link>
<description>&lt;p&gt;Ракетний обстріл столиці.&lt;/p&gt;</description>
<pubDate>Thu, 22 Oct 2026 13:00:00 +0300</pubDate></item>
<item><title></title><link>https://example.com/empty</link></item>
</channel></rss>""".encode()

XXE = b"""<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<rss version="2.0"><channel><item><title>&x;</title><link>https://e.com/1</link></item></channel></rss>"""


def test_normalize_url_strips_tracking():
    assert normalize_url("https://x.com/a?at_medium=RSS&utm_source=y&id=5#f") == "https://x.com/a?id=5"


def test_parse_feed_normalizes_date_to_utc():
    entries = parse_feed_bytes(RSS, SRC)
    assert len(entries) == 1  # entry without a title is dropped
    assert entries[0].url == "https://example.com/a?id=5"
    assert entries[0].published_at == datetime(2026, 10, 22, 10, 0)  # 13:00 +03:00


def test_parse_feed_rejects_xxe():
    assert parse_feed_bytes(XXE, SRC) == []


def test_extractor_strips_html_and_truncates():
    assert extract_from_html_snippet("<p>Hello <b>world</b></p>") == "Hello world"
    text = "\n".join(["Речення одне. Речення два."] * 10)
    assert len(truncate_paragraphs(text).split("\n")) == 3
    assert len(truncate_paragraphs("слово " * 300)) <= 701


async def test_fetch_article_text_respects_max_bytes():
    from unittest.mock import AsyncMock, MagicMock
    from services.fetcher.extractor import fetch_article_text

    async def fake_iter_chunked(size):
        for _ in range(50):
            yield b"x" * (64 * 1024)

    resp = MagicMock()
    resp.status = 200
    resp.content.iter_chunked = fake_iter_chunked
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=resp)
    session.get.return_value.__aexit__ = AsyncMock(return_value=None)

    text = await fetch_article_text(session, "https://example.com/huge")
    assert isinstance(text, str)


def test_categorizer():
    assert infer_category("ЗСУ відбили наступ, обстріл Харкова") == "war"
    assert infer_category("НБУ знизив облікову ставку, інфляція сповільнилась") == "economy"
    assert infer_category("Вчені NASA зробили відкриття про галактики") == "science"
    assert infer_category("Зірки Голлівуду та скандал на весіллі") == "showbiz"
    assert infer_category("Щось нейтральне") is None
    assert infer_category("x", tags=["Культура"]) == "culture"
    assert infer_category("x", tags=["Наука"]) == "science"
    assert infer_category("x", tags=["Шоубіз"]) == "showbiz"


async def test_ingest_feeds_dedups(session, monkeypatch):
    from services.fetcher import rss_client

    async def fake_fetch_all(http, sources):
        return parse_feed_bytes(RSS, SRC)

    async def fake_summary(http, url, snippet):
        return "Ракетний обстріл столиці."

    monkeypatch.setattr(rss_client, "fetch_all_feeds", fake_fetch_all)
    monkeypatch.setattr(rss_client, "build_summary", fake_summary)

    class DummyHttp:
        async def close(self): ...

    assert await ingest_feeds(session, [SRC], http=DummyHttp()) == 1
    assert await ingest_feeds(session, [SRC], http=DummyHttp()) == 0
