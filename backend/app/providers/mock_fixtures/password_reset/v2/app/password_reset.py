"""Password-reset workflow: request a token, then confirm with a new password.

Implements security-policy.md SEC-7 .. SEC-12:
  SEC-7  tokens expire after 15 minutes
  SEC-8  tokens are stored hashed, never in plaintext
  SEC-9  tokens never appear in logs
  SEC-10 tokens are single-use
  SEC-11 responses do not reveal whether an account exists
  SEC-12 existing sessions are invalidated after a reset
"""
import logging
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import config, notifications
from .db import get_db
from .security import hash_password, hash_token

logger = logging.getLogger("portal.password_reset")
router = APIRouter(prefix="/password-reset", tags=["password-reset"])

GENERIC_RESPONSE = {
    "status": "accepted",
    "detail": "If the account exists, a reset link has been sent.",
}


class ResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetConfirm(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/request", status_code=202)
def request_reset(body: ResetRequest, db=Depends(get_db)):
    email = body.email.strip().lower()
    now = time.time()
    user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        logger.info("password reset requested for unknown account")
        return GENERIC_RESPONSE

    recent = db.execute(
        "SELECT COUNT(*) FROM password_reset_tokens WHERE user_id = ? AND created_at > ?",
        (user["id"], now - 3600),
    ).fetchone()[0]
    if recent >= config.RESET_MAX_REQUESTS_PER_HOUR:
        logger.warning("password reset rate limit reached user_id=%s", user["id"])
        return GENERIC_RESPONSE

    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO password_reset_tokens (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (hash_token(token), user["id"], now, now + config.RESET_TOKEN_TTL_SECONDS),
    )
    notifications.send_reset_email(email, token)
    logger.info("password reset issued user_id=%s", user["id"])
    return GENERIC_RESPONSE


@router.post("/confirm")
def confirm_reset(body: ResetConfirm, db=Depends(get_db)):
    if len(body.new_password) < config.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {config.MIN_PASSWORD_LENGTH} characters.",
        )
    now = time.time()
    row = db.execute(
        "SELECT token_hash, user_id, expires_at, used_at FROM password_reset_tokens WHERE token_hash = ?",
        (hash_token(body.token),),
    ).fetchone()
    if row is None or row["used_at"] is not None or row["expires_at"] < now:
        logger.warning("password reset rejected: invalid, expired or already used")
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")

    db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ?", (now, row["token_hash"]))
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), row["user_id"]))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    logger.info("password reset completed user_id=%s", row["user_id"])
    return {"status": "password_updated"}
