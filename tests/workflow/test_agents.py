from __future__ import annotations
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
