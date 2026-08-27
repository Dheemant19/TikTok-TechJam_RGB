from __future__ import annotations

import os
from pathlib import Path

from rigor_rs.knowledge.budgets import BudgetManager
from rigor_rs.knowledge.cache import QueryCache
from rigor_rs.knowledge.config import load_budget_config, load_knowledge_config, secret_from_env
from rigor_rs.knowledge.embeddings import FastEmbedProvider
from rigor_rs.knowledge.ingestion import IngestionService
from rigor_rs.knowledge.providers.github import GitHubProvider
from rigor_rs.knowledge.providers.openalex import OpenAlexProvider
from rigor_rs.knowledge.providers.papers_with_code import PapersWithCodeProvider
from rigor_rs.knowledge.retrieval import RetrievalService
from rigor_rs.knowledge.store import KnowledgeStore
from rigor_rs.ledger.mcp import MCPReceiptMirror


class KnowledgeRuntime:
    def __init__(self, config_path: Path | str = "configs/knowledge/research.yaml") -> None:
        self.config = load_knowledge_config(config_path)
        self.budget_config = load_budget_config(self.config.budget_config)
        self.store = KnowledgeStore(self.config.storage.database)
        self.store.migrate()
        self.embeddings = FastEmbedProvider(self.config.embedding)
        openalex_cfg = self.config.providers.openalex
        self.openalex = OpenAlexProvider(
            api_key=secret_from_env(openalex_cfg.api_key_env),
            mailto=secret_from_env(openalex_cfg.contact_email_env),
            timeout_seconds=openalex_cfg.timeout_seconds or 20,
            retry_limit=openalex_cfg.retry_limit,
        ) if openalex_cfg.enabled else None
        github_cfg = self.config.providers.github
        self.github = GitHubProvider(
            token=secret_from_env(github_cfg.token_env), timeout_seconds=github_cfg.timeout_seconds or 20,
            retry_limit=github_cfg.retry_limit,
        ) if github_cfg.enabled else None
        pwc_cfg = self.config.providers.papers_with_code
        self.papers_with_code = PapersWithCodeProvider(
            enabled=pwc_cfg.enabled, endpoint=secret_from_env(pwc_cfg.endpoint_env),
        )
        self.budgets = BudgetManager(self.store, self.budget_config.mcp)
        self.cache = QueryCache(self.store, self.config.retrieval.cache_ttl_seconds)
        self.ingestion = IngestionService(
            self.config, self.store, self.embeddings, openalex=self.openalex, github=self.github,
        )
        self.retrieval = RetrievalService(
            self.config, self.store, self.embeddings, self.budgets, self.cache, self.ingestion,
            openalex=self.openalex, github=self.github,
            session_id=os.getenv("RIGOR_RS_SESSION_ID", "standalone"),
            experiment_id=os.getenv("RIGOR_RS_EXPERIMENT_ID", "standalone"),
        )
        root = Path(__file__).resolve().parents[3]
        self.mirror = MCPReceiptMirror(root / "state/rigor.sqlite3")

    async def close(self) -> None:
        if self.openalex:
            await self.openalex.close()
        if self.github:
            await self.github.close()
