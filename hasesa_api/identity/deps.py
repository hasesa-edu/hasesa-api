from typing import Annotated

from fastapi import Depends, Header, HTTPException

from hasesa_api.db import DbDep
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
