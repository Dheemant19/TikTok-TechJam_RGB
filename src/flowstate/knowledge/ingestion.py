from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from flowstate.knowledge.config import KnowledgeConfig
from flowstate.knowledge.embeddings import EmbeddingProvider, vector_to_bytes
from flowstate.knowledge.models import (
    CodeRecord, CuratedManifest, CuratedPaper, IngestionReceipt, PaperIdentifiers,
    PaperRecord, ProviderWork,
)
from flowstate.knowledge.providers.github import GitHubProvider
from flowstate.knowledge.providers.huggingface_papers import HuggingFacePapersProvider
from flowstate.knowledge.sanitize import sanitize_text
from flowstate.knowledge.store import KnowledgeStore, utc_now


class ManifestValidationFailure(ValueError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        super().__init__("curated manifest validation failed")
        self.errors = errors


def validate_manifest(path: Path, expected_count: int | None = None) -> CuratedManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestValidationFailure([{"location": ["file"], "message": str(error)}]) from error
    try:
        manifest = CuratedManifest.model_validate(raw)
    except ValidationError as error:
        raise ManifestValidationFailure([
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]) from error
    if expected_count is not None and len(manifest.papers) != expected_count:
        raise ManifestValidationFailure([{
            "location": ["papers"],
            "message": f"expected exactly {expected_count} papers, found {len(manifest.papers)}",
            "type": "value_error.paper_count",
        }])
    return manifest


def normalized_work_key(paper_id: str, identifiers: PaperIdentifiers) -> str:
    stable = identifiers.stable_values()
    return f"{stable[0][0]}:{stable[0][1]}" if stable else f"paper_id:{paper_id.casefold()}"


def _hash_document(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


class IngestionService:
    def __init__(
        self, config: KnowledgeConfig, store: KnowledgeStore, embeddings: EmbeddingProvider,
        huggingface: HuggingFacePapersProvider | None = None, github: GitHubProvider | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.embeddings = embeddings
        self.huggingface = huggingface
        self.github = github

    def queue_curated(self, manifest: CuratedManifest) -> list[int]:
        return [self.store.enqueue(
            normalized_work_key(paper.paper_id, paper.identifiers), "curated",
            paper.model_dump_json(), requested_query=None,
        ) for paper in manifest.papers]

    async def ingest_curated(self, path: Path | None = None, *, enrich: bool = False, resolve_code: bool = False) -> list[IngestionReceipt]:
        manifest = validate_manifest(path or self.config.curated_source.file, self.config.curated_source.expected_paper_count)
        self.queue_curated(manifest)
        return await self.process_queue(enrich=enrich, resolve_code=resolve_code)

    async def ensure_curated_bank(self, path: Path | None = None) -> list[IngestionReceipt]:
        """Guarantee the curated, code-backed paper bank actually has its
        declared GitHub repositories resolved and verified.

        Hugging Face Papers discovery hard-checks for a linked repository, so
        it can genuinely satisfy this requirement too now -- but only the
        curated bank is guaranteed to be present before the very first
        research() call, since live discovery happens per-experiment.
        `ingest_curated()` defaults to `resolve_code=False` (a manual CLI
        opt-in) and idempotent re-ingestion resolves the repository BEFORE
        checking whether the paper's content is unchanged, so simply calling
        it here every run would cost ~2 GitHub requests per curated paper on
        every session start even after the first. Only papers still missing
        a verified repository are re-queued, so a fully-bootstrapped bank
        costs zero network calls on every later run.
        """
        if not self.github:
            return []
        manifest = validate_manifest(path or self.config.curated_source.file, self.config.curated_source.expected_paper_count)
        resolvable_ids = [paper.paper_id for paper in manifest.papers if paper.github_repositories]
        missing = self.store.papers_missing_verified_code(resolvable_ids)
        if not missing:
            return []
        pending = CuratedManifest(
            schema_version=manifest.schema_version,
            papers=[paper for paper in manifest.papers if paper.paper_id in missing],
        )
        self.queue_curated(pending)
        return await self.process_queue(resolve_code=True)

    async def enqueue_provider_records(self, records: list[ProviderWork], requested_query: str | None) -> None:
        for record in records:
            self.store.enqueue(
                normalized_work_key(record.paper_id, record.identifiers), record.source,
                record.model_dump_json(), requested_query=requested_query,
            )

    async def process_queue(self, *, enrich: bool = False, resolve_code: bool = False) -> list[IngestionReceipt]:
        self.store.resume_expired_leases(self.config.ingestion.queue_lease_seconds)
        receipts: list[IngestionReceipt] = []
        while item := self.store.lease_next():
            try:
                payload = json.loads(item.payload_json)
                if item.source == "curated":
                    paper = CuratedPaper.model_validate(payload)
                    receipt = await self._process_curated(item.queue_id, item.work_key, paper, enrich, resolve_code)
                else:
                    work = ProviderWork.model_validate(payload)
                    receipt = await self._process_provider(item.queue_id, item.work_key, work, resolve_code)
                receipts.append(receipt)
            except Exception as error:
                self.store.finish_queue(item.queue_id, "failed", str(error))
                event_id = self.store.append_ingestion_event(
                    item.queue_id, item.work_key, item.source, "failed", None, None,
                    {"error": str(error), "attempt": item.attempt_count},
                )
                receipts.append(IngestionReceipt(
                    receipt_id=event_id, paper_id=None, work_key=item.work_key, source=item.source,
                    outcome="failed", error=str(error),
                ))
        return receipts

    async def _process_curated(
        self, queue_id: int, work_key: str, source: CuratedPaper,
        enrich: bool, resolve_code: bool,
    ) -> IngestionReceipt:
        enriched: ProviderWork | None = None
        if enrich and self.huggingface:
            identifier = next((value for _, value in source.identifiers.stable_values()), None)
            if identifier:
                enriched = await self.huggingface.get_work(identifier)
        title = source.title
        authors = source.authors or (enriched.authors if enriched else [])
        abstract = source.abstract or (enriched.abstract if enriched else None)
        identifiers = PaperIdentifiers(
            doi=source.identifiers.doi or (enriched.identifiers.doi if enriched else None),
            arxiv_id=source.identifiers.arxiv_id or (enriched.identifiers.arxiv_id if enriched else None),
            openalex_id=source.identifiers.openalex_id or (enriched.identifiers.openalex_id if enriched else None),
        )
        code = await self._code_records(source.paper_id, source.github_repositories, resolve_code)
        record = self._paper_record(
            paper_id=source.paper_id, title=title, authors=authors, year=source.year,
            venue=source.venue or (enriched.venue if enriched else None), abstract=abstract,
            identifiers=identifiers, paper_url=str(source.paper_url) if source.paper_url else (enriched.paper_url if enriched else None),
            license_value=source.license or (enriched.license if enriched else None), retracted=bool(enriched.retracted if enriched else False),
            trust_tier="curated", priority_areas=source.priority_areas, relevance_notes=source.relevance_notes,
            keywords=source.keywords, code=code,
        )
        return self._persist(queue_id, work_key, "curated", record)

    async def _process_provider(self, queue_id: int, work_key: str, source: ProviderWork, resolve_code: bool) -> IngestionReceipt:
        if source.retracted and self.config.ingestion.reject_retracted_works:
            self.store.finish_queue(queue_id, "rejected", "retracted work")
            event_id = self.store.append_ingestion_event(
                queue_id, work_key, source.source, "rejected", source.paper_id, None,
                {"reason": "retracted work", "raw_response_hash": source.raw_response_hash},
            )
            return IngestionReceipt(
                receipt_id=event_id, paper_id=source.paper_id, work_key=work_key,
                source=source.source, outcome="rejected", error="retracted work",
            )
        code = await self._code_records(source.paper_id, source.github_repositories, resolve_code)
        record = self._paper_record(
            paper_id=source.paper_id, title=source.title, authors=source.authors, year=source.year,
            venue=source.venue, abstract=source.abstract, identifiers=source.identifiers,
            paper_url=source.paper_url, license_value=source.license, retracted=source.retracted,
            trust_tier="discovered", priority_areas=[], relevance_notes="Discovered from provider search.",
            keywords=[], code=code,
        )
        return self._persist(queue_id, work_key, source.source, record)

    async def _code_records(self, paper_id: str, repositories: list[Any], resolve: bool) -> list[CodeRecord]:
        records: list[CodeRecord] = []
        for repository in repositories:
            url = str(repository.url)
            if resolve and self.github:
                resolved = await self.github.resolve_repository(url, paper_id)
                if resolved:
                    records.append(resolved)
                    continue
            digest = _hash_document({"url": url, "commit": repository.commit, "license": repository.license})
            records.append(CodeRecord(
                repository_url=url, pinned_commit=repository.commit, license=repository.license,
                paper_id=paper_id, source_url=url, retrieved_at=utc_now(), content_hash=digest,
                verified=bool(repository.commit and repository.license),
            ))
        return records

    def _paper_record(
        self, *, paper_id: str, title: str, authors: list[str], year: int | None, venue: str | None,
        abstract: str | None, identifiers: PaperIdentifiers, paper_url: str | None, license_value: str | None,
        retracted: bool, trust_tier: str, priority_areas: list[str], relevance_notes: str,
        keywords: list[str], code: list[CodeRecord],
    ) -> PaperRecord:
        sanitized_title = sanitize_text(title, self.config.sanitizer.maximum_field_characters)
        sanitized_abstract = sanitize_text(abstract, self.config.sanitizer.maximum_field_characters)
        sanitized_notes = sanitize_text(relevance_notes, self.config.sanitizer.maximum_field_characters)
        flags = list(dict.fromkeys([*sanitized_title.flags, *sanitized_abstract.flags, *sanitized_notes.flags]))
        quarantined = any(item.quarantined for item in (sanitized_title, sanitized_abstract, sanitized_notes))
        content = {
            "paper_id": paper_id, "title": sanitized_title.text, "authors": authors, "year": year,
            "venue": venue, "abstract": sanitized_abstract.text or None, "identifiers": identifiers.model_dump(),
            "paper_url": paper_url, "license": license_value, "retracted": retracted, "trust_tier": trust_tier,
            "priority_areas": priority_areas, "relevance_notes": sanitized_notes.text, "keywords": keywords,
            "sanitizer_flags": flags, "quarantined": quarantined,
            "code": [{
                "repository_url": item.repository_url,
                "pinned_commit": item.pinned_commit,
                "license": item.license,
                "stars": item.stars,
                "topics": item.topics,
                "source_url": item.source_url,
            } for item in code],
        }
        content_hash = _hash_document(content)
        return PaperRecord(
            paper_id=paper_id, title=sanitized_title.text, authors=authors, year=year, venue=venue,
            abstract=sanitized_abstract.text or None, identifiers=identifiers, paper_url=paper_url,
            license=license_value, retracted=retracted, trust_tier=trust_tier,
            content_completeness="abstract" if sanitized_abstract.text else "metadata_only",
            priority_areas=priority_areas, relevance_notes=sanitized_notes.text, keywords=keywords,
            sanitizer_flags=flags, quarantined=quarantined, content_hash=content_hash,
            retrieved_at=datetime.now(UTC).isoformat(), code=code,
        )

    def _persist(self, queue_id: int, work_key: str, source: str, record: PaperRecord) -> IngestionReceipt:
        if record.quarantined:
            # Metadata stays reviewable, but prompt-facing retrieval excludes it.
            pass
        embedding_text = "\n".join(filter(None, [record.title, record.abstract, " ".join(record.keywords), " ".join(record.priority_areas), record.relevance_notes]))
        vector = self.embeddings.embed([embedding_text])[0]
        outcome = self.store.upsert_paper(
            record, vector_to_bytes(vector), self.embeddings.model_id,
            self.embeddings.revision, self.embeddings.dimensions,
        )
        self.store.finish_queue(queue_id, "succeeded")
        event_id = self.store.append_ingestion_event(
            queue_id, work_key, source, outcome, record.paper_id, record.content_hash,
            {"sanitizer_flags": record.sanitizer_flags, "quarantined": record.quarantined},
        )
        return IngestionReceipt(
            receipt_id=event_id, paper_id=record.paper_id, work_key=work_key,
            source=source, outcome=outcome, content_hash=record.content_hash,
        )

    async def ingest_scheduled(self, once: bool = True) -> list[IngestionReceipt]:
        if not self.huggingface:
            return []
        areas = self.config.ingestion.scheduled_priority_areas
        # HuggingFacePapersProvider.search() always returns at most one
        # record per call by design (see its docstring); discover this
        # area's fair share one call at a time instead of asking for a
        # single large batch, stopping early once an area runs out of
        # fresh, code-linked candidates.
        per_area_cap = max(1, self.config.ingestion.maximum_automatic_documents // max(len(areas), 1))
        discovered = 0
        for area in areas:
            query = area.replace("_", " ")
            for _ in range(per_area_cap):
                if discovered >= self.config.ingestion.maximum_automatic_documents:
                    break
                result = await self.huggingface.search(query, None, 1)
                if result.error or not result.records:
                    break
                await self.enqueue_provider_records(result.records, area)
                discovered += len(result.records)
        return await self.process_queue(resolve_code=True)
