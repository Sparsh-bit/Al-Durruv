from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai import claude
from app.ai import usage as ai_usage
from app.ai.grounding import build_context, validate_statements
from app.models import HSCode
from app.security import DB, CurrentUser

router = APIRouter(prefix="/api/ai", tags=["ai"])


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskIn(BaseModel):
    hs_code: str
    question: str = Field(min_length=3, max_length=2000)
    focus_m49: int | None = None
    history: list[Turn] = Field(default_factory=list, max_length=12)


@router.post("/ask")
def ask(body: AskIn, user: CurrentUser, db: DB):
    if not db.get(HSCode, body.hs_code):
        raise HTTPException(404, f"Unknown HS code {body.hs_code}.")
    ai_usage.check_budget(db, user.id)
    evidence = build_context(db, body.hs_code, body.focus_m49)
    history = [t.model_dump() for t in body.history]
    answer, usage = claude.answer_question(body.question, evidence, history)
    usage["cost_usd"] = ai_usage.record(db, user.id, "analyst", usage)
    usage.pop("model", None)
    db.commit()
    statements = validate_statements([s.model_dump() for s in answer.statements], evidence)
    cited = {i for s in statements for i in s["evidence_ids"]}
    return {
        "statements": statements,
        "follow_up_questions": answer.follow_up_questions[:3],
        "evidence": [e.as_dict() for e in evidence if e.id in cited],
        "usage": usage,
    }
