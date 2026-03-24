"""
이 코드의 역할: 최근 전송한 뉴스 상태를 로컬 파일 또는 Upstash Redis에 저장하고 복원한다.
GitHub Actions에서는 Upstash Redis를 사용해 실행 간 상태를 유지하고,
로컬에서는 파일 기반 저장소를 fallback으로 사용한다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import requests

from news_fetcher import NewsItem


class StateStore(Protocol):
    def load_recent_items(self, max_age_minutes: int = 30) -> list[NewsItem]:
        raise NotImplementedError

    def save_recent_items(self, items: list[NewsItem], max_items: int = 200) -> None:
        raise NotImplementedError


class FileStateStore:
    def __init__(self, state_path: str) -> None:
        self.state_path = Path(state_path)

    def load_recent_items(self, max_age_minutes: int = 30) -> list[NewsItem]:
        if not self.state_path.exists():
            return []

        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        return _restore_recent_items(payload, max_age_minutes=max_age_minutes)

    def save_recent_items(self, items: list[NewsItem], max_items: int = 200) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        serialized_payload = _serialize_recent_items(items, max_items=max_items)
        self.state_path.write_text(
            json.dumps(serialized_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class UpstashRedisStateStore:
    def __init__(
        self,
        rest_url: str,
        rest_token: str,
        redis_key: str,
        ttl_seconds: int = 172800,
        timeout: int = 15,
    ) -> None:
        self.rest_url = rest_url.rstrip("/")
        self.rest_token = rest_token
        self.redis_key = redis_key
        self.ttl_seconds = ttl_seconds
        self.timeout = timeout

    def load_recent_items(self, max_age_minutes: int = 30) -> list[NewsItem]:
        try:
            response = self._execute(["GET", self.redis_key])
        except Exception as error:
            print(f"[state] Upstash load failed: {error}")
            return []

        raw_value = response.get("result")
        if not raw_value:
            return []

        try:
            payload = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError) as error:
            print(f"[state] Upstash payload parse failed: {error}")
            return []

        return _restore_recent_items(payload, max_age_minutes=max_age_minutes)

    def save_recent_items(self, items: list[NewsItem], max_items: int = 200) -> None:
        payload = _serialize_recent_items(items, max_items=max_items)
        try:
            self._execute(["SETEX", self.redis_key, self.ttl_seconds, json.dumps(payload, ensure_ascii=False)])
        except Exception as error:
            print(f"[state] Upstash save failed: {error}")

    def _execute(self, command: list[object]) -> dict:
        response = requests.post(
            self.rest_url,
            headers={
                "Authorization": f"Bearer {self.rest_token}",
                "Content-Type": "application/json",
            },
            json=command,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload


class CompositeStateStore:
    def __init__(self, primary: StateStore, secondary: StateStore) -> None:
        self.primary = primary
        self.secondary = secondary

    def load_recent_items(self, max_age_minutes: int = 30) -> list[NewsItem]:
        primary_items = self.primary.load_recent_items(max_age_minutes=max_age_minutes)
        if primary_items:
            return primary_items
        return self.secondary.load_recent_items(max_age_minutes=max_age_minutes)

    def save_recent_items(self, items: list[NewsItem], max_items: int = 200) -> None:
        self.primary.save_recent_items(items, max_items=max_items)
        self.secondary.save_recent_items(items, max_items=max_items)


def create_state_store() -> StateStore:
    file_store = FileStateStore(state_path=".runtime/news_state.json")

    rest_url = _env("UPSTASH_REDIS_REST_URL")
    rest_token = _env("UPSTASH_REDIS_REST_TOKEN")
    redis_key = _env("UPSTASH_REDIS_STATE_KEY", default="telegram_news_pipeline_state")
    ttl_seconds = int(_env("UPSTASH_REDIS_TTL_SECONDS", default="172800"))

    if not rest_url or not rest_token:
        print("[state] Using local file state store")
        return file_store

    print("[state] Using Upstash Redis state store with local fallback")
    upstash_store = UpstashRedisStateStore(
        rest_url=rest_url,
        rest_token=rest_token,
        redis_key=redis_key,
        ttl_seconds=ttl_seconds,
    )
    return CompositeStateStore(primary=upstash_store, secondary=file_store)


def _restore_recent_items(payload: dict, max_age_minutes: int) -> list[NewsItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    restored: list[NewsItem] = []
    for item in payload.get("recent_items", []):
        try:
            published_at = datetime.fromisoformat(item["published_at"])
        except (KeyError, TypeError, ValueError):
            continue

        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        if published_at < cutoff:
            continue

        restored.append(
            NewsItem(
                title=item.get("title", ""),
                description=item.get("description", ""),
                url=item.get("url", ""),
                published_at=published_at,
                source=item.get("source", "unknown"),
                content=item.get("content", ""),
                tags=set(item.get("tags", [])),
                is_urgent=bool(item.get("is_urgent", False)),
                matched_domains=list(item.get("matched_domains", [])),
                urgent_reasons=list(item.get("urgent_reasons", [])),
            )
        )
    return restored


def _serialize_recent_items(items: list[NewsItem], max_items: int) -> dict:
    serializable_items = []
    for item in sorted(items, key=lambda news: news.published_at, reverse=True)[:max_items]:
        payload = asdict(item)
        payload["published_at"] = item.published_at.isoformat()
        payload["tags"] = sorted(item.tags)
        serializable_items.append(payload)
    return {"recent_items": serializable_items}


def _env(name: str, default: str = "") -> str:
    import os

    return os.getenv(name, default)