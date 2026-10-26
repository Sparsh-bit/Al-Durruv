import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app.adapters import comtrade
from app.ai import claude
from app.main import app
from app.models import ApiCache, Product, SourceRecord, TradeObservation
from app.services import research, trade

# ---------- auth & access control ----------


def test_login_and_protection(viewer):
    anon = TestClient(app)
    assert anon.post("/api/auth/login", data={"username": "admin@example.com", "password": "wrong"}).status_code == 401
    assert anon.get("/api/products").status_code == 401
    assert viewer.get("/api/products").status_code == 200
    assert viewer.post("/api/products", json={"sku": "A", "name": "A", "hs_code": "190531"}).status_code == 403
    assert viewer.get("/api/admin/sources").status_code == 403


def test_admin_cannot_demote_self(admin):
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/auth/users/{me['id']}", json={"role": "viewer"}).status_code == 400


# ---------- catalogue ----------


def test_product_crud_validates_hs(analyst):
    assert analyst.post("/api/products", json={"sku": "X1", "name": "X", "hs_code": "999999"}).status_code == 422
    r = analyst.post("/api/products", json={"sku": "X1", "name": "Biscuits", "hs_code": "1905.31"})
    assert r.status_code == 201 and r.json()["hs_code"] == "190531"
    assert analyst.post("/api/products", json={"sku": "X1", "name": "Dup", "hs_code": "190531"}).status_code == 409


def test_csv_import_reports_row_errors_and_restores_leading_zero(analyst, db):
    csv = b"SKU,Name,HS Code\nC1,Coffee,90111\nB1,Biscuits,190531.0\nZ1,Bad,123\n,NoSku,190531\n"
    r = analyst.post("/api/products/import", files={"file": ("p.csv", csv, "text/csv")})
    body = r.json()
    assert r.status_code == 200 and body["created"] == 2 and len(body["errors"]) == 2
    assert {e["line"] for e in body["errors"]} == {4, 5}
    assert db.scalar(select(Product.hs_code).where(Product.sku == "C1")) == "090111"
    # re-import updates instead of duplicating
    r = analyst.post(
        "/api/products/import", files={"file": ("p.csv", b"sku,name,hs_code\nC1,Coffee beans,090111\n", "text/csv")}
    )
    assert r.json() == {"created": 0, "updated": 1, "errors": []}


def test_import_rejects_missing_columns_and_bad_type(analyst):
    r = analyst.post("/api/products/import", files={"file": ("p.csv", b"sku,name\nA,B\n", "text/csv")})
    assert r.status_code == 422 and "hs_code" in r.json()["detail"]
    assert analyst.post("/api/products/import", files={"file": ("p.txt", b"x", "text/plain")}).status_code == 415


# ---------- comtrade adapter: cache, retries, provenance ----------

ROWS = [
    {
        "refYear": 2023,
        "reporterCode": 826,
        "reporterISO": "GBR",
        "reporterDesc": "United Kingdom",
        "partnerCode": 0,
        "partnerISO": "W00",
        "partnerDesc": "World",
        "flowCode": "M",
        "primaryValue": 500e6,
        "netWgt": 1e8,
        "qty": 1e8,
        "qtyUnitAbbr": "kg",
    },
]


def test_fetch_caches_and_records_provenance(db):
    calls = []

    def fake(params, key):
        calls.append(params)
        return ROWS

    rows1, src1 = comtrade.fetch(db, period=2023, cmd="190531", flow="M", caller=fake)
    rows2, src2 = comtrade.fetch(db, period=2023, cmd="190531", flow="M", caller=fake)
    assert len(calls) == 1 and rows1 == rows2 and src1.id == src2.id
    assert src1.url.startswith("https://comtradeapi.un.org/public/v1/preview/C/A/HS?")
    assert "subscription" not in src1.url and src1.reporting_period == "2023" and src1.licence
    assert db.scalar(select(ApiCache).where(ApiCache.adapter == "un_comtrade")) is not None


def test_fetch_retries_then_raises(db, monkeypatch):
    monkeypatch.setattr(comtrade.time, "sleep", lambda s: None)
    attempts = []

    def flaky(params, key):
        attempts.append(1)
        if len(attempts) < 3:
            raise comtrade.ComtradeError("429 rate limit")
        return ROWS

    rows, _ = comtrade.fetch(db, period=2022, cmd="190531", flow="M", caller=flaky)
    assert len(attempts) == 3 and rows == ROWS

    def down(params, key):
        raise comtrade.ComtradeError("503")

    with pytest.raises(comtrade.ComtradeError, match="after 3 attempts"):
        comtrade.fetch(db, period=2021, cmd="190531", flow="M", caller=down)


def test_client_error_output_becomes_typed_error(monkeypatch):
    def prints_and_returns_none(**kw):
        print('{"statusCode": 429, "message": "Rate limit is exceeded"}')
        return None

    monkeypatch.setattr(comtrade.comtradeapicall, "previewFinalData", prints_and_returns_none)
    with pytest.raises(comtrade.ComtradeError, match="Rate limit"):
        comtrade._call({"period": "2023", "cmdCode": "190531", "flowCode": "M"}, "")


def _load(db):
    """Synthetic but realistic observations for two markets, with supplier detail."""
    rows = []
    for year, gbr, deu in [(2020, 400e6, 600e6), (2021, 420e6, 610e6), (2022, 460e6, 640e6), (2023, 500e6, 650e6)]:
        for code, iso, name, v in [(826, "GBR", "United Kingdom", gbr), (276, "DEU", "Germany", deu)]:
            rows.append(
                {
                    **ROWS[0],
                    "refYear": year,
                    "reporterCode": code,
                    "reporterISO": iso,
                    "reporterDesc": name,
                    "primaryValue": v,
                    "netWgt": v / 4,
                }
            )
    for pcode, piso, pname, v in [(484, "MEX", "Mexico", 300e6), (528, "NLD", "Netherlands", 200e6)]:
        rows.append(
            {
                **ROWS[0],
                "reporterCode": 826,
                "partnerCode": pcode,
                "partnerISO": piso,
                "partnerDesc": pname,
                "primaryValue": v,
                "netWgt": v / 4,
            }
        )
    src = SourceRecord(adapter="un_comtrade", url="https://comtradeapi.un.org/test", reporting_period="2023")
    db.add(src)
    db.flush()
    trade._store(db, rows, "190531", src.id)
    db.commit()


def test_every_observation_has_provenance_and_world_is_not_a_country(db, viewer):
    _load(db)
    obs = db.scalars(select(TradeObservation)).all()
    assert obs and all(o.source_record_id for o in obs)
    ov = viewer.get("/api/markets/190531/overview").json()
    assert ov["has_data"] and ov["reference_year"] == 2023 and ov["world_imports_usd"] == pytest.approx(1150e6)
    assert ov["top_importers"][0]["source"]["url"] == "https://comtradeapi.un.org/test"
    detail = viewer.get("/api/markets/190531/countries/826").json()
    assert [s["name"] for s in detail["suppliers"]] == ["Mexico", "Netherlands"]
    assert detail["suppliers"][0]["share"] == pytest.approx(0.6)
    rank = viewer.post("/api/markets/190531/ranking", json={}).json()["markets"]
    assert {m["iso3"] for m in rank} == {"GBR", "DEU"}
    assert viewer.post("/api/markets/190531/ranking", json={k: 0 for k in rank[0]["components"]}).status_code == 422


# ---------- AI: grounding enforced at the API ----------


def test_ai_endpoints_return_503_without_key(analyst):
    r = analyst.post("/api/ai/ask", json={"hs_code": "190531", "question": "Which market?"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert analyst.post("/api/research", json={"hs_code": "190531", "country_m49": 826}).status_code == 503


def test_ask_validates_model_output(db, analyst, ai_on, monkeypatch):
    _load(db)

    def fake_answer(question, evidence, history):
        uk = next(e for e in evidence if "United Kingdom imported" in e.text)
        return claude.Answer(
            statements=[
                claude.Statement(
                    text="The United Kingdom imported $500.0 million.", label="verified", evidence_ids=[uk.id]
                ),
                claude.Statement(text="UK imports were $9 billion.", label="verified", evidence_ids=[uk.id]),
                claude.Statement(text="A distributor route is advisable.", label="verified", evidence_ids=["E999"]),
            ],
            follow_up_questions=["Next?"],
        ), {"model": "test", "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(claude, "answer_question", fake_answer)
    body = analyst.post("/api/ai/ask", json={"hs_code": "190531", "question": "Tell me about the UK"}).json()
    labels = [s["label"] for s in body["statements"]]
    assert labels == ["verified", "unverified", "inference"]
    assert {e["id"] for e in body["evidence"]} == {body["statements"][0]["evidence_ids"][0]}


def test_research_keeps_only_candidates_with_retrieved_sources():
    results = {
        "https://acme.co.uk/about": {
            "url": "https://acme.co.uk/about/",
            "title": "Acme",
            "quotes": ["Acme imports biscuits"],
        }
    }
    kept, dropped = research.validate_candidates(
        [
            {"name": "Acme Foods Ltd", "roles": ["importer", "spaceship"], "source_url": "https://acme.co.uk/about/"},
            {"name": "Ghost Trading", "roles": ["importer"], "source_url": "https://invented.example/page"},
            {"name": "acme foods ltd", "roles": ["importer"], "source_url": "https://acme.co.uk/about"},
        ],
        results,
    )
    assert [k["name"] for k in kept] == ["Acme Foods Ltd"] and kept[0]["roles"] == ["importer"]
    assert {d["reason"] for d in dropped} == {"source_url was not among retrieved search results", "duplicate"}


# ---------- reports: generation, withholding, export ----------


def test_brief_withholds_unverified_and_exports(db, analyst, ai_on, monkeypatch):
    _load(db)
    pid = analyst.post("/api/products", json={"sku": "B1", "name": "Butter cookies", "hs_code": "190531"}).json()["id"]

    def fake_brief(product, hs, evidence):
        uk = next(e for e in evidence if "United Kingdom imported" in e.text)
        return claude.Brief(
            sections=[
                claude.BriefSection(
                    title="Executive summary",
                    statements=[
                        claude.Statement(
                            text="The United Kingdom imported $500.0 million.", label="verified", evidence_ids=[uk.id]
                        ),
                        claude.Statement(text="The UK buys 7 billion units.", label="inference", evidence_ids=[]),
                    ],
                )
            ]
        ), {"model": "test-model", "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(claude, "write_brief", fake_brief)
    r = analyst.post("/api/reports", json={"product_id": pid})
    assert r.status_code == 201
    rep = r.json()
    assert rep["validation"] == {"statements": 2, "exported": 1, "withheld": 1}

    pdf = analyst.get(f"/api/reports/{rep['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "attachment" in pdf.headers["content-disposition"]

    xlsx = analyst.get(f"/api/reports/{rep['id']}/export?format=xlsx")
    wb = load_workbook(io.BytesIO(xlsx.content))
    statements = [row[2] for row in wb["Brief"].iter_rows(min_row=2, values_only=True)]
    assert statements == ["The United Kingdom imported $500.0 million."]  # unverified never exported
    assert analyst.get(f"/api/reports/{rep['id']}/export?format=doc").status_code == 400


def test_brief_requires_trade_data(analyst, ai_on):
    pid = analyst.post("/api/products", json={"sku": "C1", "name": "Coffee", "hs_code": "090111"}).json()["id"]
    assert analyst.post("/api/reports", json={"product_id": pid}).status_code == 409


def test_logistics_quotes_are_labelled_client_provided(analyst, viewer):
    r = analyst.post(
        "/api/logistics",
        json={
            "origin": "Jebel Ali",
            "destination": "Felixstowe",
            "destination_iso3": "gbr",
            "mode": "sea",
            "cost_usd": 2400,
            "transit_days": 24,
            "source_note": "Forwarder quote ref 1",
        },
    )
    assert r.status_code == 201 and r.json()["provenance"] == "client_provided"
    data = viewer.get("/api/logistics?destination_iso3=GBR").json()
    assert len(data["quotes"]) == 1 and {p["status"] for p in data["providers"]} == {"not_connected"}
    assert (
        analyst.post(
            "/api/logistics",
            json={"origin": "A", "destination": "B", "destination_iso3": "GBR", "mode": "teleport", "source_note": "x"},
        ).status_code
        == 422
    )
