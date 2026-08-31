from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace

import pytest

import flowstate.agents.azure_foundry as azure_foundry
from flowstate.contract.models import ExperimentBudget, ExperimentContract, OutcomeBranches


def _research_contract(
    mechanism_id: str,
    method_family: str,
    *,
    iteration_strategy: str = "new_model",
) -> ExperimentContract:
    return ExperimentContract(
        experiment_id=f"E-{mechanism_id}",
        parent_run_id="B0",
        hypothesis=f"Test whether {mechanism_id} materially improves within-user ranking",
        observed_evidence_ids=[],
        primary_change=f"Implement {mechanism_id}",
        method_family=method_family,
        implementation_kind="architecture",
        mechanism_id=mechanism_id,
        iteration_strategy=iteration_strategy,
        decision_rationale="Prior validation evidence supports testing a materially different model.",
        allowed_files=[
            "src/flowstate/models/candidate.py",
            "src/flowstate/training/experiment.py",
            "configs/experiments/candidate.yaml",
        ],
        prohibited_files=[],
        predicted_gauc_direction="up",
        predicted_ndcg_at_5_direction="up",
        falsifiers=["Primary score does not improve"],
        outcome_branches=OutcomeBranches(success="retain", ambiguous="confirm", regression="reject"),
        comparator_run_id="B0",
        minimum_primary_improvement=0.002,
        guardrails=["official evaluator"],
        budget=ExperimentBudget(
            wall_seconds=60,
            gpu_hours=0,
            bedrock_input_tokens=1_000,
            bedrock_output_tokens=1_000,
        ),
        fallback_run_id="B0",
        recovery_attempt_limit=2,
    )


def test_model_output_limit_uses_profile_and_remaining_budget(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")
    captured = []

    class FakeChatModel:
        def __init__(self, **arguments):
            captured.append(arguments)
            self.profile = (
                {"max_output_tokens": 128_000}
                if arguments["model"] == "research-model"
                else {}
            )

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(azure_foundry, "AzureAIOpenAIApiChatModel", FakeChatModel)

    factory._chat(factory.config.research_agent, remaining_output_tokens=5_000)
    assert captured[-1]["max_tokens"] == 5_000
    assert captured[-1]["reasoning_effort"] == "high"

    captured.clear()
    factory._chat(factory.config.research_agent, remaining_output_tokens=200_000)
    assert captured[-1]["max_tokens"] == 128_000

    captured.clear()
    factory._chat(factory.config.code_recovery_agent, remaining_output_tokens=5_000)
    assert "max_tokens" not in captured[-1]

    with pytest.raises(RuntimeError, match="budget is exhausted"):
        factory._chat(factory.config.research_agent, remaining_output_tokens=0)


def test_file_replacements_generate_valid_unified_diff() -> None:
    draft = azure_foundry.FileReplacementProposal(
        replacements=[
            azure_foundry.FileReplacement(
                path="model.py",
                content="LOSS = 'bpr'\n",
            )
        ],
        tests=["pytest -q tests/test_model.py"],
        explanation="align the loss",
    )

    proposal = azure_foundry.AzureAgentFactory._build_patch(
        SimpleNamespace(allowed_files=["model.py"]),
        {"model.py": "LOSS = 'bce'\n"},
        draft,
    )

    assert "+++ b/model.py" in proposal.unified_diff
    assert "@@ -1 +1 @@" in proposal.unified_diff
    assert "-LOSS = 'bce'" in proposal.unified_diff
    assert "new file mode" not in proposal.unified_diff
    assert "+LOSS = 'bpr'" in proposal.unified_diff



@pytest.mark.asyncio
async def test_code_agent_is_explicit_when_reference_code_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")
    captured: list[object] = []

    class FakeRunnable:
        async def ainvoke(self, prompt):
            captured.extend(prompt)
            return {
                "parsed": azure_foundry.FileReplacementProposal(
                    replacements=[azure_foundry.FileReplacement(path="model.py", content="LOSS = 'bpr'\n")],
                    explanation="align loss",
                ),
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1}),
            }

    class FakeChat:
        def with_structured_output(self, *_args, **_kwargs):
            return FakeRunnable()

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(factory, "_chat", lambda *_args, **_kwargs: FakeChat())
    experiment = SimpleNamespace(
        allowed_files=["model.py"],
        model_dump=lambda mode: {"experiment_id": "E1"},
    )

    await factory.propose_patch(
        experiment,
        {
            "source_context": {"model.py": "LOSS = 'bce'\n"},
            "reference_code_available": False,
        },
    )

    assert "no compatible implementation was found" in captured[0].content
    request = json.loads(captured[1].content)
    assert request["reference_code_available"] is False
    assert "one hard 600-second wall-clock budget" in captured[0].content
    assert "infeasible_reason" in captured[0].content
    assert request["code_writing_seconds_remaining"] is None
    assert request["execution_constraints"] == {}


@pytest.mark.asyncio
async def test_research_agent_receives_execution_limits_and_timeout_history(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")
    captured: list[object] = []

    class FakeRunnable:
        async def ainvoke(self, prompt):
            captured.extend(prompt)
            return {
                "parsed": _research_contract("dcnv2_cross_network", "dcnv2"),
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1}),
            }

    class FakeChat:
        def with_structured_output(self, *_args, **_kwargs):
            return FakeRunnable()

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(factory, "_chat", lambda *_args, **_kwargs: FakeChat())
    timeout_run = {
        "experiment_id": "E1",
        "hypothesis": "Build a complete sequence transformer",
        "primary_change": "Add SASRec",
        "outcome": "abandoned_after_code_timeout",
        "failure_category": "code_stage_timeout",
        "failure_summary": "Code Agent exceeded the 600-second code-writing limit",
    }
    execution_constraints = {
        "code_writing_wall_seconds": 600,
        "fast_proxy_rows": 100_000,
        "fast_proxy_wall_seconds": 600,
    }

    await factory.research(
        {
            "challenge": {},
            "profile": {},
            "runs": [timeout_run],
            "frontier": {},
            "remaining_budget": {
                "experiments": 2,
                "bedrock_input_tokens": 10_000,
                "bedrock_output_tokens": 10_000,
            },
            "execution_constraints": execution_constraints,
            "evidence": [],
            "allowed_files": ["model.py"],
            "prohibited_files": [],
            "fallback_run_id": "B0",
        }
    )

    assert "implementation contract for one Code Agent call" in captured[0].content
    assert "`code_stage_timeout` or `experiment_scope` is direct evidence" in captured[0].content
    assert "After two consecutive code timeouts" in captured[0].content
    request = json.loads(captured[1].content)
    assert request["runs"] == [timeout_run]
    assert request["execution_constraints"] == execution_constraints
    assert request["research_diversity_policy"] == {}


@pytest.mark.asyncio
async def test_research_agent_retries_duplicate_inside_one_call(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")
    responses = [
        _research_contract("fm_soft_rank_ndcg5", "factorization_machine"),
        _research_contract("din_history_bpr", "din"),
    ]
    prompts: list[list[object]] = []

    class FakeRunnable:
        async def ainvoke(self, prompt):
            prompts.append(prompt)
            parsed = responses.pop(0)
            return {
                "parsed": parsed,
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 3, "output_tokens": 2}),
            }

    class FakeChat:
        def with_structured_output(self, *_args, **_kwargs):
            return FakeRunnable()

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(factory, "_chat", lambda *_args, **_kwargs: FakeChat())
    result = await factory.research(
        {
            "challenge": {},
            "profile": {},
            "runs": [],
            "frontier": {},
            "remaining_budget": {
                "experiments": 2,
                "bedrock_input_tokens": 10_000,
                "bedrock_output_tokens": 10_000,
            },
            "execution_constraints": {
                "code_writing_wall_seconds": 600,
                "fast_proxy_rows": 100_000,
                "fast_proxy_wall_seconds": 600,
            },
            "evidence": [],
            "allowed_files": ["model.py"],
            "prohibited_files": [],
            "fallback_run_id": "B0",
            "research_diversity_policy": {
                "forbidden_mechanism_ids": ["fm_soft_rank_ndcg5"],
                "forbidden_rejected_mechanism_ids": ["fm_soft_rank_ndcg5"],
                "fm_family_names": ["factorization_machine", "deepfm"],
                "required_model_scope": "non_fm",
                "research_duplicate_retry_limit": 2,
            },
        }
    )

    assert result.value.mechanism_id == "din_history_bpr"
    assert result.usage.input_tokens == 6
    assert result.usage.output_tokens == 4
    assert len(prompts) == 2
    assert "rejected before orchestration" in prompts[1][-1].content


@pytest.mark.asyncio
async def test_research_agent_corrects_unavailable_ensemble_before_orchestration(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")
    invalid_ensemble = _research_contract("single_model_blend", "ensemble").model_copy(update={
        "implementation_kind": "ensemble",
        "allowed_files": [
            "src/flowstate/training/experiment.py",
            "configs/experiments/candidate.yaml",
        ],
    })
    responses = [
        invalid_ensemble,
        _research_contract("sasrec_history_bpr", "sasrec"),
    ]
    prompts: list[list[object]] = []

    class FakeRunnable:
        async def ainvoke(self, prompt):
            prompts.append(prompt)
            return {
                "parsed": responses.pop(0),
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 2, "output_tokens": 1}),
            }

    class FakeChat:
        def with_structured_output(self, *_args, **_kwargs):
            return FakeRunnable()

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(factory, "_chat", lambda *_args, **_kwargs: FakeChat())
    result = await factory.research(
        {
            "challenge": {},
            "profile": {},
            "runs": [],
            "frontier": {},
            "remaining_budget": {
                "experiments": 2,
                "bedrock_input_tokens": 10_000,
                "bedrock_output_tokens": 10_000,
            },
            "execution_constraints": {
                "code_writing_wall_seconds": 600,
                "fast_proxy_rows": 100_000,
                "fast_proxy_wall_seconds": 600,
            },
            "evidence": [],
            "allowed_files": [
                "src/flowstate/models/candidate.py",
                "src/flowstate/training/experiment.py",
                "configs/experiments/candidate.yaml",
            ],
            "prohibited_files": [],
            "fallback_run_id": "B0",
            "research_diversity_policy": {
                "forbidden_mechanism_ids": [],
                "fm_family_names": ["factorization_machine", "deepfm"],
                "required_model_scope": "non_fm",
                "research_duplicate_retry_limit": 2,
                "ensemble_allowed": False,
                "ensemble_candidates": [{"method_family": "mmoe", "run_id": "E2"}],
                "minimum_eligible_models_for_ensemble": 2,
            },
        }
    )

    assert result.value.mechanism_id == "sasrec_history_bpr"
    assert len(prompts) == 2
    assert "only 1 currently qualify" in prompts[1][-1].content
    assert "must include a model implementation file" in prompts[1][-1].content



def test_research_contract_rejects_ambiguous_run_as_new_model_parent() -> None:
    contract = _research_contract("next_sequence_model", "sasrec").model_copy(
        update={"parent_run_id": "run-ambiguous"}
    )
    policy = {
        "accepted_parent_run_id": "B0",
        "allowed_new_model_parent_run_ids": ["B0"],
        "ensemble_allowed": False,
    }

    violations = azure_foundry.AzureAgentFactory._research_contract_violations(
        contract,
        policy,
    )

    assert any(
        "new_model parent_run_id must be one of ['B0']" in violation
        for violation in violations
    )
    valid = contract.model_copy(update={"parent_run_id": "B0"})
    assert not any(
        "parent_run_id" in violation
        for violation in azure_foundry.AzureAgentFactory._research_contract_violations(
            valid,
            policy,
        )
    )

def test_code_agent_can_reject_an_oversized_immutable_contract() -> None:
    proposal = azure_foundry.FileReplacementProposal(
        explanation="The contract requires a new data pipeline and full transformer.",
        infeasible_reason="Cannot implement and wire the requested pipeline inside 600 seconds.",
    )

    assert proposal.replacements == []
    assert proposal.infeasible_reason


@pytest.mark.asyncio
async def test_code_agent_surfaces_infeasible_contract_before_patch_build(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://example.invalid/openai/v1")
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_FOUNDRY_API_VERSION", "v1")
    monkeypatch.setenv("AZURE_RESEARCH_MODEL_DEPLOYMENT", "research-model")
    monkeypatch.setenv("AZURE_CODE_MODEL_DEPLOYMENT", "code-model")

    class FakeRunnable:
        async def ainvoke(self, _prompt):
            return {
                "parsed": azure_foundry.FileReplacementProposal(
                    explanation="The requested full pipeline cannot fit.",
                    infeasible_reason="Requires new preprocessing, architecture, and training integration.",
                ),
                "raw": SimpleNamespace(usage_metadata={"input_tokens": 1, "output_tokens": 1}),
            }

    class FakeChat:
        def with_structured_output(self, *_args, **_kwargs):
            return FakeRunnable()

    factory = azure_foundry.AzureAgentFactory()
    monkeypatch.setattr(factory, "_chat", lambda *_args, **_kwargs: FakeChat())
    experiment = SimpleNamespace(
        allowed_files=["model.py"],
        model_dump=lambda mode: {"experiment_id": "E-large"},
    )

    with pytest.raises(azure_foundry.ExperimentScopeError, match="new preprocessing"):
        await factory.propose_patch(
            experiment,
            {
                "source_context": {"model.py": "LOSS = 'bce'\n"},
                "reference_code_available": True,
                "code_writing_seconds_remaining": 540,
            },
        )

@pytest.mark.asyncio
async def test_invoke_raises_on_hung_call_instead_of_blocking_forever(monkeypatch) -> None:
    config = azure_foundry.AgentConfig(
        model_deployment_env="AZURE_RESEARCH_MODEL_DEPLOYMENT",
        temperature=0,
        timeout_seconds=180,
        transient_retry_limit=2,
    )

    class HungRunnable:
        async def ainvoke(self, _prompt):
            await asyncio.sleep(3600)

    async def fake_wait_for(coro, timeout):
        # Real hang scenario: assert the outer bound covers every internal SDK
        # retry (timeout_seconds * (transient_retry_limit + 1) + margin), then
        # simulate the timeout firing without actually sleeping in the test.
        assert timeout == 180 * 3 + 30
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(azure_foundry.asyncio, "wait_for", fake_wait_for)

    with pytest.raises(TimeoutError, match="did not respond within"):
        await azure_foundry.AzureAgentFactory._invoke(HungRunnable(), [], config)


def test_hung_call_timeout_classifies_as_transient_external_for_bounded_retry() -> None:
    from flowstate.recovery.controller import RecoveryController

    receipt = RecoveryController().recover(
        "run",
        "Azure Foundry call to AZURE_RESEARCH_MODEL_DEPLOYMENT did not respond within 30s",
        1,
        2,
    )

    assert receipt.category == "transient_external"
    assert receipt.action == "bounded_retry"
    assert receipt.result == "retry permitted"
