"""Tests for Google geocoding confidence scoring (no live API calls)."""
import pytest

from app.geocode import (
    GeocodeResult,
    GoogleGeocoder,
    _municipality_matches,
    _normalize_query,
    _pick_best_google_result,
    extract_municipality_hint,
    score_google_result,
)


def test_normalize_query_adds_quebec_bias():
    assert "Canada" in _normalize_query("90 Devon")
    assert "J7V 8P4" in _normalize_query("18 Simone-De Beauvoir, J7V 8P4")


def test_normalize_query_preserves_explicit_city():
    q = _normalize_query("100 Lakeshore Rd, Pointe-Claire QC")
    assert "Pointe-Claire" in q or "Pointe Claire" in q
    assert "West Island" not in q


def test_extract_municipality_hint():
    assert extract_municipality_hint("50 Elm, Beaconsfield QC") == "beaconsfield"
    assert extract_municipality_hint("75 Hymus, Kirkland QC") == "kirkland"


def test_municipality_mismatch_detected():
    result = score_google_result(
        "100 Lakeshore Rd, Pointe-Claire QC",
        {
            "formatted_address": "100 Chem. Lakeshore, Beaconsfield, QC H9W 2W9, Canada",
            "geometry": {
                "location": {"lat": 45.4298121, "lng": -73.8452393},
                "location_type": "ROOFTOP",
            },
            "address_components": [
                {"long_name": "Beaconsfield", "types": ["locality"]},
                {"long_name": "H9W 2W9", "types": ["postal_code"]},
                {"short_name": "QC", "types": ["administrative_area_level_1"]},
            ],
            "types": ["street_address"],
            "place_id": "abc",
        },
        expected_municipality="pointe-claire",
    )
    assert result.needs_review
    assert any("does not match expected" in i for i in result.issues)


def test_pick_best_prefers_matching_municipality():
    results = [
        {
            "formatted_address": "100 Chem. Lakeshore, Beaconsfield, QC H9W 2W9, Canada",
            "geometry": {"location": {"lat": 45.43, "lng": -73.85}, "location_type": "ROOFTOP"},
            "address_components": [{"long_name": "Beaconsfield", "types": ["locality"]}],
            "types": ["street_address"],
            "place_id": "wrong",
        },
        {
            "formatted_address": "200 Av. Saint-Louis, Pointe-Claire, QC H9R 4X7, Canada",
            "geometry": {"location": {"lat": 45.46, "lng": -73.79}, "location_type": "ROOFTOP"},
            "address_components": [{"long_name": "Pointe-Claire", "types": ["locality"]}],
            "types": ["street_address"],
            "place_id": "right",
        },
    ]
    picked = _pick_best_google_result(
        "100 Lakeshore Rd, Pointe-Claire QC",
        results,
        expected_municipality="pointe-claire",
    )
    assert _municipality_matches("pointe-claire", "Pointe-Claire", picked.formatted_address)
    assert picked.lat == pytest.approx(45.46)


def test_municipality_matches_aliases():
    assert _municipality_matches("pointe-claire", "Pointe-Claire", "")
    assert _municipality_matches("kirkland", "Kirkland", "171 Boul Hymus, Kirkland, QC")


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
