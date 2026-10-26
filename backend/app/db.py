from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_url = get_settings().database_url
# Neon's pooled endpoint (PgBouncer, transaction mode) cannot keep server-side prepared statements.
_connect_args = {"prepare_threshold": None} if "-pooler." in _url else {}
engine = create_engine(
    _url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300, connect_args=_connect_args
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
