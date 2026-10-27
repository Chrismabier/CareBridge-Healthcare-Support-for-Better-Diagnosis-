"""Authentication: PBKDF2 password hashing + HMAC-signed bearer tokens.

Implemented with the standard library only (no PyJWT / passlib dependency).
Tokens use the familiar three-part JWT shape
``base64url(header).base64url(payload).base64url(HMAC-SHA256)`` so they are
easy to inspect with any JWT debugger, and the signature is verified with
``hmac.compare_digest`` (constant time).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, db

PBKDF2_ITERATIONS = 240_000
_bearer = HTTPBearer(auto_error=False)

# The token is accepted from three places (first match wins):
#   1. ``Authorization: Bearer <token>``   - standard API usage
#   2. ``X-Bridge-Token: <token>``         - some reverse proxies / preview
#      gateways strip or reserve the Authorization header, which made the
#      web UI log in and immediately get 401s ("doesn't stay logged in")
#   3. ``bridge_token`` cookie             - set at login as a fallback
TOKEN_COOKIE = "bridge_token"
TOKEN_HEADER = "x-bridge-token"


# --------------------------------------------------------------- passwords

def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, pw_hash: str, pw_salt: str) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(pw_salt), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), pw_hash)


# ------------------------------------------------------------------ tokens

def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user_id: int) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": str(user_id), "iat": now, "exp": now + config.TOKEN_TTL_SECONDS}
    signing_input = f"{_b64encode(json.dumps(header).encode())}.{_b64encode(json.dumps(payload).encode())}"
    signature = hmac.new(config.SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_token(token: str) -> int:
    """Return the user id or raise HTTPException(401)."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(config.SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(sig_b64), expected):
            raise unauthorized
        payload = json.loads(_b64decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise unauthorized
        return int(payload["sub"])
    except HTTPException:
        raise
    except Exception:
        raise unauthorized


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    # Try each credential transport in turn: a proxy that overwrites the
    # Authorization header with its own value must not shadow a valid
    # X-Bridge-Token header / cookie.
    candidates: list[str] = []
    if credentials is not None:
        candidates.append(credentials.credentials)
    if header_token := request.headers.get(TOKEN_HEADER):
        candidates.append(header_token)
    if cookie_token := request.cookies.get(TOKEN_COOKIE):
        candidates.append(cookie_token)

    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="You need to log in first.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    for token in candidates:
        try:
            user_id = decode_token(token)
        except HTTPException:
            continue  # try the next transport
        user = db.get_user_by_id(user_id)
        if user is not None:
            return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired session. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
