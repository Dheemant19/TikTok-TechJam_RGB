from __future__ import annotations

from rigor_rs.contract.models import FrontierState, MetricReceipt


class FrontierManager:
    def __init__(self, epsilon: float, patience: int) -> None:
        self.epsilon = epsilon
        self.patience = patience

    def register_baseline(self, run_id: str) -> FrontierState:
        return FrontierState(validation_best=run_id, stable_fallback=run_id, accepted_parent=run_id)

    def decide(
        self, state: FrontierState, receipt: MetricReceipt, run_id: str,
        best_receipt: MetricReceipt, parent_receipt: MetricReceipt,
    ) -> tuple[FrontierState, str, bool]:
        if state.locked:
            raise RuntimeError("frontier is locked")
        if not receipt.comparable or receipt.scope != "validation":
            return state.model_copy(deep=True), "proxy_non_comparable", False
        updated = state.model_copy(deep=True)
        delta_parent = receipt.primary - parent_receipt.primary
        delta_best = receipt.primary - best_receipt.primary
        if delta_parent < 0:
            updated.rejected.append(run_id)
            decision = "reject"
        elif delta_best > self.epsilon:
            updated.validation_best = run_id
            updated.stable_fallback = run_id
            updated.accepted_parent = run_id
            updated.no_improvement_count = 0
            decision = "retain"
        else:
            updated.no_improvement_count += 1
            updated.rejected.append(run_id)
            decision = "ambiguous" if delta_best >= 0 else "reject"
        return updated, decision, updated.no_improvement_count >= self.patience

    @staticmethod
    def budget_stop(state: FrontierState) -> FrontierState:
        updated = state.model_copy(deep=True)
        updated.locked = True
        return updated
