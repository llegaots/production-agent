from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.tools._db import tools_db
from app.tools.schemas import (
    GetWeatherInput,
    GetWeatherOutput,
    WeatherWindow,
)


def _cache_key(lat: float, lng: float, forecast_date) -> str:
    raw = f"{round(lat, 3)}:{round(lng, 3)}:{forecast_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _mock_weather(inp: GetWeatherInput) -> GetWeatherOutput:
    return GetWeatherOutput(
        lat=inp.lat,
        lng=inp.lng,
        forecast_date=inp.forecast_date,
        provider="mock",
        windows=[
            WeatherWindow(
                start_hour=7,
                end_hour=12,
                suitable_for_exterior_work=True,
                precip_probability=0.1,
                wind_speed_kmh=12,
                summary="Mock AM: suitable for window cleaning",
            ),
            WeatherWindow(
                start_hour=13,
                end_hour=17,
                suitable_for_exterior_work=True,
                precip_probability=0.2,
                wind_speed_kmh=18,
                summary="Mock PM: light breeze, acceptable",
            ),
        ],
        cached=False,
    )


def _fetch_tomorrow_io(api_key: str, inp: GetWeatherInput) -> dict:
    """Tomorrow.io timeline for a point (simplified)."""
    url = "https://api.tomorrow.io/v4/weather/forecast"
    params = {
        "location": f"{inp.lat},{inp.lng}",
        "timesteps": "1h",
        "units": "metric",
        "apikey": api_key,
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _parse_tomorrow_payload(payload: dict, inp: GetWeatherInput) -> list[WeatherWindow]:
    windows: list[WeatherWindow] = []
    timelines = payload.get("timelines", {})
    hourly = timelines.get("hourly", [])
    if not hourly:
        return _mock_weather(inp).windows
    values = hourly[0].get("values", []) if hourly else []
    am, pm = [], []
    for entry in values[:24]:
        t = entry.get("time", "")
        if not t:
            continue
        hour = int(t[11:13]) if len(t) >= 13 else 0
        precip = float(entry.get("precipitationProbability", 0) or 0) / 100.0
        wind = float(entry.get("windSpeed", 0) or 0)
        suitable = precip < 0.35 and wind < 40
        bucket = am if hour < 12 else pm
        bucket.append((hour, suitable, precip, wind))
    if am:
        windows.append(
            WeatherWindow(
                start_hour=min(h for h, *_ in am),
                end_hour=max(h for h, *_ in am),
                suitable_for_exterior_work=all(s for _, s, _, _ in am),
                precip_probability=max(p for _, _, p, _ in am),
                wind_speed_kmh=max(w for _, _, _, w in am),
                summary="Tomorrow.io AM forecast",
            )
        )
    if pm:
        windows.append(
            WeatherWindow(
                start_hour=min(h for h, *_ in pm),
                end_hour=max(h for h, *_ in pm),
                suitable_for_exterior_work=all(s for _, s, _, _ in pm),
                precip_probability=max(p for _, _, p, _ in pm),
                wind_speed_kmh=max(w for _, _, _, w in pm),
                summary="Tomorrow.io PM forecast",
            )
        )
    return windows or _mock_weather(inp).windows


def _read_cache(key: str) -> GetWeatherOutput | None:
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()
    row = (
        tools_db()
        .table("weather_cache")
        .select("*")
        .eq("cache_key", key)
        .gt("expires_at", now)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return None
    data = row[0]["data"]
    return GetWeatherOutput.model_validate({**data, "cached": True, "provider": "cache"})


def _write_cache(key: str, inp: GetWeatherInput, out: GetWeatherOutput) -> None:
    settings = get_settings()
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.weather_cache_ttl_hours)
    tools_db().table("weather_cache").upsert(
        {
            "cache_key": key,
            "lat": inp.lat,
            "lng": inp.lng,
            "forecast_date": inp.forecast_date.isoformat(),
            "data": out.model_dump(mode="json"),
            "provider": out.provider,
            "expires_at": expires.isoformat(),
        }
    ).execute()


def get_weather(inp: GetWeatherInput) -> GetWeatherOutput:
    """Weather for a location/date; cached in Supabase."""
    key = _cache_key(inp.lat, inp.lng, inp.forecast_date)
    if not inp.force_refresh:
        cached = _read_cache(key)
        if cached:
            return cached

    settings = get_settings()
    if settings.tomorrow_io_api_key:
        try:
            payload = _fetch_tomorrow_io(settings.tomorrow_io_api_key, inp)
            out = GetWeatherOutput(
                lat=inp.lat,
                lng=inp.lng,
                forecast_date=inp.forecast_date,
                provider="tomorrow_io",
                windows=_parse_tomorrow_payload(payload, inp),
                raw=payload,
            )
        except Exception:
            out = _mock_weather(inp)
    else:
        out = _mock_weather(inp)

    _write_cache(key, inp, out)
    return out
