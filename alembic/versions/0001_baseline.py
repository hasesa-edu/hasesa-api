"""Baseline: the schema the web app built with Drizzle.

On the existing Neon database these tables already exist, so this migration
detects that and does nothing (the database is adopted as-is, no data moves).
On an empty database it creates the full schema.

Revision ID: 0001
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, *, default_now: bool = False, nullable: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable and not default_now,
        server_default=sa.func.now() if default_now else None,
    )


def _user_fk(name: str, *, cascade: bool = True) -> sa.Column:
    fk = sa.ForeignKey("users.id", ondelete="CASCADE" if cascade else None)
    return sa.Column(name, sa.Text(), fk, nullable=False)


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("users"):
        # Existing database created by the web app: adopt it unchanged.
        return

    op.create_table(
        "users",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("google_sub", sa.Text()),
        sa.Column("avatar_url", sa.Text()),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False, server_default=sa.text("'en'")),
        sa.Column("region", sa.Text()),
        sa.Column("school", sa.Text()),
        sa.Column("under_18", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extended_retention", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("subjects", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("grade", sa.Integer()),
        sa.Column("role", sa.Text(), nullable=False, server_default=sa.text("'student'")),
        _ts("paid_until"),
        _ts("created_at", default_now=True),
    )
    op.create_index("users_email_lower_idx", "users", ["email"], unique=True)
    op.create_index("users_google_sub_idx", "users", ["google_sub"], unique=True)

    op.create_table(
        "experiment_progress",
        _user_fk("user_id"),
        sa.Column("experiment_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("observations", sa.Text()),
        _ts("updated_at", default_now=True),
        _ts("completed_at"),
        sa.PrimaryKeyConstraint("user_id", "experiment_id"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Text(), primary_key=True),
        _user_fk("user_id"),
        sa.Column("lesson_id", sa.Text()),
        _ts("created_at", default_now=True),
        _ts("updated_at", default_now=True),
    )
    op.create_index("conversations_user_idx", "conversations", ["user_id", "updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        _ts("created_at", default_now=True),
    )
    op.create_index("messages_conv_idx", "messages", ["conversation_id", "created_at"])
    op.create_index("messages_created_idx", "messages", ["created_at"])

    op.create_table(
        "page_views",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("country", sa.Text()),
        sa.Column("region", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("referrer", sa.Text()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("user_id", sa.Text()),
        _ts("created_at", default_now=True),
    )
    op.create_index("page_views_created_idx", "page_views", ["created_at"])
    op.create_index("page_views_path_idx", "page_views", ["path"])
    op.create_index("page_views_country_idx", "page_views", ["country"])

    op.create_table(
        "usage",
        _user_fk("user_id"),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("chat_turns", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("user_id", "period"),
    )

    op.create_table(
        "payments",
        sa.Column("tx_ref", sa.Text(), primary_key=True),
        _user_fk("user_id"),
        sa.Column("amount_etb", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'ETB'")),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("chapa_ref", sa.Text()),
        sa.Column("note", sa.Text()),
        _ts("created_at", default_now=True),
        _ts("verified_at"),
    )
    op.create_index("payments_user_idx", "payments", ["user_id", "created_at"])
    op.create_index("payments_verified_idx", "payments", ["verified_at"])

    op.create_table(
        "module_enrollments",
        _user_fk("user_id"),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        _ts("started_at", default_now=True),
        _ts("updated_at", default_now=True),
        _ts("completed_at"),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("flag_note", sa.Text()),
        sa.PrimaryKeyConstraint("user_id", "module_id"),
    )

    op.create_table(
        "step_progress",
        _user_fk("user_id"),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text()),
        _ts("updated_at", default_now=True),
        _ts("completed_at"),
        sa.PrimaryKeyConstraint("user_id", "module_id", "step_id"),
    )

    op.create_table(
        "unit_progress",
        _user_fk("user_id"),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _ts("updated_at", default_now=True),
        _ts("completed_at"),
        sa.PrimaryKeyConstraint("user_id", "unit_id"),
    )

    op.create_table(
        "question_attempts",
        sa.Column("id", sa.Text(), primary_key=True),
        _user_fk("user_id"),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("question_id", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        _ts("created_at", default_now=True),
    )
    op.create_index("question_attempts_user_unit_idx", "question_attempts", ["user_id", "unit_id", "created_at"])

    op.create_table(
        "signoffs",
        _user_fk("user_id"),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text()),
        _user_fk("guide_id", cascade=False),
        _ts("signed_at", default_now=True),
        sa.Column("certificate_code", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "module_id"),
    )
    op.create_index("signoffs_code_idx", "signoffs", ["certificate_code"], unique=True)

    op.create_table(
        "guide_feedback",
        sa.Column("id", sa.Text(), primary_key=True),
        _user_fk("student_id"),
        _user_fk("guide_id", cascade=False),
        sa.Column("module_id", sa.Text()),
        sa.Column("step_id", sa.Text()),
        sa.Column("body", sa.Text(), nullable=False),
        _ts("created_at", default_now=True),
        _ts("read_at"),
    )
    op.create_index("guide_feedback_student_idx", "guide_feedback", ["student_id", "created_at"])

    op.create_table(
        "unit_assignments",
        sa.Column("id", sa.Text(), primary_key=True),
        _user_fk("student_id"),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        _user_fk("guide_id", cascade=False),
        _ts("created_at", default_now=True),
    )
    op.create_index("unit_assignments_student_idx", "unit_assignments", ["student_id", "created_at"])


def downgrade() -> None:
    # Never drop the production schema from a migration.
    raise RuntimeError("The baseline cannot be downgraded")
