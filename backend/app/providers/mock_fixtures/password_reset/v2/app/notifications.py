"""Outbound notifications.

The portal has no mail provider in this environment, so messages go to an in-memory
outbox that tests can inspect. The reset token is only ever handed to this module;
it must never be written to logs (SEC-9).
"""
import logging

logger = logging.getLogger("portal.notifications")

outbox: list[dict] = []


def send_reset_email(email: str, token: str) -> None:
    outbox.append({"to": email, "template": "password-reset", "token": token})
    logger.info("password reset email queued")
