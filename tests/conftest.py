"""
Pytest configuration and database fixtures for OWI test suite.
Completely isolated in-memory test database with zero side effects on default data/.
"""

import os
import sys
import tempfile
from pathlib import Path

# CRITICAL: Establish a disposable OWI_DATA_DIR and disable .env loading
# BEFORE importing ANY owi modules or creating database engines.
# This guarantees that tests never target or initialize the default project data/ directory,
# even when invoked without environment variables or when caller forgets env flags.
if "PYTHON_DOTENV_DISABLED" not in os.environ:
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"

if "OWI_DATA_DIR" not in os.environ or not os.environ["OWI_DATA_DIR"].strip():
    _session_disposable_dir = tempfile.mkdtemp(prefix="owi_test_iso_")
    os.environ["OWI_DATA_DIR"] = _session_disposable_dir

_backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from owi.config import settings, DEFAULT_DATA_DIR
from owi.db.database import Base, get_db, engine
from owi.db.migrations import init_db
from owi.main import app

@pytest.fixture(scope="session", autouse=True)
def isolate_session_data_dir():
    """
    Guarantees zero side-effects on default project data/ directory.
    Initializes directories in the pre-configured disposable test directory and sets up schema.
    """
    settings.init_directories()
    init_db()

# In-memory SQLite database for test isolation
TEST_DB_URL = "sqlite:///:memory:"

@pytest.fixture(scope="function")
def test_db(monkeypatch, tmp_path):
    # Ensure any file operations use disposable tmp_path and never touch default data/
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    settings.init_directories()

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
            conn.execute(text("""
                CREATE VIRTUAL TABLE IF NOT EXISTS derived_fts USING fts5(
                    media_asset_id UNINDEXED,
                    message_id UNINDEXED,
                    conversation_id UNINDEXED,
                    file_name UNINDEXED,
                    source_type,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                );
            """))
            conn.commit()
        except Exception:
            pass

    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    app.dependency_overrides[get_db] = lambda: session

    yield session

    app.dependency_overrides.pop(get_db, None)
    session.close()
    Base.metadata.drop_all(bind=engine)
