"""Acceptance criteria from the client brief (audit & gap-closure spec), one test or more per criterion."""

import csv
import json
import time

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.adapters import comtrade
from app.ai import claude
from app.ai.grounding import Evidence, validate_statements
from app.config import get_settings
from app.models import Clarification, Company, Country, Entity, HSCode, Product, SourceRecord, TradeObservation
from app.services import client_data, explore, trade

HS_ROWS = list(csv.DictReader(client_data.HS_LIST.open(encoding="utf-8")))
OFFICIAL_DOMAINS = ("walmart.com", "thekrogerco.com", "luluretail.com", "wam.ae")


def _hs_reference(db):
    codes = {r["analysis_hs6"] for r in HS_ROWS} | {"200570", "200599", "200899"}
    db.execute(insert(HSCode).values([{"code": c, "description": f"HS {c}"} for c in codes]).on_conflict_do_nothing())
    db.commit()


def _apply(db):
    _hs_reference(db)
    db.add(Product(sku="DUR-PKL-001", name="Pickled Cucumber", hs_code="200110", category="Pickles"))
    db.add(Product(sku="DUR-TOM-001", name="Tomato Paste", hs_code="200290", category="Tomato Paste"))
    db.add(Product(sku="DUR-OIL-001", name="Virgin Olive Oil", hs_code=None, category="Oils", hs_status="unmapped"))
    db.commit()
    return client_data.apply(db, force=True)


# 1. client HS codes are preserved exactly ------------------------------------------------------------


def test_client_hs_codes_preserved_verbatim(db, analyst, admin):
    _apply(db)
    by_code = {p.sku: p for p in db.scalars(select(Product))}
    assert by_code["DUR-PKL-001"].client_hs_code == "2001190000"
    molokhia = by_code["DUR-DRV-101"]
    assert molokhia.client_hs_code == "0712900010"  # leading zero kept
    assert molokhia.name_ar == "ملوخية ورق" and "row 8" in molokhia.client_hs_source
    # every client row lands on at least one product, with its code unchanged
    stored = {p.client_hs_code for p in by_code.values()}
    landed = [r for r in HS_ROWS if r["new_sku"] or set(r["skus"].split(";")) & set(by_code)]
    assert {r["client_hs_code"] for r in landed} <= stored
    # the API refuses to rewrite it
    p = by_code["DUR-TOM-001"]
    body = {"sku": p.sku, "name": p.name, "hs_code": "200290", "client_hs_code": "2002900000"}
    r = analyst.put(f"/api/products/{p.id}", json=body)
    assert r.status_code == 422 and "kept exactly" in r.json()["detail"]
    csv_bytes = b"sku,name,hs_code,client_hs_code\nDUR-TOM-001,Tomato Paste,200290,1111111111\n"
    res = admin.post("/api/products/import", files={"file": ("p.csv", csv_bytes, "text/csv")}).json()
    assert res["errors"] and "kept unchanged" in res["errors"][0]["error"]
    db.expire_all()
    assert db.get(Product, p.id).client_hs_code == "2103200090"


def test_reapplying_client_data_never_overwrites_review(db, analyst, admin):
    _apply(db)
    p = db.scalar(select(Product).where(Product.sku == "DUR-TOM-001"))
    admin.post(f"/api/products/{p.id}/hs-review", json={"hs_code": "200290", "status": "confirmed"})
    client_data.apply(db, force=True)
    db.expire_all()
    p = db.get(Product, p.id)
    assert p.hs_status == "confirmed" and p.hs_reviewed_at is not None
    assert db.scalar(select(func.count()).select_from(Company)) == 5  # not duplicated
    assert client_data.apply(db) == {"skipped": True}  # same file version


# 2. unverified classifications are flagged -----------------------------------------------------------


def test_unverified_codes_are_flagged_with_reasons(db, viewer):
    _apply(db)
    products = {p["sku"]: p for p in viewer.get("/api/products").json()}
    assert all(p["hs_status"] != "confirmed" for p in products.values())
    cucumber = products["DUR-PKL-001"]
    assert cucumber["hs_status"] == "discrepancy"  # client prefix 200119 does not exist
    assert any("not an HS6 subheading" in i for i in cucumber["hs_check"]["issues"])  # 200119 does not exist
    paste = products["DUR-TOM-001"]
    assert paste["hs_check"]["client_hs6"] == "210320" and not paste["hs_check"]["matches_client"]
    assert products["DUR-SNK-101"]["hs_status"] == "insufficient_info"
    assert products["DUR-OIL-001"]["hs_status"] == "unmapped"
    assert "No client HS code" in products["DUR-OIL-001"]["hs_check"]["issues"][0]
    hs_questions = db.scalars(select(Clarification).where(Clarification.topic == "hs")).all()
    assert any("Tomato Paste" in q.question for q in hs_questions)


def test_hs_review_requires_valid_code_and_is_audited(db, analyst, admin, viewer):
    _apply(db)
    p = db.scalar(select(Product).where(Product.sku == "DUR-TOM-001"))
    assert (
        admin.post(f"/api/products/{p.id}/hs-review", json={"hs_code": "999999", "status": "confirmed"}).status_code
        == 422
    )
    assert admin.post(f"/api/products/{p.id}/hs-review", json={"status": "confirmed"}).status_code == 422
    assert (
        viewer.post(f"/api/products/{p.id}/hs-review", json={"hs_code": "200290", "status": "confirmed"}).status_code
        == 403
    )
    ok = admin.post(f"/api/products/{p.id}/hs-review", json={"hs_code": "200290", "status": "confirmed"}).json()
    assert ok["hs_status"] == "confirmed" and ok["client_hs_code"] == "2103200090"
    assert any(e["action"] == "hs_review" for e in admin.get("/api/admin/audit").json())
    # editing the code afterwards drops the confirmation
    body = {"sku": p.sku, "name": p.name, "hs_code": "210320", "hs_status": "confirmed", "client_hs_code": "2103200090"}
    assert analyst.put(f"/api/products/{p.id}", json=body).status_code == 403  # mapping changes are admin-only
    assert admin.put(f"/api/products/{p.id}", json=body).json()["hs_status"] == "candidate"


def test_priority_categories_entities_and_clarifications_loaded(db, analyst):
    _apply(db)
    cats = {p.priority_category for p in db.scalars(select(Product)) if p.priority_category}
    assert {"Pickles", "Tomato paste", "Sauces"} <= cats
    assert db.scalar(select(Product.priority_category).where(Product.sku == "DUR-OIL-001")) == "Olive oil"
    names = {e.name: e for e in db.scalars(select(Entity))}
    assert names["Bertaya Food Industries"].country_iso3 == "EGY"
    assert all(e.status == "pending_verification" for e in names.values())
    questions = [c.question for c in db.scalars(select(Clarification))]
    assert any("three countries" in q for q in questions) and any("Molokai" in q for q in questions)
    c = db.scalar(select(Clarification).where(Clarification.topic == "market"))
    assert analyst.patch(f"/api/clarifications/{c.id}", json={"status": "answered"}).status_code == 422
    done = analyst.patch(f"/api/clarifications/{c.id}", json={"answer": "List attached", "status": "answered"}).json()
    assert done["status"] == "answered" and done["answered_at"]


# 3./4./5./6. Comtrade: real request or truthful error, metadata, gaps, comparability ----------------


def _countries(db):
    rows = [
        {"m49": 826, "iso3": "GBR", "name": "United Kingdom"},
        {"m49": 276, "iso3": "DEU", "name": "Germany"},
        {"m49": 250, "iso3": "FRA", "name": "France"},
        {"m49": 840, "iso3": "USA", "name": "United States of America"},
        {"m49": 842, "iso3": "USA", "name": "USA"},
    ]
    db.execute(insert(Country).values(rows).on_conflict_do_nothing())
    db.commit()


def _obs(db, hs="190531", data=None):
    _countries(db)
    src = SourceRecord(
        adapter="un_comtrade",
        url="https://comtradeapi.un.org/public/v1/preview/C/A/HS?x=1",
        reporting_period="2021,2022,2023",
        licence=comtrade.LICENCE,
    )
    db.add(src)
    db.flush()
    data = data or {826: {2021: 10e6, 2022: 12e6, 2023: 15e6}, 276: {2021: 20e6, 2022: 22e6}, 842: {2023: 50e6}}
    for m49, ys in data.items():
        for y, v in ys.items():
            db.add(
                TradeObservation(
                    reporter_m49=m49,
                    partner_m49=0,
                    hs_code=hs,
                    flow="M",
                    year=y,
                    value_usd=v,
                    net_weight_kg=v / 4,
                    qty=v / 4,
                    qty_unit="kg",
                    source_record_id=src.id,
                )
            )
    db.commit()


def test_explorer_keeps_metadata_and_never_fills_gaps_with_zero(db, viewer):
    _obs(db)
    r = viewer.get("/api/markets/190531/explore", params={"reporters": ["GBR", "DEU", "FRA"]}).json()
    series = {s["iso3"]: s for s in r["series"]}
    assert series["DEU"]["values"]["2023"] is None and series["DEU"]["missing_years"] == [2023]
    assert series["FRA"]["latest_year"] is None and all(v is None for v in series["FRA"]["values"].values())
    assert r["sources"][0]["url"].startswith("https://comtradeapi.un.org/") and r["sources"][0]["retrieved_at"]
    assert "UN Comtrade" in r["licence"] and series["GBR"]["qty_unit"] == "kg"
    assert any("No stored data for FRA" in w for w in r["warnings"])
    assert any("latest years differ" in w for w in r["warnings"])
    totals = {t["year"]: t for t in r["totals"]}
    assert totals[2023]["value_usd"] is None and not totals[2023]["comparable"]  # DEU missing → no fake total


def test_explorer_region_and_iso_with_two_m49_codes(db, viewer, admin):
    _obs(db)
    assert admin.put("/api/regions", json={"regions": {"Europe": ["GBR", "DEU"], "USA": ["usa"]}}).status_code == 200
    assert admin.put("/api/regions", json={"regions": {"Bad": ["XXX"]}}).status_code == 422
    r = viewer.get("/api/markets/190531/explore", params={"region": "Europe", "year_from": 2021, "year_to": 2022})
    body = r.json()
    assert [s["iso3"] for s in body["series"]] == ["DEU", "GBR"] and body["latest_comparable_year"] == 2022
    assert {t["year"]: t["value_usd"] for t in body["totals"]} == {2021: 30e6, 2022: 34e6}
    usa = viewer.get("/api/markets/190531/explore", params={"region": "USA"}).json()["series"][0]
    assert usa["values"]["2023"] == 50e6  # reported under 842, requested as USA
    assert viewer.get("/api/markets/190531/explore", params={"region": "Mars"}).status_code == 404
    assert viewer.get("/api/markets/999999/explore").status_code == 404
    assert viewer.get("/api/markets/190531/explore", params={"year_from": 2023, "year_to": 2020}).status_code == 422


def test_live_fetch_real_request_path_and_truthful_errors(db, analyst, viewer, monkeypatch, admin):
    _countries(db)
    monkeypatch.setattr(comtrade.time, "sleep", lambda s: None)
    calls = []

    def preview(**kw):
        calls.append(kw)
        return pd.DataFrame(
            [
                {
                    "refYear": 2023,
                    "reporterCode": 826,
                    "reporterISO": "GBR",
                    "reporterDesc": "UK",
                    "partnerCode": 0,
                    "flowCode": "M",
                    "cmdCode": "190531",
                    "primaryValue": 7e6,
                    "netWgt": 1e6,
                    "qty": 1e6,
                    "qtyUnitAbbr": "kg",
                }
            ]
        )

    monkeypatch.setattr(comtrade.comtradeapicall, "previewFinalData", preview)
    body = {"flow": "M", "reporters": ["GBR"], "years": [2023]}
    assert viewer.post("/api/markets/190531/explore/fetch", json=body).status_code == 403
    ok = admin.post("/api/markets/190531/explore/fetch", json=body).json()
    assert ok["stored"] == 1 and calls[0]["reporterCode"] == "826" and calls[0]["cmdCode"] == "190531"
    assert ok["source"]["url"].startswith("https://comtradeapi.un.org/public/v1/preview")
    admin.post("/api/markets/190531/explore/fetch", json=body)
    assert len(calls) == 1  # identical request served from cache

    def quota(**kw):
        print("Error: Out of call volume quota. Quota will be replenished in 00:02:00.")

    monkeypatch.setattr(comtrade.comtradeapicall, "previewFinalData", quota)
    r = admin.post("/api/markets/190531/explore/fetch", json={**body, "years": [2022]})
    assert r.status_code == 429 and r.headers["Retry-After"]

    def down(**kw):
        print('{"statusCode": 503, "message": "Service unavailable"}')

    monkeypatch.setattr(comtrade.comtradeapicall, "previewFinalData", down)
    r = admin.post("/api/markets/190531/explore/fetch", json={**body, "years": [2021]})
    assert r.status_code == 502 and "did not return data" in r.json()["detail"]
    assert admin.post("/api/markets/190531/explore/fetch", json={**body, "reporters": ["XXX"]}).status_code == 422
    assert admin.post("/api/markets/190531/explore/fetch", json={**body, "years": [2999]}).status_code == 422


def test_duplicate_live_requests_are_rejected(db, analyst, admin):
    _countries(db)
    key = "190531|M|[826]|0|[2023]"
    explore._inflight.add(key)
    try:
        r = admin.post("/api/markets/190531/explore/fetch", json={"reporters": ["GBR"], "years": [2023]})
        assert r.status_code == 409
    finally:
        explore._inflight.discard(key)


# 7./8. retailers and competitors: no fabricated data, identity uncertainty kept ----------------------


def test_priority_retailers_have_only_sourced_facts(db, viewer):
    _apply(db)
    accounts = {c["name"]: c for c in viewer.get("/api/companies", params={"relationship": "retailer"}).json()}
    assert set(accounts) == {"Walmart Inc.", "The Kroger Co.", "Lulu Retail Holdings PLC"}
    for a in accounts.values():
        assert a["contact"] == {}  # no contacts until verified
        assert a["evidence"] and all(any(d in e["source"]["url"] for d in OFFICIAL_DOMAINS) for e in a["evidence"])
        assert a["pipeline_stage"] == "identified" and a["prospect_score"] is None
    assert accounts["Walmart Inc."]["vendor_url"].startswith("https://corporate.walmart.com/suppliers")
    assert accounts["Lulu Retail Holdings PLC"]["vendor_url"] == ""  # not found on the official site


def test_competitors_stay_unconfirmed_and_separate(db, viewer, analyst):
    _apply(db)
    comps = {c["name"]: c for c in viewer.get("/api/companies", params={"relationship": "competitor"}).json()}
    assert set(comps) == {"Hadaek Shtora", "Hiens company"}
    for c in comps.values():
        assert c["identity_status"] == "needs_confirmation" and c["evidence"] == [] and c["website"] == ""
    hiens = comps["Hiens company"]
    r = analyst.patch(
        f"/api/companies/{hiens['id']}",
        json={"next_action": "Ask client", "follow_up_on": "2026-11-15", "owner_id": 999},
    )
    assert r.status_code == 422
    ok = analyst.patch(
        f"/api/companies/{hiens['id']}", json={"next_action": "Ask client", "follow_up_on": "2026-11-15"}
    )
    assert ok.json()["follow_up_on"] == "2026-11-15" and ok.json()["identity_status"] == "needs_confirmation"
    assert analyst.patch(f"/api/companies/{hiens['id']}", json={"follow_up_on": None}).json()["follow_up_on"] is None


# 9. AI labels ------------------------------------------------------------------------------------------


def test_ai_labels_distinguish_client_info_and_hypotheses():
    ev = [Evidence("E1", "client", "Our company: ALDurra.", []), Evidence("E2", "trade_stat", "Imports $5.0M.", [5e6])]
    out = validate_statements(
        [
            {"text": "Durra makes pickles.", "label": "client_provided", "evidence_ids": ["E1"]},
            {"text": "Imports were $5.0M.", "label": "client_provided", "evidence_ids": ["E2"]},
            {"text": "Imports were $5.0M.", "label": "verified", "evidence_ids": ["E2"]},
            {"text": "Imports were $9.0M.", "label": "verified", "evidence_ids": ["E2"]},
            {"text": "Buyer budgets are unknown.", "label": "unavailable", "evidence_ids": []},
        ],
        ev,
    )
    assert [s["label"] for s in out] == ["client_provided", "inference", "verified", "unverified", "unavailable"]
    assert "client_provided" in claude.Statement.model_fields["label"].annotation.__args__
    assert "Never state or imply that anyone has contacted" in claude.GROUNDING_RULES


# 10. keys never exposed -------------------------------------------------------------------------------


def test_keys_are_never_exposed(db, admin, viewer, monkeypatch):
    secret = "sk-SECRET-comtrade-123"
    monkeypatch.setattr(get_settings(), "comtrade_subscription_key", secret)
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-SECRET")
    url = comtrade.public_url({"cmdCode": "190531", "period": "2023"}, secret)
    assert secret not in url
    for path in ("/api/admin/sources", "/api/health", "/api/admin/settings", "/api/overview"):
        text = admin.get(path).text
        assert secret not in text and "sk-ant-SECRET" not in text


# 12. empty results, invalid input, unavailable integrations ------------------------------------------


def test_empty_and_unavailable_states(db, viewer, analyst):
    r = viewer.get("/api/markets/190531/explore").json()
    assert r["series"] == [] and r["totals"] == [] and r["latest_comparable_year"] is None
    opp = viewer.post("/api/markets/opportunities", json={}).json()
    assert opp["rows"] == [] and opp["target_list_loaded"] is False
    assert viewer.post("/api/markets/opportunities", json=dict.fromkeys(opp["weights"], 0)).status_code == 422
    sources = {s["key"]: s for s in viewer.get("/api/admin/sources").json()}
    assert sources["claude"]["status"] == "not_configured"
    assert any(s["status"] == "not_connected" for s in sources.values())
    assert analyst.post("/api/ai/ask", json={"hs_code": "190531", "question": "Best market?"}).status_code == 503


def test_target_market_import_validates_rows(db, analyst, viewer, admin):
    _countries(db)
    data = "country,segment,notes\nGermany,existing,since 2019\nusa,expansion,\nAtlantis,existing,\nFRA,maybe,\n"
    r = admin.post("/api/target-markets/import", files={"file": ("m.csv", data.encode(), "text/csv")}).json()
    assert r["imported"] == 2 and {e["line"] for e in r["errors"]} == {4, 5}
    listed = viewer.get("/api/target-markets").json()
    assert listed["counts"] == {"existing": 1, "expansion": 1}
    bad = admin.post("/api/target-markets/import", files={"file": ("m.csv", b"name_x\nA\n", "text/csv")})
    assert bad.status_code == 422


def test_private_label_opportunities_are_transparent(db, viewer, analyst, admin):
    _apply(db)
    _countries(db)
    for hs in ("200110", "200190", "200290"):
        _obs(db, hs, {826: {2021: 10e6, 2022: 12e6, 2023: 15e6}, 842: {2021: 40e6, 2022: 45e6, 2023: 50e6}})
    admin.put("/api/target-markets/USA", json={"segment": "expansion"})
    admin.put("/api/target-markets/GBR", json={"segment": "existing"})
    res = viewer.post("/api/markets/opportunities", json={}).json()
    assert res["target_list_loaded"]
    rows = [r for r in res["rows"] if r["category"] == "Tomato paste"]
    usa = [r for r in rows if r["iso3"] == "USA"]
    assert {r["retailer"]["name"] for r in usa} == {"Walmart Inc.", "The Kroger Co."}
    gbr = next(r for r in rows if r["iso3"] == "GBR")
    assert gbr["retailer"] is None and gbr["components"]["retailer_presence"] == 0
    assert set(gbr["missing"]) == {"private_label_signal", "evidence"}
    assert all(0 <= r["score"] <= 100 for r in res["rows"] if r["score"] is not None)
    assert usa[0]["score"] > gbr["score"]
    only_size = viewer.post("/api/markets/opportunities", json={**dict.fromkeys(res["weights"], 0), "market_size": 1})
    top = only_size.json()["rows"]
    assert top[0]["components"]["market_size"] == top[0]["score"]
    csv_text = viewer.get("/api/markets/opportunities/export").content.decode("utf-8-sig")
    assert csv_text.startswith("# Weights:") and "component_market_size" in csv_text
    assert any("Grape leaves" in g for g in res["gaps"])  # no trade data loaded for that HS code
    unscored = [r for r in res["rows"] if r["components"]["market_size"] is None]
    assert unscored and all(r["score"] is None for r in unscored)  # retailer factors alone never rank a row


def test_overview_reports_freshness_and_workload(db, viewer):
    _apply(db)
    _obs(db, "200290")
    ov = viewer.get("/api/overview").json()
    assert (
        ov["products"]["by_hs_status"]["unmapped"] >= 1 and ov["products"]["with_client_code"] == 21
    )  # 19 new + 2 existing
    assert ov["trade"]["loaded_hs"] == 1 and ov["trade"]["oldest_retrieval"]
    assert ov["clarifications_open"]["hs"] >= 5 and ov["entities"]["pending_verification"] == 2


# large-scale behaviour ------------------------------------------------------------------------------


def test_scale_catalogue_import_and_explorer(db, analyst, viewer, admin):
    _hs_reference(db)
    lines = ["sku,name,hs_code,client_hs_code,category"] + [
        f"S{i:05d},Product {i},200190,2001900020,Pickles" for i in range(3000)
    ]
    t0 = time.monotonic()
    r = admin.post("/api/products/import", files={"file": ("big.csv", "\n".join(lines).encode(), "text/csv")})
    assert r.json()["created"] == 3000
    assert len(viewer.get("/api/products").json()) == 3000
    iso = [chr(65 + i // 26) + chr(65 + i % 26) + "Z" for i in range(150)]
    countries = [{"m49": 1000 + i, "iso3": iso[i], "name": f"Country {i}"} for i in range(150)]
    db.execute(insert(Country).values(countries).on_conflict_do_nothing())
    src = SourceRecord(adapter="un_comtrade", url="https://comtradeapi.un.org/x", reporting_period="")
    db.add(src)
    db.flush()
    rows = [
        {
            "refYear": y,
            "reporterCode": 1000 + i,
            "reporterISO": iso[i],
            "reporterDesc": f"Country {i}",
            "partnerCode": 0,
            "flowCode": "M",
            "primaryValue": 1e6 * (i + 1) + y,
            "netWgt": 1e5,
        }
        for i in range(150)
        for y in range(2018, 2024)
    ]
    assert trade._store(db, rows, "200190", src.id) == 900
    db.commit()
    ex = viewer.get("/api/markets/200190/explore").json()
    assert len(ex["series"]) == explore.DEFAULT_TOP and ex["series"][0]["values"]["2023"] == pytest.approx(150e6 + 2023)
    assert time.monotonic() - t0 < 60


def test_brief_patch_applies_once(db, viewer):
    _apply(db)
    from app.models import RetailerRequirement
    from app.services import settings as app_settings

    hiens = db.scalar(select(Company).where(Company.name == "Hiens company"))
    assert "Kraft Heinz" in hiens.aliases and hiens.identity_status == "needs_confirmation"
    q = db.scalar(select(Clarification).where(Clarification.question.contains("three countries")))
    assert q.status == "answered" and "Syria, Jordan and Egypt" in q.answer
    regions = app_settings.get(db, "regions")
    assert regions["GCC"] == ["ARE", "BHR", "KWT", "OMN", "QAT", "SAU"]
    assert regions["Far East"] == ["JPN", "KOR", "CHN", "MYS", "SGP", "AUS"]
    assert {r["name"]: r["note"] for r in viewer.get("/api/regions").json()}["Far East"].startswith("Country list")
    n = db.scalar(select(func.count()).select_from(RetailerRequirement))
    assert n == 7 and all(r.source_url.startswith("https://") for r in db.scalars(select(RetailerRequirement)))
    client_data.apply_patches(db, json.loads(client_data.SETUP.read_text())["patches"])
    assert db.scalar(select(func.count()).select_from(RetailerRequirement)) == n  # applied once
