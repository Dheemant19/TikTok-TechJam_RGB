from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any

from pydantic import BaseModel

from flowstate.knowledge.store import KnowledgeStore


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip().casefold()


def _canonical(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple, set)):
        normalized = [_canonical(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def canonical_cache_key(
    provider: str, query: str, filters: Any, cutoff_date: date | str | None, result_limit: int,
) -> tuple[str, dict[str, Any]]:
    request = {
        "provider": provider,
        "normalized_query": normalize_query(query),
        "canonical_filters": _canonical(filters or {}),
        "cutoff_date": cutoff_date.isoformat() if isinstance(cutoff_date, date) else cutoff_date,
        "result_limit": result_limit,
    }
    raw = json.dumps(request, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(), request


class QueryCache:
    def __init__(self, store: KnowledgeStore, ttl_seconds: int) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> dict[str, Any] | None:
        return self.store.get_cache(key)

    def put(self, key: str, provider: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        self.store.put_cache(key, provider, request, response, self.ttl_seconds)
