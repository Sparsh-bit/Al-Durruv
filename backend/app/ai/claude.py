"""Claude calls. All prompts forbid invented facts; outputs are validated by grounding.py."""

import json
import logging
import re
from typing import Literal

import anthropic
from fastapi import HTTPException
from pydantic import BaseModel

from app.ai.grounding import Evidence
from app.config import get_settings

log = logging.getLogger("trade_intel.ai")

GROUNDING_RULES = """You are a senior trade analyst for an international exporter and private-label manufacturer.
Rules you must follow:
- Use ONLY the evidence items provided. Cite evidence IDs (e.g. E3) in evidence_ids for every statement.
- Never invent company names, shipment values, purchasing budgets, order quantities, freight costs or transit times.
- Copy numbers exactly as written in the evidence. Do not calculate new numbers.
- Label each statement:
  verified    = directly stated by the cited evidence
  estimate    = a client-provided or modelled figure that is explicitly an estimate in the evidence
  inference   = your reasoning or recommendation based on the evidence (no new numbers)
  unavailable = the information needed is not in the evidence (say what is missing)
- Country-level import statistics describe a whole country, never a specific company's purchases.
- Be concise and commercially useful. Write in clear international business English."""


class Statement(BaseModel):
    text: str
    label: Literal["verified", "estimate", "inference", "unavailable"]
    evidence_ids: list[str]


class Answer(BaseModel):
    statements: list[Statement]
    follow_up_questions: list[str]


class BriefSection(BaseModel):
    title: str
    statements: list[Statement]


class Brief(BaseModel):
    sections: list[BriefSection]


BRIEF_SECTIONS = [
    "Executive summary",
    "Priority import markets",
    "Competitive landscape (supplier countries)",
    "Prospective buyers and partners",
    "Logistics and market access",
    "Risks, data gaps and uncertainty",
    "Recommended next steps",
]


def _client() -> anthropic.Anthropic:
    s = get_settings()
    if not s.ai_enabled:
        raise HTTPException(503, "AI is not configured. Add ANTHROPIC_API_KEY to the backend .env file.")
    return anthropic.Anthropic(api_key=s.anthropic_api_key, max_retries=3, timeout=180)


def _api_errors(fn):
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except anthropic.AuthenticationError:
            raise HTTPException(503, "The Claude API key was rejected. Check ANTHROPIC_API_KEY.") from None
        except anthropic.PermissionDeniedError:
            raise HTTPException(503, "The Claude API key lacks permission or credits for this model.") from None
        except anthropic.RateLimitError:
            raise HTTPException(429, "The AI service is busy (rate limit). Please retry in a minute.") from None
        except anthropic.BadRequestError as exc:
            log.error("Claude bad request: %s", exc)
            raise HTTPException(502, "The AI request was rejected. See server logs.") from None
        except anthropic.APIStatusError as exc:
            log.error("Claude API error %s: %s", exc.status_code, exc)
            raise HTTPException(502, "The AI service returned an error. Please retry.") from None
        except anthropic.APIConnectionError:
            raise HTTPException(502, "Could not reach the AI service. Check the network connection.") from None

    return wrapper


def _evidence_block(evidence: list[Evidence]) -> str:
    return "\n".join(f"[{e.id}] ({e.kind}) {e.text}" for e in evidence)


def _check_stop(resp) -> None:
    if resp.stop_reason == "refusal":
        raise HTTPException(422, "The AI declined this request. Rephrase the question.")
    if resp.stop_reason == "max_tokens":
        raise HTTPException(502, "The AI response was too long and was cut off. Ask a narrower question.")


@_api_errors
def answer_question(question: str, evidence: list[Evidence], history: list[dict]) -> tuple[Answer, dict]:
    s = get_settings()
    messages = [
        *history[-6:],
        {
            "role": "user",
            "content": f"EVIDENCE\n{_evidence_block(evidence)}\n\nQUESTION\n{question}\n\n"
            "Answer in 2-8 statements, then suggest up to 3 follow-up questions.",
        },
    ]
    resp = _client().messages.parse(
        model=s.claude_model, max_tokens=8000, system=GROUNDING_RULES, messages=messages, output_format=Answer
    )
    _check_stop(resp)
    return resp.parsed_output, _usage(resp)


@_api_errors
def write_brief(product: str, hs: str, evidence: list[Evidence]) -> tuple[Brief, dict]:
    s = get_settings()
    prompt = (
        f"EVIDENCE\n{_evidence_block(evidence)}\n\nWrite a market and prospect brief for the product "
        f"'{product}' (HS {hs}) for a sales negotiation. Use exactly these sections in order: "
        f"{'; '.join(BRIEF_SECTIONS)}. 2-6 statements per section. In 'Risks, data gaps and uncertainty' "
        "list what is unavailable (shipment records, freight rates, company purchase volumes)."
    )
    resp = _client().messages.parse(
        model=s.claude_model,
        max_tokens=16000,
        system=GROUNDING_RULES,
        messages=[{"role": "user", "content": prompt}],
        output_format=Brief,
    )
    _check_stop(resp)
    return resp.parsed_output, _usage(resp)


def _usage(resp) -> dict:
    u = resp.usage
    return {"model": resp.model, "input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


RESEARCH_PROMPT = """Use web search to find up to {limit} REAL companies in {country} that are {role_text} of
{product} (HS {hs}: {hs_desc}).
Prefer company websites, official business directories, trade-fair exhibitor lists and reputable news.
Rules:
- Include a company only if a search result you retrieved names it and supports its role.
- source_url MUST be the exact URL of that search result.
- evidence_quote MUST be a short verbatim quote from that result supporting the role.
- Do not guess websites, revenues, volumes or contacts. Leave a field empty if unknown.
Finish with ONLY a JSON array in a ```json code block, items:
{{"name": str, "website": str, "roles": [one or more of {roles}], "summary": str (one sentence),
  "source_url": str, "evidence_quote": str}}"""


@_api_errors
def research_companies(
    *, country: str, product: str, hs: str, hs_desc: str, roles: list[str], limit: int = 8
) -> tuple[list[dict], dict[str, dict], dict]:
    """Returns (candidates, retrieved_results_by_url, usage). Candidates are NOT yet validated."""
    s = get_settings()
    role_text = " or ".join(r.replace("_", " ") + "s" for r in roles)
    prompt = RESEARCH_PROMPT.format(
        limit=limit,
        country=country,
        role_text=role_text,
        product=product,
        hs=hs,
        hs_desc=hs_desc,
        roles=json.dumps(roles),
    )
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": s.research_max_searches}]
    messages: list[dict] = [{"role": "user", "content": prompt}]
    client = _client()
    results: dict[str, dict] = {}
    texts: list[str] = []
    usage = {"model": s.claude_model, "input_tokens": 0, "output_tokens": 0, "web_searches": 0}
    for _ in range(4):  # pause_turn continuations
        resp = client.messages.create(model=s.claude_model, max_tokens=12000, messages=messages, tools=tools)
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        stu = getattr(resp.usage, "server_tool_use", None)
        usage["web_searches"] += getattr(stu, "web_search_requests", 0) or 0
        for block in resp.content:
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                for r in block.content:
                    results[_norm(r.url)] = {"url": r.url, "title": r.title, "quotes": []}
            elif block.type == "text":
                texts.append(block.text)
                for c in block.citations or []:
                    url = getattr(c, "url", None)
                    if url and _norm(url) in results:
                        results[_norm(url)]["quotes"].append(getattr(c, "cited_text", ""))
        if resp.stop_reason != "pause_turn":
            _check_stop(resp)
            break
        messages = [messages[0], {"role": "assistant", "content": resp.content}]
    return _parse_json_array("\n".join(texts)), results, usage


def _norm(url: str) -> str:
    return url.strip().rstrip("/").split("#")[0].lower()


def _parse_json_array(text: str) -> list[dict]:
    m = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL) or re.search(r"(\[\s*\{.*\}\s*\])", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]
