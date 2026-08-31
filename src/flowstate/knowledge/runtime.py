from __future__ import annotations

import os
from pathlib import Path

from flowstate.knowledge.budgets import BudgetManager
from flowstate.knowledge.cache import QueryCache
from flowstate.knowledge.config import load_budget_config, load_knowledge_config, secret_from_env
from flowstate.knowledge.embeddings import FastEmbedProvider
from flowstate.knowledge.ingestion import IngestionService
from flowstate.knowledge.providers.github import GitHubProvider
from flowstate.knowledge.providers.huggingface_papers import HuggingFacePapersProvider
from flowstate.knowledge.providers.papers_with_code import PapersWithCodeProvider
from flowstate.knowledge.retrieval import RetrievalService
from flowstate.knowledge.store import KnowledgeStore
from flowstate.ledger.mcp import MCPReceiptMirror


class KnowledgeRuntime:
    def __init__(self, config_path: Path | str = "configs/knowledge/research.yaml") -> None:
        self.config = load_knowledge_config(config_path)
        self.budget_config = load_budget_config(self.config.budget_config)
        self.store = KnowledgeStore(self.config.storage.database)
        self.store.migrate()
        self.embeddings = FastEmbedProvider(self.config.embedding)
        huggingface_cfg = self.config.providers.huggingface_papers
        self.huggingface = HuggingFacePapersProvider(
            timeout_seconds=huggingface_cfg.timeout_seconds or 20,
            retry_limit=huggingface_cfg.retry_limit,
        ) if huggingface_cfg.enabled else None
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
            self.config, self.store, self.embeddings, huggingface=self.huggingface, github=self.github,
        )
        self.retrieval = RetrievalService(
            self.config, self.store, self.embeddings, self.budgets, self.cache, self.ingestion,
            huggingface=self.huggingface, github=self.github,
            session_id=os.getenv("FLOWSTATE_SESSION_ID", "standalone"),
            experiment_id=os.getenv("FLOWSTATE_EXPERIMENT_ID", "standalone"),
        )
        root = Path(__file__).resolve().parents[3]
        self.mirror = MCPReceiptMirror(root / "state/flowstate.sqlite3")

    async def close(self) -> None:
        if self.huggingface:
            await self.huggingface.close()
        if self.github:
            await self.github.close()
