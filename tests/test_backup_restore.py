"""
Tests for native SQLite WAL-aware backup and atomic restore.
Verifies:
1. create_backup flushes database to standalone snapshot and includes manifest.json with SHA-256.
2. restore_backup validates staging integrity and successfully restores data to a fresh target directory.
3. Tampered or corrupted backup archives are strictly rejected before touching active state.
"""

import tempfile
import zipfile
import json
from pathlib import Path
import pytest
from datetime import datetime

from owi.config import settings
from owi.db.database import SessionLocal, engine
from owi.db.models import Conversation, Message
from owi.db.backup import create_backup, restore_backup
from owi.core.hashing import compute_file_sha256

def test_backup_and_restore_cycle():
    # 1. Insert test data
    db = SessionLocal()
    try:
        conv = Conversation(title="Backup Verification Chat", message_count=2)
        db.add(conv)
        db.commit()
        db.refresh(conv)

        msg1 = Message(conversation_id=conv.id, sender_name="Omar", content="Test message 1", timestamp=datetime.utcnow())
        msg2 = Message(conversation_id=conv.id, sender_name="Ahmed", content="Test message 2", timestamp=datetime.utcnow())
        db.add_all([msg1, msg2])
        db.commit()
    finally:
        db.close()

    # 2. Create backup
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        backup_zip = tmp_dir / "test_backup.zip"
        
        result_path = create_backup(backup_zip)
        assert result_path.exists()
        assert zipfile.is_zipfile(result_path)

        # Inspect zip contents
        with zipfile.ZipFile(result_path, 'r') as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            assert "owi.db" in names
            
            manifest_bytes = archive.read("manifest.json")
            manifest = json.loads(manifest_bytes)
            assert manifest["application"] == settings.APP_NAME
            assert "database" in manifest
            assert manifest["database"]["sha256"] is not None

        # 3. Restore to a new isolated target directory
        restore_target = tmp_dir / "restored_data"
        restore_target.mkdir(parents=True, exist_ok=True)

        restore_summary = restore_backup(result_path, target_data_dir=restore_target)
        assert restore_summary["status"] == "restored"
        assert (restore_target / "owi.db").exists()

        # Verify restored DB has exact SHA256 as recorded in manifest
        restored_db_hash = compute_file_sha256(restore_target / "owi.db")
        assert restored_db_hash == manifest["database"]["sha256"]

def test_restore_tampered_backup_rejection():
    # Create valid backup first
    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        valid_backup = tmp_dir / "valid_backup.zip"
        create_backup(valid_backup)

        # Read manifest, modify it to a fake hash, and rewrite zip
        tampered_backup = tmp_dir / "tampered_backup.zip"
        with zipfile.ZipFile(valid_backup, 'r') as zin:
            with zipfile.ZipFile(tampered_backup, 'w') as zout:
                for item in zin.infolist():
                    content = zin.read(item.filename)
                    if item.filename == "manifest.json":
                        data = json.loads(content)
                        # Corrupt the expected database hash
                        data["database"]["sha256"] = "0" * 64
                        content = json.dumps(data).encode("utf-8")
                    zout.writestr(item, content)

        # Attempt to restore tampered archive
        restore_target = tmp_dir / "fail_target"
        restore_target.mkdir()

        with pytest.raises(ValueError, match="Database SHA-256 mismatch"):
            restore_backup(tampered_backup, target_data_dir=restore_target)
