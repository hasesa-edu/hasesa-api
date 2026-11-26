"""Payments and enrolment days. Ported from hasesa-lab-web lib/billing/payments.ts.

Phase 4 needs only admin grants; Chapa checkout and its webhook arrive in phase 5.
"""

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.models import Payment

# Marks a pending payment paid and adds its days to the student's enrolment in
# one statement. The status = 'pending' guard makes it idempotent, so the
# return page, the callback and the webhook can all call it safely.
_CLAIM_AND_EXTEND = text(
    """
    WITH claimed AS (
      UPDATE payments
      SET status = 'success', verified_at = now(), chapa_ref = :chapa_ref
      WHERE tx_ref = :tx_ref AND status = 'pending'
      RETURNING user_id, days
    )
    UPDATE users u
    SET paid_until = GREATEST(COALESCE(u.paid_until, now()), now()) + make_interval(days => c.days)
    FROM claimed c
    WHERE u.id = c.user_id
    RETURNING u.paid_until
    """
)


async def claim_and_extend(db: AsyncSession, tx_ref: str, chapa_ref: str | None) -> datetime | None:
    """Returns the new paid-until date, or None if nothing was applied (already claimed)."""
    return await db.scalar(_CLAIM_AND_EXTEND, {"tx_ref": tx_ref, "chapa_ref": chapa_ref})


async def grant_days(db: AsyncSession, user_id: str, days: int, note: str) -> datetime | None:
    """Admin comp or fix: adds days to a student's enrolment without a Chapa payment."""
    tx_ref = f"admin-{uuid.uuid4()}"
    db.add(
        Payment(
            tx_ref=tx_ref,
            user_id=user_id,
            amount_etb=0,
            currency="ETB",
            days=days,
            status="pending",
            source="admin",
            note=note[:200] or None,
        )
    )
    await db.flush()
    until = await claim_and_extend(db, tx_ref, None)
    await db.commit()
    return until
