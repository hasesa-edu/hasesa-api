"""Per-user rate limits, counted from rows the API already writes.

The website has its own per-IP limits, but students can call the API directly
(the mobile sign-in gives anyone tokens for their own account), so the costly
or table-filling endpoints check here too. Counting existing rows works across
every serverless instance without a new table.
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.models import AuthSession, Payment, QuestionAttempt

# Chapa checkouts started in 10 minutes (each one calls Chapa with the merchant key).
CHECKOUTS_PER_10_MIN = 10
# Saved answers per minute; a whole test-out counts each of its answers.
ANSWERS_PER_MINUTE = 120
# Sessions a mobile sign-in may create per hour.
SIGN_INS_PER_HOUR = 20


def slow_down(message: str = "Too many requests. Please slow down.", retry_after: int = 60) -> HTTPException:
    return HTTPException(status_code=429, detail=message, headers={"Retry-After": str(retry_after)})


async def _count_since(db: AsyncSession, column, user_column, user_id: str, since: timedelta, *extra) -> int:  # type: ignore[no-untyped-def]
    cutoff = datetime.now(UTC) - since
    stmt = select(func.count()).where(user_column == user_id, column >= cutoff, *extra)
    return (await db.scalar(stmt)) or 0


async def check_checkouts(db: AsyncSession, user_id: str) -> None:
    n = await _count_since(
        db, Payment.created_at, Payment.user_id, user_id, timedelta(minutes=10), Payment.source == "chapa"
    )
    if n >= CHECKOUTS_PER_10_MIN:
        raise slow_down("Too many attempts. Please wait a few minutes.", 600)


async def check_answers(db: AsyncSession, user_id: str, adding: int = 1) -> None:
    n = await _count_since(db, QuestionAttempt.created_at, QuestionAttempt.user_id, user_id, timedelta(minutes=1))
    if n + adding > ANSWERS_PER_MINUTE:
        raise slow_down()


async def sign_ins_last_hour(db: AsyncSession, user_id: str) -> int:
    return await _count_since(db, AuthSession.created_at, AuthSession.user_id, user_id, timedelta(hours=1))
