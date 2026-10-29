"""Maersk Commodities and Locations integration: auth header, caching, limits, errors, workflow, no secret leaks.

HTTP is mocked with responses shaped by the official OpenAPI schema examples (see fixtures/maersk_README.md).
Live calls are verified separately once MAERSK_CONSUMER_KEY is configured.
"""

import json
import logging
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.connectors import maersk, sources
from app.models import AuditLog, HSCode, Product

FIX = Path(__file__).parent / "fixtures"
SECRET = "test-consumer-key-NOT-REAL-123"
COMMODITIES = json.loads((FIX / "maersk_commodities.json").read_text())
LOCATIONS = json.loads((FIX / "maersk_locations.json").read_text())


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
        status, body, hdrs = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return httpx.Response(status, json=body, headers=hdrs or {}, request=httpx.Request("GET", url))


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(get_settings(), "maersk_consumer_key", SECRET)
    for q in maersk._calls.values():
        q.clear()
    monkeypatch.setattr(maersk.time, "sleep", lambda s: None)
    monkeypatch.setattr(sources, "iso2_to_iso3", lambda: {"US": "USA", "EG": "EGY", "JO": "JOR"})


def fake(monkeypatch, *responses):
    f = FakeHTTP(responses)
    monkeypatch.setattr(maersk.httpx, "get", f)
    return f


def _product(db, **kw):
    db.execute(
        insert(HSCode).values([{"code": c, "description": c} for c in ("200290", "210320")]).on_conflict_do_nothing()
    )
    p = Product(
        sku="T-1", name="Tomato Paste", hs_code="200290", client_hs_code="2103200090", hs_status="discrepancy", **kw
    )
    db.add(p)
    db.commit()
    return p


def test_not_configured_is_a_clear_503(db, viewer):
    r = viewer.get("/api/maersk/commodities", params={"q": "tomato"})
    assert r.status_code == 503 and "MAERSK_CONSUMER_KEY" in r.json()["detail"]
    assert viewer.get("/api/maersk/status").json()["configured"] is False


def test_commodity_search_sends_consumer_key_and_caches(db, viewer, keyed, monkeypatch):
    f = fake(monkeypatch, (200, COMMODITIES, None))
    r = viewer.get("/api/maersk/commodities", params={"q": "tomato paste"}).json()
    assert f.calls[0]["url"] == "https://api.maersk.com/commodity-classifications"
    assert f.calls[0]["headers"]["Consumer-Key"] == SECRET and f.calls[0]["params"] == {"commodityName": "tomato paste"}
    assert r["results"][1]["hs_codes"][0] == {"code": "200290", "name": "Tomatoes, prepared or preserved"}
    assert SECRET not in json.dumps(r) and "disclaimer" in r
    viewer.get("/api/maersk/commodities", params={"q": "tomato paste"})
    assert len(f.calls) == 1  # served from cache
    assert viewer.get("/api/maersk/commodities", params={"q": "x"}).status_code == 422  # needs 2 letters
    assert viewer.get("/api/maersk/commodities", params={"hs": "20029"}).status_code == 422


def test_upstream_errors_are_truthful_and_never_leak_the_key(db, viewer, keyed, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    fake(monkeypatch, (401, {"message": "Invalid ApiKey"}, None))
    r = viewer.get("/api/maersk/commodities", params={"q": "olive oil"})
    assert r.status_code == 502 and "Consumer Key" in r.json()["detail"] and SECRET not in r.text
    fake(monkeypatch, (429, {}, {"Retry-After": "30"}))
    r = viewer.get("/api/maersk/locations", params={"q": "Alexandria"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "30"
    fake(monkeypatch, (503, {}, None))
    r = viewer.get("/api/maersk/locations", params={"q": "Hamburg"})
    assert r.status_code == 503 and "unaffected" in r.json()["detail"]
    fake(monkeypatch, (400, {"message": "bad", "subErrors": [{"field": "cityName", "message": "invalid"}]}, None))
    r = viewer.get("/api/maersk/locations", params={"q": "Rotterdam"})
    assert r.status_code == 422 and "cityName: invalid" in r.json()["detail"]
    assert SECRET not in caplog.text
    assert viewer.get("/api/products").status_code == 200  # the rest of the platform keeps working


def test_local_rate_limit_stays_under_maersk_limits(db, keyed, monkeypatch):
    fake(monkeypatch, (200, [], None))
    monkeypatch.setattr(maersk, "LIMITS", {**maersk.LIMITS, "locations": (2, 100)})
    maersk._request("locations", maersk.LOCATIONS_URL, {"cityName": "a"})
    maersk._request("locations", maersk.LOCATIONS_URL, {"cityName": "b"})
    with pytest.raises(maersk.RateLimited):
        maersk._request("locations", maersk.LOCATIONS_URL, {"cityName": "c"})


def test_product_suggestions_keep_client_code_and_flag_matches(db, viewer, analyst, admin, keyed, monkeypatch):
    p = _product(db)
    f = fake(monkeypatch, (200, COMMODITIES, None))
    d = viewer.get(f"/api/products/{p.id}/maersk-commodities").json()
    assert f.calls[0]["params"] == {"commodityName": "Tomato Paste"}
    tomato = next(c for c in d["candidates"] if c["commodity_code"] == "000903")
    assert tomato["matches_analysis_hs6"] and not tomato["matches_client_hs6"]
    assert d["ambiguous"] and d["codes"][0] == {
        "source": "client",
        "label": "Client-provided code",
        "code": "2103200090",
        "hs6": "210320",
    }
    # analyst saves the reference without touching the analysis code
    r = analyst.post(f"/api/products/{p.id}/maersk-commodity", json={"commodity_code": "000903", "hs_code": "200290"})
    assert (
        r.status_code == 200
        and r.json()["client_hs_code"] == "2103200090"
        and r.json()["hs_source"] != "maersk_reference"
    )
    # only an admin may use it for analysis; the result is still 'needs review', never confirmed
    body = {"commodity_code": "000903", "hs_code": "200290", "use_for_analysis": True}
    assert analyst.post(f"/api/products/{p.id}/maersk-commodity", json=body).status_code == 403
    out = admin.post(f"/api/products/{p.id}/maersk-commodity", json=body).json()
    assert out["hs_source"] == "maersk_reference" and out["hs_status"] == "candidate"
    db.expire_all()
    assert db.get(Product, p.id).client_hs_code == "2103200090"
    # an HS code Maersk does not list for that commodity is refused (no invented mappings)
    bad = {"commodity_code": "000903", "hs_code": "999999"}
    assert analyst.post(f"/api/products/{p.id}/maersk-commodity", json=bad).status_code == 422
    assert db.scalars(select(AuditLog.action).where(AuditLog.action == "maersk_commodity")).all()


def test_no_match_lets_the_user_continue(db, viewer, keyed, monkeypatch):
    p = _product(db)
    fake(monkeypatch, (404, {"message": "No commodity groups found"}, None))
    d = viewer.get(f"/api/products/{p.id}/maersk-commodities").json()
    assert d["candidates"] == [] and "needing review" in d["message"]


def test_location_search_is_explicit_and_saved_locations_feed_quotes(db, viewer, analyst, admin, keyed, monkeypatch):
    f = fake(monkeypatch, (200, LOCATIONS, {"Next-Page": "abc"}))
    r = viewer.get("/api/maersk/locations", params={"q": "Houston", "country": "USA"}).json()
    assert f.calls[0]["url"] == "https://api.maersk.com/reference-data/locations"
    assert f.calls[0]["params"] == {"limit": 25, "cityName": "Houston", "countryCode": "US"}
    assert r["ambiguous"] and r["next_page"] == "abc" and r["results"][0]["un_location_code"] == "USHOU"
    assert r["results"][0]["carrier_geo_id"] == "0UGZOU2O902YE"  # Geo ID and UN/LOCODE kept apart
    # 'Cairo' looks like a UN/LOCODE but is searched as a name unless the user chooses UN/LOCODE mode
    viewer.get("/api/maersk/locations", params={"q": "Cairo"})
    assert f.calls[-1]["params"]["cityName"] == "Cairo"
    viewer.get("/api/maersk/locations", params={"q": "egaly", "mode": "unlocode"})
    assert f.calls[-1]["params"]["UNLocationCode"] == "EGALY"
    assert viewer.get("/api/maersk/locations", params={"q": "EGA", "mode": "unlocode"}).status_code == 422
    # saving re-reads the location by Geo ID from Maersk; nothing from the browser is trusted
    f2 = fake(monkeypatch, (200, LOCATIONS[0], None))
    saved = analyst.post("/api/route-locations", json={"carrier_geo_id": "0UGZOU2O902YE"}).json()
    assert f2.calls[0]["url"].endswith("/carrier-locations/0UGZOU2O902YE")
    assert saved["country_iso3"] == "USA" and saved["un_location_code"] == "USHOU"
    assert viewer.post("/api/route-locations", json={"carrier_geo_id": "0UGZOU2O902YE"}).status_code == 403
    assert viewer.get("/api/maersk/locations/short").status_code == 422
    q = admin.post(
        "/api/logistics",
        json={
            "origin": "Alexandria",
            "origin_iso3": "EGY",
            "destination": "Houston",
            "destination_iso3": "USA",
            "mode": "sea",
            "source_note": "Forwarder quote, Oct 2026",
            "destination_location_id": saved["id"],
        },
    )
    assert q.status_code == 201 and q.json()["destination_location_id"] == saved["id"]
    assert (
        admin.post("/api/logistics", json={**q.json(), "source_note": "x x x", "origin_location_id": 9999}).status_code
        == 422
    )


def test_ai_evidence_labels_maersk_reference_and_calculated(db, keyed):
    from app.ai.grounding import Evidence, build_context, validate_statements

    p = _product(
        db,
        maersk_commodity={
            "commodity_code": "000903",
            "commodity_name": "Tomato paste",
            "hs_codes": [{"code": "200290", "name": "x"}],
            "retrieved_at": "2026-10-29",
        },
    )
    ev = build_context(db, p.hs_code)
    text = " ".join(e.text for e in ev)
    assert "Maersk commodity reference" in text and "not a customs classification" in text
    out = validate_statements(
        [{"text": "Score is 50.", "label": "calculated", "evidence_ids": ["E1"]}],
        [Evidence("E1", "client", "x", [50.0])],
    )
    assert out[0]["label"] == "inference"  # 'calculated' must cite computed evidence


def test_status_never_returns_the_key(db, admin, keyed):
    for path in ("/api/maersk/status", "/api/admin/sources", "/api/health"):
        assert SECRET not in admin.get(path).text
    assert admin.get("/api/maersk/status").json()["configured"] is True


def test_security_headers(viewer):
    h = viewer.get("/api/health").headers
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert "geolocation=()" in h["Permissions-Policy"] and h["Cross-Origin-Opener-Policy"] == "same-origin"


# --- WTO Timeseries tariffs (HTTP mocked; shapes from the portal's DataPointExtended model) --------------


def test_wto_tariffs_resolve_codes_by_name_and_store_caveats(db, monkeypatch):
    from app.connectors import wto
    from app.models import Tariff

    monkeypatch.setattr(get_settings(), "wto_api_key", "wto-test-key-NOT-REAL")
    monkeypatch.setattr(wto.time, "sleep", lambda s: None)
    wto._calls.clear()
    db.execute(insert(HSCode).values([{"code": "200290", "description": "x"}]).on_conflict_do_nothing())
    seen = []

    def get(url, params=None, headers=None, timeout=None):
        seen.append((url, dict(params or {}), dict(headers or {})))
        if url.endswith("/indicators"):
            body = [
                {"code": "HS_A_0010", "name": "HS MFN - Simple average ad valorem duty"},
                {"code": "HS_A_0020", "name": "HS MFN - Maximum  ad valorem duty"},
                {"code": "HS_A_0030", "name": "HS MFN - Number of NAV tariff lines"},
            ]
        elif url.endswith("/reporters"):
            body = [
                {"code": "918", "name": "European Union", "iso3A": "EUN"},
                {"code": "392", "iso3A": "JPN", "name": "Japan"},
            ]
        else:
            v = {"HS_A_0010": 14.4, "HS_A_0020": 18.0, "HS_A_0030": 1}[params["i"]]
            body = {"Dataset": [{"Year": 2023, "Value": v - 1}, {"Year": 2024, "Value": v}]}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(wto.httpx, "get", get)
    rows = wto.load_tariffs(db, "EUN", "200290")
    mfn = next(t for t in rows if t.rate_type == "MFN")
    assert mfn.ad_valorem_pct == 14.4 and mfn.data_year == 2024 and mfn.source == "wto"
    assert "up to 18%" in mfn.notes and "non-ad-valorem" in mfn.notes
    assert all(h["Ocp-Apim-Subscription-Key"] == "wto-test-key-NOT-REAL" for _u, _p, h in seen)
    assert all("subscription-key" not in p for _u, p, _h in seen)  # key only in the header
    assert seen[-1][1]["r"] == "918" and seen[-1][1]["pc"] == "200290"
    assert db.query(Tariff).filter(Tariff.source == "wto").count() == 1
    n = len(seen)
    wto.load_tariffs(db, "EUN", "200290")
    assert len(seen) == n  # cached
    monkeypatch.setattr(get_settings(), "wto_api_key", "")
    with pytest.raises(Exception, match="WTO_API_KEY"):
        wto._get("/indicators", {})
