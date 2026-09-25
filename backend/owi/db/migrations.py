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

            res_msg = conn.execute(text("PRAGMA table_info(messages);"))
            existing_msg_cols = {row[1] for row in res_msg.fetchall()}
            if existing_msg_cols and "timestamp_provenance" not in existing_msg_cols:
                conn.execute(text("ALTER TABLE messages ADD COLUMN timestamp_provenance VARCHAR(50) DEFAULT 'verified';"))
            if existing_msg_cols and "attachment_status" not in existing_msg_cols:
                conn.execute(text("ALTER TABLE messages ADD COLUMN attachment_status VARCHAR(50) DEFAULT 'none';"))

            conn.commit()
        except Exception as e:
            logger.warning(f"Column migration notice: {e}")

        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS attachment_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
                    media_asset_id INTEGER REFERENCES media_assets(id) ON DELETE SET NULL,
                    session_id VARCHAR(100),
                    message_key VARCHAR(150),
                    attachment_position INTEGER,
                    file_name VARCHAR(255) NOT NULL,
                    file_type VARCHAR(50) NOT NULL,
                    mime_type VARCHAR(100),
                    file_size INTEGER DEFAULT 0,
                    sha256_hash VARCHAR(64),
                    status VARCHAR(50) NOT NULL DEFAULT 'unavailable',
                    reason VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """))
            conn.commit()

            res_att = conn.execute(text("PRAGMA table_info(attachment_records);"))
            existing_att_cols = {row[1] for row in res_att.fetchall()}
            if existing_att_cols and "attachment_position" not in existing_att_cols:
                conn.execute(text("ALTER TABLE attachment_records ADD COLUMN attachment_position INTEGER;"))
                conn.commit()
        except Exception as e:
            logger.warning(f"attachment_records table notice: {e}")

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
