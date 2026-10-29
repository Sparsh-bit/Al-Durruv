"""Maersk reference data in the product and route workflows: commodity references and route locations.

All calls go through the backend (the Consumer Key never reaches the browser). Responses carry the source and
retrieval time. Maersk failures return a truthful error without affecting the rest of the platform.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.connectors import maersk, sources
from app.models import ApiCache, HSCode, HsStatus, LogisticsQuote, Product, RouteLocation
from app.security import DB, Admin, Analyst, CurrentUser
from app.services import audit
from app.services.client_data import hs6_of

router = APIRouter(prefix="/api", tags=["maersk"])
DISCLAIMER = (
    "Maersk commodity references are carrier reference data for bookings. They are not a customs classification; "
    "the correct HS code depends on ingredients, preparation, preservation and the importing country's tariff."
)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except maersk.MaerskError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(exc.status, str(exc), headers=headers) from None


@router.get("/maersk/status")
def status(_: CurrentUser, db: DB):
    cached = dict(
        db.execute(
            select(ApiCache.adapter, func.count())
            .where(ApiCache.adapter.in_(["maersk_commodities", "maersk_locations"]))
            .group_by(ApiCache.adapter)
        ).all()
    )
    return {
        "configured": maersk.configured(),
        "apis": [
            {
                "key": "commodities",
                "name": "Maersk Commodities API v1.1",
                "auth": "Consumer-Key header",
                "published_limits": "15,000/hour, 250/minute",
                "our_limits": "12,000/hour, 200/minute",
                "cached_responses": cached.get("maersk_commodities", 0),
            },
            {
                "key": "locations",
                "name": "Maersk Locations API v4",
                "auth": "Consumer-Key header",
                "published_limits": "36,000/hour, 60/minute",
                "our_limits": "30,000/hour, 50/minute",
                "cached_responses": cached.get("maersk_locations", 0),
            },
        ],
        "not_provided": "Freight prices, schedules, transit times and customs rulings are not part of these APIs.",
    }


# --- commodities ------------------------------------------------------------------------------------


@router.get("/maersk/commodities")
def search_commodities(
    user: CurrentUser,
    db: DB,
    q: str = Query("", max_length=100),
    hs: str = Query("", max_length=6),
    refresh: bool = False,
):
    res = _call(maersk.search_commodities, db, q.strip(), hs.strip(), refresh and user.role == "admin")
    db.commit()
    return {**res, "disclaimer": DISCLAIMER}


def _search_terms(p: Product) -> list[str]:
    """Product name first; then its significant words. Never more than 3 searches per product."""
    name = re.sub(r"\(.*?\)", " ", p.name)
    name = re.sub(r"[^A-Za-z0-9 ,&'/-]", " ", name)
    name = " ".join(name.split())
    words = [w for w in name.split() if len(w) >= 4 and w.lower() not in {"with", "from", "style", "durra"}]
    terms = [name] if sum(ch.isalpha() for ch in name) >= 2 else []
    for w in sorted(words, key=len, reverse=True):
        if w.lower() != name.lower() and w not in terms:
            terms.append(w)
    return terms[:3]


@router.get("/products/{product_id}/maersk-commodities")
def product_commodities(product_id: int, _: CurrentUser, db: DB):
    """Candidate Maersk commodity references for a product, compared with its client and analysis codes."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    client6 = hs6_of(p.client_hs_code)
    found: dict[str, dict] = {}
    searches = []
    for term in _search_terms(p):
        res = _call(maersk.search_commodities, db, term, "")
        searches.append(
            {"by": "name", "term": term, "results": len(res["results"]), "retrieved_at": res["retrieved_at"]}
        )
        for c in res["results"]:
            found.setdefault(c["commodity_code"], {**c, "matched_by": f"name: {term}"})
        if found:
            break  # the most specific term that matches wins; broader words only when nothing matched
    for code, label in ((p.hs_code, "analysis HS6"), (client6, "client HS6")):
        if code and code not in {s.get("term") for s in searches}:
            res = _call(maersk.search_commodities, db, "", code)
            searches.append(
                {"by": "hs", "term": code, "results": len(res["results"]), "retrieved_at": res["retrieved_at"]}
            )
            for c in res["results"]:
                found.setdefault(c["commodity_code"], {**c, "matched_by": f"{label} {code}"})
    db.commit()
    candidates = []
    for c in found.values():
        hs6s = {h["code"][:6] for h in c["hs_codes"]}
        candidates.append(
            {
                **c,
                "matches_client_hs6": bool(client6 and client6 in hs6s),
                "matches_analysis_hs6": bool(p.hs_code and p.hs_code in hs6s),
            }
        )
    candidates.sort(key=lambda c: (not c["matches_analysis_hs6"], not c["matches_client_hs6"], c["commodity_name"]))
    return {
        "product": {"id": p.id, "name": p.name},
        "codes": [
            {
                "source": "client",
                "label": "Client-provided code",
                "code": p.client_hs_code or None,
                "hs6": client6 or None,
            },
            {"source": p.hs_source, "label": "HS6 used for trade analysis", "code": p.hs_code, "status": p.hs_status},
        ],
        "selected": p.maersk_commodity,
        "candidates": candidates,
        "ambiguous": len(candidates) > 1,
        "searches": searches,
        "message": None
        if candidates
        else "No Maersk commodity reference matched this product. Continue with the existing record; the "
        "classification stays marked as needing review.",
        "disclaimer": DISCLAIMER,
    }


class CommodityChoice(BaseModel):
    commodity_code: str = Field(pattern=r"^[0-9]{6}$")
    hs_code: str = Field("", pattern=r"^([A-Za-z0-9]{6,10})?$")
    use_for_analysis: bool = False


@router.post("/products/{product_id}/maersk-commodity")
def choose_commodity(product_id: int, body: CommodityChoice, user: Analyst, db: DB):
    """Save a reviewer's choice of Maersk reference. The client's own code is never changed. Using the HS6
    for trade analysis is an HS-mapping change: admin only, and the status stays 'needs review'."""
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    if body.use_for_analysis and user.role != "admin":
        raise HTTPException(403, "Only an administrator can change the HS code used for analysis.")
    # re-read the commodity from Maersk (cached) so only real reference data is stored
    res = _call(maersk.search_commodities_by_code, db, body.commodity_code)
    commodity = next((c for c in res["results"] if c["commodity_code"] == body.commodity_code), None)
    if not commodity:
        raise HTTPException(422, "Maersk has no commodity with that code.")
    hs_codes = {h["code"] for h in commodity["hs_codes"]}
    if body.hs_code and body.hs_code not in hs_codes:
        raise HTTPException(422, "That HS code is not listed for this Maersk commodity.")
    p.maersk_commodity = {
        **commodity,
        "selected_hs": body.hs_code or None,
        "retrieved_at": res["retrieved_at"],
        "selected_by": user.email,
        "selected_at": datetime.now(UTC).isoformat(),
        "source": res["source"],
    }
    detail = f"{p.sku}: Maersk {commodity['commodity_code']} {commodity['commodity_name']}"
    if body.use_for_analysis:
        hs6 = body.hs_code[:6]
        if not hs6 or not db.get(HSCode, hs6):
            raise HTTPException(422, "Choose an HS code from the commodity that exists in the HS6 nomenclature.")
        before = p.hs_code
        p.hs_code, p.hs_status, p.hs_source = hs6, HsStatus.candidate, "maersk_reference"
        p.hs_note = (
            f"Analysis HS6 {hs6} taken from Maersk commodity reference {commodity['commodity_code']} "
            f"({commodity['commodity_name']}); not a customs classification. {p.hs_note}"
        ).strip()[:2000]
        detail += f"; analysis HS6 {before or '-'} -> {hs6}"
    audit.record(db, user, "maersk_commodity", "product", p.id, detail)
    db.commit()
    return {
        "selected": p.maersk_commodity,
        "hs_code": p.hs_code,
        "hs_source": p.hs_source,
        "hs_status": p.hs_status,
        "client_hs_code": p.client_hs_code,
    }


@router.delete("/products/{product_id}/maersk-commodity", status_code=204)
def clear_commodity(product_id: int, user: Analyst, db: DB):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found.")
    p.maersk_commodity = None
    audit.record(db, user, "maersk_commodity_cleared", "product", p.id, p.sku)
    db.commit()


# --- locations --------------------------------------------------------------------------------------


def _iso2(code: str) -> str:
    code = code.strip().upper()
    if not code or len(code) == 2:
        return code
    if len(code) == 3:
        reverse = {v: k for k, v in sources.iso2_to_iso3().items()}
        if code in reverse:
            return reverse[code]
    raise HTTPException(422, "Country must be a 2- or 3-letter ISO code.")


@router.get("/maersk/locations")
def search_locations(
    user: CurrentUser,
    db: DB,
    q: str = Query("", max_length=50),
    mode: Literal["name", "unlocode"] = "name",
    country: str = Query("", max_length=3),
    type: str = Query("", max_length=40),
    limit: int = Query(25, ge=1, le=100),
    page: str | None = Query(None, max_length=200),
    refresh: bool = False,
):
    res = _call(
        maersk.search_locations,
        db,
        query=q,
        mode=mode,
        country_code=_iso2(country),
        location_type=type,
        limit=limit,
        page=page,
        force=refresh and user.role == "admin",
    )
    db.commit()
    saved = set(db.scalars(select(RouteLocation.carrier_geo_id)))
    results = [{**r, "saved": r["carrier_geo_id"] in saved} for r in res["results"]]
    return {
        **res,
        "results": results,
        "ambiguous": len(results) > 1,
        "message": "No Maersk location matches this search."
        if not results
        else ("Several locations match; choose the right one." if len(results) > 1 else None),
    }


@router.get("/maersk/locations/{geo_id}")
def location(geo_id: str, _: CurrentUser, db: DB):
    loc = _call(maersk.location_by_geo_id, db, geo_id)
    db.commit()
    if not loc:
        raise HTTPException(404, "Maersk has no location with this Geo ID.")
    return loc


def _route_out(r: RouteLocation) -> dict:
    return {
        "id": r.id,
        "carrier_geo_id": r.carrier_geo_id,
        "un_location_code": r.un_location_code,
        "location_name": r.location_name,
        "location_type": r.location_type,
        "city_name": r.city_name,
        "country_code": r.country_code,
        "country_iso3": r.country_iso3,
        "country_name": r.country_name,
        "region_name": r.region_name,
        "has_cy_service": r.has_cy_service,
        "source": r.source,
        "retrieved_at": r.retrieved_at.isoformat(),
    }


@router.get("/route-locations")
def route_locations(_: CurrentUser, db: DB):
    rows = db.scalars(select(RouteLocation).order_by(RouteLocation.country_name, RouteLocation.location_name))
    return [_route_out(r) for r in rows]


class SaveLocation(BaseModel):
    carrier_geo_id: str = Field(pattern=r"^[0-9a-zA-Z]{13}$")


@router.post("/route-locations", status_code=201)
def save_location(body: SaveLocation, user: Analyst, db: DB):
    """Keep a Maersk location for shipment routes. Details are re-read from Maersk by Geo ID, never taken from
    the browser."""
    existing = db.scalar(select(RouteLocation).where(RouteLocation.carrier_geo_id == body.carrier_geo_id))
    if existing:
        return _route_out(existing)
    loc = _call(maersk.location_by_geo_id, db, body.carrier_geo_id)
    if not loc:
        raise HTTPException(404, "Maersk has no location with this Geo ID.")
    r = RouteLocation(
        carrier_geo_id=loc["carrier_geo_id"] or body.carrier_geo_id,
        un_location_code=loc["un_location_code"][:5],
        location_name=loc["location_name"],
        location_type=loc["location_type"],
        city_name=loc["city_name"],
        country_code=loc["country_code"][:2],
        country_iso3=sources.iso2_to_iso3().get(loc["country_code"], "") if loc["country_code"] else "",
        country_name=loc["country_name"],
        region_name=loc["region_name"],
        has_cy_service=loc["has_cy_service"],
        raw={k: v for k, v in loc.items() if k != "retrieved_at"},
        saved_by=user.id,
    )
    db.add(r)
    db.flush()
    audit.record(db, user, "create", "route_location", r.id, f"{r.location_name} {r.carrier_geo_id}")
    db.commit()
    return _route_out(r)


@router.delete("/route-locations/{loc_id}", status_code=204)
def delete_location(loc_id: int, user: Admin, db: DB):
    r = db.get(RouteLocation, loc_id)
    if not r:
        raise HTTPException(404, "Location not found.")
    in_use = db.scalar(
        select(func.count())
        .select_from(LogisticsQuote)
        .where((LogisticsQuote.origin_location_id == loc_id) | (LogisticsQuote.destination_location_id == loc_id))
    )
    audit.record(db, user, "delete", "route_location", r.id, f"{r.location_name} (used by {in_use} quotes)")
    db.delete(r)
    db.commit()
