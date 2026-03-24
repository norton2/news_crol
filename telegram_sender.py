"""
이 코드의 역할: 필터링된 뉴스를 텔레그램 봇 API를 통해 채널 또는 그룹으로 전송한다.
티어별 포맷을 구분하여 Tier 1은 긴급 강조, Tier 2/3는 중요도에 맞는 형식으로 전송한다.
"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING, Iterable

import requests

from news_fetcher import NewsItem
from translator import NewsTranslator

if TYPE_CHECKING:
    from crawler_tiers import TierConfig


class TelegramSender:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        translator: NewsTranslator | None = None,
        timeout: int = 15,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.translator = translator
        self.timeout = timeout

    def send_items(self, items: Iterable[NewsItem]) -> None:
        if not self.bot_token or not self.chat_id:
            print("[telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing; skipping send")
            return

        for item in items:
            self._send_message(self._format_message(item))

    def send_tier_batch(self, items: list[NewsItem], config: "TierConfig") -> None:
        """티어 설정에 맞는 포맷으로 항목 목록을 전송한다."""
        if not self.bot_token or not self.chat_id:
            print("[telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing; skipping send")
            return

        header = f"{config.emoji} <b>[{config.name}]</b> {len(items)}건 수신"
        self._send_message(header)

        for item in items:
            self._send_message(self._format_tier_message(item, config))

    def _send_message(self, text: str) -> None:
        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _format_message(self, item: NewsItem) -> str:
        label = "🚨 <b>속보</b>" if item.is_urgent else "<b>일반 뉴스</b>"
        summary = item.description.strip() or item.content.strip() or "요약 없음"
        summary = " ".join(summary.split())
        short_summary = summary[:220] + "..." if len(summary) > 220 else summary
        translated_title = self._translate(item.title)
        translated_summary = self._translate(short_summary)
        domain_text = ", ".join(item.matched_domains) or "미분류"
        source_text = escape(item.source)

        lines = [
            label,
            f"<b>{escape(item.title)}</b>",
            self._translated_line(translated_title),
            f"분류: {escape(domain_text)} | 출처: {source_text}",
            escape(short_summary),
            self._translated_line(translated_summary),
            item.url,
        ]

        if item.is_urgent and item.urgent_reasons:
            lines.insert(3, f"사유: {escape(', '.join(item.urgent_reasons))}")

        return "\n".join(line for line in lines if line)

    def _format_tier_message(self, item: NewsItem, config: "TierConfig") -> str:
        summary = item.description.strip() or item.content.strip() or "요약 없음"
        summary = " ".join(summary.split())
        short_summary = summary[:220] + "..." if len(summary) > 220 else summary
        translated_title = self._translate(item.title)
        translated_summary = self._translate(short_summary)
        domain_text = ", ".join(item.matched_domains) or "미분류"

        lines = [
            f"{config.emoji} <b>{escape(item.title)}</b>",
            self._translated_line(translated_title),
            f"분류: {escape(domain_text)} | 출처: {escape(item.source)}",
            escape(short_summary),
            self._translated_line(translated_summary),
            item.url,
        ]

        return "\n".join(line for line in lines if line)

    def _translate(self, text: str) -> str | None:
        if not self.translator:
            return None
        return self.translator.translate_to_korean(text)

    @staticmethod
    def _translated_line(text: str | None) -> str:
        if not text:
            return ""
        return f"한글: {escape(text)}"