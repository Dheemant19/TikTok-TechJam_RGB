from __future__ import annotations

import asyncio
import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from rigor_rs.knowledge.models import EvidenceFilters, ProviderResult, ProviderWork


class ProviderFailure(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, transient: bool = False, attempts: int = 1) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient
        self.attempts = attempts


@dataclass(frozen=True)
class JSONResponse:
    data: Any
    response_hash: str
    attempts: int
    bytes_received: int


class RetryingHTTPClient:
    def __init__(self, client: httpx.AsyncClient, retry_limit: int) -> None:
        self.client = client
        self.retry_limit = retry_limit

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
        attempts = 0
        while True:
            attempts += 1
            try:
                response = await self.client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if attempts > self.retry_limit:
                    raise ProviderFailure(str(error), transient=True, attempts=attempts) from error
                await asyncio.sleep(min(2 ** (attempts - 1), 4))
                continue
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempts > self.retry_limit:
                    raise ProviderFailure(
                        f"provider returned HTTP {response.status_code}", status_code=response.status_code,
                        transient=True, attempts=attempts,
                    )
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2 ** (attempts - 1), 4)
                except ValueError:
                    delay = min(2 ** (attempts - 1), 4)
                await asyncio.sleep(min(delay, 30))
                continue
            if response.status_code >= 400:
                raise ProviderFailure(
                    f"provider returned HTTP {response.status_code}", status_code=response.status_code,
                    transient=False, attempts=attempts,
                )
            raw = response.content
            try:
                data = response.json()
            except json.JSONDecodeError as error:
                raise ProviderFailure("provider returned malformed JSON", attempts=attempts) from error
            return JSONResponse(
                data=data,
                response_hash=hashlib.sha256(raw).hexdigest(),
                attempts=attempts,
                bytes_received=len(raw),
            )


class KnowledgeProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, filters: EvidenceFilters | None, limit: int) -> ProviderResult: ...

    @abstractmethod
    async def get_work(self, identifier: str) -> ProviderWork | None: ...

    async def get_citations(self, identifier: str, direction: str, limit: int) -> ProviderResult:
        return ProviderResult(error="provider_unavailable", error_message=f"{self.name} does not support citations")
