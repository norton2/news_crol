"""
이 코드의 역할: 수집된 뉴스 목록에서 URL과 제목 유사도를 기준으로 중복 기사를 제거한다.
"""

from __future__ import annotations

from typing import Iterable

from rapidfuzz import fuzz

from news_fetcher import NewsItem


class NewsDeduplicator:
    def __init__(self, title_similarity_threshold: int = 88) -> None:
        self.title_similarity_threshold = title_similarity_threshold

    def deduplicate(
        self,
        items: Iterable[NewsItem],
        already_sent: Iterable[NewsItem] | None = None,
    ) -> list[NewsItem]:
        """
        items: 이번 실행에서 수집·필터된 뉴스
        already_sent: 이전 실행에서 이미 전송한 뉴스 (재전송 방지용)
        """
        # 이전에 보낸 항목들로 seen 집합을 미리 채운다
        prev_items: list[NewsItem] = list(already_sent or [])
        seen_urls: set[str] = {
            self._normalize_url(item.url) for item in prev_items
        }
        unique_items: list[NewsItem] = []  # 이번 실행에서 새로 추가될 항목

        for item in sorted(items, key=lambda news: news.published_at, reverse=True):
            normalized_url = self._normalize_url(item.url)
            if normalized_url in seen_urls:
                continue

            # 이전 전송 목록 + 이번 실행 신규 목록 모두와 유사도 비교
            if self._is_similar_to_existing(item, prev_items + unique_items):
                continue

            seen_urls.add(normalized_url)
            unique_items.append(item)

        unique_items.sort(key=lambda news: (not news.is_urgent, news.published_at), reverse=False)
        return unique_items

    def _is_similar_to_existing(self, candidate: NewsItem, existing_items: Iterable[NewsItem]) -> bool:
        candidate_title = self._normalize_title(candidate.title)
        for existing in existing_items:
            score = fuzz.token_set_ratio(candidate_title, self._normalize_title(existing.title))
            if score >= self.title_similarity_threshold:
                return True
        return False

    @staticmethod
    def _normalize_url(url: str) -> str:
        return url.strip().rstrip("/")

    @staticmethod
    def _normalize_title(title: str) -> str:
        return " ".join(title.lower().split())