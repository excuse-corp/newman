from __future__ import annotations

from datetime import datetime, timedelta


FIELD_RANGES = [
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 6),
]


def matches_cron(expr: str, dt: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Cron 表达式必须包含 5 段")
    values = [dt.minute, dt.hour, dt.day, dt.month, dt.weekday()]
    return all(_matches_part(part, value, bounds) for part, value, bounds in zip(parts, values, FIELD_RANGES, strict=True))


def next_run(expr: str, from_dt: datetime) -> datetime:
    current = from_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):
        if matches_cron(expr, current):
            return current
        current += timedelta(minutes=1)
    raise ValueError(f"Unable to resolve next run for cron: {expr}")


def _matches_part(part: str, value: int, bounds: tuple[int, int]) -> bool:
    if part == "*":
        return True
    candidates = set()
    for chunk in part.split(","):
        if chunk.startswith("*/"):
            step = int(chunk[2:])
            candidates.update(range(bounds[0], bounds[1] + 1, step))
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            candidates.update(range(int(start), int(end) + 1))
            continue
        candidates.add(int(chunk))
    return value in candidates
