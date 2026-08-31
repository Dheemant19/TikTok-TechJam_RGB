from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StorageConfig(StrictModel):
    database: Path
    journal_mode: str = "WAL"
    vector_backend: str = "auto"
    numpy_fallback_when_sqlite_vec_unavailable: bool = True


class CuratedSourceConfig(StrictModel):
    file: Path
    expected_paper_count: int = Field(ge=1, le=25)
    preserve_curated_notes: bool = True


class EmbeddingConfig(StrictModel):
    provider: str
    model: str
    revision: str
    dimensions: int = 384
    model_manifest: Path
    allow_initial_download: bool


class ProviderConfig(StrictModel):
    enabled: bool
    timeout_seconds: float | None = None
    requests_per_second: float | None = None
    retry_limit: int = Field(default=3, ge=0, le=3)
    api_key_env: str | None = None
    contact_email_env: str | None = None
    token_env: str | None = None
    endpoint_env: str | None = None


class ProvidersConfig(StrictModel):
    huggingface_papers: ProviderConfig
    github: ProviderConfig
    papers_with_code: ProviderConfig


class HTTPTransportConfig(StrictModel):
    enabled: bool
    host: str
    port: int = Field(ge=1, le=65535)


class TransportConfig(StrictModel):
    stdio: dict[str, bool]
    streamable_http: HTTPTransportConfig


class RetrievalConfig(StrictModel):
    reciprocal_rank_constant: int = Field(ge=1)
    curated_bank_share: float = Field(default=0.5, ge=0.0, le=1.0)
    cache_ttl_seconds: int = Field(ge=1)
    maximum_search_results: int = Field(ge=1)
    maximum_code_results: int = Field(ge=1)
    maximum_citation_results: int = Field(ge=1)
    maximum_research_card_evidence: int = Field(ge=1)


class SanitizerConfig(StrictModel):
    maximum_field_characters: int = Field(ge=100)
    quarantine_high_risk_records: bool = True
    remove_hidden_unicode: bool = True
    remove_hidden_html: bool = True
    store_fulltext_only_when_license_permits: bool = True


class IngestionConfig(StrictModel):
    queue_lease_seconds: int = Field(ge=1)
    scheduled_priority_areas: list[str]
    reject_retracted_works: bool = True
    maximum_automatic_documents: int = Field(ge=0)


class KnowledgeConfig(StrictModel):
    schema_version: int
    storage: StorageConfig
    curated_source: CuratedSourceConfig
    embedding: EmbeddingConfig
    providers: ProvidersConfig
    transport: TransportConfig
    retrieval: RetrievalConfig
    sanitizer: SanitizerConfig
    ingestion: IngestionConfig
    budget_config: Path


class CapConfig(StrictModel):
    outbound_provider_requests: int = Field(ge=0)
    returned_documents: int = Field(ge=0)
    response_characters: int = Field(ge=0)


class MCPBudgetConfig(StrictModel):
    per_session: CapConfig
    per_experiment: CapConfig


class BudgetDocument(StrictModel):
    schema_version: int
    azure: dict[str, Any]
    limits: dict[str, int | float]
    mcp: MCPBudgetConfig
    proxy_tier: dict[str, int | float]
    research_strategy: dict[str, Any]
    resource_sampling: dict[str, int | float]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_paths(config: KnowledgeConfig, root: Path) -> KnowledgeConfig:
    data = config.model_dump()
    for section, key in (
        ("storage", "database"),
        ("curated_source", "file"),
        ("embedding", "model_manifest"),
    ):
        path = Path(data[section][key])
        data[section][key] = path if path.is_absolute() else root / path
    budget_path = Path(data["budget_config"])
    data["budget_config"] = budget_path if budget_path.is_absolute() else root / budget_path
    return KnowledgeConfig.model_validate(data)


def load_knowledge_config(path: Path | str = "configs/knowledge/research.yaml") -> KnowledgeConfig:
    root = repository_root()
    load_dotenv(root / ".env", override=False)
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = root / config_path
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return _resolve_paths(KnowledgeConfig.model_validate(raw), root)


def load_budget_config(path: Path) -> BudgetDocument:
    return BudgetDocument.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def secret_from_env(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    return value if value else None
