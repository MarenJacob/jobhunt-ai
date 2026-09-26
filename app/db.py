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
