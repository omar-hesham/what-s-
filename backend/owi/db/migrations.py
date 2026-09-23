"""
Database schema migrations and FTS5 table initialization.
"""

from sqlalchemy import text
from owi.db.database import engine, Base
from owi.core.logging import logger

def init_db():
    """Create all relational tables and virtual FTS5 search tables."""
    logger.info("Initializing relational schema...")
    Base.metadata.create_all(bind=engine)

    # Initialize SQLite FTS5 table for full-text search across messages
    with engine.connect() as conn:
        try:
            res = conn.execute(text("PRAGMA table_info(jobs);"))
            existing_cols = {row[1] for row in res.fetchall()}
            if existing_cols:
                if "attempts" not in existing_cols:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN attempts INTEGER DEFAULT 0;"))
                if "lease_expires_at" not in existing_cols:
                    conn.execute(text("ALTER TABLE jobs ADD COLUMN lease_expires_at DATETIME;"))
            conn.commit()
        except Exception as e:
            logger.warning(f"Column migration notice: {e}")

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
            logger.info("FTS5 full-text search index verified.")
        except Exception as e:
            logger.warning(f"FTS5 initialization notice: {e}")

def sync_message_fts(conn, message_id: int, content: str, sender_name: str):
    """Insert or replace record in FTS5 index."""
    try:
        conn.execute(text("""
            DELETE FROM messages_fts WHERE message_id = :mid;
        """), {"mid": message_id})
        conn.execute(text("""
            INSERT INTO messages_fts(message_id, content, sender_name)
            VALUES(:mid, :content, :sender);
        """), {"mid": message_id, "content": content, "sender": sender_name})
    except Exception as e:
        logger.warning(f"Failed to sync message {message_id} to FTS: {e}")
