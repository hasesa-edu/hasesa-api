import base64
import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from hasesa_api.access import is_admin
from hasesa_api.config import get_settings
from hasesa_api.db import DbDep, get_sessionmaker
from hasesa_api.identity import sessions, tokens
from hasesa_api.models import User

_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def bearer_claims(authorization: Annotated[str | None, Header()] = None) -> tokens.AccessClaims:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Please sign in.", headers=_UNAUTHORIZED)
    try:
        return tokens.verify_access_token(token)
    except tokens.TokenError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token.", headers=_UNAUTHORIZED) from e


ClaimsDep = Annotated[tokens.AccessClaims, Depends(bearer_claims)]


async def current_user(claims: ClaimsDep, db: DbDep) -> User:
    """The signed-in user. Also checks the session is still active, so signing out takes effect at once."""
    if not await sessions.session_active(db, claims.session_id):
        raise HTTPException(status_code=401, detail="Session ended. Please sign in again.", headers=_UNAUTHORIZED)
    user = await db.get(User, claims.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found.", headers=_UNAUTHORIZED)
    return user


CurrentUserDep = Annotated[User, Depends(current_user)]


def optional_bearer_claims(authorization: Annotated[str | None, Header()] = None) -> tokens.AccessClaims | None:
    """Like bearer_claims, but signed-out callers get None instead of a 401."""
    if not authorization:
        return None
    return bearer_claims(authorization)


async def optional_user(
    claims: Annotated[tokens.AccessClaims | None, Depends(optional_bearer_claims)],
) -> User | None:
    """Opens a database session only when a token was sent, so public requests never touch the database."""
    if claims is None:
        return None
    async with get_sessionmaker()() as db:
        user = await current_user(claims, db)
        db.expunge(user)
        return user


OptionalUserDep = Annotated[User | None, Depends(optional_user)]


async def guide_user(user: CurrentUserDep) -> User:
    """The signed-in guide. Everyone else gets a 403."""
    if user.role != "guide":
        raise HTTPException(status_code=403, detail="Only the guide can do this.")
    return user


GuideDep = Annotated[User, Depends(guide_user)]


async def admin_user(user: CurrentUserDep) -> User:
    """Someone who runs Hasesa (their email is in ADMIN_EMAILS)."""
    if not is_admin(user.email):
        raise HTTPException(status_code=403, detail="Not authorized.")
    return user


AdminDep = Annotated[User, Depends(admin_user)]


def confidential_client(authorization: Annotated[str | None, Header()] = None) -> str:
    """HTTP Basic auth with a confidential client's ID and secret (the website's server).

    Checked against CLIENT_SECRETS only, so the content endpoints never need the database.
    """
    scheme, _, encoded = (authorization or "").partition(" ")
    try:
        client_id, sep, secret = base64.b64decode(encoded, validate=True).decode().partition(":")
    except ValueError:
        client_id, sep, secret = "", "", ""
    if scheme.lower() != "basic" or not sep:
        raise HTTPException(status_code=401, detail="Client authentication required.")
    expected = get_settings().client_secrets.get(client_id)
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Client authentication failed.")
    return client_id


ClientDep = Annotated[str, Depends(confidential_client)]
