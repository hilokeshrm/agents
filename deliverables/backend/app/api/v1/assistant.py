"""
Ask OppTrack (the chat panel). One endpoint, no writes.

The router is thin on purpose: the read-only tool surface and both answer modes
live in app/services/assistant.py, so the MCP server (WBS 10.12) can expose the
same tools to a sibling agent without a second implementation of them drifting
away from this one.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.security.roles import Actor, current_actor
from app.services.assistant import CAPABILITIES, TOOL_SCHEMAS, ask

router = APIRouter(prefix="/assistant", tags=["assistant"])


class AskRequest(BaseModel):
    question: str


class ToolCallRead(BaseModel):
    name: str
    input: dict
    summary: str


class AnswerRead(BaseModel):
    mode: str  # live | reader | refused
    answer: str
    tool_calls: list[ToolCallRead]
    model_id: str | None
    note: str | None
    intent: str = "answer"
    grounded: bool | None = None
    untraceable: list[str] = []
    citations: list[str] = []


class SurfaceRead(BaseModel):
    mode: str
    model_id: str | None
    tools: list[dict]
    capabilities: list[str]
    writes: list[str]


@router.post("/ask", response_model=AnswerRead)
def ask_question(
    payload: AskRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> AnswerRead:
    answer = ask(db, actor, payload.question, request_id=getattr(request.state, "request_id", None))
    return AnswerRead(
        mode=answer.mode, answer=answer.answer, model_id=answer.model_id, note=answer.note,
        tool_calls=[ToolCallRead(name=c.name, input=c.input, summary=c.summary) for c in answer.tool_calls],
        intent=answer.intent, grounded=answer.grounded, untraceable=answer.untraceable, citations=answer.citations,
    )


class ConversationRead(BaseModel):
    id: str
    actor: str
    question: str
    answer: str
    mode: str
    intent: str
    grounded: bool | None
    untraceable: list[str]
    tool_calls: list[dict]
    request_id: str | None
    created_at: str


@router.get("/history", response_model=list[ConversationRead])
def history(limit: int = 50, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)) -> list[ConversationRead]:
    """WBS 14.5: the caller's own conversations; an admin sees everyone's."""
    from app.db.models.conversation import Conversation

    # id is the tiebreak so the order is at least deterministic across replicas.
    stmt = select(Conversation).order_by(Conversation.created_at.desc(), Conversation.id.desc()).limit(limit)
    if actor.role != "admin":
        stmt = stmt.where(Conversation.actor == actor.user_id)
    return [ConversationRead(id=c.id, actor=c.actor, question=c.question, answer=c.answer, mode=c.mode, intent=c.intent,
                             grounded=c.grounded, untraceable=c.untraceable, tool_calls=c.tool_calls,
                             request_id=c.request_id, created_at=c.created_at.isoformat())
            for c in db.scalars(stmt).all()]


@router.get("/embed")
def embed() -> dict:
    """WBS 14.6: how the Workflow Manager embeds the panel. The SPA serves the
    panel standalone at /embed/assistant; the host passes the acting identity
    and receives answers over postMessage. No write tool exists in the panel,
    so embedding it grants nothing the API would not."""
    return {
        "iframe_path": "/embed/assistant",
        "query_params": {"theme": "light|dark"},
        "post_message": {
            "to_panel": {"type": "opptrack.identity", "actor": "<user id>", "role": "<role>", "regions": "<csv or *>",
                         "token": "<bearer token when SSO is on>"},
            "from_panel": [{"type": "opptrack.answer", "question": "...", "answer": "...", "grounded": True,
                            "citations": ["get_rollup({...})"]},
                           {"type": "opptrack.ready"}],
        },
        "writes": [],
    }


@router.get("/surface", response_model=SurfaceRead)
def surface() -> SurfaceRead:
    """What the assistant can reach, so the panel can say it rather than the user
    discovering the boundary by being refused."""
    from app.core.config import settings

    live = settings.judgment_mode == "live" and bool(settings.anthropic_api_key)
    return SurfaceRead(
        mode="live" if live else "reader",
        model_id=settings.judgment_model if live else None,
        tools=[{"name": t["name"], "description": t["description"]} for t in TOOL_SCHEMAS],
        capabilities=CAPABILITIES,
        # Named explicitly, because "there is no such tool" is a design claim
        # worth being able to check rather than take on trust.
        writes=[],
    )
