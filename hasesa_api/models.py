"""Database tables.

These mirror the schema the web app created with Drizzle (hasesa-lab-web
lib/db/schema.ts) exactly: same table, column and index names. From now on
Alembic owns the schema; change it here and add a migration.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _user_fk(*, cascade: bool = True) -> Any:
    return ForeignKey("users.id", ondelete="CASCADE" if cascade else None)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("users_email_lower_idx", "email", unique=True),
        Index("users_google_sub_idx", "google_sub", unique=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    # Google account ID ("sub"). Nullable so accounts created before Google
    # sign-in can be linked by email on their first Google sign-in.
    google_sub: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'en'"))  # en | am | om
    region: Mapped[str | None] = mapped_column(Text)
    school: Mapped[str | None] = mapped_column(Text)
    under_18: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    extended_retention: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Retired with the grade 9-12 catalogue; dropped in a later migration.
    subjects: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    grade: Mapped[int | None] = mapped_column(Integer)
    # student | guide
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'student'"))
    # End of the Academy enrolment. Null or in the past = not enrolled.
    paid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class ExperimentProgress(Base):
    """Retired grade 9-12 catalogue; no longer written. Dropped in a later migration."""

    __tablename__ = "experiment_progress"
    __table_args__ = (PrimaryKeyConstraint("user_id", "experiment_id"),)

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    experiment_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # started | done
    observations: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("conversations_user_idx", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    lesson_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("messages_conv_idx", "conversation_id", "created_at"),
        Index("messages_created_idx", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()


class PageView(Base):
    __tablename__ = "page_views"
    __table_args__ = (
        Index("page_views_created_idx", "created_at"),
        Index("page_views_path_idx", "path"),
        Index("page_views_country_idx", "country"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    referrer: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Usage(Base):
    """Per-user daily usage counters for cost caps."""

    __tablename__ = "usage"
    __table_args__ = (PrimaryKeyConstraint("user_id", "period"),)

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    period: Mapped[str] = mapped_column(Text, nullable=False)  # Addis Ababa calendar day, "2026-10-19"
    chat_turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))


class Payment(Base):
    """One row per checkout attempt (Chapa) or manual grant (admin)."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("payments_user_idx", "user_id", "created_at"),
        Index("payments_verified_idx", "verified_at"),
    )

    tx_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    amount_etb: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ETB'"))
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    # pending | success | failed | review ("review": paid but amount or currency mismatched)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # chapa | admin
    chapa_ref: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------- Academy modules ----------


class ModuleEnrollment(Base):
    __tablename__ = "module_enrollments"
    __table_args__ = (PrimaryKeyConstraint("user_id", "module_id"),)

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    module_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # active | dropped | completed
    started_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    flag_note: Mapped[str | None] = mapped_column(Text)


class StepProgress(Base):
    __tablename__ = "step_progress"
    __table_args__ = (PrimaryKeyConstraint("user_id", "module_id", "step_id"),)

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    module_id: Mapped[str] = mapped_column(Text, nullable=False)
    step_id: Mapped[str] = mapped_column(Text, nullable=False)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnitProgress(Base):
    __tablename__ = "unit_progress"
    __table_args__ = (PrimaryKeyConstraint("user_id", "unit_id"),)

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    unit_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # started | completed | tested_out
    # Practice: % right on the first try. Tested out: the test-out score.
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"
    __table_args__ = (Index("question_attempts_user_unit_idx", "user_id", "unit_id", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    unit_id: Mapped[str] = mapped_column(Text, nullable=False)
    question_id: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)  # practice | testout
    created_at: Mapped[datetime] = _now()


class Signoff(Base):
    """The guide's sign-off on a finished module. The row is the certificate."""

    __tablename__ = "signoffs"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "module_id"),
        Index("signoffs_code_idx", "certificate_code", unique=True),
    )

    user_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    module_id: Mapped[str] = mapped_column(Text, nullable=False)
    checks: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    guide_id: Mapped[str] = mapped_column(Text, _user_fk(cascade=False), nullable=False)
    signed_at: Mapped[datetime] = _now()
    certificate_code: Mapped[str] = mapped_column(Text, nullable=False)


class GuideFeedback(Base):
    __tablename__ = "guide_feedback"
    __table_args__ = (Index("guide_feedback_student_idx", "student_id", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    guide_id: Mapped[str] = mapped_column(Text, _user_fk(cascade=False), nullable=False)
    module_id: Mapped[str | None] = mapped_column(Text)
    step_id: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnitAssignment(Base):
    """Concept units the guide asked a student to study. Done = unit_progress says so."""

    __tablename__ = "unit_assignments"
    __table_args__ = (Index("unit_assignments_student_idx", "student_id", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    student_id: Mapped[str] = mapped_column(Text, _user_fk(), nullable=False)
    unit_id: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    guide_id: Mapped[str] = mapped_column(Text, _user_fk(cascade=False), nullable=False)
    created_at: Mapped[datetime] = _now()
