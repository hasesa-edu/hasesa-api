"""Access rules: who can see what. Ported from hasesa-lab-web lib/access-rules.ts."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from hasesa_api.config import get_settings

AccessLevel = Literal["public", "signed-in", "enrolled", "guide"]

# Pilot: every account is enrolled at the Academy until the end of 2027
# (Addis Ababa time). New sign-ups get this as their paid_until.
PILOT_ENROLLED_UNTIL = datetime(2028, 1, 1, tzinfo=timezone(timedelta(hours=3)))


def access_level(role: str | None, paid_until: datetime | None, now: datetime | None = None) -> AccessLevel:
    """The access level of a signed-in user (never "public")."""
    now = now or datetime.now(UTC)
    if role == "guide":
        return "guide"
    if paid_until is not None and paid_until > now:
        return "enrolled"
    return "signed-in"


def is_admin(email: str) -> bool:
    """Admins are listed by email in ADMIN_EMAILS (no database role)."""
    return email.strip().lower() in get_settings().admin_emails


def has_full_access(level: AccessLevel) -> bool:
    """Enrolled students and the guide get every step, unit and the assistant."""
    return level in ("enrolled", "guide")
