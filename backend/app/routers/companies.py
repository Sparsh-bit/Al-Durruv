from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import any_, select

from app.config import get_settings
from app.models import Company, Country, HSCode, ProspectList, ProspectListItem, RefreshRun, ReviewStatus
from app.routers.markets import _run_out
from app.security import DB, Analyst, CurrentUser
from app.services import research

router = APIRouter(prefix="/api", tags=["companies"])


def company_out(c: Company, countries: dict[str, str] | None = None) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "country_iso3": c.country_iso3,
        "country_name": (countries or {}).get(c.country_iso3, c.country_iso3),
        "website": c.website,
        "roles": c.roles,
        "summary": c.summary,
        "hs_codes": c.hs_codes,
        "review_status": c.review_status,
        "evidence": [
            {
                "id": e.id,
                "claim": e.claim,
                "excerpt": e.excerpt,
                "source": {
                    "id": e.source.id,
                    "url": e.source.url,
                    "title": e.source.title,
                    "retrieved_at": e.source.retrieved_at.isoformat(),
                },
            }
            for e in c.evidence
        ],
    }


def _country_names(db) -> dict[str, str]:
    return {c.iso3: c.name for c in db.scalars(select(Country)) if c.iso3}


@router.get("/companies")
def list_companies(
    _: CurrentUser,
    db: DB,
    hs: str | None = None,
    country_iso3: str | None = None,
    status: str | None = None,
    role: str | None = None,
):
    stmt = select(Company).order_by(Company.name)
    if hs:
        stmt = stmt.where(hs == any_(Company.hs_codes))
    if country_iso3:
        stmt = stmt.where(Company.country_iso3 == country_iso3.upper())
    if status:
        stmt = stmt.where(Company.review_status == status)
    if role:
        stmt = stmt.where(role == any_(Company.roles))
    names = _country_names(db)
    return [company_out(c, names) for c in db.scalars(stmt)]


class ReviewIn(BaseModel):
    review_status: ReviewStatus


@router.patch("/companies/{company_id}")
def review(company_id: int, body: ReviewIn, user: Analyst, db: DB):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found.")
    c.review_status, c.reviewed_by = body.review_status, user.id
    db.commit()
    return company_out(c, _country_names(db))


class ResearchIn(BaseModel):
    hs_code: str
    country_m49: int
    kind: str = Field("buyers", pattern="^(buyers|competitors)$")
    product_id: int | None = None
    force: bool = False


@router.post("/research", status_code=202)
def start_research(body: ResearchIn, user: Analyst, db: DB, tasks: BackgroundTasks):
    if not get_settings().ai_enabled:
        raise HTTPException(503, "AI is not configured. Add ANTHROPIC_API_KEY to the backend .env file.")
    country = db.get(Country, body.country_m49)
    if not country or not db.get(HSCode, body.hs_code):
        raise HTTPException(404, "Unknown country or HS code.")
    scope = f"HS {body.hs_code} · {country.iso3} · {body.kind}"
    prev = db.scalar(
        select(RefreshRun)
        .where(RefreshRun.adapter == "web_research", RefreshRun.scope == scope)
        .order_by(RefreshRun.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    if prev and prev.status == "running" and now - prev.started_at < timedelta(minutes=10):
        return _run_out(prev)
    if prev and prev.status == "succeeded" and not body.force and now - prev.started_at < timedelta(days=7):
        return _run_out(prev)  # cached: avoids paying for the same searches twice
    run = RefreshRun(adapter="web_research", scope=scope, started_by=user.id, message="Queued")
    db.add(run)
    db.commit()
    tasks.add_task(research.run_research, run.id, body.hs_code, body.country_m49, body.kind, body.product_id)
    return _run_out(run)


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hs_code: str | None = None


@router.get("/prospect-lists")
def lists(_: CurrentUser, db: DB):
    out = []
    names = _country_names(db)
    for pl in db.scalars(select(ProspectList).order_by(ProspectList.created_at.desc())):
        items = db.scalars(select(ProspectListItem).where(ProspectListItem.list_id == pl.id)).all()
        comps = [db.get(Company, i.company_id) for i in items]
        out.append(
            {
                "id": pl.id,
                "name": pl.name,
                "hs_code": pl.hs_code,
                "created_at": pl.created_at.isoformat(),
                "companies": [company_out(c, names) for c in comps if c],
            }
        )
    return out


@router.post("/prospect-lists", status_code=201)
def create_list(body: ListIn, user: Analyst, db: DB):
    pl = ProspectList(name=body.name, hs_code=body.hs_code, created_by=user.id)
    db.add(pl)
    db.commit()
    return {
        "id": pl.id,
        "name": pl.name,
        "hs_code": pl.hs_code,
        "created_at": pl.created_at.isoformat(),
        "companies": [],
    }


@router.post("/prospect-lists/{list_id}/companies/{company_id}", status_code=204)
def add_to_list(list_id: int, company_id: int, _: Analyst, db: DB):
    if not db.get(ProspectList, list_id) or not db.get(Company, company_id):
        raise HTTPException(404, "List or company not found.")
    exists = db.scalar(
        select(ProspectListItem).where(ProspectListItem.list_id == list_id, ProspectListItem.company_id == company_id)
    )
    if not exists:
        db.add(ProspectListItem(list_id=list_id, company_id=company_id))
        db.commit()


@router.delete("/prospect-lists/{list_id}/companies/{company_id}", status_code=204)
def remove_from_list(list_id: int, company_id: int, _: Analyst, db: DB):
    item = db.scalar(
        select(ProspectListItem).where(ProspectListItem.list_id == list_id, ProspectListItem.company_id == company_id)
    )
    if item:
        db.delete(item)
        db.commit()
