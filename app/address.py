"""Address parsing and normalization with confidence scoring.

Handles messy spreadsheet paste (Canadian addresses common in window-cleaning
ops). When confidence is below the confirmation threshold, the UI must ask
the user to approve before creating jobs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Canadian postal code: A1A 1A1
CA_POSTAL_RE = re.compile(
    r"\b([A-Za-z]\d[A-Za-z])[\s,-]*(\d[A-Za-z]\d)\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b"
)
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?|\b\d{1,5}(?:\.\d{2})?\b")
STREET_NUM_RE = re.compile(r"^\s*(\d+[A-Za-z]?)\s+")

# First letter of Canadian postal → province hint (rough)
POSTAL_PROVINCE = {
    "A": "NL",
    "B": "NS",
    "C": "PE",
    "E": "NB",
    "G": "QC",
    "H": "QC",
    "J": "QC",
    "K": "ON",
    "L": "ON",
    "M": "ON",
    "N": "ON",
    "P": "ON",
    "R": "MB",
    "S": "SK",
    "T": "AB",
    "V": "BC",
    "X": "NT/NU",
    "Y": "YT",
}

CONFIRM_THRESHOLD = 0.82  # at or above: auto-accept; below: ask user


@dataclass
class AddressParseResult:
    raw: str
    formatted: str
    street: str = ""
    city: str = ""
    province: str = ""
    postal_code: str = ""
    country: str = "CA"
    confidence: float = 0.0
    needs_confirmation: bool = True
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)  # alternate formatted strings
    lat: Optional[float] = None
    lng: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "formatted": self.formatted,
            "street": self.street,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "confidence": round(self.confidence, 3),
            "needs_confirmation": self.needs_confirmation,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "lat": self.lat,
            "lng": self.lng,
        }


def _title_segment(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    # Preserve hyphenated place names: Notre-Dame-de-l'Île-Perrot style
    parts = re.split(r"(\s+|-|')", s)
    out = []
    for p in parts:
        if p.strip() and p not in (" ", "-", "'"):
            out.append(p[:1].upper() + p[1:].lower() if len(p) > 1 else p.upper())
        else:
            out.append(p)
    return "".join(out)


def _clean_raw(raw: str) -> str:
    t = raw.strip()
    t = re.sub(r",\s*,+", ", ", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*,\s*", ", ", t)
    return t.strip(" ,")


def _extract_postal(text: str) -> tuple[str, str, Optional[str]]:
    """Return (text_without_postal, normalized_postal, province_hint)."""
    m = CA_POSTAL_RE.search(text)
    if not m:
        return text, "", None
    fsa, ldu = m.group(1).upper(), m.group(2).upper()
    postal = f"{fsa} {ldu}"
    without = (text[: m.start()] + text[m.end() :]).strip(" ,")
    prov = POSTAL_PROVINCE.get(fsa[0])
    return without, postal, prov


def parse_address(raw: str, *, default_lat: float = 45.5017, default_lng: float = -73.5673) -> AddressParseResult:
    """Parse and score a single address string."""
    issues: list[str] = []
    suggestions: list[str] = []
    confidence = 0.35

    if not raw or not raw.strip():
        return AddressParseResult(
            raw=raw or "",
            formatted="",
            confidence=0.0,
            needs_confirmation=True,
            issues=["Address is empty."],
        )

    cleaned = _clean_raw(raw)
    remainder, postal, prov_hint = _extract_postal(cleaned)

    if postal:
        confidence += 0.35
    else:
        issues.append("No valid Canadian postal code found (expected format A1A 1A1).")

    # Split remainder: street is usually before last 1-2 comma segments (city)
    parts = [p.strip() for p in remainder.split(",") if p.strip()]
    street = ""
    city = ""

    if len(parts) >= 2:
        street = parts[0]
        city = ", ".join(parts[1:])
        confidence += 0.2
    elif len(parts) == 1:
        street = parts[0]
        issues.append("City may be missing — only one address segment before postal code.")
    else:
        issues.append("Could not separate street from city.")

    if street and STREET_NUM_RE.match(street):
        confidence += 0.15
    elif street:
        issues.append("Street line has no leading street number.")
        confidence -= 0.05

    if city:
        confidence += 0.1
        # Duplicate city names in one field (e.g. "L'île Perrot, Pincourt")
        if city.lower().count(",") >= 1 or len(re.findall(r"\b\w+", city)) > 6:
            issues.append("Multiple place names in city field — verify which municipality is correct.")
            confidence -= 0.12
            if len(parts) >= 3:
                alt_city = parts[-1]
                alt_street = ", ".join(parts[:-1])
                suggestions.append(
                    f"{_title_segment(alt_street)}, {_title_segment(alt_city)}, {postal}".strip(", ")
                )

    province = prov_hint or ""
    if province:
        confidence += 0.08

    street_fmt = _title_segment(street) if street else ""
    city_fmt = _title_segment(city) if city else ""

    formatted_parts = [p for p in [street_fmt, city_fmt, postal] if p]
    formatted = ", ".join(formatted_parts)

    # Obvious fixes applied → small boost
    if cleaned != raw.strip():
        confidence += 0.05

    confidence = max(0.0, min(1.0, confidence))
    needs = confidence < CONFIRM_THRESHOLD or bool(issues)

    return AddressParseResult(
        raw=raw,
        formatted=formatted,
        street=street_fmt,
        city=city_fmt,
        province=province,
        postal_code=postal,
        confidence=confidence,
        needs_confirmation=needs,
        issues=issues,
        suggestions=suggestions[:3],
        lat=default_lat,
        lng=default_lng,
    )


async def refine_with_llm(result: AddressParseResult) -> AddressParseResult:
    """Optional LLM pass when confidence is borderline and API key is set."""
    from .llm import llm, safe_json

    if not llm.enabled or result.confidence >= CONFIRM_THRESHOLD:
        return result

    system = (
        "You normalize Canadian mailing addresses for a field-service company. "
        "Return STRICT JSON only:\n"
        '{"formatted":"...", "street":"...", "city":"...", "province":"QC", '
        '"postal_code":"A1A 1A1", "confidence":0.0-1.0, "issues":["..."], '
        '"suggestions":["alternate if ambiguous"]}\n'
        "Fix double commas, postal spacing, and city duplication. "
        "If two cities appear, pick the most likely delivery municipality and "
        "note the ambiguity in issues. Never invent a postal code."
    )
    user = f"Raw address from spreadsheet:\n{result.raw}\n\nCurrent parse:\n{result.formatted}"
    raw = await llm.chat(system, user, max_tokens=280, temperature=0.1)
    data = safe_json(raw or "")
    if not data:
        return result

    try:
        conf = float(data.get("confidence", result.confidence))
    except (TypeError, ValueError):
        conf = result.confidence

    formatted = str(data.get("formatted") or result.formatted).strip()
    postal = str(data.get("postal_code") or result.postal_code).strip().upper()
    if postal and len(postal) == 6:
        postal = f"{postal[:3]} {postal[3:]}"

    issues = list(data.get("issues") or result.issues)
    suggestions = list(data.get("suggestions") or result.suggestions)

    return AddressParseResult(
        raw=result.raw,
        formatted=formatted or result.formatted,
        street=str(data.get("street") or result.street),
        city=str(data.get("city") or result.city),
        province=str(data.get("province") or result.province),
        postal_code=postal or result.postal_code,
        confidence=max(0.0, min(1.0, conf)),
        needs_confirmation=conf < CONFIRM_THRESHOLD or len(issues) > 0,
        issues=issues,
        suggestions=suggestions[:3],
        lat=result.lat,
        lng=result.lng,
    )
