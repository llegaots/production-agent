"""Google Geocoding for job addresses with confidence and service-area checks.

Used by GeoClusterAgent before clustering and during spreadsheet import.
Requires ``GOOGLE_MAPS_API_KEY`` (Geocoding API enabled in Google Cloud Console).
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# West Island / greater Montreal west — where this demo business operates
SERVICE_CENTROID_LAT = float(os.getenv("SERVICE_AREA_LAT", "45.4030"))
SERVICE_CENTROID_LNG = float(os.getenv("SERVICE_AREA_LNG", "-73.9470"))
SERVICE_RADIUS_KM = float(os.getenv("SERVICE_AREA_RADIUS_KM", "45"))

# Quebec postal FSA prefixes common for West Island window-cleaning routes
WEST_ISLAND_POSTAL_FSA = frozenset(
    {
        "H9A", "H9B", "H9C", "H9G", "H9H", "H9J", "H9K", "H9R", "H9S", "H9W", "H9X", "H9Y",
        "J7T", "J7V", "J7W", "J7R", "J7A", "J7B", "J7C", "J7E", "J7G", "J7K",
    }
)

LOCATION_TYPE_SCORE = {
    "ROOFTOP": 0.95,
    "RANGE_INTERPOLATED": 0.88,
    "GEOMETRIC_CENTER": 0.72,
    "APPROXIMATE": 0.52,
}

GEOCODE_CONFIRM_THRESHOLD = 0.82


@dataclass
class GeocodeResult:
    input_address: str
    success: bool
    lat: Optional[float] = None
    lng: Optional[float] = None
    formatted_address: str = ""
    confidence: float = 0.0
    needs_review: bool = True
    in_service_area: bool = False
    location_type: str = ""
    place_id: str = ""
    postal_code: str = ""
    province: str = ""
    issues: list[str] = field(default_factory=list)
    source: str = "none"  # google | fallback | cache

    def to_dict(self) -> dict:
        return {
            "input_address": self.input_address,
            "success": self.success,
            "lat": self.lat,
            "lng": self.lng,
            "formatted_address": self.formatted_address,
            "confidence": round(self.confidence, 3),
            "needs_review": self.needs_review,
            "in_service_area": self.in_service_area,
            "location_type": self.location_type,
            "place_id": self.place_id,
            "postal_code": self.postal_code,
            "province": self.province,
            "issues": self.issues,
            "source": self.source,
        }


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize_query(address: str) -> str:
    """Turn partial inputs like '90 devon' into a Canada-biased geocode query."""
    t = re.sub(r"\s+", " ", (address or "").strip())
    if not t:
        return t
    lower = t.lower()
    if "canada" not in lower and "qc" not in lower and "quebec" not in lower:
        if re.search(r"\b[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d\b", t):
            t = f"{t}, QC, Canada"
        else:
            t = f"{t}, West Island, Quebec, Canada"
    return t


def _extract_component(components: list[dict], ctype: str) -> str:
    for c in components:
        if ctype in c.get("types", []):
            return c.get("long_name") or c.get("short_name") or ""
    return ""


def _postal_fsa(postal: str) -> str:
    p = (postal or "").replace(" ", "").upper()
    return p[:3] if len(p) >= 3 else ""


def score_google_result(
    input_address: str,
    result: dict,
    *,
    partial_match: bool = False,
) -> GeocodeResult:
    """Score a single Geocoding API result."""
    issues: list[str] = []
    geometry = result.get("geometry") or {}
    loc = geometry.get("location") or {}
    lat = loc.get("lat")
    lng = loc.get("lng")
    loc_type = geometry.get("location_type") or "APPROXIMATE"
    formatted = result.get("formatted_address") or ""
    components = result.get("address_components") or []
    place_id = result.get("place_id") or ""

    province = _extract_component(components, "administrative_area_level_1")
    postal = _extract_component(components, "postal_code")
    fsa = _postal_fsa(postal)
    types = set(result.get("types") or [])

    confidence = LOCATION_TYPE_SCORE.get(loc_type, 0.5)

    if partial_match:
        confidence -= 0.18
        issues.append("Google returned a partial match — verify street number and city.")

    if "street_address" in types or "premise" in types or "subpremise" in types:
        confidence += 0.06
    elif "route" in types and "street_number" not in str(components):
        confidence -= 0.12
        issues.append("Matched a street/route only, not a specific building number.")
    elif "locality" in types and "street_address" not in types:
        confidence -= 0.25
        issues.append("Matched city/locality only — add a street number.")

    # Province must be Quebec for this business
    prov_ok = province.upper() in ("QC", "QUÉBEC", "QUEBEC") or fsa.startswith(("H", "J", "G"))
    if province and not prov_ok:
        confidence -= 0.35
        issues.append(f"Province looks like {province}, not Quebec — outside service territory.")

    in_service = False
    if lat is not None and lng is not None:
        dist = haversine_km(lat, lng, SERVICE_CENTROID_LAT, SERVICE_CENTROID_LNG)
        if dist <= SERVICE_RADIUS_KM:
            in_service = True
            if fsa and fsa in WEST_ISLAND_POSTAL_FSA:
                confidence += 0.05
            elif fsa and fsa[0] in ("H", "J"):
                confidence += 0.02
        else:
            confidence -= 0.3
            issues.append(
                f"Location is {dist:.0f} km from the West Island depot — likely outside the service area."
            )

    if fsa and fsa not in WEST_ISLAND_POSTAL_FSA and fsa[0] in ("H", "J"):
        issues.append(f"Postal {fsa} is in Quebec but not a usual West Island sector — double-check.")

    # Input had a postal code — compare to geocoded
    input_postal = re.search(r"\b([A-Za-z]\d[A-Za-z])\s*(\d[A-Za-z]\d)\b", input_address, re.I)
    if input_postal:
        in_fsa = input_postal.group(1).upper()
        if fsa and in_fsa != fsa:
            confidence -= 0.15
            issues.append(f"Postal code mismatch: input {in_fsa} vs geocoded {fsa}.")

    # Street number in input should appear in formatted result
    num_m = re.match(r"^\s*(\d+[A-Za-z]?)\b", input_address)
    if num_m and num_m.group(1) not in formatted:
        confidence -= 0.08
        issues.append("Street number from input not found on geocoded address.")

    confidence = max(0.0, min(1.0, confidence))
    needs_review = confidence < GEOCODE_CONFIRM_THRESHOLD or bool(issues)

    return GeocodeResult(
        input_address=input_address,
        success=lat is not None and lng is not None,
        lat=lat,
        lng=lng,
        formatted_address=formatted,
        confidence=confidence,
        needs_review=needs_review,
        in_service_area=in_service,
        location_type=loc_type,
        place_id=place_id,
        postal_code=postal,
        province=province,
        issues=issues,
        source="google",
    )


class GoogleGeocoder:
    def __init__(self) -> None:
        self.api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip() or os.getenv(
            "GOOGLE_GEOCODING_API_KEY", ""
        ).strip()
        self.base_url = "https://maps.googleapis.com/maps/api/geocode/json"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def geocode(self, address: str) -> GeocodeResult:
        raw = (address or "").strip()
        if not raw:
            return GeocodeResult(
                input_address=raw,
                success=False,
                confidence=0.0,
                needs_review=True,
                issues=["Address is empty."],
            )

        if not self.enabled:
            return GeocodeResult(
                input_address=raw,
                success=False,
                confidence=0.0,
                needs_review=True,
                issues=["GOOGLE_MAPS_API_KEY not set — cannot verify location."],
                source="none",
            )

        query = _normalize_query(raw)
        params = {
            "address": query,
            "key": self.api_key,
            "region": "ca",
            "components": "country:CA",
            # Bias results to West Island / Montreal west viewport
            "bounds": "45.30,-74.10|45.55,-73.60",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(self.base_url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return GeocodeResult(
                input_address=raw,
                success=False,
                confidence=0.0,
                needs_review=True,
                issues=[f"Geocoding request failed: {exc}"],
                source="none",
            )

        status = data.get("status")
        if status != "OK" or not data.get("results"):
            msg = data.get("error_message") or status or "ZERO_RESULTS"
            return GeocodeResult(
                input_address=raw,
                success=False,
                confidence=0.0,
                needs_review=True,
                issues=[f"Google Geocoding: {msg}"],
                source="google",
            )

        best = data["results"][0]
        partial = len(data["results"]) > 1 or "partial_match" in str(best.get("types", []))
        # API sets partial_match on result object in some responses
        if best.get("partial_match"):
            partial = True

        return score_google_result(raw, best, partial_match=partial)


geocoder = GoogleGeocoder()
