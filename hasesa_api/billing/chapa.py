"""Chapa, the payment provider. Ported from hasesa-lab-web lib/billing/chapa.ts."""

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

from hasesa_api.config import get_settings

log = logging.getLogger(__name__)

CHAPA_API = "https://api.chapa.co/v1"
BRAND = "Hasesa"


class ChapaError(Exception):
    """A message that is safe to show to the student."""


def _secret_key() -> str:
    key = get_settings().chapa_secret_key
    if not key:
        raise ChapaError("Payments aren't set up yet.")
    return key


async def initialize_checkout(
    *,
    tx_ref: str,
    amount_etb: int,
    email: str,
    first_name: str | None,
    last_name: str | None,
    return_url: str,
    callback_url: str,
) -> str:
    """Start a hosted checkout. Returns its URL."""
    body = {
        "amount": str(amount_etb),
        "currency": "ETB",
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "tx_ref": tx_ref,
        "return_url": return_url,
        "callback_url": callback_url,
        # Chapa only allows letters, numbers, spaces, dots, hyphens and underscores here.
        "customization": {"title": BRAND, "description": "30 day pass"},
        "meta": {"payment_reason": f"{BRAND} 30 day pass"},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{CHAPA_API}/transaction/initialize",
                json={k: v for k, v in body.items() if v is not None},
                headers={"Authorization": f"Bearer {_secret_key()}"},
            )
    except httpx.HTTPError as e:
        log.error("chapa initialize unreachable: %s", e)
        raise ChapaError("Couldn't reach the payment provider. Please try again.") from e
    try:
        data = res.json()
    except ValueError:
        data = None
    url = ((data or {}).get("data") or {}).get("checkout_url") if isinstance(data, dict) else None
    if res.is_error or not isinstance(data, dict) or data.get("status") != "success" or not isinstance(url, str):
        log.error("chapa initialize failed: %s %s", res.status_code, str((data or {}).get("message", data))[:300])
        raise ChapaError("Couldn't start the payment. Please try again.")
    return url


@dataclass
class VerifiedTx:
    status: Literal["success", "failed", "pending"]
    amount: float
    currency: str
    reference: str | None


async def verify_transaction(tx_ref: str) -> VerifiedTx | None:
    """Ask Chapa for the real status of a transaction: the only thing trusted to mark a payment paid.
    None means "not confirmed yet" (unreachable, or Chapa hasn't seen it paid)."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{CHAPA_API}/transaction/verify/{quote(tx_ref, safe='')}",
                headers={"Authorization": f"Bearer {_secret_key()}"},
            )
    except httpx.HTTPError as e:
        log.error("chapa verify unreachable: %s", e)
        return None
    try:
        data = res.json()
    except ValueError:
        data = None
    tx = data.get("data") if isinstance(data, dict) else None
    if res.is_error or not isinstance(tx, dict):
        # Chapa answers 4xx for references it hasn't seen paid yet.
        log.warning("chapa verify: %s %s", res.status_code, str((data or {}).get("message", data))[:200])
        return None
    raw = tx.get("status")
    status: Literal["success", "failed", "pending"] = (
        "success" if raw == "success" else "failed" if raw == "failed" else "pending"
    )
    try:
        amount = float(tx.get("amount"))
    except (TypeError, ValueError):
        amount = float("nan")
    reference = tx.get("reference")
    return VerifiedTx(
        status=status,
        amount=amount,
        currency=str(tx.get("currency") or ""),
        reference=reference if isinstance(reference, str) else None,
    )


def _hmac_hex(key: str, data: bytes) -> bytes:
    return hmac.new(key.encode(), data, hashlib.sha256).hexdigest().encode()


def _same(sig: str | None, expected: bytes) -> bool:
    return sig is not None and hmac.compare_digest(sig.encode(), expected)


def is_valid_webhook_signature(raw_body: bytes, payload_sig: str | None, secret_sig: str | None) -> bool:
    """Chapa sends x-chapa-signature (HMAC-SHA256 of the payload) and chapa-signature
    (HMAC-SHA256 of the secret itself); one valid header is enough. The dashboard's
    webhook secret is used when set, otherwise the API secret key."""
    s = get_settings()
    keys = [k for k in (s.chapa_webhook_secret, s.chapa_secret_key) if k]
    return any(_same(payload_sig, _hmac_hex(k, raw_body)) or _same(secret_sig, _hmac_hex(k, k.encode())) for k in keys)
