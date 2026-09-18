"""
SSO via OIDC (WBS 9.4) -- enforcement point 1.

When `auth_issuer` is configured, every request must carry a Bearer token the
issuer signed (RS256, keys from the issuer's JWKS; or HS256 with a shared
secret for a dev issuer), with the configured audience. The token proves who
is calling. What they may do comes from the app_user row an admin provisioned
for that subject -- never from a claim, so a user cannot grant themselves a
role by editing their directory profile. MFA is the identity provider's job
(R4 identity), which is why nothing here asks for a second factor.

A service account authenticates with `X-OppTrack-Api-Key` against the hash on
its app_user row; it is scoped to one connector and can never act as a person.

Without `auth_issuer`, the header stand-in in app/security/roles.py applies.
That is development only, and app/security/roles.py says so.
"""

import hashlib
import time
from dataclasses import dataclass

from app.core.config import settings


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Identity:
    subject: str
    email: str | None
    claims: dict


_jwks_client = None
_discovery_cache: dict = {}


def _jwks_url() -> str:
    if settings.auth_jwks_url:
        return settings.auth_jwks_url
    import requests

    if "jwks_uri" not in _discovery_cache or _discovery_cache.get("_at", 0) < time.time() - 3600:
        doc = requests.get(settings.auth_issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=10).json()
        _discovery_cache.update(doc)
        _discovery_cache["_at"] = time.time()
    return _discovery_cache["jwks_uri"]


def _signing_key(token: str):
    global _jwks_client
    import jwt

    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(_jwks_url(), cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_bearer(token: str) -> Identity:
    """Validates signature, issuer, audience and expiry. Raises AuthError."""
    import jwt

    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg", "RS256")
        if algorithm.startswith("HS"):
            if not settings.auth_hs256_secret:
                raise AuthError("HS256 token but no shared secret configured")
            key = settings.auth_hs256_secret
        else:
            key = _signing_key(token)
        claims = jwt.decode(
            token, key, algorithms=[algorithm], issuer=settings.auth_issuer,
            audience=settings.auth_audience, options={"require": ["exp", "iss", "sub"]},
        )
    except AuthError:
        raise
    except Exception as exc:  # noqa: BLE001 -- every PyJWT failure is a 401 with the reason
        raise AuthError(f"invalid token: {type(exc).__name__}: {exc}") from exc
    return Identity(subject=str(claims["sub"]), email=claims.get("email"), claims=claims)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_api_key() -> str:
    import secrets

    return "opk_" + secrets.token_urlsafe(32)
