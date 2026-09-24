"""
Pytest configuration and database fixtures for OWI test suite.
"""

import pytest
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from owi.db.database import Base
from owi.db.migrations import init_db

# Use an in-memory SQLite database or temp file for testing
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    message_id UNINDEXED,
                    content,
                    sender_name,
                    tokenize='unicode61 remove_diacritics 2'
                );
            """))
            conn.commit()
        except Exception:
            pass
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(bind=engine)
