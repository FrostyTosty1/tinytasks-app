from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.config import get_database_url


class Base(DeclarativeBase):
    pass


_engine = None
_session_local = None


def _build_connect_args(database_url: str) -> dict:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def build_engine(database_url: str | None = None):
    url = database_url or get_database_url()

    # Create SQLAlchemy engine
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args=_build_connect_args(url),
    )


def get_engine():
    global _engine

    if _engine is None:
        _engine = build_engine()

    return _engine


def get_session_local():
    global _session_local

    if _session_local is None:
        # Session factory; request handlers manage commit/rollback explicitly.
        _session_local = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            future=True,
        )

    return _session_local


# FastAPI dependency that provides one DB session per request.
def get_db() -> Session:
    db: Session = get_session_local()()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Minimal connectivity check used by /db/healthz.
def check_db() -> bool:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return True


# Create tables directly from ORM metadata for local SQLite runs only.
def init_db_schema() -> None:
    # Postgres environments should use Alembic migrations instead.
    Base.metadata.create_all(bind=get_engine())
