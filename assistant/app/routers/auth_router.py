"""Auth endpoints: register, login, demo account, current user."""
from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from .. import auth, config, db

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEMO_EMAIL = "demo@carebridge.local"
DEMO_PASSWORD = "demo1234"


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=8, max_length=200)


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


def _token_response(user: dict, response: Response | None = None) -> dict:
    token = auth.create_token(user["id"])
    if response is not None:
        # Fallback transport for the token (see auth.py): survives proxies
        # that strip Authorization. HttpOnly so JS never needs to read it -
        # the SPA keeps its own copy from the JSON body.
        response.set_cookie(
            auth.TOKEN_COOKIE, token, max_age=config.TOKEN_TTL_SECONDS,
            path="/", samesite="lax", httponly=True,
        )
    return {"token": token, "token_type": "bearer", "user": db.public_user(user)}


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterBody, response: Response):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Please enter a valid email address.")
    pw_hash, pw_salt = auth.hash_password(body.password)
    try:
        user = db.create_user(email, body.name.strip(), pw_hash, pw_salt)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with that email already exists. Try logging in.")
    return _token_response(user, response)


@router.post("/login")
def login(body: LoginBody, response: Response):
    user = db.get_user_by_email(body.email.strip().lower())
    # Same message either way - don't reveal whether the email exists.
    if user is None or not auth.verify_password(body.password, user["pw_hash"], user["pw_salt"]):
        raise HTTPException(401, "Incorrect email or password.")
    return _token_response(user, response)


@router.post("/demo")
def demo_login(response: Response):
    """One-click demo account so reviewers can try everything instantly."""
    user = db.get_user_by_email(DEMO_EMAIL)
    if user is None:
        pw_hash, pw_salt = auth.hash_password(DEMO_PASSWORD)
        user = db.create_user(DEMO_EMAIL, "Demo User", pw_hash, pw_salt)
    return _token_response(user, response)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.TOKEN_COOKIE, path="/")
    return {"logged_out": True}


@router.get("/me")
def me(user: dict = Depends(auth.get_current_user)):
    return {"user": db.public_user(user), "stats": db.stats(user["id"])}
