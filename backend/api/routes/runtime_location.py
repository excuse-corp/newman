from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.sessions.models import utc_now


router = APIRouter(prefix="/api/runtime", tags=["runtime"])


class ResolveLocationRequest(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


@router.post("/location/resolve")
async def resolve_location(payload: ResolveLocationRequest, request: Request):
    city = await _reverse_geocode_city(
        latitude=payload.latitude,
        longitude=payload.longitude,
        app_version=str(getattr(request.app, "version", "dev")),
    )
    if not city:
        return {
            "resolved": False,
            "city": None,
            "source": "browser_geolocation",
            "precision": "city",
            "captured_at_utc": utc_now(),
        }
    return {
        "resolved": True,
        "city": city,
        "source": "browser_geolocation",
        "precision": "city",
        "captured_at_utc": utc_now(),
    }


async def _reverse_geocode_city(*, latitude: float, longitude: float, app_version: str) -> str | None:
    city = await _reverse_geocode_city_bigdatacloud(
        latitude=latitude,
        longitude=longitude,
        app_version=app_version,
    )
    if city:
        return city
    return await _reverse_geocode_city_nominatim(
        latitude=latitude,
        longitude=longitude,
        app_version=app_version,
    )


async def _reverse_geocode_city_bigdatacloud(*, latitude: float, longitude: float, app_version: str) -> str | None:
    headers = {
        "User-Agent": f"Newman/{app_version} (+local runtime reverse geocode)",
        "Accept": "application/json",
    }
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "localityLanguage": "en",
    }
    try:
        async with httpx.AsyncClient(timeout=3.0, headers=headers) as client:
            response = await client.get("https://api.bigdatacloud.net/data/reverse-geocode-client", params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("city", "locality", "principalSubdivision"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def _reverse_geocode_city_nominatim(*, latitude: float, longitude: float, app_version: str) -> str | None:
    headers = {
        "User-Agent": f"Newman/{app_version} (+local runtime reverse geocode)",
        "Accept": "application/json",
    }
    params = {
        "format": "jsonv2",
        "lat": str(latitude),
        "lon": str(longitude),
        "zoom": "10",
        "addressdetails": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=2.0, headers=headers) as client:
            response = await client.get("https://nominatim.openstreetmap.org/reverse", params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return _extract_city(payload)


def _extract_city(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    address = payload.get("address")
    if not isinstance(address, dict):
        return None
    for key in ("city", "town", "municipality", "village", "county", "state_district", "state"):
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
