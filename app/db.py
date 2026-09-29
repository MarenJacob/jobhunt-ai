import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings

# Vercel's function filesystem is not a persistent writable application directory.
# If PostgreSQL is not configured yet, use /tmp so the function can still boot.
database_url = settings.database_url
if os.getenv("VERCEL") and database_url.startswith("sqlite") and ":memory:" not in database_url:
    database_url = "sqlite:////tmp/job_hunt.db"

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
if database_url.startswith("sqlite") and ":memory:" not in database_url:
    db_path = database_url.replace("sqlite:///", "", 1)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase):
    pass

def init_db():
    from . import models
    Base.metadata.create_all(bind=engine)
    migrate_additive()


def migrate_additive():
    """Small additive migration for existing deployments; never drops data."""
    from sqlalchemy import inspect, text
    inspector=inspect(engine)
    tables=set(inspector.get_table_names())
    if "profile" in tables:
        cols={x["name"] for x in inspector.get_columns("profile")}
        additions={"phone":"VARCHAR(80) NOT NULL DEFAULT ''","address":"VARCHAR(500) NOT NULL DEFAULT ''","linkedin":"VARCHAR(500) NOT NULL DEFAULT ''","github":"VARCHAR(500) NOT NULL DEFAULT ''","website":"VARCHAR(500) NOT NULL DEFAULT ''","work_authorization":"VARCHAR(300) NOT NULL DEFAULT ''","sponsorship":"VARCHAR(300) NOT NULL DEFAULT ''","salary":"VARCHAR(200) NOT NULL DEFAULT ''","resume_filename":"VARCHAR(300) NOT NULL DEFAULT ''","resume_blob":"BYTEA" if database_url.startswith("postgres") else "BLOB"}
        with engine.begin() as conn:
            for name,typ in additions.items():
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE profile ADD COLUMN {name} {typ}"))
    if "jobs" in tables:
        cols={x["name"] for x in inspector.get_columns("jobs")}
        additions={"verified":"BOOLEAN NOT NULL DEFAULT FALSE","posted_at":"TIMESTAMP","last_checked_at":"TIMESTAMP","expired":"BOOLEAN NOT NULL DEFAULT FALSE"}
        with engine.begin() as conn:
            for name,typ in additions.items():
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {typ}"))
