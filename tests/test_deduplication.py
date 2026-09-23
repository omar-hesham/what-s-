"""
Unit tests for SHA-256 deduplication and idempotent import behavior.
"""

from pathlib import Path
from owi.core.hashing import compute_sha256, compute_text_fingerprint
from owi.ingest.zip_importer import ZipImporter

def test_sha256_computation(tmp_path):
    f1 = tmp_path / "test1.txt"
    f2 = tmp_path / "test2.txt"
    
    f1.write_text("Hello WhatsApp Intelligence", encoding="utf-8")
    f2.write_text("Hello WhatsApp Intelligence", encoding="utf-8")

    assert compute_sha256(f1) == compute_sha256(f2)
    assert compute_text_fingerprint("  Hello   WhatsApp   Intelligence  ") == compute_sha256("Hello WhatsApp Intelligence")

def test_idempotent_zip_import(test_db):
    zip_path = Path("synthetic_chats/WhatsApp Chat - Omar Team Office.zip")
    if not zip_path.exists():
        pytest.skip("Synthetic ZIP archive not found")

    # First import
    res1 = ZipImporter.import_zip(zip_path, test_db)
    assert res1["status"] == "success"
    assert res1["duplicate"] is False
    conv_id = res1["conversation_id"]

    # Second import of identical archive
    res2 = ZipImporter.import_zip(zip_path, test_db)
    assert res2["status"] == "already_imported"
    assert res2["duplicate"] is True
    assert res2["conversation_id"] == conv_id
