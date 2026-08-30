from __future__ import annotations

import re

from rigor_rs.contract.models import RecoveryReceipt
from rigor_rs.ledger.workflow import new_id


class RecoveryController:
    RECIPES = {
        "syntax_import_config": ["minimal_code_repair", "rerun_tier_1"],
        "schema_data": ["expected_actual_schema_diff", "validated_adapter_or_config_correction"],
        "oom": ["halve_micro_batch", "enable_amp", "preserve_effective_batch_with_accumulation", "enable_checkpointing"],
        "timeout": ["profile_bottleneck", "reduce_evaluation_cadence_or_proxy_breadth"],
        "nan_divergence": ["restore_stable_settings", "check_labels_lr_precision_normalization"],
        "agent_output": ["bounded_structured_output_retry", "restore_stable_fallback"],
        "code_patch": ["regenerate_standard_git_diff", "abandon_redundant_contract"],
        "behavior_unchanged": ["activate_new_capability_in_config_or_callsites", "abandon_redundant_contract"],
        "transient_external": ["bounded_retry", "local_evidence_or_pause_planning"],
        "metric_regression": ["reject_without_technical_retry"],
        "infrastructure": ["bounded_restart", "restore_stable_fallback"],
    }

    @staticmethod
    def classify(error: str) -> str:
        value = error.casefold()
        if any(term in value for term in ("invalid json", "json_invalid", "eof while parsing", "structured output", "cited evidence not supplied")):
            return "agent_output"
        if any(term in value for term in (
            "patch contains no file changes", "git apply", "patch does not apply", "hunk header",
            "did not produce required artifacts", "main entrypoint may not have run",
        )):
            return "code_patch"
        if any(term in value for term in (
            "no measurable change in training behavior",
            "no measurable change in ranking behavior",
            "within-user validation ordering is identical",
            "inert patch",
        )):
            return "behavior_unchanged"
        if any(term in value for term in ("syntaxerror", "importerror", "modulenotfounderror", "config")):
            return "syntax_import_config"
        if any(term in value for term in ("schema", "column", "dtype", "row count", "taint")):
            return "schema_data"
        if any(term in value for term in ("out of memory", "cuda oom", "cublas_status_alloc_failed")):
            return "oom"
        if "timeout" in value or "timed out" in value:
            return "timeout"
        if any(term in value for term in ("nan", "inf", "diverge")):
            return "nan_divergence"
        if any(term in value for term in ("429", "503", "connection", "rate limit", "throttl", "azure", "openai", "openalex", "github")):
            return "transient_external"
        if "regression" in value:
            return "metric_regression"
        if any(term in value for term in (
            "typeerror:", "attributeerror:", "nameerror:", "keyerror:",
            "valueerror:", "runtimeerror:", "assertionerror:",
        )):
            return "code_patch"
        return "infrastructure"

    def recover(
        self, run_id: str, error: str, attempt: int, cap: int, category: str | None = None
    ) -> RecoveryReceipt:
        category = category if category in self.RECIPES else self.classify(error)
        recipe = self.RECIPES[category]
        if attempt > cap:
            action, result = "restore_stable_fallback", "recovery cap exhausted"
        else:
            action = recipe[min(attempt - 1, len(recipe) - 1)]
            result = "retry permitted" if category != "metric_regression" else "reject experiment"
        return RecoveryReceipt(
            recovery_id=new_id("recovery"), run_id=run_id, category=category,
            original_error=error, diagnosis=f"classified as {category}", action=action,
            attempt=attempt, result=result,
        )
