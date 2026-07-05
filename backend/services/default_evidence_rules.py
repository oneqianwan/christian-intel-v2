from __future__ import annotations

from urllib.parse import urlparse


SOURCE_AUTHORITY_SCORES = {
    "arda": 0.95,
    "pew": 0.95,
    "pew research": 0.95,
    "joshua": 0.90,
    "joshua project": 0.90,
    "official": 0.90,
    "official_website": 0.90,
    "wikidata": 0.85,
    "wikipedia": 0.75,
    "reuters": 0.70,
    "ap": 0.70,
    "bbc": 0.70,
    "cnn": 0.70,
    "rss": 0.60,
    "newsapi": 0.55,
    "unknown": 0.30,
}


def normalize_domain(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        return str(parsed.netloc or "").strip().lower()
    except Exception:
        return ""


def normalize_source_type(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return "unknown"
    aliases = {
        "official website": "official_website",
        "official": "official_website",
        "website": "official_website",
        "manual seed": "manual_seed",
    }
    return aliases.get(lowered, lowered)


def default_source_authority(source_type: str, domain: str = "") -> float:
    normalized_type = normalize_source_type(source_type)
    normalized_domain = str(domain or "").strip().lower()
    if normalized_type in SOURCE_AUTHORITY_SCORES:
        return float(SOURCE_AUTHORITY_SCORES[normalized_type])
    if normalized_domain.endswith(".org"):
        return 0.75
    if normalized_domain.endswith(".edu"):
        return 0.80
    if normalized_domain.endswith(".gov"):
        return 0.90
    return float(SOURCE_AUTHORITY_SCORES["unknown"])


def default_confidence(explicit_confidence: float | int | str | None, authority: float) -> float:
    try:
        score = float(explicit_confidence or 0.0)
    except Exception:
        score = 0.0
    if score > 0:
        return round(max(0.0, min(score, 1.0)), 3)
    return round(max(0.0, min(float(authority or 0.0) * 0.85, 1.0)), 3)


def default_relevance(title: str, snippet: str, raw_content: str) -> float:
    signals = 0
    if str(title or "").strip():
        signals += 1
    if str(snippet or "").strip():
        signals += 1
    if str(raw_content or "").strip():
        signals += 1
    if signals <= 0:
        return 0.0
    return round(min(1.0, 0.35 + signals * 0.2), 3)
