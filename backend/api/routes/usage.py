from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request

from backend.usage.models import ModelUsageRecord


router = APIRouter(prefix="/api/usage", tags=["usage"])


UsageBucket = dict[str, object]


@router.get("/summary")
async def get_usage_summary(
    request: Request,
    days: int = 7,
    tz: str = "Asia/Shanghai",
    model: str | None = None,
    recent_limit: int = 7,
    include_estimated: bool = False,
):
    if days <= 0 or days > 366:
        raise HTTPException(status_code=400, detail="days 必须在 1 到 366 之间")
    if recent_limit <= 0 or recent_limit > 100:
        raise HTTPException(status_code=400, detail="recent_limit 必须在 1 到 100 之间")

    try:
        local_zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"无效时区: {tz}") from exc

    now_local = datetime.now(local_zone)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    end_local = start_local + timedelta(days=days)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    runtime = request.app.state.runtime
    usage_store = getattr(runtime, "usage_store", None)
    if usage_store is None:
        return _empty_usage_summary(
            available=False,
            days=days,
            tz=tz,
            start_local=start_local,
            end_local=end_local,
            model_filter=model,
            error="usage store unavailable",
        )

    try:
        records = usage_store.list_records_window(start_at=start_utc, end_at=end_utc)
    except Exception as exc:
        return _empty_usage_summary(
            available=False,
            days=days,
            tz=tz,
            start_local=start_local,
            end_local=end_local,
            model_filter=model,
            error=str(exc),
        )

    session_titles = _build_session_title_index(getattr(runtime, "session_store", None))

    available_models = sorted({record.model for record in records if record.model})
    filtered_records = [record for record in records if not model or record.model == model]
    actual_records = [record for record in filtered_records if record.usage_available and record.total_tokens > 0]
    missing_records = [record for record in filtered_records if not (record.usage_available and record.total_tokens > 0)]
    missing_with_estimate_records = [record for record in missing_records if _estimated_total_tokens(record) > 0]
    aggregate_records = _records_for_aggregate(filtered_records, include_estimated=include_estimated)

    response = {
        "available": True,
        "error": None,
        "range": {
            "days": days,
            "timezone": tz,
            "start_at": start_local.isoformat(),
            "end_at": end_local.isoformat(),
            "start_date": start_local.date().isoformat(),
            "end_date": (end_local - timedelta(days=1)).date().isoformat(),
        },
        "filters": {
            "model": model,
            "include_estimated": include_estimated,
        },
        "available_models": available_models,
        "totals": {
            "request_count": len(aggregate_records),
            "input_tokens": sum(int(record["input_tokens"]) for record in aggregate_records),
            "output_tokens": sum(int(record["output_tokens"]) for record in aggregate_records),
            "total_tokens": sum(int(record["total_tokens"]) for record in aggregate_records),
            "usage_missing_count": len(missing_records),
            "estimated_request_count": len(missing_with_estimate_records) if include_estimated else 0,
            "estimated_input_tokens": (
                sum(_estimated_input_tokens(record) for record in missing_with_estimate_records)
                if include_estimated
                else 0
            ),
            "estimated_output_tokens": 0,
            "estimated_total_tokens": (
                sum(_estimated_total_tokens(record) for record in missing_with_estimate_records)
                if include_estimated
                else 0
            ),
        },
        "by_day": _aggregate_by_day(aggregate_records, local_zone),
        "by_model": _aggregate_by_model(aggregate_records),
        "by_request_kind": _aggregate_by_request_kind(aggregate_records),
        "by_session": _aggregate_by_session(aggregate_records, session_titles),
        "recent_records": [
            _serialize_record(record, session_titles)
            for record in filtered_records[:recent_limit]
        ],
    }
    return response


def _empty_usage_summary(
    *,
    available: bool,
    days: int,
    tz: str,
    start_local: datetime,
    end_local: datetime,
    model_filter: str | None,
    error: str | None,
) -> dict[str, object]:
    return {
        "available": available,
        "error": error,
        "range": {
            "days": days,
            "timezone": tz,
            "start_at": start_local.isoformat(),
            "end_at": end_local.isoformat(),
            "start_date": start_local.date().isoformat(),
            "end_date": (end_local - timedelta(days=1)).date().isoformat(),
        },
        "filters": {
            "model": model_filter,
            "include_estimated": False,
        },
        "available_models": [],
        "totals": {
            "request_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "usage_missing_count": 0,
            "estimated_request_count": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
        },
        "by_day": [],
        "by_model": [],
        "by_request_kind": [],
        "by_session": [],
        "recent_records": [],
    }


def _aggregate_by_day(records: list[UsageBucket], local_zone: ZoneInfo) -> list[dict[str, object]]:
    buckets: dict[str, UsageBucket] = {}
    for record in records:
        created_at = _parse_record_time(str(record["created_at"])).astimezone(local_zone)
        key = created_at.date().isoformat()
        bucket = buckets.setdefault(
            key,
            {
                "date": key,
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_request_count": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
            },
        )
        _add_usage(bucket, record)
    return [buckets[key] for key in sorted(buckets)]


def _aggregate_by_model(records: list[UsageBucket]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], UsageBucket] = {}
    for record in records:
        key = (str(record["provider_type"]), str(record["model"]))
        bucket = buckets.setdefault(
            key,
            {
                "provider_type": record["provider_type"],
                "model": record["model"],
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_request_count": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
            },
        )
        _add_usage(bucket, record)
    return sorted(buckets.values(), key=lambda item: int(item["total_tokens"]), reverse=True)


def _aggregate_by_request_kind(records: list[UsageBucket]) -> list[dict[str, object]]:
    buckets: dict[str, UsageBucket] = {}
    for record in records:
        bucket = buckets.setdefault(
            str(record["request_kind"]),
            {
                "request_kind": record["request_kind"],
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_request_count": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
            },
        )
        _add_usage(bucket, record)
    return sorted(buckets.values(), key=lambda item: int(item["total_tokens"]), reverse=True)


def _aggregate_by_session(
    records: list[UsageBucket],
    session_titles: dict[str, str],
) -> list[dict[str, object]]:
    buckets: dict[str, UsageBucket] = {}
    for record in records:
        session_id = str(record.get("attributed_session_id") or "__unknown__")
        bucket = buckets.setdefault(
            session_id,
            {
                "session_id": None if session_id == "__unknown__" else session_id,
                "session_title": _session_title(None if session_id == "__unknown__" else session_id, session_titles),
                "request_count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_request_count": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_total_tokens": 0,
            },
        )
        _add_usage(bucket, record)
    return sorted(buckets.values(), key=lambda item: int(item["total_tokens"]), reverse=True)


def _serialize_record(record: ModelUsageRecord, session_titles: dict[str, str]) -> dict[str, object]:
    attributed_session_id = _record_attributed_session_id(record)
    return {
        "request_id": record.request_id,
        "session_id": record.session_id,
        "session_title": _session_title(record.session_id, session_titles),
        "attributed_session_id": attributed_session_id,
        "attributed_session_title": _session_title(attributed_session_id, session_titles),
        "turn_id": record.turn_id,
        "request_kind": record.request_kind,
        "provider_type": record.provider_type,
        "model": record.model,
        "usage_available": record.usage_available,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "total_tokens": record.total_tokens,
        "estimated_total_tokens": _estimated_total_tokens(record),
        "finish_reason": record.finish_reason,
        "created_at": record.created_at,
        "metadata": record.metadata,
    }


def _session_title(session_id: str | None, session_titles: dict[str, str]) -> str | None:
    if not session_id:
        return None
    return session_titles.get(session_id) or session_id


def _build_session_title_index(session_store) -> dict[str, str]:
    if session_store is None:
        return {}
    if hasattr(session_store, "list_records"):
        try:
            return {
                str(item.session_id): str(item.title)
                for item in session_store.list_records(include_subagents=True)
                if getattr(item, "session_id", None)
            }
        except Exception:
            pass
    if hasattr(session_store, "list"):
        try:
            return {
                str(item.session_id): str(item.title)
                for item in session_store.list()
                if getattr(item, "session_id", None)
            }
        except Exception:
            return {}
    return {}


def _add_usage(bucket: UsageBucket, record: UsageBucket) -> None:
    bucket["request_count"] = int(bucket["request_count"]) + 1
    bucket["input_tokens"] = int(bucket["input_tokens"]) + int(record["input_tokens"])
    bucket["output_tokens"] = int(bucket["output_tokens"]) + int(record["output_tokens"])
    bucket["total_tokens"] = int(bucket["total_tokens"]) + int(record["total_tokens"])
    if bool(record.get("estimated")):
        bucket["estimated_request_count"] = int(bucket["estimated_request_count"]) + 1
        bucket["estimated_input_tokens"] = int(bucket["estimated_input_tokens"]) + int(record["input_tokens"])
        bucket["estimated_output_tokens"] = int(bucket["estimated_output_tokens"]) + int(record["output_tokens"])
        bucket["estimated_total_tokens"] = int(bucket["estimated_total_tokens"]) + int(record["total_tokens"])


def _records_for_aggregate(records: list[ModelUsageRecord], *, include_estimated: bool) -> list[UsageBucket]:
    aggregated: list[UsageBucket] = []
    for record in records:
        if record.usage_available and record.total_tokens > 0:
            aggregated.append(_usage_bucket_from_record(record, estimated=False))
            continue
        if include_estimated:
            estimated_total = _estimated_total_tokens(record)
            if estimated_total > 0:
                aggregated.append(_usage_bucket_from_record(record, estimated=True))
    return aggregated


def _usage_bucket_from_record(record: ModelUsageRecord, *, estimated: bool) -> UsageBucket:
    input_tokens = _estimated_input_tokens(record) if estimated else record.input_tokens
    output_tokens = 0 if estimated else record.output_tokens
    total_tokens = _estimated_total_tokens(record) if estimated else record.total_tokens
    return {
        "request_id": record.request_id,
        "session_id": record.session_id,
        "attributed_session_id": _record_attributed_session_id(record),
        "request_kind": record.request_kind,
        "provider_type": record.provider_type,
        "model": record.model,
        "created_at": record.created_at,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated": estimated,
    }


def _record_attributed_session_id(record: ModelUsageRecord) -> str | None:
    if record.request_kind == "subagent_turn":
        parent_session_id = record.metadata.get("parent_session_id")
        if isinstance(parent_session_id, str) and parent_session_id.strip():
            return parent_session_id.strip()
    return record.session_id


def _estimated_input_tokens(record: ModelUsageRecord) -> int:
    value = record.metadata.get("estimated_input_tokens")
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        try:
            return max(int(value.strip()), 0)
        except ValueError:
            return 0
    return 0


def _estimated_total_tokens(record: ModelUsageRecord) -> int:
    return _estimated_input_tokens(record)


def _parse_record_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value)
