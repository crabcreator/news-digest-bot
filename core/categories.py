"""News category definitions shared by the fetcher, summarizer and bot UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Subcategory:
    key: str
    title: str
    emoji: str


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    emoji: str


TECH_SUBCATEGORIES: tuple[Subcategory, ...] = (
    Subcategory("ai", "Штучний інтелект (AI)", "🤖"),
    Subcategory("cybersec", "Кібербезпека", "🛡"),
    Subcategory("gadgets", "Гаджети та залізо", "📱"),
    Subcategory("business", "IT-бізнес та стартапи", "💼"),
    Subcategory("software", "Софт та розробка", "👨‍💻"),
)

TECH_SUBCATEGORY_KEYS: tuple[str, ...] = tuple(s.key for s in TECH_SUBCATEGORIES)
TECH_SUBCATEGORY_BY_KEY: dict[str, Subcategory] = {s.key: s for s in TECH_SUBCATEGORIES}


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
