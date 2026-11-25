"""Accounts. Ported from hasesa-lab-web lib/auth/users.ts; keep the two in step until the web stops writing users."""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.access import PILOT_ENROLLED_UNTIL, access_level
from hasesa_api.identity.google import GoogleProfile
from hasesa_api.models import User
from hasesa_api.schemas import ApiModel

VALID_LOCALES = {"en"}
MAX_TEXT = 120


class EmailTakenError(Exception):
    """The email belongs to an account linked to a different Google account."""


class UserOut(ApiModel):
    id: str
    email: str
    display_name: str
    language: str
    region: str | None
    school: str | None
    under18: bool
    extended_retention: bool
    avatar_url: str | None
    # ISO timestamp the Academy enrolment ends, or null if never enrolled.
    paid_until: datetime | None
    role: Literal["student", "guide"]
    access: Literal["signed-in", "enrolled", "guide"]


class ProfilePatch(ApiModel):
    language: str | None = None
    region: str | None = None
    school: str | None = None
    extended_retention: bool | None = None


def _cap(value: str | None, limit: int = MAX_TEXT) -> str | None:
    return value.strip()[:limit] if isinstance(value, str) else None


async def _find_by_sub(db: AsyncSession, sub: str) -> str | None:
    return await db.scalar(select(User.id).where(User.google_sub == sub).limit(1))


async def upsert_google_user(db: AsyncSession, profile: GoogleProfile) -> tuple[str, bool]:
    """Find or create the account for a verified Google identity.

    Matches on the Google account ID first. An email match only links an
    account that has no Google ID yet (created before Google sign-in), so a
    second Google account with the same email can't take over an existing
    one. Returns (user_id, is_new). The caller commits.
    """
    email = profile.email.strip().lower()[:254]
    display_name = (_cap(profile.name, 100) or email.split("@")[0])[:100]
    avatar_url = profile.picture if profile.picture and profile.picture.startswith("https://") else None

    by_sub = await _find_by_sub(db, profile.sub)
    if by_sub:
        # Keep the email in sync with Google, unless another account already holds it.
        taken = await db.scalar(select(User.id).where(and_(User.email == email, User.id != by_sub)).limit(1))
        values: dict = {"avatar_url": avatar_url} if taken else {"email": email, "avatar_url": avatar_url}
        await db.execute(update(User).where(User.id == by_sub).values(**values))
        return by_sub, False

    linked = await db.scalar(
        update(User)
        .where(and_(User.email == email, User.google_sub.is_(None)))
        .values(google_sub=profile.sub, avatar_url=avatar_url)
        .returning(User.id)
    )
    if linked:
        return linked, False

    new_id = str(uuid.uuid4())
    inserted = await db.scalar(
        insert(User)
        .values(
            id=new_id,
            email=email,
            google_sub=profile.sub,
            display_name=display_name,
            avatar_url=avatar_url,
            paid_until=PILOT_ENROLLED_UNTIL,
        )
        .on_conflict_do_nothing()
        .returning(User.id)
    )
    if inserted:
        return inserted, True

    # Lost a race with a parallel sign-in for the same Google account.
    raced = await _find_by_sub(db, profile.sub)
    if raced:
        return raced, False
    raise EmailTakenError()


def user_out(u: User) -> UserOut:
    level = access_level(u.role, u.paid_until)
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        language=u.language,
        region=u.region,
        school=u.school,
        under18=u.under_18,
        extended_retention=u.extended_retention,
        avatar_url=u.avatar_url,
        paid_until=u.paid_until,
        role="guide" if u.role == "guide" else "student",
        access=level,  # type: ignore[arg-type]  # never "public" for a real user
    )


async def update_profile(db: AsyncSession, user_id: str, patch: ProfilePatch) -> None:
    values: dict = {}
    fields = patch.model_fields_set
    if "language" in fields and patch.language in VALID_LOCALES:
        values["language"] = patch.language
    if "region" in fields:
        values["region"] = _cap(patch.region)
    if "school" in fields:
        values["school"] = _cap(patch.school)
    if "extended_retention" in fields and patch.extended_retention is not None:
        values["extended_retention"] = patch.extended_retention
    if values:
        await db.execute(update(User).where(User.id == user_id).values(**values))
