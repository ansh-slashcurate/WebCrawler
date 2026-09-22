"""Postgres (Neon) connection - engine/session setup for the control panel's
relational config data (Tenders page: bank sites + tags, plus a users/roles
table laid down for future role-based access - see crawler.models).

Read from DATABASE_URL in crawler/.env, loaded the same way webapi.py/
settings.py already load that file (webapi.py's load_dotenv() call runs
before this module is imported, at process startup). The crawl/pipeline side
of the app (scrapy crawl subprocesses) never imports this module - only
webapi.py does, so a `scrapy crawl` run has no Postgres dependency.

Schema changes go through Alembic migrations under crawler/alembic/ (run
`alembic upgrade head` from the crawler/ directory) rather than
Base.metadata.create_all() - see crawler/alembic/README for the one-time
setup this project used to generate the initial schema.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set - add your Postgres connection string to crawler/.env"
        )
    return url


# pool_pre_ping: Neon (serverless Postgres) closes idle connections on its
# own schedule: without this, a connection that's been sitting in the pool
# gets a "connection already closed"/"SSL SYSCALL error" the first time a
# request reuses it after a quiet period, instead of a fresh reconnect.
engine = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    """FastAPI dependency - one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
