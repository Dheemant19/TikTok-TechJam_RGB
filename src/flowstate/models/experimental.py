from __future__ import annotations

import torch
from torch import nn


class FactorizationMachine(nn.Module):
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
