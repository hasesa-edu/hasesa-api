"""Access tokens (RS256 JWTs) and refresh tokens (HMAC-signed session references)."""

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from hasesa_api.config import get_settings

log = logging.getLogger(__name__)

ACCESS_TOKEN_SECONDS = 15 * 60
_DEV_REFRESH_SECRET = "dev-only-refresh-secret-not-for-production-use"


class TokenError(Exception):
    """A token is malformed, expired, forged or meant for someone else."""


# ---------- signing key ----------


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: rsa.RSAPrivateKey

    @property
    def public_jwk(self) -> dict[str, Any]:
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {**jwk, "kid": self.kid, "use": "sig", "alg": "RS256"}


@lru_cache
def signing_key() -> SigningKey:
    settings = get_settings()
    pem = settings.jwt_private_key.replace("\\n", "\n").strip()
    if pem:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise RuntimeError("JWT_PRIVATE_KEY must be an RSA private key")
        return SigningKey(settings.jwt_key_id, key)
    if settings.is_production:
        # Fail closed: never sign production tokens with a throwaway key.
        raise RuntimeError("JWT_PRIVATE_KEY must be set in production")
    log.warning("JWT_PRIVATE_KEY not set: using a temporary development key")
    return SigningKey("dev", rsa.generate_private_key(public_exponent=65537, key_size=2048))


def jwks() -> dict[str, Any]:
    return {"keys": [signing_key().public_jwk]}


def issue_access_token(*, user_id: str, session_id: str, client_id: str, now: int | None = None) -> str:
    now = int(now if now is not None else time.time())
    key = signing_key()
    claims = {
        "iss": get_settings().api_base_url,
        "sub": user_id,
        "aud": client_id,
        "sid": session_id,
        "iat": now,
        "exp": now + ACCESS_TOKEN_SECONDS,
    }
    return jwt.encode(claims, key.private_key, algorithm="RS256", headers={"kid": key.kid})


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    client_id: str


def verify_access_token(token: str) -> AccessClaims:
    key = signing_key()
    try:
        claims = jwt.decode(
            token,
            key.private_key.public_key(),
            algorithms=["RS256"],
            issuer=get_settings().api_base_url,
            options={"require": ["exp", "iat", "sub", "aud", "sid"], "verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise TokenError(str(e)) from e
    if jwt.get_unverified_header(token).get("kid") != key.kid:
        raise TokenError("unknown key")
    return AccessClaims(user_id=claims["sub"], session_id=claims["sid"], client_id=claims["aud"])


# ---------- refresh tokens ----------
#
# Format: "<session_id>.<generation>.<mac>". The MAC is an HMAC of the session ID
# and generation, so tokens can't be forged, and the token for any generation
# can be recomputed. That lets a refresh that repeats the previous generation
# (two requests refreshing at the same moment) get the same answer again
# instead of signing the user out.


def _refresh_secret() -> bytes:
    settings = get_settings()
    secret = settings.refresh_token_secret
    if len(secret) >= 32:
        return secret.encode()
    if settings.is_production:
        raise RuntimeError("REFRESH_TOKEN_SECRET must be set (32+ characters) in production")
    return _DEV_REFRESH_SECRET.encode()


def _mac(session_id: str, generation: int) -> str:
    digest = hmac.new(_refresh_secret(), f"{session_id}.{generation}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def make_refresh_token(session_id: str, generation: int) -> str:
    return f"{session_id}.{generation}.{_mac(session_id, generation)}"


def parse_refresh_token(token: str) -> tuple[str, int]:
    """Return (session_id, generation) of a genuine refresh token."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[1].isdigit() or len(parts[1]) > 9:
        raise TokenError("malformed refresh token")
    session_id, generation = parts[0], int(parts[1])
    if not hmac.compare_digest(parts[2], _mac(session_id, generation)):
        raise TokenError("bad refresh token")
    return session_id, generation


# ---------- small helpers ----------


def random_id(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_b64(value: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).rstrip(b"=").decode()


def pkce_matches(verifier: str, challenge: str) -> bool:
    """PKCE S256: challenge == BASE64URL(SHA256(verifier))."""
    if not 43 <= len(verifier) <= 128:
        return False
    return hmac.compare_digest(sha256_b64(verifier), challenge)
