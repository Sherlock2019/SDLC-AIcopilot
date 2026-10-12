"""Login and profile endpoints."""
import logging
import secrets
import sqlite3
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from . import config
from .db import get_db
from .security import hash_password, hash_token, verify_password

logger = logging.getLogger("portal.auth")
router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def create_user(db: sqlite3.Connection, email: str, password: str, full_name: str) -> int:
    cur = db.execute(
        "INSERT INTO users (email, full_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (email.strip().lower(), full_name, hash_password(password), time.time()),
    )
    db.commit()
    return cur.lastrowid


def get_current_user(authorization: str | None = Header(default=None), db=Depends(get_db)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    row = db.execute(
        "SELECT u.id, u.email, u.full_name, s.expires_at FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None or row["expires_at"] < time.time():
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return row


@router.post("/login")
def login(body: LoginRequest, db=Depends(get_db)):
    email = body.email.strip().lower()
    user = db.execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not verify_password(body.password, user["password_hash"]):
        logger.info("login failed")
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (hash_token(token), user["id"], time.time() + config.SESSION_TTL_SECONDS),
    )
    logger.info("login succeeded user_id=%s", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": config.SESSION_TTL_SECONDS}


@router.get("/profile")
def profile(user=Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"], "full_name": user["full_name"]}
