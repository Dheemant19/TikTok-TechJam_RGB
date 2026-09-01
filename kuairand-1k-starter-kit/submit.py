"""Streamed KuaiRand-1K submission alignment checker.

The 1K evaluation log contains millions of rows, so checking does not load the
entire CSV into Python objects. Scoring is intentionally restricted to local
validation labels; test labels remain unavailable to the research loop.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import sys

from data import iter_evaluation_rows

HEADER = ["row_id", "user_id", "video_id", "score"]


def read_submission(path: str, data_dir: str, split: str, *, retain: bool):
    scores = [] if retain else None
    users = [] if retain else None
    labels = [] if retain else None
    count = 0
    expected = iter_evaluation_rows(data_dir, split)
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != HEADER:
            raise ValueError(f"header must be {','.join(HEADER)}; received {header}")
        for line_number, record in enumerate(reader, start=2):
            if len(record) != 4:
                raise ValueError(f"line {line_number} has {len(record)} fields; expected 4")
            try:
                expected_user, expected_video, label = next(expected)
            except StopIteration as error:
                raise ValueError(f"submission has extra row at line {line_number}") from error
            row_id, user_id, video_id, score = record
            if row_id != str(count):
                raise ValueError(f"line {line_number} row_id must be {count}; received {row_id!r}")
            if user_id != expected_user or video_id != expected_video:
                raise ValueError(
                    f"line {line_number} does not match evaluation order: "
                    f"expected ({expected_user}, {expected_video}), received ({user_id}, {video_id})"
                )
            try:
                value = float(score)
            except ValueError as error:
                raise ValueError(f"line {line_number} score is not numeric: {score!r}") from error
            if not math.isfinite(value):
                raise ValueError(f"line {line_number} score must be finite")
            if retain:
                assert scores is not None and users is not None and labels is not None
                scores.append(value)
                users.append(user_id)
                labels.append(label)
            count += 1
    try:
        next(expected)
    except StopIteration:
        pass
    else:
        raise ValueError(f"submission ended after {count:,} rows before the evaluation split ended")
    return count, users, labels, scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--data_dir", default="./KuaiRand-1K/data")
    parser.add_argument("--split", default="test", choices=["valid", "test"])
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true", help="validate schema and deterministic row alignment")
    actions.add_argument("--score", action="store_true", help="score a local validation submission")
    arguments = parser.parse_args()
    if arguments.score and arguments.split != "valid":
        parser.error("--score is available only for the validation split")
    count, users, labels, scores = read_submission(
        arguments.path,
        arguments.data_dir,
        arguments.split,
        retain=arguments.score,
    )
    print(f"format and alignment check passed: {count:,} rows, split={arguments.split}")
    if arguments.score:
        starter = Path(__file__).resolve().parents[1] / "kuairand-starter-kit"
        sys.path.insert(0, str(starter))
        from evaluate import evaluate

        result = evaluate(users, labels, scores)
        print(
            f"GAUC {result['GAUC']:.4f} | nDCG@5 {result['nDCG@5']:.4f} "
            f"| primary {result['primary']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
