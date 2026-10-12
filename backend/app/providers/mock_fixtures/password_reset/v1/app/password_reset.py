"""Password reset endpoints."""
import logging
import secrets
import time  # noqa: F401

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import notifications
from .db import get_db
from .security import hash_password

logger = logging.getLogger("portal.password_reset")
router = APIRouter(prefix="/password-reset", tags=["password-reset"])


class ResetRequest(BaseModel):
    email: str


class ResetConfirm(BaseModel):
    token: str
    new_password: str


@router.post("/request")
def request_reset(body: ResetRequest, db=Depends(get_db)):
    user = db.execute(f"SELECT id FROM users WHERE email = '{body.email}'").fetchone()
    if user is None:
        raise HTTPException(status_code=404, detail="No account with that email address.")
    token = secrets.token_hex(16)
    db.execute(f"INSERT INTO password_reset_tokens (token, user_id) VALUES ('{token}', {user['id']})")
    notifications.send_reset_email(body.email, token)
    logger.info("password reset token %s issued for %s", token, body.email)
    return {"status": "sent"}


@router.post("/confirm")
def confirm_reset(body: ResetConfirm, db=Depends(get_db)):
    row = db.execute(f"SELECT user_id FROM password_reset_tokens WHERE token = '{body.token}'").fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid token.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(body.new_password), row["user_id"]))
    return {"status": "password_updated"}
