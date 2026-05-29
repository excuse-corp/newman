from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_environment_context(raw_context: object | None, *, server_received_at: str | None = None) -> dict[str, Any]:
    server_time = server_received_at or datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "time": {
            "server_received_at_utc": server_time,
        }
    }
    raw = raw_context if isinstance(raw_context, dict) else {}
    time_context = _normalize_time_context(raw.get("time"))
    if time_context:
        payload["time"].update(time_context)
        clock_skew_seconds = _compute_clock_skew_seconds(
            time_context.get("client_local_now"),
            server_time,
        )
        if clock_skew_seconds is not None:
            payload["time"]["clock_skew_seconds"] = clock_skew_seconds
    location_context = _normalize_location_context(raw.get("location"))
    if location_context:
        payload["location"] = location_context
    return payload


def _normalize_time_context(raw_context: object) -> dict[str, Any]:
    if not isinstance(raw_context, dict):
        return {}
    payload: dict[str, Any] = {}
    client_timezone = _normalize_text(raw_context.get("client_timezone"), max_length=128)
    if client_timezone:
        payload["client_timezone"] = client_timezone
    client_local_now = _normalize_iso_timestamp(raw_context.get("client_local_now"), to_utc=False)
    if client_local_now:
        payload["client_local_now"] = client_local_now
    return payload


def _normalize_location_context(raw_context: object) -> dict[str, Any] | None:
    if not isinstance(raw_context, dict):
        return None
    city = _normalize_text(raw_context.get("city"), max_length=128)
    if not city:
        return None
    source = _normalize_text(raw_context.get("source"), max_length=64) or "client_provided"
    if source == "timezone_inference":
        return None
    payload: dict[str, Any] = {
        "city": city,
        "source": source,
        "precision": _normalize_text(raw_context.get("precision"), max_length=32) or "city",
    }
    captured_at = _normalize_iso_timestamp(raw_context.get("captured_at_utc"), to_utc=True)
    if captured_at:
        payload["captured_at_utc"] = captured_at
    timezone_hint = _normalize_text(raw_context.get("timezone_hint"), max_length=128)
    if timezone_hint:
        payload["timezone_hint"] = timezone_hint
    return payload


def _compute_clock_skew_seconds(client_local_now: object, server_received_at: str) -> int | None:
    client_time = _parse_iso_datetime(client_local_now)
    server_time = _parse_iso_datetime(server_received_at)
    if client_time is None or server_time is None:
        return None
    return int(round((client_time - server_time).total_seconds()))


def _normalize_iso_timestamp(value: object, *, to_utc: bool) -> str | None:
    parsed = _parse_iso_datetime(value, to_utc=to_utc)
    if parsed is None:
        return None
    return parsed.isoformat()


def _parse_iso_datetime(value: object, *, to_utc: bool = True) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if to_utc:
        return parsed.astimezone(timezone.utc)
    return parsed


def _normalize_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:max_length]
