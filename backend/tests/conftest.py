"""Test configuration. The lab is pointed at a throw-away data directory before `app` is imported."""
import os
import shutil
import tempfile

_DATA_DIR = tempfile.mkdtemp(prefix="lab-tests-")
os.environ["LAB_DATA_DIR"] = _DATA_DIR
os.environ["MOCK_AI"] = "true"
os.environ["GITHUB_ENABLED"] = "false"
os.environ.pop("DATABASE_URL", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main, services  # noqa: E402
from app.core.gateway import Actor  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.tools import impl  # noqa: E402


def _fresh_state() -> None:
    Base.metadata.drop_all(engine)
    shutil.rmtree(os.path.join(_DATA_DIR, "workspaces"), ignore_errors=True)
    impl.MOCK_EFFECTS.clear()
    services.reset()


@pytest.fixture()
def client():
    _fresh_state()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def module_client():
    _fresh_state()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def db(client):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def gateway(client):
    return services.get_gateway()


@pytest.fixture()
def store(client):
    return services.get_store()


def agent(name: str) -> Actor:
    return Actor(name, "agent")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DATA_DIR, ignore_errors=True)
