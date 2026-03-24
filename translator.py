"""
이 코드의 역할: 뉴스 제목과 요약을 한국어로 번역한다.
googletrans를 우선 사용하되, Python 3.13 호환성 문제 등으로 실패하면
Google 번역 공개 엔드포인트를 직접 호출하는 방식으로 안전하게 동작한다.
"""

from __future__ import annotations

import re

import requests


class NewsTranslator:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._translator = None
        self._use_http_fallback = False
        self._cache: dict[str, str | None] = {}

        if not enabled:
            return

        try:
            from googletrans import Translator  # type: ignore[import]

            self._translator = Translator()
        except ImportError as error:
            self._use_http_fallback = True
            print(f"[translator] googletrans 사용 불가 → HTTP 번역 fallback 사용: {error}")
        except Exception as error:
            self._use_http_fallback = True
            print(f"[translator] 초기화 실패 → HTTP 번역 fallback 사용: {error}")

    def translate_to_korean(self, text: str) -> str | None:
        normalized = " ".join(text.split())
        if not normalized:
            return None

        if normalized in self._cache:
            return self._cache[normalized]

        if self._looks_korean(normalized):
            self._cache[normalized] = None
            return None

        result = None
        if self._translator is not None:
            try:
                translated = self._translator.translate(normalized, dest="ko")
                result = " ".join((translated.text or "").split())
            except Exception as error:
                print(f"[translator] googletrans 번역 실패, HTTP fallback 시도: {error}")

        if result is None and self._use_http_fallback:
            result = self._translate_via_http(normalized)

        if not result or result == normalized:
            result = None

        self._cache[normalized] = result
        return result

    @staticmethod
    def _looks_korean(text: str) -> bool:
        return bool(re.search(r"[가-힣]", text))

    @staticmethod
    def _translate_via_http(text: str) -> str | None:
        try:
            response = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={
                    "client": "gtx",
                    "sl": "auto",
                    "tl": "ko",
                    "dt": "t",
                    "q": text,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            translated_chunks = payload[0] if payload and isinstance(payload, list) else []
            translated_text = "".join(
                chunk[0] for chunk in translated_chunks if isinstance(chunk, list) and chunk
            )
            return " ".join(translated_text.split()) or None
        except Exception as error:
            print(f"[translator] HTTP 번역 실패: {error}")
            return None