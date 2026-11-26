"""Student progress: enrolments, steps, units, attempts and certificates.

Ported from hasesa-lab-web lib/progress.ts and lib/certificates.ts. The rules
(what counts as completed, how scores are kept) must stay identical, because
the website reads and writes the same tables until every part has switched over.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hasesa_api.content.loader import get_content
from hasesa_api.content.models import Concept
from hasesa_api.learning.grade import TEST_OUT_PASS, Problem, is_correct, js_round, score_unit
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

MAX_NOTES = 4000
MAX_ANSWER = 200
CERTIFICATE_CODE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{6}$")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class StudentState:
    enrollments: list[ModuleEnrollment]
    steps: list[StepProgress]
    units: list[UnitProgress]
    signoffs: list[Signoff]
    feedback: list[GuideFeedback]
    assignments: list[UnitAssignment]


async def get_student_state(db: AsyncSession, user_id: str) -> StudentState:
    """Everything about one student's progress."""

    async def rows(stmt: Any) -> list[Any]:
        return list((await db.scalars(stmt)).all())

    return StudentState(
        enrollments=await rows(select(ModuleEnrollment).where(ModuleEnrollment.user_id == user_id)),
        steps=await rows(select(StepProgress).where(StepProgress.user_id == user_id)),
        units=await rows(select(UnitProgress).where(UnitProgress.user_id == user_id)),
        signoffs=await rows(select(Signoff).where(Signoff.user_id == user_id)),
        feedback=await rows(
            select(GuideFeedback)
            .where(GuideFeedback.student_id == user_id)
            .order_by(GuideFeedback.created_at.desc())
            .limit(50)
        ),
        assignments=await rows(
            select(UnitAssignment)
            .where(UnitAssignment.student_id == user_id)
            .order_by(UnitAssignment.created_at.desc())
        ),
    )


async def get_attempts(db: AsyncSession, user_id: str, unit_ids: list[str] | None = None) -> list[QuestionAttempt]:
    stmt = select(QuestionAttempt).where(QuestionAttempt.user_id == user_id)
    if unit_ids:
        stmt = stmt.where(QuestionAttempt.unit_id.in_(unit_ids))
    return list((await db.scalars(stmt.order_by(QuestionAttempt.created_at))).all())


async def set_enrollment(db: AsyncSession, user_id: str, module_id: str, status: Literal["active", "dropped"]) -> str:
    """Start or drop a module. Returns the enrolment's status afterwards."""
    existing = await db.scalar(
        select(ModuleEnrollment.status).where(
            ModuleEnrollment.user_id == user_id, ModuleEnrollment.module_id == module_id
        )
    )
    # A signed-off module stays completed; dropping or restarting it changes nothing.
    if existing == "completed":
        return existing
    now = _now()
    await db.execute(
        insert(ModuleEnrollment)
        .values(user_id=user_id, module_id=module_id, status=status, started_at=now, updated_at=now)
        .on_conflict_do_update(
            index_elements=[ModuleEnrollment.user_id, ModuleEnrollment.module_id],
            set_={"status": status, "updated_at": now},
        )
    )
    await db.commit()
    return status


@dataclass
class StepState:
    done: bool
    notes: str | None


async def save_step(
    db: AsyncSession, user_id: str, module_id: str, step_id: str, *, done: bool | None, notes: str | None
) -> StepState:
    now = _now()
    existing = (
        await db.execute(
            select(StepProgress.done, StepProgress.notes, StepProgress.completed_at).where(
                StepProgress.user_id == user_id,
                StepProgress.module_id == module_id,
                StepProgress.step_id == step_id,
            )
        )
    ).first()
    new_done = done if done is not None else (existing.done if existing else False)
    if notes is not None:
        new_notes = notes.strip()[:MAX_NOTES] or None
    else:
        new_notes = existing.notes if existing else None
    completed_at = ((existing.completed_at if existing else None) or now) if new_done else None
    await db.execute(
        insert(StepProgress)
        .values(
            user_id=user_id,
            module_id=module_id,
            step_id=step_id,
            done=new_done,
            notes=new_notes,
            updated_at=now,
            completed_at=completed_at,
        )
        .on_conflict_do_update(
            index_elements=[StepProgress.user_id, StepProgress.module_id, StepProgress.step_id],
            set_={"done": new_done, "notes": new_notes, "updated_at": now, "completed_at": completed_at},
        )
    )
    # Working on a step means the student is in the module, even if they never pressed "Start".
    await db.execute(
        insert(ModuleEnrollment)
        .values(user_id=user_id, module_id=module_id, status="active", started_at=now, updated_at=now)
        .on_conflict_do_update(
            index_elements=[ModuleEnrollment.user_id, ModuleEnrollment.module_id],
            set_={"updated_at": now},
        )
    )
    await db.commit()
    return StepState(done=new_done, notes=new_notes)


@dataclass
class UnitState:
    status: str
    score: int


async def _refresh_unit(
    db: AsyncSession, user_id: str, concept: Concept, test_out_score: int | None = None
) -> UnitState:
    """Recompute a unit's status and score from every attempt the student has made."""
    attempts = await get_attempts(db, user_id, [concept.id])
    scored = score_unit([p.id for p in concept.problems], attempts)
    existing = (
        await db.execute(
            select(UnitProgress.status, UnitProgress.score, UnitProgress.completed_at).where(
                UnitProgress.user_id == user_id, UnitProgress.unit_id == concept.id
            )
        )
    ).first()

    now = _now()
    status = existing.status if existing else "started"
    score = scored.first_try_pct
    if test_out_score is not None and test_out_score >= TEST_OUT_PASS * 100 and status != "completed":
        status = "tested_out"
        score = test_out_score
    elif status == "tested_out":
        score = existing.score  # type: ignore[union-attr]  # tested_out implies a row exists
    elif scored.all_correct:
        status = "completed"
    completed_at = None if status == "started" else ((existing.completed_at if existing else None) or now)
    await db.execute(
        insert(UnitProgress)
        .values(
            user_id=user_id, unit_id=concept.id, status=status, score=score, updated_at=now, completed_at=completed_at
        )
        .on_conflict_do_update(
            index_elements=[UnitProgress.user_id, UnitProgress.unit_id],
            set_={"status": status, "score": score, "updated_at": now, "completed_at": completed_at},
        )
    )
    return UnitState(status=status, score=score)


async def record_attempt(
    db: AsyncSession, user_id: str, concept: Concept, problem: Problem, answer: str, correct: bool
) -> UnitState:
    db.add(
        QuestionAttempt(
            id=str(uuid.uuid4()),
            user_id=user_id,
            unit_id=concept.id,
            question_id=problem.id,
            answer=answer[:MAX_ANSWER],
            correct=correct,
            mode="practice",
        )
    )
    await db.flush()
    unit = await _refresh_unit(db, user_id, concept)
    await db.commit()
    return unit


@dataclass
class GradedAnswer:
    problem: Problem
    answer: str
    correct: bool


@dataclass
class GradedTestOut:
    score: int
    passed: bool
    results: list[GradedAnswer]
    unit: UnitState | None


async def grade_test_out(
    db: AsyncSession, user_id: str | None, concept: Concept, answers: dict[str, Any]
) -> GradedTestOut:
    """Grade a full test-out. Records every answer when a user is given."""
    results = []
    for p in concept.problems:
        raw = answers.get(p.id)
        answer = raw if isinstance(raw, str) else ""
        results.append(GradedAnswer(problem=p, answer=answer, correct=answer != "" and is_correct(p, answer)))
    score = js_round(sum(r.correct for r in results) / len(results) * 100)
    unit = None
    if user_id:
        now = _now()
        db.add_all(
            QuestionAttempt(
                id=str(uuid.uuid4()),
                user_id=user_id,
                unit_id=concept.id,
                question_id=r.problem.id,
                answer=r.answer[:MAX_ANSWER],
                correct=r.correct,
                mode="testout",
                # Keep the order stable for first-try scoring.
                created_at=now + timedelta(milliseconds=i),
            )
            for i, r in enumerate(results)
        )
        await db.flush()
        unit = await _refresh_unit(db, user_id, concept, score)
        await db.commit()
    return GradedTestOut(score=score, passed=score >= TEST_OUT_PASS * 100, results=results, unit=unit)


async def mark_feedback_read(db: AsyncSession, user_id: str, feedback_id: str) -> None:
    await db.execute(
        update(GuideFeedback)
        .where(GuideFeedback.id == feedback_id, GuideFeedback.student_id == user_id)
        .values(read_at=_now())
    )
    await db.commit()


@dataclass
class Certificate:
    module_id: str
    signed_at: datetime
    note: str | None
    code: str
    student: str
    guide: str


async def get_certificate(db: AsyncSession, code: str) -> Certificate | None:
    if not CERTIFICATE_CODE.match(code):
        return None
    student = aliased(User)
    guide = aliased(User)
    row = (
        await db.execute(
            select(Signoff, student.display_name, guide.display_name)
            .join(student, student.id == Signoff.user_id)
            .outerjoin(guide, guide.id == Signoff.guide_id)
            .where(Signoff.certificate_code == code)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    s, student_name, guide_name = row
    return Certificate(
        module_id=s.module_id,
        signed_at=s.signed_at,
        note=s.note,
        code=s.certificate_code,
        student=student_name,
        guide=guide_name or "Hasesa Academy guide",
    )


def find_concept(unit_id: str) -> Concept | None:
    return get_content().concepts.get(unit_id)
