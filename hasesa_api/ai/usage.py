"""Daily message caps, reset at midnight Addis Ababa time. Ported from hasesa-lab-web lib/usage.ts."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.models import Conversation, Message, Usage

DAILY_CHAT_CAP = 30
# A student may send at most this many messages in any 5 minutes, so a loop
# can't burn the AI provider's quota. Counted from the messages table, which
# works across every server instance.
BURST_LIMIT = 20
BURST_WINDOW = timedelta(minutes=5)


def current_period(now: datetime | None = None) -> str:
    """Today's date in Addis Ababa (UTC+3, no DST), e.g. "2026-10-19"."""
    return ((now or datetime.now(UTC)) + timedelta(hours=3)).strftime("%Y-%m-%d")


async def chat_turns_used(db: AsyncSession, user_id: str) -> int:
    used = await db.scalar(select(Usage.chat_turns).where(Usage.user_id == user_id, Usage.period == current_period()))
    return used or 0


@dataclass
class CapResult:
    ok: bool
    current: int
    cap: int


async def check_and_increment(db: AsyncSession, user_id: str, amount: int = 1) -> CapResult:
    """Count a message against today's cap, in one statement so parallel
    requests can't all slip under it. Commits."""
    period = current_period()
    await db.execute(insert(Usage).values(user_id=user_id, period=period, chat_turns=0).on_conflict_do_nothing())
    value = await db.scalar(
        update(Usage)
        .where(
            Usage.user_id == user_id,
            Usage.period == period,
            Usage.chat_turns + amount <= DAILY_CHAT_CAP,
        )
        .values(chat_turns=Usage.chat_turns + amount)
        .returning(Usage.chat_turns)
    )
    await db.commit()
    if value is None:
        return CapResult(False, await chat_turns_used(db, user_id), DAILY_CHAT_CAP)
    return CapResult(True, value, DAILY_CHAT_CAP)


async def refund(db: AsyncSession, user_id: str, amount: int = 1) -> None:
    """Give back a message that got no answer (e.g. the AI provider failed). Commits."""
    await db.execute(
        update(Usage)
        .where(Usage.user_id == user_id, Usage.period == current_period())
        .values(chat_turns=func.greatest(Usage.chat_turns - amount, 0))
    )
    await db.commit()


async def recent_messages(db: AsyncSession, user_id: str) -> int:
    """How many messages the student has sent in the last 5 minutes."""
    since = datetime.now(UTC) - BURST_WINDOW
    return (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Message.role == "user", Message.created_at >= since)
        )
        or 0
    )
