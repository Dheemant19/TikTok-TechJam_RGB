from __future__ import annotations

from typing import Any

import torch
from torch import nn


class FactorizationMachine(nn.Module):
    model_family = "factorization_machine"
    requires_history = False

    def __init__(self, dimension: int, factors: int = 16) -> None:
        super().__init__()
        self.embedding = nn.Embedding(dimension, factors)
        self.linear = nn.Embedding(dimension, 1)
        self.bias = nn.Parameter(torch.zeros(()))
        nn.init.normal_(self.embedding.weight, std=0.01)
        nn.init.zeros_(self.linear.weight)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        embeddings = self.embedding(features)
        summed = embeddings.sum(dim=1)
        interaction = 0.5 * (summed.square().sum(dim=1) - embeddings.square().sum(dim=(1, 2)))
        return self.bias + self.linear(features).sum(dim=(1, 2)) + interaction


class DeepFactorizationMachine(nn.Module):
    model_family = "deepfm"
    requires_history = False

    def __init__(
        self,
        dimension: int,
        field_count: int,
        factors: int = 16,
        hidden_dimensions: tuple[int, ...] = (128, 64),
        auxiliary_tasks: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(dimension, factors)
        self.linear = nn.Embedding(dimension, 1)
        layers: list[nn.Module] = []
        width = field_count * factors
        for hidden in hidden_dimensions:
            layers.extend((nn.Linear(width, hidden), nn.ReLU(), nn.Dropout(0.1)))
            width = hidden
        self.tower = nn.Sequential(*layers)
        self.main_head = nn.Linear(width, 1)
        self.auxiliary_heads = nn.ModuleDict({task: nn.Linear(width, 1) for task in auxiliary_tasks})
        self.bias = nn.Parameter(torch.zeros(()))
        nn.init.normal_(self.embedding.weight, std=0.01)
        nn.init.zeros_(self.linear.weight)

    def forward(self, features: torch.Tensor) -> torch.Tensor | dict[str, torch.Tensor]:
        embeddings = self.embedding(features)
        summed = embeddings.sum(dim=1)
        interaction = 0.5 * (summed.square().sum(dim=1) - embeddings.square().sum(dim=(1, 2)))
        hidden = self.tower(embeddings.flatten(start_dim=1))
        long_view = self.bias + self.linear(features).sum(dim=(1, 2)) + interaction + self.main_head(hidden).squeeze(1)
        if not self.auxiliary_heads:
            return long_view
        return {
            "long_view": long_view,
            **{name: head(hidden).squeeze(1) for name, head in self.auxiliary_heads.items()},
        }


class CrossNetworkModel(nn.Module):
    model_family = "dcnv2"
    requires_history = False

    def __init__(
        self,
        dimension: int,
        field_count: int,
        factors: int = 16,
        cross_layers: int = 2,
        hidden_dimension: int = 128,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(dimension, factors)
        width = field_count * factors
        self.cross_weights = nn.ModuleList(nn.Linear(width, width) for _ in range(cross_layers))
        self.deep = nn.Sequential(nn.Linear(width, hidden_dimension), nn.ReLU(), nn.Linear(hidden_dimension, width))
        self.output = nn.Linear(width * 2, 1)
        nn.init.normal_(self.embedding.weight, std=0.01)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        base = self.embedding(features).flatten(start_dim=1)
        crossed = base
        for layer in self.cross_weights:
            crossed = base * layer(crossed) + crossed
        return self.output(torch.cat((crossed, self.deep(base)), dim=1)).squeeze(1)


class DeepInterestNetwork(nn.Module):
    model_family = "din"
    requires_history = True

    def __init__(
        self,
        dimension: int,
        field_count: int,
        factors: int = 16,
        hidden_dimension: int = 128,
    ) -> None:
        super().__init__()
        self.embedding = nn.Embedding(dimension, factors)
        width = field_count * factors + factors * 4
        self.tower = nn.Sequential(
            nn.Linear(width, hidden_dimension),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dimension, hidden_dimension // 2),
            nn.ReLU(),
            nn.Linear(hidden_dimension // 2, 1),
        )
        nn.init.normal_(self.embedding.weight, std=0.01)

    def forward(
        self,
        features: torch.Tensor,
        history: torch.Tensor | None = None,
        history_mask: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if history is None or history_mask is None:
            raise ValueError("DIN requires past-only history and its mask")
        feature_embeddings = self.embedding(features)
        candidate = feature_embeddings[:, 1, :]
        history_embeddings = self.embedding(history)
        attention = (history_embeddings * candidate.unsqueeze(1)).sum(dim=2)
        attention = attention.masked_fill(~history_mask, -1e9)
        weights = torch.softmax(attention, dim=1) * history_mask
        weights = weights / weights.sum(dim=1, keepdim=True).clamp_min(1e-8)
        interest = (history_embeddings * weights.unsqueeze(2)).sum(dim=1)
        interaction = torch.cat((candidate, interest, candidate - interest, candidate * interest), dim=1)
        return self.tower(torch.cat((feature_embeddings.flatten(start_dim=1), interaction), dim=1)).squeeze(1)


def build_candidate_model(dimension: int, field_count: int, config: dict[str, Any]) -> nn.Module:
    """Build the model named by the experiment config; FM is only one option."""
    model_config = dict(config.get("model", {}))
    name = str(model_config.get("name", "factorization_machine")).lower()
    factors = int(model_config.get("factors", 16))
    hidden = tuple(int(value) for value in model_config.get("hidden_dimensions", [128, 64]))
    auxiliary_tasks = tuple(str(value) for value in config.get("training", {}).get("auxiliary_tasks", []))

    if name in {"factorization_machine", "fm"}:
        return FactorizationMachine(dimension, factors)
    if name == "deepfm":
        return DeepFactorizationMachine(dimension, field_count, factors, hidden, auxiliary_tasks)
    if name == "dcnv2":
        return CrossNetworkModel(
            dimension,
            field_count,
            factors,
            int(model_config.get("cross_layers", 2)),
            int(model_config.get("hidden_dimension", 128)),
        )
    if name == "din":
        return DeepInterestNetwork(
            dimension,
            field_count,
            factors,
            int(model_config.get("hidden_dimension", 128)),
        )
    raise ValueError(
        f"unsupported model {name!r}; built-ins are factorization_machine, deepfm, dcnv2, and din. "
        "A new model may be added and wired through build_candidate_model in the experiment worktree."
    )
