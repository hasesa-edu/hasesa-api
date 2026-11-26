"""The lab assistant: chat on course pages, streamed as Server-Sent Events.

POST /v1/chat streams these events:
  meta   {"conversationId", "remaining"}   first, always
  delta  {"text"}                          pieces of the answer
  done   {}                                the answer is complete (and saved)
  error  {"error"}                         the provider failed mid-answer

Anything wrong before the answer starts is an ordinary JSON error instead, with
`detail` (safe to show) and, where useful, an `X-Error-Code` header: `signin`,
`enrol`, `daily_cap`.
"""

import logging
import uuid
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import Field
from sqlalchemy import delete, select, update

from hasesa_api.access import access_level, has_full_access
from hasesa_api.ai import context as ctx
from hasesa_api.ai import provider, usage
from hasesa_api.ai.prompt import build_system_prompt
from hasesa_api.db import DbDep, get_sessionmaker
from hasesa_api.identity.deps import CurrentUserDep
from hasesa_api.models import Conversation, Message, User
from hasesa_api.schemas import ApiModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["lab assistant"])

MAX_MESSAGE_CHARS = 8000
MAX_HISTORY = 20


def _error(status: int, detail: str, code: str | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail=detail, headers={"X-Error-Code": code} if code else None)


def _require_assistant(user: User) -> None:
    if not has_full_access(access_level(user.role, user.paid_until)):
        raise _error(403, "The lab assistant is for students enrolled at the Academy.", "enrol")


# ---------- chat ----------


class ChatIn(ApiModel):
    # Only "user" and "assistant" turns of up to 8000 characters are used; the last 20 count.
    messages: Annotated[list[Any], Field(max_length=200)]
    locale: str = "en"
    # "m:<module>", "m:<module>/<step>" or "c:<concept>": the page the student is on.
    context: str | None = Field(default=None, max_length=300)
    conversation_id: str | None = Field(default=None, max_length=100)


@dataclass
class Turn:
    user_id: str
    conversation_id: str
    remaining: int
    stream: provider.OpenStream


def _clean(messages: list[Any]) -> list[dict[str, str]]:
    """Only trust user/assistant turns from the client: drop any injected "system" role and malformed entries."""
    ok = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if isinstance(m, dict)
        and m.get("role") in ("user", "assistant")
        and isinstance(m.get("content"), str)
        and len(m["content"]) <= MAX_MESSAGE_CHARS
    ]
    return ok[-MAX_HISTORY:]


async def start_turn(body: ChatIn, user: CurrentUserDep, db: DbDep) -> Turn:
    """Everything that can fail with a normal HTTP error, before the answer streams."""
    _require_assistant(user)
    if await usage.recent_messages(db, user.id) >= usage.BURST_LIMIT:
        raise HTTPException(
            status_code=429, detail="Too many requests. Please slow down.", headers={"Retry-After": "60"}
        )
    context = body.context if ctx.is_valid_context(body.context) else None
    messages = _clean(body.messages)
    if not messages:
        raise HTTPException(status_code=400, detail="messages required")

    conversation_id = body.conversation_id
    if conversation_id:
        owned = await db.scalar(
            select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user.id)
        )
        if owned is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Count the message only once the request is known to be valid.
    cap = await usage.check_and_increment(db, user.id)
    if not cap.ok:
        raise _error(
            429,
            f"You've used all {cap.cap} messages for today. They reset at midnight (Addis Ababa time).",
            "daily_cap",
        )

    now = datetime.now(UTC)
    if conversation_id is None:
        conversation_id = str(uuid.uuid4())
        db.add(Conversation(id=conversation_id, user_id=user.id, lesson_id=context))
    else:
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user.id)
            .values(updated_at=now)
        )
    last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)
    if last_user:
        db.add(
            Message(id=str(uuid.uuid4()), conversation_id=conversation_id, role="user", content=last_user["content"])
        )
    await db.commit()

    student = None
    if context:
        try:
            student = await ctx.student_context_for(db, user.id, context)
        except Exception:  # noqa: BLE001  # the answer is still useful without it
            log.exception("student context failed")
    try:
        stream = await provider.open_stream(build_system_prompt(context, student), messages)
    except provider.ProviderUnavailable as e:
        # The student got no answer, so don't count it against today's messages.
        await usage.refund(db, user.id)
        raise HTTPException(
            status_code=502, detail="The lab assistant is temporarily unavailable. Please try again."
        ) from e
    return Turn(user.id, conversation_id, max(0, cap.cap - cap.current), stream)


async def _save_answer(conversation_id: str, text: str) -> None:
    async with get_sessionmaker()() as db:
        db.add(Message(id=str(uuid.uuid4()), conversation_id=conversation_id, role="assistant", content=text))
        await db.commit()


@router.post("", response_class=EventSourceResponse)
async def chat(turn: Annotated[Turn, Depends(start_turn)]) -> AsyncIterable[ServerSentEvent]:
    """Ask the lab assistant. Enrolled students and guides; 30 messages a day."""
    yield ServerSentEvent(event="meta", data={"conversationId": turn.conversation_id, "remaining": turn.remaining})
    answer: list[str] = []
    failed = False
    try:
        async for piece in turn.stream.deltas():
            answer.append(piece)
            yield ServerSentEvent(event="delta", data={"text": piece})
    except httpx.HTTPError as e:
        log.error("AI provider stream broke: %s", e)
        failed = True
    finally:
        await turn.stream.close()
    if answer:
        try:
            await _save_answer(turn.conversation_id, "".join(answer))
        except Exception:  # noqa: BLE001  # the student already has the answer
            log.exception("saving the assistant's answer failed")
    if failed:
        yield ServerSentEvent(event="error", data={"error": "The lab assistant stopped answering. Please try again."})
    else:
        yield ServerSentEvent(event="done", data={})


# ---------- threads and history ----------


class ChatMessageOut(ApiModel):
    role: str
    content: str


class ThreadOut(ApiModel):
    conversation_id: str | None
    messages: list[ChatMessageOut]
    remaining: int
    cap: int


@router.get("/thread")
async def thread(
    user: CurrentUserDep,
    db: DbDep,
    response: Response,
    context: Annotated[str, Query(max_length=300)],
) -> ThreadOut:
    """The student's latest conversation on this page (one thread per page), and messages left today."""
    _require_assistant(user)
    if not ctx.is_valid_context(context):
        raise HTTPException(status_code=400, detail="Unknown page")
    response.headers["Cache-Control"] = "private, no-store"
    convo = await db.scalar(
        select(Conversation.id)
        .where(Conversation.user_id == user.id, Conversation.lesson_id == context)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    messages = []
    if convo:
        rows = await db.execute(
            select(Message.role, Message.content)
            .where(Message.conversation_id == convo)
            .order_by(Message.created_at)
            .limit(60)
        )
        messages = [ChatMessageOut(role=r.role, content=r.content) for r in rows]
    used = await usage.chat_turns_used(db, user.id)
    return ThreadOut(
        conversation_id=convo,
        messages=messages,
        remaining=max(0, usage.DAILY_CHAT_CAP - used),
        cap=usage.DAILY_CHAT_CAP,
    )


class ConversationOut(ApiModel):
    id: str
    user_id: str
    lesson_id: str | None
    created_at: datetime
    updated_at: datetime


class ConversationsOut(ApiModel):
    conversations: list[ConversationOut]
    retention_days: int


class HistoryMessageOut(ApiModel):
    id: str
    role: str
    content: str
    created_at: datetime


class ConversationDetailOut(ApiModel):
    conversation: ConversationOut
    messages: list[HistoryMessageOut]


def _retention_days(user: User) -> int:
    return 365 if user.extended_retention else 90


def _conversation_out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id, user_id=c.user_id, lesson_id=c.lesson_id, created_at=c.created_at, updated_at=c.updated_at
    )


@router.get("/conversations")
async def conversations(user: CurrentUserDep, db: DbDep, response: Response) -> ConversationsOut:
    """Recent conversations: 90 days, or 365 with extended retention. The latest 50."""
    response.headers["Cache-Control"] = "private, no-store"
    days = _retention_days(user)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.updated_at >= cutoff)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    return ConversationsOut(conversations=[_conversation_out(c) for c in rows], retention_days=days)


async def _own_conversation(db: DbDep, user: User, conversation_id: str) -> Conversation:
    c = await db.get(Conversation, conversation_id)
    if c is None or c.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    return c


@router.get("/conversations/{conversation_id}")
async def conversation(
    conversation_id: str, user: CurrentUserDep, db: DbDep, response: Response
) -> ConversationDetailOut:
    response.headers["Cache-Control"] = "private, no-store"
    c = await _own_conversation(db, user, conversation_id)
    cutoff = datetime.now(UTC) - timedelta(days=_retention_days(user))
    rows = await db.execute(
        select(Message.id, Message.role, Message.content, Message.created_at)
        .where(Message.conversation_id == c.id, Message.created_at >= cutoff)
        .order_by(Message.created_at)
    )
    return ConversationDetailOut(
        conversation=_conversation_out(c),
        messages=[HistoryMessageOut(id=r.id, role=r.role, content=r.content, created_at=r.created_at) for r in rows],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user: CurrentUserDep, db: DbDep) -> Response:
    c = await _own_conversation(db, user, conversation_id)
    await db.execute(delete(Conversation).where(Conversation.id == c.id))
    await db.commit()
    return Response(status_code=204)
