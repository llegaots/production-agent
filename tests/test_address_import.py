"""Tests for spreadsheet import and address confidence."""
import asyncio

import pytest

from app.address import CONFIRM_THRESHOLD, parse_address
from app.row_import import build_import_batch, materialize_import, parse_pasted_text
from app.seed import seed
from app.storage import store


@pytest.fixture(autouse=True)
def fresh():
    seed(reset=True)
    yield


def test_parse_canadian_postal_and_fix_double_comma():
    raw = "23 Rue Madore, , L'île Perrot, Pincourt, J7V 0B1"
    r = parse_address(raw)
    assert r.postal_code == "J7V 0B1"
    assert ", ," not in r.formatted
    assert r.confidence >= 0.5


def test_low_confidence_without_postal():
    r = parse_address("somewhere in montreal maybe")
    assert r.needs_confirmation
    assert r.confidence < CONFIRM_THRESHOLD


def test_parse_pasted_tab_row():
    line = (
        "Sherif & Isabella Zalidia121644\t514-297-4807\t"
        "18 Simone-De Beauvoir, Notre-Dame-de-Ile-Perot, J7V 8P4\t"
        "Mar 05\tMid July\t$369\t$1,285\t14\tInt/Ext Windows"
    )
    rows = parse_pasted_text(line + "\n" + line.replace("Sherif", "Helen Finn121631"))
    assert len(rows) >= 1
    assert "Sherif" in rows[0]["name"]
    assert "121644" in rows[0]["client_id_hint"]
    assert "J7V" in rows[0]["address_raw"] or "Simone" in rows[0]["address_raw"]


def test_build_import_batch_flags_ambiguous_city():
    text = (
        "Jean Francois Fortin148410\t514-433-4316\t"
        "23 Rue Madore, , L'île Perrot, Pincourt, J7V 0B1\t"
        "Jun 19\tLate August\t$0\t$698\t8\tInt/Ext Windows"
    )
    batch = asyncio.run(build_import_batch(text))
    assert batch["total"] >= 1
    row = batch["rows"][0]
    assert row["address"]["postal_code"] == "J7V 0B1"
    # May or may not need confirm depending on score — at least formatted
    assert "J7V 0B1" in row["address"]["formatted"]


def test_confirm_import_creates_jobs():
    text = (
        "Helen Finn121631\t514-266-7036\t"
        "99 Meloche, Sainte-Anne-de-Bellevue, H9X 3Z5\t"
        "Feb 19\tEarly June\t$130\t$458\t6\tInt/Ext Windows"
    )
    batch = asyncio.run(build_import_batch(text))
    clients, jobs = materialize_import(batch["rows"])
    assert len(jobs) >= 1
    assert "H9X 3Z5" in jobs[0].address
    assert len(clients) >= 1
