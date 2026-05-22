"""Tests for Google geocoding confidence scoring (no live API calls)."""
import pytest

from app.geocode import (
    GeocodeResult,
    GoogleGeocoder,
    _normalize_query,
    score_google_result,
)


def test_normalize_query_adds_quebec_bias():
    assert "Canada" in _normalize_query("90 Devon")
    assert "J7V 8P4" in _normalize_query("18 Simone-De Beauvoir, J7V 8P4")


def test_score_rooftop_west_island_high_confidence():
    result = score_google_result(
        "18 Simone-De Beauvoir, Notre-Dame-de-l'Île-Perrot, QC J7V 8P4",
        {
            "formatted_address": "18 Simone-De Beauvoir, Notre-Dame-de-l'Île-Perrot, QC J7V 8P4, Canada",
            "geometry": {
                "location": {"lat": 45.3838, "lng": -73.8825},
                "location_type": "ROOFTOP",
            },
            "address_components": [
                {"long_name": "18", "types": ["street_number"]},
                {"long_name": "J7V 8P4", "types": ["postal_code"]},
                {"short_name": "QC", "types": ["administrative_area_level_1"]},
            ],
            "types": ["street_address"],
            "place_id": "abc",
        },
    )
    assert result.success
    assert result.confidence >= 0.82
    assert result.in_service_area
    assert not result.needs_review


def test_score_partial_match_and_far_away_low_confidence():
    result = score_google_result(
        "90 Devon",
        {
            "formatted_address": "Devon, AB, Canada",
            "geometry": {
                "location": {"lat": 53.0, "lng": -113.0},
                "location_type": "APPROXIMATE",
            },
            "address_components": [
                {"long_name": "Alberta", "short_name": "AB", "types": ["administrative_area_level_1"]},
            ],
            "types": ["locality"],
            "place_id": "xyz",
        },
        partial_match=True,
    )
    assert result.needs_review
    assert result.confidence < 0.82
    assert not result.in_service_area
    assert result.issues


def test_geocoder_without_key_returns_review():
    import asyncio

    g = GoogleGeocoder()
    g.api_key = ""
    r = asyncio.run(g.geocode("9 Place Bastien, Pincourt QC"))
    assert not r.success
    assert r.needs_review
    assert "GOOGLE_MAPS_API_KEY" in " ".join(r.issues)
