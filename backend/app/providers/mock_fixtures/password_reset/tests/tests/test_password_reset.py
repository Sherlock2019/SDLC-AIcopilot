"""Tests for the password-reset workflow.

Classes map to the test categories the Test Agent reports:
unit, API, integration, negative and security.
"""
import hashlib
import logging

import pytest

from app import config, db, notifications, password_reset
from app.auth import create_user
from app.security import hash_token

NEW_PASSWORD = "a-much-better-passphrase"


@pytest.fixture(autouse=True)
def _empty_outbox():
    notifications.outbox.clear()
    yield
    notifications.outbox.clear()


def _request(client, email):
    return client.post("/password-reset/request", json={"email": email})


def _confirm(client, token, password=NEW_PASSWORD):
    return client.post("/password-reset/confirm", json={"token": token, "new_password": password})


def _issue_token(client, email):
    _request(client, email)
    return notifications.outbox[-1]["token"]


def _login(client, email, password):
    return client.post("/login", json={"email": email, "password": password})


def _advance_clock(monkeypatch, seconds):
    real = password_reset.time.time
    monkeypatch.setattr(password_reset.time, "time", lambda: real() + seconds)


class TestUnit:
    def test_hash_token_is_sha256_and_deterministic(self):
        assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()
        assert hash_token("abc") == hash_token("abc")

    def test_token_ttl_is_fifteen_minutes(self):
        assert config.RESET_TOKEN_TTL_SECONDS == 15 * 60

    def test_issued_tokens_are_unique_and_long(self, client, user):
        first = _issue_token(client, user["email"])
        second = _issue_token(client, user["email"])
        assert first != second
        assert len(first) >= 32


class TestApi:
    def test_request_returns_202_generic_message(self, client, user):
        response = _request(client, user["email"])
        assert response.status_code == 202
        assert "If the account exists" in response.json()["detail"]

    def test_request_queues_exactly_one_email(self, client, user):
        _request(client, user["email"])
        assert [m["to"] for m in notifications.outbox] == [user["email"]]

    def test_confirm_returns_password_updated(self, client, user):
        response = _confirm(client, _issue_token(client, user["email"]))
        assert response.status_code == 200
        assert response.json() == {"status": "password_updated"}


class TestIntegration:
    def test_full_reset_flow_allows_login_with_new_password(self, client, user):
        _confirm(client, _issue_token(client, user["email"]))
        assert _login(client, user["email"], NEW_PASSWORD).status_code == 200

    def test_old_password_stops_working_after_reset(self, client, user):
        _confirm(client, _issue_token(client, user["email"]))
        assert _login(client, user["email"], user["password"]).status_code == 401

    def test_email_is_normalised_before_lookup(self, client, user):
        response = _request(client, "  " + user["email"].upper() + " ")
        assert response.status_code == 202
        assert len(notifications.outbox) == 1


class TestNegative:
    def test_unknown_token_rejected(self, client):
        assert _confirm(client, "x" * 43).status_code == 400

    def test_weak_password_rejected(self, client, user):
        response = _confirm(client, _issue_token(client, user["email"]), password="short")
        assert response.status_code == 422

    def test_missing_fields_rejected(self, client):
        assert client.post("/password-reset/confirm", json={}).status_code == 422
        assert client.post("/password-reset/request", json={}).status_code == 422

    def test_weak_password_does_not_consume_token(self, client, user):
        token = _issue_token(client, user["email"])
        _confirm(client, token, password="short")
        assert _confirm(client, token).status_code == 200


class TestSecurity:
    def test_expired_token_rejected(self, client, user, monkeypatch):
        token = _issue_token(client, user["email"])
        _advance_clock(monkeypatch, 16 * 60)
        assert _confirm(client, token).status_code == 400

    def test_token_still_valid_just_before_expiry(self, client, user, monkeypatch):
        token = _issue_token(client, user["email"])
        _advance_clock(monkeypatch, 14 * 60)
        assert _confirm(client, token).status_code == 200

    def test_token_reuse_rejected(self, client, user):
        token = _issue_token(client, user["email"])
        assert _confirm(client, token).status_code == 200
        assert _confirm(client, token, password="another-long-passphrase").status_code == 400

    def test_invalid_user_handled_safely(self, client, user):
        known = _request(client, user["email"])
        unknown = _request(client, "nobody@example.com")
        assert unknown.status_code == known.status_code == 202
        assert unknown.json() == known.json()
        assert len(notifications.outbox) == 1

    def test_token_not_logged(self, client, user, caplog):
        caplog.set_level(logging.DEBUG)
        token = _issue_token(client, user["email"])
        _confirm(client, token)
        assert token not in caplog.text

    def test_token_stored_hashed_not_plaintext(self, client, user):
        token = _issue_token(client, user["email"])
        conn = db.connect()
        rows = [tuple(row) for row in conn.execute("SELECT * FROM password_reset_tokens")]
        conn.close()
        assert rows
        assert all(token not in [str(value) for value in row] for row in rows)

    def test_sql_injection_attempt_rejected(self, client, user):
        _issue_token(client, user["email"])
        response = _confirm(client, "' OR '1'='1' --  padding-to-min-length")
        assert response.status_code == 400
        assert _login(client, user["email"], user["password"]).status_code == 200

    def test_unauthorized_reset_blocked(self, client, user):
        conn = db.connect()
        create_user(conn, "bob@example.com", "bobs-original-passphrase", "Bob Example")
        conn.close()
        bob_token = _issue_token(client, "bob@example.com")
        _confirm(client, bob_token)
        assert _login(client, user["email"], user["password"]).status_code == 200
        assert _login(client, user["email"], NEW_PASSWORD).status_code == 401

    def test_sessions_invalidated_after_reset(self, client, user):
        session = _login(client, user["email"], user["password"]).json()["access_token"]
        _confirm(client, _issue_token(client, user["email"]))
        response = client.get("/profile", headers={"Authorization": f"Bearer {session}"})
        assert response.status_code == 401

    def test_rate_limit_caps_tokens_per_hour(self, client, user):
        for _ in range(config.RESET_MAX_REQUESTS_PER_HOUR + 3):
            assert _request(client, user["email"]).status_code == 202
        assert len(notifications.outbox) == config.RESET_MAX_REQUESTS_PER_HOUR
