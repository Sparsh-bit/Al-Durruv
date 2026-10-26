"""Cost accounting for Claude calls and the monthly budget cap."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AiUsage
from app.services import settings

# USD per million tokens (input, output). Cache reads bill at 10% of input, cache writes at 125%.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
WEB_SEARCH_USD = 0.01  # per search ($10 per 1,000); check current pricing at claude.com/pricing


def cost(model: str, usage: dict) -> float:
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])  # unknown model: assume the dearer tier
    return round(
        (
            usage.get("input_tokens", 0) * pin
            + usage.get("output_tokens", 0) * pout
            + usage.get("cache_read_tokens", 0) * pin * 0.1
            + usage.get("cache_write_tokens", 0) * pin * 1.25
        )
        / 1e6
        + usage.get("web_searches", 0) * WEB_SEARCH_USD,
        6,
    )


def month_spend(db: Session) -> float:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(db.scalar(select(func.coalesce(func.sum(AiUsage.cost_usd), 0)).where(AiUsage.created_at >= start)))


def check_budget(db: Session) -> None:
    budget = float(settings.get(db, "ai_monthly_budget_usd"))
    spent = month_spend(db)
    if spent >= budget:
        raise HTTPException(
            429,
            f"The monthly AI budget of ${budget:.2f} has been reached (${spent:.2f} used). "
            "An admin can raise it in Administration.",
        )


def record(db: Session, user_id: int | None, feature: str, usage: dict) -> float:
    model = usage.get("model", "")
    c = cost(model, usage)
    db.add(
        AiUsage(
            user_id=user_id,
            feature=feature,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_write_tokens=usage.get("cache_write_tokens", 0),
            web_searches=usage.get("web_searches", 0),
            cost_usd=c,
        )
    )
    return c
