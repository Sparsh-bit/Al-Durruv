"""Sea routes (self-hosted auto-sea-way) and the freshness staleness policy. HTTP is mocked to the contract in
app/connectors/seaway.py; the live check against a running service is in docs/RUNBOOK.md."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import get_settings
from app.connectors import seaway
from app.connectors.http import ConnectorError
from app.models import RouteLocation
from app.routers import intel

KEY = "asw-test-key-NOT-REAL"
ROUTE = {
    "distance_nm": 6170.4,
    "raw_hops": 900,
    "smooth_hops": 120,
    "geometry": {"type": "LineString", "coordinates": [[29.9, 31.2], [-5.6, 36.0], [-95.0, 29.3]]},
    "shore_buffer_nm": 0.0,
    "land_legs": [],
}


@pytest.fixture
def asw(monkeypatch):
    monkeypatch.setattr(get_settings(), "asw_base_url", "http://asw.test:3000/")
    monkeypatch.setattr(get_settings(), "asw_api_key", KEY)
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": dict(params or {}), "headers": headers})
        body = (
            {"nodes": 1, "edges": 2, "graph_path": "x", "version": "0.10.0", "graph_version": "g-1"}
            if url.endswith("/info")
            else ROUTE
        )
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(seaway.httpx, "get", get)
    return calls


def test_route_sends_key_caches_per_graph_and_labels_output(db, asw):
    r = seaway.route(db, (31.2, 29.9), (29.3, -95.0))
    assert r["distance_nm"] == 6170.4 and r["distance_km"] == round(6170.4 * 1.852, 1)
    assert r["confidence"] == "calculated" and "OpenStreetMap" in r["source"] and r["graph_version"] == "g-1"
    route_call = next(c for c in asw if c["url"].endswith("/route"))
    assert route_call["url"] == "http://asw.test:3000/route" and route_call["headers"] == {"X-Api-Key": KEY}
    assert route_call["params"]["from"] == "31.200000,29.900000"
    assert "_graph" not in route_call["params"]
    n = len(asw)
    seaway.route(db, (31.2, 29.9), (29.3, -95.0))
    assert len(asw) == n  # info and route both served from cache
    db.rollback()


def test_route_errors_are_truthful(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "asw_base_url", "")
    with pytest.raises(ConnectorError, match="not configured"):
        seaway.route(db, (0, 0), (1, 1))
    monkeypatch.setattr(get_settings(), "asw_base_url", "http://asw.test")
    monkeypatch.setattr(get_settings(), "asw_api_key", KEY)
    for status, msg in [(401, "rejected"), (503, "starting"), (422, "no water")]:
        monkeypatch.setattr(
            seaway.httpx,
            "get",
            lambda url, status=status, **kw: httpx.Response(
                status, json={"error": "no water path"}, request=httpx.Request("GET", url)
            ),
        )
        with pytest.raises(ConnectorError, match=msg):
            seaway._get("/route")
    with pytest.raises(ConnectorError, match="out of range"):
        seaway._coord(91, 0)
    with pytest.raises(ConnectorError, match="Speed"):
        seaway.sailing_days(1000, 0.5)
    assert seaway.sailing_days(4800, 20) == 10.0


def test_sea_route_endpoint(db, viewer, asw):
    def loc(geo, **raw):
        r = RouteLocation(carrier_geo_id=geo, location_name=geo, raw=raw)
        db.add(r)
        return r

    a, b, c = (
        loc("SEATEST0000A", latitude="31.2", longitude="29.9"),
        loc("SEATEST0000B", latitude="29.3", longitude="-95"),
        loc("SEATEST0000C"),
    )
    db.commit()
    try:
        ok = viewer.get(f"/api/sea-routes?origin_location_id={a.id}&destination_location_id={b.id}&speed_knots=18")
        assert ok.status_code == 200, ok.text
        body = ok.json()
        assert body["distance_nm"] == 6170.4 and body["sailing_time_estimate"]["confidence"] == "estimate"
        assert "Maersk" in body["coordinates_source"]
        same = viewer.get(f"/api/sea-routes?origin_location_id={a.id}&destination_location_id={a.id}")
        nocoord = viewer.get(f"/api/sea-routes?origin_location_id={a.id}&destination_location_id={c.id}")
        missing = viewer.get(f"/api/sea-routes?origin_location_id={a.id}&destination_location_id=999999")
        assert (same.status_code, nocoord.status_code, missing.status_code) == (422, 422, 404)
    finally:
        for r in (a, b, c):
            db.delete(r)
        db.commit()


def test_staleness_policy():
    now = datetime.now(UTC)
    fresh = intel._staleness({"key": "fx", "last_retrieved": (now - timedelta(days=2)).isoformat()}, now)
    old = intel._staleness({"key": "fx", "last_retrieved": (now - timedelta(days=30)).isoformat()}, now)
    lagging = intel._staleness({"key": "census", "last_retrieved": now.isoformat(), "latest_period": "2025-01"}, now)
    never = intel._staleness({"key": "comext", "last_retrieved": None, "rows": 5}, now)
    assert fresh["stale"] is False and old["stale"] is True and old["stale_reasons"]
    assert never["stale"] is True and lagging["stale"] is True


def test_every_statement_label_renders_in_a_report_pdf():
    from app.ai.claude import Statement
    from app.reports import LABEL_COLORS, render_pdf

    labels = Statement.model_fields["label"].annotation.__args__
    assert set(labels) <= set(LABEL_COLORS)
    content = {
        "title": "T",
        "product": "P",
        "hs_code": "200290",
        "hs_description": "d",
        "generated_at": "2026-10-30T10:00:00",
        "validation": {"exported": len(labels), "withheld": 0},
        "evidence": [],
        "sections": [{"title": "S", "statements": [{"text": "x", "label": x, "evidence_ids": []} for x in labels]}],
    }
    assert render_pdf({"content": content}).startswith(b"%PDF")


def test_arabic_company_name_downloads_with_a_safe_file_name(db, viewer):
    from app.models import Company

    c = Company(
        name="شركة الدرة",
        country_iso3="EGY",
        brief={
            "company": "x",
            "generated_at": "2026-10-30T10:00:00",
            "language": "en",
            "sections": [],
            "evidence": [],
        },
    )
    db.add(c)
    db.commit()
    try:
        r = viewer.get(f"/api/companies/{c.id}/brief/pdf")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        assert 'filename="brief-company.pdf"' in r.headers["content-disposition"]
    finally:
        db.delete(c)
        db.commit()


def test_no_ai_vendor_name_reaches_the_client(viewer):
    assert "model" not in viewer.get("/api/health").json()
