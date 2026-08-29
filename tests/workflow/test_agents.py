from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import rigor_rs.agents.azure_foundry as azure_foundry


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
    assert captured[-1]["reasoning_effort"] == "low"

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
    assert "+LOSS = 'bpr'" in proposal.unified_diff


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
    from rigor_rs.recovery.controller import RecoveryController

    receipt = RecoveryController().recover(
        "run",
        "Azure Foundry call to AZURE_RESEARCH_MODEL_DEPLOYMENT did not respond within 30s",
        1,
        2,
    )

    assert receipt.category == "transient_external"
    assert receipt.action == "bounded_retry"
    assert receipt.result == "retry permitted"
