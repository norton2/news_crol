"""
이 코드의 역할: 뉴스 수집, 필터링, 중복 제거, 텔레그램 전송을 순서대로 실행하는 메인 파이프라인 진입점이다.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from crawler_tiers import TIER_CONFIGS, TierCrawler
from deduplicator import NewsDeduplicator
from filter import NewsFilter, default_country_keywords, default_rules, default_urgent_keywords
from news_fetcher import NewsAPISource, NewsFetcher, NewsItem, RSSNewsSource
from scorer import NewsScorer
from state_store import create_state_store
from telegram_sender import TelegramSender
from translator import NewsTranslator


DEFAULT_RSS_SOURCES: tuple[tuple[str, str], ...] = (
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Reuters World", "https://feeds.reuters.com/Reuters/worldNews"),
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("AP Top News", "https://feeds.apnews.com/apf-topnews"),
    ("Yonhap World", "https://www.yna.co.kr/rss/international.xml"),
    ("Yonhap Economy", "https://www.yna.co.kr/rss/economy.xml"),
)

class TieredNewsPipeline:
    """
    [수집 → 필터링 → 중복 제거 → 중요도 스코어링 → 티어별 전송] 파이프라인.

    Tier 1 (긴급속보, score ≥ 80): 해당 뉴스 없으면 전송 스킵
    Tier 2 (중요뉴스,  score 50~79): 해당 뉴스 없으면 전송 스킵
    Tier 3 (일반뉴스,  score  0~49): 해당 뉴스 없으면 전송 스킵
    """

    def __init__(self) -> None:
        load_dotenv()

        self.fetch_window_minutes = int(os.getenv("FETCH_WINDOW_MINUTES", "60"))
        self.dedup_lookback_minutes = int(os.getenv("DEDUP_LOOKBACK_MINUTES", "1440"))
        self.state_max_items = int(os.getenv("STATE_MAX_ITEMS", "1000"))
        self.fetcher = NewsFetcher(self._build_sources())
        self.news_filter = NewsFilter(
            rules=default_rules(),
            country_keywords=default_country_keywords(),
            urgent_keywords=default_urgent_keywords(),
            burst_window_minutes=int(os.getenv("BURST_WINDOW_MINUTES", "30")),
        )
        self.deduplicator = NewsDeduplicator(
            title_similarity_threshold=int(os.getenv("TITLE_SIMILARITY_THRESHOLD", "88"))
        )
        self.scorer = NewsScorer(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        )
        self.translator = NewsTranslator(
            enabled=os.getenv("ENABLE_TRANSLATION", "true").lower() == "true"
        )
        self.sender = TelegramSender(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            translator=self.translator,
        )
        self.state_store = create_state_store()
        self.tier_crawlers = [TierCrawler(cfg) for cfg in TIER_CONFIGS]

    def run(self) -> None:
        # 1. 수집
        recent_items = self.state_store.load_recent_items(
            max_age_minutes=self.dedup_lookback_minutes
        )
        fetched_items = self.fetcher.fetch_all()
        print(f"[pipeline] 수집: {len(fetched_items)}건")
        fetched_items = self._limit_to_recent_items(fetched_items)
        print(f"[pipeline] 최근 {self.fetch_window_minutes}분 이내 기사: {len(fetched_items)}건")

        # 2. 키워드 필터링
        filtered_items = self.news_filter.filter_items(fetched_items, recent_items=recent_items)
        print(f"[pipeline] 필터 통과: {len(filtered_items)}건")

        # 3. 중복 제거 (이전 실행에서 이미 보낸 항목 제외)
        deduped_items = self.deduplicator.deduplicate(filtered_items, already_sent=recent_items)
        print(f"[pipeline] 중복 제거 후: {len(deduped_items)}건 (신규)")

        # 4. 중요도 스코어링
        scored_items = self.scorer.score_all(deduped_items)

        # 5. 티어별 선택 및 전송
        for crawler in self.tier_crawlers:
            items_to_send = crawler.select(scored_items)
            if items_to_send:
                print(f"[pipeline] Tier {crawler.config.tier} ({crawler.config.name}): {len(items_to_send)}건 전송")
                self.sender.send_tier_batch(items_to_send, crawler.config)
            else:
                print(f"[pipeline] Tier {crawler.config.tier} ({crawler.config.name}): 해당 뉴스 없음 - 전송 스킵")

        # 6. 상태 저장 (다음 실행 시 버스트 감지에 활용)
        self.state_store.save_recent_items(
            recent_items + deduped_items,
            max_items=self.state_max_items,
        )

    def _build_sources(self) -> list[RSSNewsSource | NewsAPISource]:
        sources: list[RSSNewsSource | NewsAPISource] = [
            RSSNewsSource(source_name=name, feed_url=url)
            for name, url in DEFAULT_RSS_SOURCES
        ]

        news_api_key = os.getenv("NEWSAPI_KEY", "")
        if news_api_key:
            sources.append(
                NewsAPISource(
                    source_name="NewsAPI",
                    api_key=news_api_key,
                    query=os.getenv(
                        "NEWSAPI_QUERY",
                        "geopolitics OR military OR economy OR inflation OR missile OR sanctions",
                    ),
                    language=os.getenv("NEWSAPI_LANGUAGE", "en"),
                )
            )

        return sources

    def _limit_to_recent_items(self, items: list[NewsItem]) -> list[NewsItem]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.fetch_window_minutes)
        return [item for item in items if item.published_at >= cutoff]


if __name__ == "__main__":
    TieredNewsPipeline().run()