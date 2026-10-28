"""Connectors (parsers against recorded real responses), shipments pipeline, entity resolution, buyer analytics,
landed cost, retailer/competitor views, alerts, security guards."""

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.connectors import sources
from app.connectors.http import cache_key
from app.exports import safe_cell
from app.models import (
    AiUsage,
    Alert,
    AuditLog,
    Company,
    Country,
    HSCode,
    LogisticsQuote,
    Product,
    Shipment,
    SourceRecord,
    Tariff,
    TradeObservation,
)
from app.services import intel, settings
from app.services.shipments import normalize_name

FIX = Path(__file__).parent / "fixtures"
ISO2 = {"DE": "DEU", "EG": "EGY", "TR": "TUR", "FR": "FRA", "US": "USA", "JO": "JOR"}


def fixture(name):
    return json.loads((FIX / name).read_text())


# --- connector parsers (recorded live responses, 28 Oct 2026) -------------------------------------


def test_comext_jsonstat_parser():
    rows = sources.comext_rows(fixture("comext_de_200290.json"), ISO2)
    assert {(r["partner_iso3"], r["period"]) for r in rows} == {
        ("EGY", "2025-06"),
        ("EGY", "2025-07"),
        ("TUR", "2025-06"),
        ("TUR", "2025-07"),
    }
    eg = next(r for r in rows if r["partner_iso3"] == "EGY" and r["period"] == "2025-06")
    assert eg["value_eur"] == 140702 and eg["kg"] == pytest.approx(1499.56 * 100)
    assert all(r["reporter_iso3"] == "DEU" for r in rows)


def test_wits_parser_mfn_and_preferential():
    assert sources.wits_rate(fixture("wits_usa_mfn_200290.json")) == (pytest.approx(11.6), "MFN")
    rate, kind = sources.wits_rate(fixture("wits_eu_egy_pref_200290.json"))
    assert rate == 0 and kind.upper().startswith("PREF")


def test_usitc_lines_and_jordan_preference():
    lines = sources.usitc_lines(fixture("usitc_hts_2002_90.json"), "200290")
    assert {line["htsno"] for line in lines} == {"2002.90.40.00", "2002.90.80"}
    assert sources.parse_percent(lines[0]["general"]) == pytest.approx(11.6)
    assert "JO" in lines[0]["special"] and sources.parse_percent("Free (A,JO)") == 0.0
    assert sources.parse_percent("2.8¢/kg") is None


def test_fx_parser_and_census_shape():
    rates = sources.parse_fx(fixture("frankfurter_eur_usd_2025q1.json"), "USD")
    assert rates["2025-01-02"]["USD"] == pytest.approx(1.0321)
    variables = fixture("census_variables.json")
    assert {"CTY_CODE", "CTY_NAME", "GEN_VAL_MO", "I_COMMODITY", "time"} <= set(variables)
    payload = [
        [
            "CTY_CODE",
            "CTY_NAME",
            "I_COMMODITY",
            "GEN_VAL_MO",
            "GEN_QY1_MO",
            "UNIT_QY1",
            "AIR_WGT_MO",
            "VES_WGT_MO",
            "time",
        ],
        ["-", "TOTAL FOR ALL COUNTRIES", "200290", "1000", "50", "KG", "0", "60", "2025-06"],
        ["0003", "EUROPE", "200290", "400", "", "", "", "", "2025-06"],
        ["7290", "EGYPT", "200290", "250", "12", "KG", "0", "13", "2025-06"],
    ]
    rows = sources.census_rows(payload, {"EGYPT": "EGY"})
    assert [(r["partner_iso3"], r["value_usd"], r["kg"]) for r in rows] == [("WLD", 1000, 60), ("EGY", 250, 13)]


def test_cache_keys_never_include_secrets():
    assert cache_key("census", "u", {"time": "2025-06", "key": "SECRET"}) == cache_key(
        "census", "u", {"time": "2025-06"}
    )


def test_census_without_key_is_a_truthful_error(db):
    with pytest.raises(sources.ConnectorError, match="CENSUS_API_KEY"):
        sources.load_census(db, "200290", ["2025-06"])


# --- entity resolution ------------------------------------------------------------------------------


def test_normalize_name_variants():
    assert normalize_name("Al-Durra Food Products Co., Ltd.") == normalize_name("ALDURRA FOOD PRODUCTS")
    assert normalize_name("El Durra Foods S.A.L") == normalize_name("Al Durra Foods")
    assert normalize_name("Smith & Sons LLC") == "SMITH AND SONS"
    assert normalize_name("Société Générale SARL") == "SOCIETE GENERALE"
    assert normalize_name("Kroger") != normalize_name("Krogers Market")
    assert normalize_name("The Kroger Co.") == normalize_name("Kroger Co") == "KROGER"


# --- shipments pipeline -------------------------------------------------------------------------------


def _countries(db):
    rows = [
        {"m49": 842, "iso3": "USA", "name": "USA"},
        {"m49": 818, "iso3": "EGY", "name": "Egypt"},
        {"m49": 792, "iso3": "TUR", "name": "Türkiye"},
        {"m49": 400, "iso3": "JOR", "name": "Jordan"},
        {"m49": 528, "iso3": "NLD", "name": "Netherlands"},
    ]
    db.execute(insert(Country).values(rows).on_conflict_do_nothing())
    db.execute(insert(HSCode).values([{"code": "200290", "description": "Tomatoes"}]).on_conflict_do_nothing())
    db.commit()


HEADER = [
    "Arrival Date",
    "Shipper",
    "Consignee",
    "Country of Origin",
    "Destination Country",
    "HS Code",
    "Product Description",
    "Weight (kg)",
    "Bill of Lading Number",
]


def _csv(rows):
    buf = io.StringIO()
    csv.writer(buf).writerows([HEADER, *rows])
    return buf.getvalue().encode()


def _months_ago(n):
    return (date.today() - timedelta(days=30 * n)).isoformat()


ROWS = [
    [_months_ago(10), "Tukas Gida AS", "Acme Foods LLC", "Turkey", "USA", "2002.90.80", "TOMATO PASTE", "20000", "B1"],
    [_months_ago(8), "Tukas Gida AS", "Acme Foods LLC", "Turkey", "USA", "2002908010", "TOMATO PASTE", "20000", "B2"],
    [
        _months_ago(2),
        "Bertaya Food Industries",
        "ACME FOODS, LLC.",
        "Egypt",
        "USA",
        "200290",
        "TOMATO PASTE",
        "30000",
        "B3",
    ],
    [_months_ago(1), "Tukas Gida AS", "Kroger Co", "Turkey", "USA", "200290", "TOMATO PASTE", "5000", "B4"],
    ["not a date", "X", "Y", "Turkey", "USA", "200290", "", "1", "B5"],
]


def _upload(admin, rows=ROWS, name="ig.csv"):
    preview = admin.post(
        "/api/shipments/preview", files={"file": (name, _csv(rows), "text/csv")}, data={"provider": "importgenius"}
    ).json()
    return preview, admin.post(
        "/api/shipments/import",
        files={"file": (name, _csv(rows), "text/csv")},
        data={"provider": "importgenius", "mapping": json.dumps(preview["suggested_mapping"])},
    )


def test_upload_maps_validates_dedupes_and_resolves(db, admin, analyst):
    _countries(db)
    preview, r = _upload(admin)
    assert set(preview["suggested_mapping"]) >= {"shipped_on", "shipper_name", "consignee_name", "origin", "hs_code"}
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["inserted"] == 4 and b["duplicates"] == 0 and b["errors"][0]["line"] == 6
    assert (
        admin.post(
            "/api/shipments/import",
            files={"file": ("ig.csv", _csv(ROWS), "text/csv")},
            data={"provider": "importgenius", "mapping": "{}"},
        ).status_code
        == 409
    )  # same file again
    _p, again = _upload(admin, ROWS[:2] + [ROWS[1]], "ig2.csv")  # overlapping rows, different file
    assert again.json()["inserted"] == 0 and again.json()["duplicates"] == 3
    acme = db.scalars(select(Company).where(Company.normalized_name == "ACME FOODS")).all()
    assert len(acme) == 1  # "Acme Foods LLC" and "ACME FOODS, LLC." resolved to one record
    s = db.scalar(select(Shipment).where(Shipment.row_key == "B2"))
    assert s.hs_code == "2002908010" and s.hs6 == "200290" and s.origin_iso3 == "TUR"
    assert (
        analyst.post(
            "/api/shipments/preview", files={"file": ("x.csv", b"a\n1", "text/csv")}, data={"provider": "x"}
        ).status_code
        == 403
    )
    bad = admin.post("/api/shipments/preview", files={"file": ("x.txt", b"a", "text/plain")}, data={"provider": "x"})
    assert bad.status_code == 422
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "upload")) == 2


def test_malformed_mapping_is_rejected(db, admin):
    _countries(db)
    r = admin.post(
        "/api/shipments/import",
        files={"file": ("m.csv", _csv(ROWS), "text/csv")},
        data={"provider": "panjiva", "mapping": json.dumps({"product_description": "Product Description"})},
    )
    assert r.status_code == 422 and "date column" in r.json()["detail"]
    assert (
        admin.post(
            "/api/shipments/import",
            files={"file": ("m.csv", _csv(ROWS), "text/csv")},
            data={"provider": "panjiva", "mapping": "not json"},
        ).status_code
        == 422
    )


def test_buyer_metrics_fit_score_and_tracker(db, admin, viewer):
    _countries(db)
    db.add(Product(sku="T1", name="Tomato Paste", hs_code="200290", client_hs_code="2103200090"))
    db.commit()
    _upload(admin)
    settings.put(db, "client_shipper_aliases", ["Bertaya Food Industries"])
    db.commit()
    res = viewer.get("/api/buyers", params={"hs": "200290", "market": "USA"}).json()
    acme = next(b for b in res["buyers"] if b["company"]["name"] == "Acme Foods LLC")
    m = acme["metrics"]
    assert m["shipments_12m"] == 3 and m["weight_kg_12m"] == 70000 and m["new_origins_6m"] == ["EGY"]
    assert acme["components"]["category_match"] == 100 and acme["components"]["supplier_change"] == 100
    assert acme["components"]["displaceable_origins"] == pytest.approx(100 * 40000 / 70000, rel=1e-3)
    assert 0 <= acme["score"] <= 100 and "category_match" in res["labels"]
    tukas = db.scalar(select(Company).where(Company.normalized_name == "TUKAS GIDA"))
    tukas.relationship_type = "competitor"
    db.commit()
    t = viewer.get(f"/api/competitors/{tukas.id}/tracker").json()
    assert {b["name"] for b in t["buyers"]} == {"Acme Foods LLC", "Kroger Co"}
    assert [b["name"] for b in t["not_our_buyers"]] == ["Kroger Co"]  # Acme also buys from the client
    assert admin.put("/api/buyers/weights", json=dict.fromkeys(intel.DEFAULT_FIT_WEIGHTS, 0)).status_code == 422
    assert viewer.put("/api/buyers/weights", json=intel.DEFAULT_FIT_WEIGHTS).status_code == 403


def test_retailer_path_direct_and_route_in(db, admin, viewer):
    _countries(db)
    db.add(Product(sku="T1", name="Tomato Paste", hs_code="200290"))
    kroger = Company(
        name="The Kroger Co.",
        country_iso3="USA",
        relationship_type="retailer",
        aliases=["Kroger Co"],
        normalized_name=normalize_name("The Kroger Co."),
    )
    db.add(kroger)
    db.commit()
    _upload(admin)
    r = viewer.get(f"/api/retailers/{kroger.id}/path").json()
    assert r["direct_importer"] and r["suppliers"][0]["shipper"] == "Tukas Gida AS"
    assert any(b["company"]["name"] == "Acme Foods LLC" for b in r["route_in"])
    assert (
        admin.post(
            "/api/requirements",
            json={
                "company_id": kroger.id,
                "title": "Register as prospect vendor",
                "source_url": "https://www.thekrogerco.com/vendor-suppliers/supplier-hub/",
            },
        ).status_code
        == 201
    )
    assert viewer.post("/api/requirements", json={"title": "x x x", "source_url": "https://a.b"}).status_code == 403
    assert len(viewer.get(f"/api/retailers/{kroger.id}/path").json()["requirements"]) == 1


def test_alerts_are_generated_once(db, admin, viewer):
    _countries(db)
    db.add(Product(sku="T1", name="Tomato Paste", hs_code="200290"))
    db.commit()
    _upload(admin)
    first = viewer.get("/api/alerts").json()
    assert any(a["type"] == "new_origin" for a in first)
    assert admin.post("/api/alerts/run").json()["created"] == 0  # deduplicated
    viewer.post(f"/api/alerts/{first[0]['id']}/read")
    assert len(viewer.get("/api/alerts", params={"unread": True}).json()) == len(first) - 1
    assert db.scalar(select(func.count()).select_from(Alert)) == len(first)


def test_landed_cost_and_best_factory(db, admin, viewer):
    _countries(db)
    src = SourceRecord(adapter="un_comtrade", url="https://comtradeapi.un.org/x")
    db.add(src)
    db.flush()
    db.add(
        TradeObservation(
            reporter_m49=842,
            partner_m49=0,
            hs_code="200290",
            flow="M",
            year=2024,
            value_usd=100_000,
            net_weight_kg=50_000,
            source_record_id=src.id,
        )
    )
    db.add(
        TradeObservation(
            reporter_m49=842,
            partner_m49=818,
            hs_code="200290",
            flow="M",
            year=2024,
            value_usd=10_000,
            net_weight_kg=None,
            source_record_id=src.id,
        )
    )
    for origin, cost in (("EGY", 2600), ("JOR", 3400)):
        db.add(
            LogisticsQuote(
                origin=origin,
                origin_iso3=origin,
                destination="New York",
                destination_iso3="USA",
                mode="sea",
                container="40ft",
                cost_usd=cost,
                payload_kg=20000,
                transit_days=24,
                provenance="estimate",
            )
        )
    db.add_all(
        [
            Tariff(importer_iso3="USA", hs_code="2002908000", rate_type="MFN", ad_valorem_pct=11.6, source="usitc"),
            Tariff(
                importer_iso3="USA",
                hs_code="2002908000",
                origin_iso3="JOR",
                rate_type="preferential",
                ad_valorem_pct=0,
                source="usitc",
                agreement="US special program JO",
            ),
        ]
    )
    db.commit()
    r = viewer.get("/api/access", params={"market": "USA", "hs": "200290"}).json()
    by = {o["origin_iso3"]: o for o in r["origins"]}
    assert r["benchmark"]["usd_per_kg"] == 2.0
    egy, jor = by["EGY"], by["JOR"]
    assert egy["duty"]["rate_pct"] == pytest.approx(11.6) and jor["duty"]["rate_pct"] == 0
    assert egy["landed_usd_per_kg"] == pytest.approx((2 + 0.13 + 0.01) * 1.116)
    assert jor["landed_usd_per_kg"] == pytest.approx(2 + 0.17 + 0.01)
    assert r["best_origin"] == "JOR"
    assert by["EGY"]["origin_unit_value"]["excluded"] == 1  # row without weight is excluded, not zero
    assert "SYR" in by and by["SYR"]["landed_usd_per_kg"] is None and "freight" in by["SYR"]["missing"]
    assert (
        admin.post(
            "/api/tariffs",
            json={
                "importer_iso3": "usa",
                "hs_code": "200290",
                "origin_iso3": "EGY",
                "rate_type": "additional",
                "ad_valorem_pct": 10,
                "source_url": "https://hts.usitc.gov/",
            },
        ).status_code
        == 201
    )
    r2 = viewer.get("/api/access", params={"market": "USA", "hs": "200290"}).json()
    assert {o["origin_iso3"]: o for o in r2["origins"]}["EGY"]["duty"]["rate_pct"] == pytest.approx(21.6)
    assert viewer.post("/api/tariffs", json={}).status_code == 403
    assert viewer.get("/api/access", params={"market": "USA", "hs": "99"}).status_code == 422


# --- security guards ----------------------------------------------------------------------------------


def test_csv_injection_neutralised(db, admin):
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and safe_cell("+1") == "'+1" and safe_cell(5) == 5
    db.add(HSCode(code="200290", description="x")) if not db.get(HSCode, "200290") else None
    db.add(Product(sku="X1", name="=cmd|' /C calc'!A0", hs_code="200290"))
    db.commit()
    text = admin.get("/api/products/export").content.decode("utf-8-sig")
    assert "'=cmd" in text and ",=cmd" not in text
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "export")) == 1


def test_roles_admin_only_actions(analyst, viewer):
    for method, path, kw in [
        ("post", "/api/admin/etl", {"json": {"connector": "fx"}}),
        ("post", "/api/markets/refresh-missing", {}),
        ("post", "/api/logistics", {"json": {}}),
        ("post", "/api/alerts/run", {}),
        ("delete", "/api/tariffs/1", {}),
        ("post", "/api/companies/1/merge", {"json": {"into_id": 2}}),
    ]:
        assert getattr(analyst, method)(path, **kw).status_code == 403, path
    assert viewer.get("/api/admin/freshness").status_code == 200


def test_daily_ai_limit_per_user(db, analyst, ai_on, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_daily_limit_per_user", 2)
    from app.models import User

    u = db.scalar(select(User).where(User.email == "analyst@example.com"))
    for _ in range(2):
        db.add(AiUsage(user_id=u.id, feature="analyst", model="claude-haiku-5-5", created_at=datetime.now(UTC)))
    db.commit()
    r = analyst.post("/api/ai/ask", json={"hs_code": "190531", "question": "Best market?"})
    assert r.status_code == 429 and "Daily AI limit" in r.json()["detail"]


def test_login_is_audited(db, viewer):
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "login")) >= 1


def test_tariff_run_makes_one_request_per_origin(db, monkeypatch):
    from app.services import etl

    calls = []
    monkeypatch.setattr(sources, "load_usitc", lambda db, hs: calls.append(("usitc", hs)) or [1, 2])

    def wits(db, market, hs, origin="", year=None):
        calls.append(("wits", market, origin, year))
        return (object(), 2022) if not origin or origin == "EGY" else (None, None)

    monkeypatch.setattr(sources, "load_wits", wits)
    n = etl._dispatch(db, "tariffs", {"hs_codes": ["200290"], "markets": ["USA", "EUN"], "origins": ["EGY", "JOR"]})
    assert calls == [
        ("usitc", "200290"),
        ("wits", "EUN", "", None),
        ("wits", "EUN", "EGY", 2022),
        ("wits", "EUN", "JOR", 2022),
    ]
    assert n == 2 + 1 + 1
