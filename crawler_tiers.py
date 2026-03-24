"""
이 코드의 역할: 중요도 점수 기반으로 3단계 티어 크롤러를 정의한다.
각 티어는 점수 구간과 최대 전송 수를 가지며, 해당 구간의 뉴스가 없으면 전송하지 않는다.

Tier 1 (긴급속보): score ≥ 80  → 전쟁/핵/속보 등 즉각 대응이 필요한 뉴스, 최대 3건
Tier 2 (중요뉴스): score 50~79 → 국제정세/군사/경제 주요 뉴스, 최대 7건
Tier 3 (일반뉴스): score  0~49 → 키워드 기반 필터링 통과 뉴스, 최대 10건
"""

from __future__ import annotations

from dataclasses import dataclass

from news_fetcher import NewsItem
from scorer import ScoredItem


@dataclass(frozen=True)
class TierConfig:
    tier: int
    name: str
    emoji: str
    min_score: float
    max_score: float
    max_send: int


TIER_CONFIGS: list[TierConfig] = [
    TierConfig(tier=1, name="긴급속보", emoji="🚨", min_score=80.0, max_score=100.0, max_send=3),
    TierConfig(tier=2, name="중요뉴스", emoji="📌", min_score=50.0, max_score=79.9, max_send=7),
    TierConfig(tier=3, name="일반뉴스", emoji="📰", min_score=0.0,  max_score=49.9, max_send=10),
]


class TierCrawler:
    """
    점수가 매겨진 뉴스 목록에서 자신의 구간에 해당하는 항목만 추려
    전송 대상 목록을 반환한다. 해당 항목이 없으면 빈 리스트를 반환한다.
    """

    def __init__(self, config: TierConfig) -> None:
        self.config = config

    def select(self, scored_items: list[ScoredItem]) -> list[NewsItem]:
        matched = [
            si for si in scored_items
            if self.config.min_score <= si.score <= self.config.max_score
        ]
        if not matched:
            return []
        matched.sort(key=lambda si: si.score, reverse=True)
        return [si.item for si in matched[: self.config.max_send]]
