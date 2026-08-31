from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import numpy as np


HISTORY_STATE_VERSION = 1


def chronological_positive_histories(
    data: dict[str, np.ndarray],
    maximum_length: int,
) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    """Build past-only positive video histories for training rows.

    Rows are processed by date and timestamp. A row's label is added only after
    that row's history has been captured, so the current or future answer can
    never appear in its own input.
    """
    if maximum_length < 1:
        raise ValueError("maximum history length must be positive")
    required = {"X", "y", "users", "date", "time_ms"}
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"history features require arrays: {missing}")

    row_count = len(data["y"])
    histories = np.zeros((row_count, maximum_length), dtype=np.int64)
    masks = np.zeros((row_count, maximum_length), dtype=np.bool_)
    order = np.lexsort((np.arange(row_count), data["time_ms"], data["date"]))
    recent: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=maximum_length))

    for row_index in order.tolist():
        user = str(data["users"][row_index])
        values = list(recent[user])
        if values:
            length = min(len(values), maximum_length)
            histories[row_index, -length:] = values[-length:]
            masks[row_index, -length:] = True
        if float(data["y"][row_index]) > 0:
            recent[user].append(int(data["X"][row_index, 1]))

    state = {user: list(values) for user, values in recent.items()}
    return histories, masks, state


def histories_from_state(
    users: np.ndarray,
    state: dict[str, list[int]],
    maximum_length: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Attach train-derived histories to validation or test candidates."""
    histories = np.zeros((len(users), maximum_length), dtype=np.int64)
    masks = np.zeros((len(users), maximum_length), dtype=np.bool_)
    for row_index, raw_user in enumerate(users.tolist()):
        values = state.get(str(raw_user), [])[-maximum_length:]
        if not values:
            continue
        histories[row_index, -len(values):] = values
        masks[row_index, -len(values):] = True
    return histories, masks


def serialize_history_state(state: dict[str, list[int]], maximum_length: int) -> dict[str, Any]:
    return {
        "version": HISTORY_STATE_VERSION,
        "maximum_length": maximum_length,
        "users": state,
    }


def load_history_state(document: dict[str, Any]) -> tuple[dict[str, list[int]], int]:
    if int(document.get("version", -1)) != HISTORY_STATE_VERSION:
        raise ValueError("unsupported history state version")
    maximum_length = int(document["maximum_length"])
    users = {
        str(user): [int(value) for value in values][-maximum_length:]
        for user, values in dict(document.get("users", {})).items()
    }
    return users, maximum_length
