from __future__ import annotations

from rigor_rs.knowledge.config import MCPBudgetConfig
from rigor_rs.knowledge.models import CapUsage
from rigor_rs.knowledge.store import KnowledgeStore


class BudgetExceeded(RuntimeError):
    pass


class BudgetManager:
    def __init__(self, store: KnowledgeStore, config: MCPBudgetConfig) -> None:
        self.store = store
        self.config = config

    def usage(self, session_id: str, experiment_id: str) -> CapUsage:
        return CapUsage.model_validate(self.store.usage_totals(session_id, experiment_id))

    def _check(self, usage: CapUsage, *, outbound: int, documents: int, characters: int) -> None:
        session = self.config.per_session
        experiment = self.config.per_experiment
        checks = (
            (usage.session_provider_requests + outbound, session.outbound_provider_requests, "session provider-request"),
            (usage.session_documents + documents, session.returned_documents, "session document"),
            (usage.session_response_characters + characters, session.response_characters, "session response-character"),
            (usage.experiment_provider_requests + outbound, experiment.outbound_provider_requests, "experiment provider-request"),
            (usage.experiment_documents + documents, experiment.returned_documents, "experiment document"),
            (usage.experiment_response_characters + characters, experiment.response_characters, "experiment response-character"),
        )
        for projected, limit, label in checks:
            if projected > limit:
                raise BudgetExceeded(f"{label} cap exhausted ({projected}>{limit})")

    def consume(
        self, *, session_id: str, experiment_id: str, provider: str, request_id: str,
        outbound: int = 0, documents: int = 0, characters: int = 0,
        bytes_received: int = 0, errors: int = 0, retries: int = 0,
    ) -> CapUsage:
        usage = self.usage(session_id, experiment_id)
        self._check(usage, outbound=outbound, documents=documents, characters=characters)
        self.store.record_usage(
            session_id, experiment_id, provider, request_id,
            outbound_requests=outbound, documents_returned=documents,
            response_characters=characters, bytes_received=bytes_received,
            error_count=errors, retry_count=retries,
        )
        return self.usage(session_id, experiment_id)

    def ensure_outbound_available(self, session_id: str, experiment_id: str) -> None:
        self._check(self.usage(session_id, experiment_id), outbound=1, documents=0, characters=0)
