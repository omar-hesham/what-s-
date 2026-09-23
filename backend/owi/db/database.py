"""
Database connection and session factory.
Configures SQLite in Write-Ahead-Logging (WAL) mode with foreign keys enabled.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from owi.config import settings

# Engine configuration for SQLite
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,
)

# Apply SQLite performance and integrity pragmas
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    # Enable Write-Ahead Logging for high concurrency
    cursor.execute("PRAGMA journal_mode=WAL;")
    # Normal synchronous mode offers great performance and safe durability
    cursor.execute("PRAGMA synchronous=NORMAL;")
    # Enforce foreign key constraints
    cursor.execute("PRAGMA foreign_keys=ON;")
    # Increase cache size (64MB)
    cursor.execute("PRAGMA cache_size=-64000;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
