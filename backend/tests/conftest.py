import os

# Must run before app modules import settings / create the engine.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://trade:trade@localhost:5433/trade_intel_test"
)
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["COMTRADE_MIN_INTERVAL_S"] = "0"
os.environ["HOME_COUNTRY_ISO3"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import HSCode, Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "test-password-123"


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([HSCode(code="190531", description="Sweet biscuits"), HSCode(code="090111", description="Coffee")])
        for role in Role:
            db.add(User(email=f"{role.value}@example.com", password_hash=hash_password(PASSWORD), role=role))
        db.commit()
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


def _client(role: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", data={"username": f"{role}@example.com", "password": PASSWORD})
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture
def admin():
    return _client("admin")


@pytest.fixture
def analyst():
    return _client("analyst")


@pytest.fixture
def viewer():
    return _client("viewer")


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "test-key")
