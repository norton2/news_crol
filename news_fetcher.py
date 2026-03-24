"""
이 코드의 역할: RSS 및 선택적 뉴스 API 소스에서 뉴스를 수집하고 공통 형식으로 정규화한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import requests
from dateutil import parser as date_parser


@dataclass(slots=True)
class NewsItem:
    title: str
    description: str
    url: str
    published_at: datetime
    source: str
    content: str = ""
    tags: set[str] = field(default_factory=set)
    is_urgent: bool = False
    matched_domains: list[str] = field(default_factory=list)
    urgent_reasons: list[str] = field(default_factory=list)

    def combined_text(self) -> str:
        return " ".join(
            part.strip()
            for part in [self.title, self.description, self.content]
            if part and part.strip()
        )


class BaseNewsSource(ABC):
    def __init__(self, source_name: str) -> None:
        self.source_name = source_name

    @abstractmethod
    def fetch(self) -> list[NewsItem]:
        raise NotImplementedError


class RSSNewsSource(BaseNewsSource):
    def __init__(self, source_name: str, feed_url: str, timeout: int = 15) -> None:
        super().__init__(source_name)
        self.feed_url = feed_url
        self.timeout = timeout

    def fetch(self) -> list[NewsItem]:
        response = requests.get(self.feed_url, timeout=self.timeout)
        response.raise_for_status()
        parsed_feed = feedparser.parse(response.content)

        items: list[NewsItem] = []
        for entry in parsed_feed.entries:
            title = (entry.get("title") or "").strip()
            description = (entry.get("summary") or entry.get("description") or "").strip()
            url = (entry.get("link") or "").strip()
            published_value = entry.get("published") or entry.get("updated")
            content_blocks = entry.get("content") or []
            content = " ".join(
                block.get("value", "").strip()
                for block in content_blocks
                if isinstance(block, dict)
            )

            if not title or not url:
                continue

            items.append(
                NewsItem(
                    title=title,
                    description=description,
                    url=url,
                    published_at=_parse_datetime(published_value),
                    source=self.source_name,
                    content=content,
                )
            )

        return items


class NewsAPISource(BaseNewsSource):
    def __init__(
        self,
        source_name: str,
        api_key: str,
        query: str,
        language: str = "en",
        timeout: int = 15,
    ) -> None:
        super().__init__(source_name)
        self.api_key = api_key
        self.query = query
        self.language = language
        self.timeout = timeout

    def fetch(self) -> list[NewsItem]:
        if not self.api_key:
            return []

        response = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": self.query,
                "language": self.language,
                "sortBy": "publishedAt",
                "pageSize": 50,
                "apiKey": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        items: list[NewsItem] = []
        for article in payload.get("articles", []):
            title = (article.get("title") or "").strip()
            description = (article.get("description") or "").strip()
            content = (article.get("content") or "").strip()
            url = (article.get("url") or "").strip()
            source_name = (article.get("source") or {}).get("name") or self.source_name

            if not title or not url:
                continue

            items.append(
                NewsItem(
                    title=title,
                    description=description,
                    url=url,
                    published_at=_parse_datetime(article.get("publishedAt")),
                    source=source_name,
                    content=content,
                )
            )

        return items


class NewsFetcher:
    def __init__(self, sources: Iterable[BaseNewsSource]) -> None:
        self.sources = list(sources)

    def fetch_all(self) -> list[NewsItem]:
        collected: list[NewsItem] = []
        for source in self.sources:
            try:
                collected.extend(source.fetch())
            except requests.RequestException as error:
                print(f"[fetcher] failed to fetch {source.source_name}: {error}")
            except Exception as error:
                print(f"[fetcher] unexpected error from {source.source_name}: {error}")

        return collected


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)

    try:
        parsed = date_parser.parse(value)
    except (ValueError, TypeError, OverflowError):
        return datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)