"""Cheap rule-based category inference (RSS tags + Ukrainian keyword stems).

Items that cannot be classified here are left with `category=None` and are
classified later by Gemini in the summarization pipeline.
"""

import re
from collections.abc import Iterable

# Keyword stems, matched case-insensitively as substrings. Order matters only for ties.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "war": (
        "фронт", "обстріл", "ракет", "дрон", "шахед", "безпілот", "атак", "зсу", "збройн", "окуп",
        "військов", "бойов", "наступ", "повітряні сили", "тривог", "генштаб", "оборон", "полон",
        "артилері", "танк", "загибл", "евакуац", "мобілізац", "перемир", "бойові дії",
    ),
    "politics": (
        "президент", "зеленськ", "верховна рада", "рада ухвалила", "уряд", "міністр", "депутат", "вибор",
        "санкці", "нато", "єс ", "євросоюз", "дипломат", "переговор", "саміт", "закон", "прем'єр",
        "кабмін", "партія", "трамп", "путін", "посол", "кремл",
    ),
    "economy": (
        "економ", "інфляц", "нбу", "курс долара", "гривн", "бюджет", "податк", "банк", "ввп", "експорт",
        "імпорт", "ціни", "ціна", "тариф", "біржа", "інвестиц", "кредит", "борг", "мвф", "ринок",
        "зарплат", "пенсі",
    ),
    "technology": (
        "технолог", "штучний інтелект", " ші ", "chatgpt", "openai", "google", "apple", "microsoft", "смартфон",
        "кібер", "хакер", "програм", "стартап", "робот", "космос", "spacex", "iphone", "android",
        "інтернет", "нейромереж", "гаджет",
    ),
    "culture": (
        "культур", "кіно", "фільм", "музик", "концерт", "театр", "виставк", "письменник", "книг", "фестивал",
        "оскар", "співак", "співачк", "художник", "музей", "серіал", "літератур", "мистецтв",
    ),
    "society": (
        "суспільств", "школ", "освіт", "лікар", "медицин", "здоров", "погода", "пожеж", "дтп", "поліці",
        "суд", "соціальн", "переселен", "біженц", "спорт", "футбол", "комунальн", "опалення",
        "освітлення", "вакцин", "екологі",
    ),
}

# Feed-provided section names mapped to our categories (rarely populated by Ukrainian feeds).
_TAG_MAP: dict[str, str] = {
    "політика": "politics",
    "війна": "war",
    "економіка": "economy",
    "технології": "technology",
    "культура": "culture",
    "суспільство": "society",
    "society": "society",
    "politics": "politics",
    "economy": "economy",
    "technology": "technology",
    "culture": "culture",
}

_WORD_SPLIT = re.compile(r"\s+")


def infer_category(title: str, summary: str | None = None, tags: Iterable[str] = ()) -> str | None:
    """Return a category key or None when the item is ambiguous."""
    for tag in tags:
        mapped = _TAG_MAP.get(tag.strip().lower())
        if mapped:
            return mapped

    text = f" {title} {summary or ''} ".lower()
    text = _WORD_SPLIT.sub(" ", text)
    scores: dict[str, int] = {}
    for category, stems in _KEYWORDS.items():
        hits = sum(1 for stem in stems if stem in text)
        # Title hits are a stronger signal than summary hits.
        hits += sum(1 for stem in stems if stem in f" {title.lower()} ")
        if hits:
            scores[category] = hits
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None  # tie: let the LLM decide
    return ranked[0][0]
