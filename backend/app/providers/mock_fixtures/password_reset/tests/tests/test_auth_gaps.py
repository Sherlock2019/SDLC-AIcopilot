"""Back-fill for gaps the Test Agent found in the existing auth coverage."""
import time

from app import db


def _login(client, user):
    response = client.post("/login", json={"email": user["email"], "password": user["password"]})
    return response.json()["access_token"]


class TestApi:
    def test_profile_returns_authenticated_customer(self, client, user):
        token = _login(client, user)
        response = client.get("/profile", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["email"] == user["email"]


class TestNegative:
    def test_profile_requires_bearer_token(self, client):
        assert client.get("/profile").status_code == 401

    def test_profile_rejects_unknown_token(self, client):
        response = client.get("/profile", headers={"Authorization": "Bearer not-a-real-session"})
        assert response.status_code == 401

    def test_login_unknown_account_matches_wrong_password(self, client, user):
        unknown = client.post("/login", json={"email": "nobody@example.com", "password": "whatever-123"})
        wrong = client.post("/login", json={"email": user["email"], "password": "whatever-123"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()


class TestSecurity:
    def test_expired_session_rejected(self, client, user):
        token = _login(client, user)
        conn = db.connect()
        conn.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
        conn.commit()
        conn.close()
        response = client.get("/profile", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_login_sql_injection_attempt_rejected(self, client):
        response = client.post("/login", json={"email": "' OR '1'='1", "password": "' OR '1'='1"})
        assert response.status_code == 401
