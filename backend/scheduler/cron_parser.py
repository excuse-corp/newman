from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


FIELD_RANGES = [
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 7),
]


def matches_cron(expr: str, dt: datetime, timezone_name: str = "UTC") -> bool:
    parts = _parse_expression(expr)
    local = _as_local(dt, timezone_name)
    values = [local.minute, local.hour, local.day, local.month, _cron_weekday(local)]
    return all(
        _matches_field(field, value, bounds)
        for field, value, bounds in zip(parts, values, FIELD_RANGES, strict=True)
    )


def next_run(expr: str, from_dt: datetime, timezone_name: str = "UTC") -> datetime:
    parts = _parse_expression(expr)
    local = _as_local(from_dt, timezone_name).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
    zone = ZoneInfo(timezone_name)
    for _ in range(60 * 24 * 366):
        values = [local.minute, local.hour, local.day, local.month, _cron_weekday(local)]
        if all(_matches_field(field, value, bounds) for field, value, bounds in zip(parts, values, FIELD_RANGES, strict=True)):
            resolved = _resolve_local_minute(zone, local)
            if resolved is not None:
                return resolved
        local += timedelta(minutes=1)
    raise ValueError(f"Unable to resolve next run for cron: {expr}")


def _parse_expression(expr: str) -> list[str]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("Cron 表达式必须包含 5 段")
    for part, bounds in zip(parts, FIELD_RANGES, strict=True):
        _validate_field(part, bounds)
    return parts


def _validate_field(part: str, bounds: tuple[int, int]) -> None:
    if part == "*":
        return
    for chunk in part.split(","):
        _expand_chunk(chunk, bounds)


def _matches_field(field: str, value: int, bounds: tuple[int, int]) -> bool:
    if field == "*":
        return True
    candidates = set()
    for chunk in field.split(","):
        candidates.update(_expand_chunk(chunk, bounds))
    return value in candidates


def _expand_chunk(chunk: str, bounds: tuple[int, int]) -> set[int]:
    if not chunk:
        raise ValueError("Cron 字段不能为空")

    base = chunk
    step = 1
    if "/" in chunk:
        base, step_raw = chunk.split("/", 1)
        if not step_raw.isdigit():
            raise ValueError(f"Cron step 非法: {chunk}")
        step = int(step_raw)
        if step <= 0:
            raise ValueError(f"Cron step 必须大于 0: {chunk}")

    if base == "*":
        start, end = bounds
    elif "-" in base:
        start_raw, end_raw = base.split("-", 1)
        start, end = _parse_number(start_raw, bounds), _parse_number(end_raw, bounds)
        if start > end:
            raise ValueError(f"Cron 范围非法: {chunk}")
    else:
        value = _parse_number(base, bounds)
        return {value}

    return set(range(start, end + 1, step))


def _parse_number(raw: str, bounds: tuple[int, int]) -> int:
    if not raw.isdigit():
        raise ValueError(f"Cron 数值非法: {raw}")
    value = int(raw)
    lower, upper = bounds
    if value < lower or value > upper:
        raise ValueError(f"Cron 数值超出范围: {value}")
    if bounds == FIELD_RANGES[4] and value == 7:
        return 0
    return value


def _as_local(dt: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(zone)


def _cron_weekday(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7


def _resolve_local_minute(zone: ZoneInfo, local_naive: datetime) -> datetime | None:
    candidates: list[datetime] = []
    seen: set[str] = set()
    local_parts = (
        local_naive.year,
        local_naive.month,
        local_naive.day,
        local_naive.hour,
        local_naive.minute,
    )
    for fold in (0, 1):
        candidate = local_naive.replace(tzinfo=zone, fold=fold)
        roundtrip = candidate.astimezone(timezone.utc).astimezone(zone)
        roundtrip_parts = (
            roundtrip.year,
            roundtrip.month,
            roundtrip.day,
            roundtrip.hour,
            roundtrip.minute,
        )
        if roundtrip_parts != local_parts:
            continue
        resolved = candidate.astimezone(timezone.utc)
        key = resolved.isoformat()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(resolved)
    if not candidates:
        return None
    return min(candidates)
