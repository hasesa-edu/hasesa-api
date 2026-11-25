"""Hasesa Accounts: clients, sessions, sign-in requests and one-time codes.

Purely additive: new tables only; the web app's tables are untouched.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The website. Previews of the web project ("ai-edu" on Vercel) get URLs like
# ai-edu-git-<branch>-w-yidnes-projects.vercel.app. The web client is
# confidential, so a code sent to a look-alike preview domain is useless
# without the web server's client secret.
WEB_REDIRECT_URIS = [
    "https://www.hasesa.com/api/auth/callback",
    "https://hasesa.com/api/auth/callback",
    "https://ai-edu-*-w-yidnes-projects.vercel.app/api/auth/callback",
    "http://localhost:3000/api/auth/callback",
]


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    clients = op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("confidential", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("session_days", sa.Integer(), nullable=False),
        _now("created_at"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.id"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        _now("created_at"),
        _now("last_used_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent", sa.Text()),
    )
    op.create_index("auth_sessions_user_idx", "auth_sessions", ["user_id"])

    op.create_table(
        "auth_requests",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.id"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("client_state", sa.Text()),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("google_verifier", sa.Text(), nullable=False),
        _now("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "auth_codes",
        sa.Column("code_hash", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Text(), sa.ForeignKey("oauth_clients.id"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("is_new_user", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _now("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )

    op.bulk_insert(
        clients,
        [
            {
                "id": "hasesa-web",
                "name": "Hasesa website",
                "kind": "web",
                "confidential": True,
                "redirect_uris": WEB_REDIRECT_URIS,
                "session_days": 30,
            },
            {
                "id": "hasesa-mobile",
                "name": "Hasesa mobile app",
                "kind": "native",
                "confidential": False,
                "redirect_uris": [],
                "session_days": 90,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("auth_codes")
    op.drop_table("auth_requests")
    op.drop_table("auth_sessions")
    op.drop_table("oauth_clients")
