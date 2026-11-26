"""The guide's tools. Ported from hasesa-lab-web app/guide/actions.ts and lib/tracker.ts."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.content.models import Module
from hasesa_api.models import (
    GuideFeedback,
    ModuleEnrollment,
    QuestionAttempt,
    Signoff,
    StepProgress,
    UnitAssignment,
    UnitProgress,
    User,
)

MAX_FEEDBACK = 2000
MAX_ASSIGNMENT_NOTE = 500
MAX_FLAG_NOTE = 300
MAX_SIGNOFF_NOTE = 1000

# 10 characters without look-alikes (0/O, 1/I/L), e.g. "HX7K-MP3Q9R".
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def certificate_code() -> str:
    s = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(10))
    return f"{s[:4]}-{s[4:]}"


async def student_exists(db: AsyncSession, student_id: str) -> bool:
    return bool(await db.scalar(select(exists().where(User.id == student_id))))


@dataclass
class RosterData:
    students: list[User]
    enrollments: list[ModuleEnrollment]
    steps: list[StepProgress]
    units: list[UnitProgress]
    signoffs: list[Signoff]
    attempts: list[QuestionAttempt]


async def roster_data(db: AsyncSession, now: datetime | None = None) -> RosterData:
    """Every student the guide should see: anyone currently enrolled, plus anyone
    who has started a module (so lapsed students don't vanish mid-module)."""
    now = now or datetime.now(UTC)
    started = select(ModuleEnrollment.user_id)
    users = (
        await db.scalars(
            select(User)
            .where(or_(User.paid_until > now, User.id.in_(started)), User.role != "guide")
            .order_by(User.display_name)
        )
    ).all()
    ids = [u.id for u in users]
    if not ids:
        return RosterData([], [], [], [], [], [])

    async def rows(model, col):  # type: ignore[no-untyped-def]
        return list((await db.scalars(select(model).where(col.in_(ids)))).all())

    return RosterData(
        students=list(users),
        enrollments=await rows(ModuleEnrollment, ModuleEnrollment.user_id),
        steps=await rows(StepProgress, StepProgress.user_id),
        units=await rows(UnitProgress, UnitProgress.user_id),
        signoffs=await rows(Signoff, Signoff.user_id),
        attempts=await rows(QuestionAttempt, QuestionAttempt.user_id),
    )


async def student_attempts(db: AsyncSession, student_id: str) -> list[QuestionAttempt]:
    """A student's answers, newest first."""
    stmt = (
        select(QuestionAttempt).where(QuestionAttempt.user_id == student_id).order_by(QuestionAttempt.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def give_feedback(
    db: AsyncSession, guide_id: str, student_id: str, body: str, module_id: str | None, step_id: str | None
) -> str:
    fid = str(uuid.uuid4())
    db.add(
        GuideFeedback(id=fid, student_id=student_id, guide_id=guide_id, module_id=module_id, step_id=step_id, body=body)
    )
    await db.commit()
    return fid


async def assign_unit(db: AsyncSession, guide_id: str, student_id: str, unit_id: str, note: str | None) -> str:
    aid = str(uuid.uuid4())
    db.add(UnitAssignment(id=aid, student_id=student_id, unit_id=unit_id, note=note, guide_id=guide_id))
    await db.commit()
    return aid


async def remove_assignment(db: AsyncSession, student_id: str, assignment_id: str) -> None:
    await db.execute(
        delete(UnitAssignment).where(UnitAssignment.id == assignment_id, UnitAssignment.student_id == student_id)
    )
    await db.commit()


async def set_flag(db: AsyncSession, student_id: str, module_id: str, flagged: bool, note: str | None) -> bool:
    """Flag (or clear) a student's module. False when they haven't started it."""
    res = await db.execute(
        update(ModuleEnrollment)
        .where(ModuleEnrollment.user_id == student_id, ModuleEnrollment.module_id == module_id)
        .values(flagged=flagged, flag_note=note if flagged else None)
        .returning(ModuleEnrollment.user_id)
    )
    found = res.first() is not None
    await db.commit()
    return found


async def sign_off(db: AsyncSession, guide_id: str, student_id: str, m: Module, note: str | None) -> str:
    """Sign off a module and mark it completed. Returns the certificate code
    (an earlier sign-off keeps its code)."""
    now = datetime.now(UTC)
    await db.execute(
        insert(Signoff)
        .values(
            user_id=student_id,
            module_id=m.id,
            checks=[s.id for s in m.signoff],
            note=note,
            guide_id=guide_id,
            signed_at=now,
            certificate_code=certificate_code(),
        )
        .on_conflict_do_nothing()
    )
    await db.execute(
        insert(ModuleEnrollment)
        .values(
            user_id=student_id, module_id=m.id, status="completed", started_at=now, updated_at=now, completed_at=now
        )
        .on_conflict_do_update(
            index_elements=[ModuleEnrollment.user_id, ModuleEnrollment.module_id],
            set_={"status": "completed", "completed_at": now, "updated_at": now, "flagged": False, "flag_note": None},
        )
    )
    code = await db.scalar(
        select(Signoff.certificate_code).where(Signoff.user_id == student_id, Signoff.module_id == m.id)
    )
    await db.commit()
    return code or ""


async def undo_sign_off(db: AsyncSession, student_id: str, module_id: str) -> None:
    await db.execute(delete(Signoff).where(Signoff.user_id == student_id, Signoff.module_id == module_id))
    await db.execute(
        update(ModuleEnrollment)
        .where(ModuleEnrollment.user_id == student_id, ModuleEnrollment.module_id == module_id)
        .values(status="active", completed_at=None, updated_at=datetime.now(UTC))
    )
    await db.commit()
