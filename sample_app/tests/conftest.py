import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.auth import create_user
from app.main import app

USER = {"email": "alice@example.com", "password": "correct-horse-battery", "full_name": "Alice Example"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "portal.db"))
    db.init_db()
    conn = db.connect()
    create_user(conn, USER["email"], USER["password"], USER["full_name"])
    conn.close()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def user():
    return dict(USER)
