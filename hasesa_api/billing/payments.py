"""Payments and enrolment days. Ported from hasesa-lab-web lib/billing/payments.ts."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hasesa_api.billing import chapa
from hasesa_api.models import Payment

log = logging.getLogger(__name__)

# The single paid plan: every successful payment adds DAYS of access, stacked
# on top of any days the student still has left.
PRICE_ETB = 300
DAYS = 30
# Chapa checkouts use this prefix; webhooks for anything else are ignored.
TX_PREFIX = "hl-"

# Marks a payment paid and adds its days to the student's enrolment in one
# statement. The status guard makes it idempotent, so the return page, the
# callback and the webhook can all call it safely. A payment Chapa once
# reported as failed can still be claimed: if the student retried on the same
# checkout and Chapa's verify call now says success, they paid.
_CLAIM_AND_EXTEND = text(
    """
    WITH claimed AS (
      UPDATE payments
      SET status = 'success', verified_at = now(), chapa_ref = :chapa_ref
      WHERE tx_ref = :tx_ref AND status IN ('pending', 'failed')
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


def new_tx_ref() -> str:
    return f"{TX_PREFIX}{uuid.uuid4()}"


async def create_pending_payment(db: AsyncSession, user_id: str) -> str:
    tx_ref = new_tx_ref()
    db.add(
        Payment(
            tx_ref=tx_ref,
            user_id=user_id,
            amount_etb=PRICE_ETB,
            currency="ETB",
            days=DAYS,
            status="pending",
            source="chapa",
        )
    )
    await db.commit()
    return tx_ref


State = Literal["paid", "pending", "failed", "review", "unknown"]


@dataclass
class ApplyResult:
    state: State
    # The new paid-until date when this call applied the payment; None if it
    # was applied earlier (or wasn't applied).
    paid_until: datetime | None = None


async def verify_and_apply(db: AsyncSession, tx_ref: str) -> ApplyResult:
    """Verify a Chapa transaction and, if it's a successful payment of the right
    amount, extend the student's enrolment. Safe to call any number of times."""
    payment = await db.get(Payment, tx_ref)
    if payment is None or payment.source != "chapa":
        return ApplyResult("unknown")
    if payment.status == "success":
        return ApplyResult("paid")
    if payment.status == "review":
        return ApplyResult("review")
    currency, amount_etb = payment.currency, payment.amount_etb

    tx = await chapa.verify_transaction(tx_ref)
    if tx is None or tx.status == "pending":
        return ApplyResult("pending")
    pending = (Payment.tx_ref == tx_ref, Payment.status == "pending")
    unclaimed = (Payment.tx_ref == tx_ref, Payment.status.in_(("pending", "failed")))
    if tx.status == "failed":
        await db.execute(update(Payment).where(*pending).values(status="failed", verified_at=datetime.now(UTC)))
        await db.commit()
        return ApplyResult("failed")
    if tx.currency != currency or not (tx.amount >= amount_etb):
        log.error("chapa amount mismatch for %s: got %s %s", tx_ref, tx.amount, tx.currency)
        await db.execute(
            update(Payment)
            .where(*unclaimed)
            .values(
                status="review",
                verified_at=datetime.now(UTC),
                chapa_ref=tx.reference,
                note=f"Chapa reported {tx.amount:g} {tx.currency}",
            )
        )
        await db.commit()
        return ApplyResult("review")
    until = await claim_and_extend(db, tx_ref, tx.reference)
    await db.commit()
    return ApplyResult("paid", until)


async def payment_owner(db: AsyncSession, tx_ref: str) -> str | None:
    return await db.scalar(select(Payment.user_id).where(Payment.tx_ref == tx_ref))
