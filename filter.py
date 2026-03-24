"""
이 코드의 역할: 뉴스 본문과 제목을 기준으로 도메인 키워드를 필터링하고 긴급 뉴스를 분류한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from news_fetcher import NewsItem


@dataclass(slots=True)
class KeywordRule:
    domain: str
    any_keywords: set[str]
    all_keywords: set[str] | None = None


class NewsFilter:
    def __init__(
        self,
        rules: Iterable[KeywordRule],
        country_keywords: Iterable[str],
        urgent_keywords: Iterable[str],
        burst_window_minutes: int = 30,
    ) -> None:
        self.rules = list(rules)
        self.country_keywords = {keyword.lower() for keyword in country_keywords}
        self.urgent_keywords = {keyword.lower() for keyword in urgent_keywords}
        self.burst_window = timedelta(minutes=burst_window_minutes)

    def filter_items(
        self,
        items: Iterable[NewsItem],
        recent_items: Iterable[NewsItem] | None = None,
    ) -> list[NewsItem]:
        filtered_items: list[NewsItem] = []
        recent_items = list(recent_items or [])
        recent_keyword_counter = self._build_recent_keyword_counter(recent_items)

        for item in items:
            text = item.combined_text().lower()
            matched_domains: list[str] = []
            matched_keywords: set[str] = set()

            for rule in self.rules:
                any_hits = {keyword for keyword in rule.any_keywords if keyword.lower() in text}
                if not any_hits:
                    continue

                all_keywords = {keyword.lower() for keyword in (rule.all_keywords or set())}
                if all_keywords and not all(keyword in text for keyword in all_keywords):
                    continue

                matched_domains.append(rule.domain)
                matched_keywords.update(keyword.lower() for keyword in any_hits)

            if not matched_keywords:
                continue

            item.matched_domains = matched_domains
            item.tags.update(matched_keywords)
            item.is_urgent, item.urgent_reasons = self._classify_urgent(
                item=item,
                text=text,
                matched_keywords=matched_keywords,
                recent_keyword_counter=recent_keyword_counter,
            )
            filtered_items.append(item)

        return filtered_items

    def _classify_urgent(
        self,
        item: NewsItem,
        text: str,
        matched_keywords: set[str],
        recent_keyword_counter: Counter[str],
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []

        if any(keyword in text for keyword in self.urgent_keywords):
            reasons.append("breaking-keyword")

        burst_hits = [keyword for keyword in matched_keywords if recent_keyword_counter[keyword] >= 1]
        if burst_hits:
            reasons.append(f"keyword-burst:{','.join(sorted(burst_hits))}")

        military_domain = "군사" in item.matched_domains
        has_country = any(country in text for country in self.country_keywords)
        if military_domain and has_country:
            reasons.append("military-country-match")

        return bool(reasons), reasons

    def _build_recent_keyword_counter(self, recent_items: Iterable[NewsItem]) -> Counter[str]:
        counter: Counter[str] = Counter()
        now = datetime.now(timezone.utc)

        for item in recent_items:
            if now - item.published_at > self.burst_window:
                continue

            for keyword in item.tags:
                counter[keyword.lower()] += 1

        return counter


def default_rules() -> list[KeywordRule]:
    return [
        KeywordRule(
            domain="국제정세",
            any_keywords={
                "미국",
                "중국",
                "러시아",
                "북한",
                "이란",
                "eu",
                "nato",
                "외교",
                "제재",
                "us",
                "china",
                "russia",
                "north korea",
                "iran",
                "diplomacy",
                "sanction",
            },
        ),
        KeywordRule(
            domain="군사",
            any_keywords={
                "전쟁",
                "공습",
                "미사일",
                "핵",
                "군사훈련",
                "무기",
                "방어",
                "공격",
                "war",
                "airstrike",
                "missile",
                "nuclear",
                "drill",
                "weapon",
                "defense",
                "attack",
            },
        ),
        KeywordRule(
            domain="경제",
            any_keywords={
                "금리",
                "인플레이션",
                "경기침체",
                "gdp",
                "환율",
                "원유",
                "공급망",
                "interest rate",
                "inflation",
                "recession",
                "exchange rate",
                "oil",
                "supply chain",
            },
        ),
    ]


def default_country_keywords() -> set[str]:
    return {
        "미국",
        "중국",
        "러시아",
        "북한",
        "이란",
        "ukraine",
        "uk",
        "usa",
        "us",
        "china",
        "russia",
        "north korea",
        "iran",
        "israel",
        "taiwan",
        "eu",
    }


def default_urgent_keywords() -> set[str]:
    return {"속보", "breaking", "urgent"}