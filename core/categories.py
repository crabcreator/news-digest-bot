"""News category definitions shared by the fetcher, summarizer and bot UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    emoji: str


CATEGORIES: tuple[Category, ...] = (
    Category("politics", "Політика", "🏛"),
    Category("war", "Війна та фронт", "🪖"),
    Category("economy", "Економіка", "💰"),
    Category("technology", "Технології", "💻"),
    Category("science", "Наука", "🔬"),
    Category("culture", "Культура", "🎭"),
    Category("showbiz", "Шоу-бізнес", "🌟"),
    Category("society", "Суспільство", "👥"),
)

CATEGORY_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}
ALL_CATEGORY_KEYS: tuple[str, ...] = tuple(c.key for c in CATEGORIES)
