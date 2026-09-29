"""
SQLite database setup.

A file-based SQLite DB is deliberate here, not a corner cut: this project is
meant to be cloned and run by a single on-call engineer or a small team in
minutes, with zero external services to provision. Swapping in Postgres later
is a one-line change to SQLALCHEMY_DATABASE_URL because everything above this
file talks to SQLAlchemy's ORM, never to SQLite directly.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Overridable so tests (and anyone deploying elsewhere) can point at a
# different file without touching code - see tests/conftest.py.
DB_PATH = os.environ.get("INCIDENT_AGENT_DB_PATH", os.path.join(DATA_DIR, "incidents.db"))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
