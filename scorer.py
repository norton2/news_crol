"""
이 코드의 역할: 필터링된 뉴스에 0~100 중요도 점수를 부여하고 1/2/3 티어로 분류한다.
기본값은 완전 무료인 규칙 기반 스코어링이며,
GEMINI_API_KEY가 설정된 경우 Tier 1 후보 항목에 한해 Gemini 1.5 Flash(무료)로 검증한다.

점수 기준:
  Tier 1 (긴급속보): 80 이상
  Tier 2 (중요뉴스):  50 ~ 79
  Tier 3 (일반뉴스):  0  ~ 49
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from news_fetcher import NewsItem

TIER1_MIN: float = 80.0
TIER2_MIN: float = 50.0

_BREAKING_TITLE: frozenset[str] = frozenset({"속보", "breaking", "urgent", "flash"})
_BREAKING_BODY: frozenset[str] = frozenset({"속보", "breaking", "urgent"})
_MILITARY_KW: frozenset[str] = frozenset({
    "전쟁", "공습", "미사일", "핵", "군사훈련", "무기", "공격",
    "war", "airstrike", "missile", "nuclear", "drill", "attack", "strike",
})
_COUNTRY_KW: frozenset[str] = frozenset({
    "미국", "중국", "러시아", "북한", "이란",
    "us", "china", "russia", "north korea", "iran",
    "ukraine", "israel", "taiwan", "nato",
})
_TRUSTED_SOURCES: frozenset[str] = frozenset({
    "BBC World", "Reuters World", "Reuters Business",
    "AP Top News", "Yonhap World", "Yonhap Economy",
})


@dataclass(slots=True)
class ScoredItem:
    item: NewsItem
    score: float
    tier: int
    reasons: list[str] = field(default_factory=list)


class NewsScorer:
    def __init__(self, gemini_api_key: str = "") -> None:
        self._gemini_model: Optional[Any] = None
        if gemini_api_key:
            try:
                import google.generativeai as genai  # type: ignore[import]
                genai.configure(api_key=gemini_api_key)
                self._gemini_model = genai.GenerativeModel("gemini-1.5-flash")
                print("[scorer] Gemini 1.5 Flash 활성화 (Tier 1 검증에 사용)")
            except ImportError:
                print("[scorer] google-generativeai 미설치 → 규칙 기반 스코어링만 사용")
            except Exception as error:
                print(f"[scorer] Gemini 초기화 실패: {error}")

    def score_all(self, items: list[NewsItem]) -> list[ScoredItem]:
        scored: list[ScoredItem] = []
        for item in items:
            si = self._score_rule_based(item)
            # Gemini는 Tier 1 후보(70점 이상)에만 호출해 무료 할당량(1,500회/일)을 절약
            if self._gemini_model and si.score >= 70:
                si = self._verify_with_gemini(si)
            scored.append(si)
        return scored

    # ------------------------------------------------------------------
    # 규칙 기반 스코어링 (완전 무료)
    # ------------------------------------------------------------------
    def _score_rule_based(self, item: NewsItem) -> ScoredItem:
        score: float = 0.0
        reasons: list[str] = []
        title_lower = item.title.lower()
        text_lower = item.combined_text().lower()

        # ① 속보 키워드: 제목에 있으면 +40, 본문에만 있으면 +20
        if any(kw in title_lower for kw in _BREAKING_TITLE):
            score += 40
            reasons.append("breaking-title")
        elif any(kw in text_lower for kw in _BREAKING_BODY):
            score += 20
            reasons.append("breaking-body")

        # ② 군사 + 국가명 동시 등장
        has_military = any(kw in text_lower for kw in _MILITARY_KW)
        has_country = any(kw in text_lower for kw in _COUNTRY_KW)
        if has_military and has_country:
            score += 30
            reasons.append("military+country")
        elif has_military:
            score += 15
            reasons.append("military")

        # ③ 복수 도메인 매칭
        num_domains = len(set(item.matched_domains))
        if num_domains >= 2:
            score += 20
            reasons.append(f"multi-domain:{num_domains}")
        elif num_domains == 1:
            score += 10
            reasons.append("single-domain")

        # ④ 키워드 버스트 감지 (filter.py 결과 활용)
        if any("burst" in r for r in item.urgent_reasons):
            score += 10
            reasons.append("burst")

        # ⑤ 최신성 보너스
        age = datetime.now(timezone.utc) - item.published_at
        if age < timedelta(hours=1):
            score += 10
            reasons.append("very-recent")
        elif age < timedelta(hours=3):
            score += 5
            reasons.append("recent")

        # ⑥ 신뢰 소스
        if item.source in _TRUSTED_SOURCES:
            score += 5
            reasons.append("trusted-source")

        score = min(score, 100.0)
        return ScoredItem(item=item, score=score, tier=_to_tier(score), reasons=reasons)

    # ------------------------------------------------------------------
    # Gemini 검증 (선택적, Tier 1 후보만)
    # ------------------------------------------------------------------
    def _verify_with_gemini(self, si: ScoredItem) -> ScoredItem:
        assert self._gemini_model is not None
        prompt = (
            "다음 뉴스가 긴급 속보(breaking news)인지 0~100 중요도 점수로만 답해. "
            "숫자 하나만 출력.\n"
            f"제목: {si.item.title}\n"
            f"요약: {si.item.description[:300]}"
        )
        try:
            response = self._gemini_model.generate_content(prompt)
            raw = "".join(c for c in response.text.strip() if c.isdigit() or c == ".")
            gemini_score = max(0.0, min(100.0, float(raw)))
            # 규칙 기반 60% + Gemini 40% 가중 평균
            blended = min(si.score * 0.6 + gemini_score * 0.4, 100.0)
            si.reasons.append(f"gemini:{gemini_score:.0f}")
            si.score = blended
            si.tier = _to_tier(blended)
        except Exception as error:
            print(f"[scorer] Gemini 호출 실패: {error}")
        return si


def _to_tier(score: float) -> int:
    if score >= TIER1_MIN:
        return 1
    if score >= TIER2_MIN:
        return 2
    return 3
