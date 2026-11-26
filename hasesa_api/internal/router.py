"""Scheduled jobs, called by Vercel Cron (see vercel.json) with CRON_SECRET."""

import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text

from hasesa_api.config import get_settings
from hasesa_api.db import DbDep
from hasesa_api.identity import sessions
from hasesa_api.schemas import ApiModel

log = logging.getLogger(__name__)


def cron_caller(authorization: Annotated[str | None, Header()] = None) -> None:
    secret = get_settings().cron_secret
    if not secret or not hmac.compare_digest((authorization or "").encode(), f"Bearer {secret}".encode()):
        raise HTTPException(status_code=403, detail="Forbidden")


router = APIRouter(prefix="/internal", tags=["jobs"], dependencies=[Depends(cron_caller)], include_in_schema=False)


# Lab assistant messages are kept 90 days, or 365 for accounts with extended
# retention. Progress, notes and answers are kept for good.
_OLD_MESSAGES = text("""
delete from messages m
using conversations c, users u
where m.conversation_id = c.id
  and c.user_id = u.id
  and (
    (u.extended_retention = false and m.created_at < now() - interval '90 days')
    or (u.extended_retention = true and m.created_at < now() - interval '365 days')
  )
""")

# Conversations left empty, a week after their last use.
_EMPTY_CONVERSATIONS = text("""
delete from conversations c
where not exists (select 1 from messages m where m.conversation_id = c.id)
  and c.updated_at < now() - interval '7 days'
""")


class CleanupOut(ApiModel):
    messages_deleted: int
    conversations_deleted: int
    sessions_deleted: int


@router.get("/cleanup")
async def cleanup(db: DbDep) -> CleanupOut:
    """Daily: delete chat messages past their retention, then empty conversations,
    then sign-in sessions that ended over a week ago."""
    messages = (await db.execute(_OLD_MESSAGES)).rowcount
    conversations = (await db.execute(_EMPTY_CONVERSATIONS)).rowcount
    old_sessions = await sessions.purge_expired(db)
    await db.commit()
    log.info("cleanup: %s messages, %s conversations, %s sessions deleted", messages, conversations, old_sessions)
    return CleanupOut(messages_deleted=messages, conversations_deleted=conversations, sessions_deleted=old_sessions)
