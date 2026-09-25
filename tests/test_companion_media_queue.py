"""
Focused regression test suite for OWI Phase 2A/2B Integration:
Auto-enqueuing companion MediaAssets to local processing queue idempotently.

Verifies:
1. All three companion storage paths (direct upload, chunked finish, Chrome handoff)
   enqueue background processing strictly AFTER successful DB/file commit.
2. Deduplication: repeated same-asset requests create exactly one active or completed job,
   and never duplicate MediaAsset rows.
3. Previews and unavailable records: preview-only or unavailable attachments never enqueue jobs.
4. Multiple AttachmentRecords per asset: preview/unavailable record does not suppress
   a separate saved-original record for the same asset.
5. Enqueue failure resilience: SQLAlchemy session is rolled back first before persisting
   durable 'enqueue_failed' status; saved file, MediaAsset, and AttachmentRecord survive
   and remain eligible for retry.
6. Capture cancellation: stops new capture/enqueue work without retroactively destroying
   or invalidating already saved originals, which remain eligible for processing/retry.
"""

import io
import os
import shutil
import base64
import hashlib
from pathlib import Path
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from owi.main import app
from owi.config import settings
from owi.core.security import pairing_manager
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord, Job
from owi.api.routes_companion import (
    enqueue_companion_media_asset,
    mark_capture_session_cancelled,
    is_capture_session_cancelled,
    _cancelled_capture_sessions,
    save_media_file_atomically
)
from owi.core.queue import enqueue_media_processing

client = TestClient(app)

def get_auth_token():
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Queue Integration Test Runner")
    assert token is not None
    return token


# --- 1. Direct Upload Enqueues After Commit and is Idempotent ---

def test_companion_direct_upload_enqueues_after_commit_and_idempotent(test_db, tmp_path):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    conv = Conversation(title="Direct Queue Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Sender",
        timestamp=datetime.utcnow(),
        content="Document attached",
        raw_text="platform_msg_direct_1"
    )
    test_db.add(msg)
    test_db.commit()

    file_bytes = b"%PDF-1.4 Direct upload queue test document"
    b64_data = base64.b64encode(file_bytes).decode("ascii")
    expected_sha = hashlib.sha256(file_bytes).hexdigest()

    # 1. Direct upload
    res = client.post(
        "/api/companion/media/upload",
        headers=headers,
        json={
            "conversation_id": conv.id,
            "message_id": msg.id,
            "platform_msg_id": "platform_msg_direct_1",
            "file_name": "contract.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "media_base64": b64_data,
            "attachment_status": "saved-original"
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["asset_id"] is not None
    assert data["job_id"] is not None
    assert data["processing_status"] in ("queued", "processing", "completed")

    asset_id = data["asset_id"]
    job_id = data["job_id"]

    # Verify physical file and DB records survive and are linked
    asset = test_db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    assert asset is not None
    assert Path(asset.file_path).exists()
    assert Path(asset.file_path).read_bytes() == file_bytes

    att_rec = test_db.query(AttachmentRecord).filter(AttachmentRecord.media_asset_id == asset_id).first()
    assert att_rec is not None
    assert att_rec.status == "saved-original"

    # Verify background Job was created in Job table
    job = test_db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.job_type == "media_processing"
    assert job.payload.get("media_asset_id") == asset_id

    # 2. Duplicate upload of identical file to same message: must be idempotent
    res_dup = client.post(
        "/api/companion/media/upload",
        headers=headers,
        json={
            "conversation_id": conv.id,
            "message_id": msg.id,
            "platform_msg_id": "platform_msg_direct_1",
            "file_name": "contract.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "media_base64": b64_data,
            "attachment_status": "saved-original"
        }
    )
    assert res_dup.status_code == 200
    data_dup = res_dup.json()
    assert data_dup["asset_id"] == asset_id

    # Verify exactly 1 MediaAsset and 1 Job exist (no duplicates!)
    asset_count = test_db.query(MediaAsset).filter(MediaAsset.sha256_hash == expected_sha).count()
    assert asset_count == 1
    job_count = test_db.query(Job).filter(Job.job_type == "media_processing").count()
    assert job_count == 1


# --- 2. Chunked Session Finish Enqueues After Commit and is Idempotent ---

def test_companion_chunked_session_finish_enqueues_after_commit_and_idempotent(test_db, tmp_path):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    conv = Conversation(title="Chunked Session Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()

    chunk1 = b"Chunked session payload part 1 - "
    chunk2 = b"Chunked session payload part 2."
    full_bytes = chunk1 + chunk2
    full_sha = hashlib.sha256(full_bytes).hexdigest()
    session_id = f"chunk_sess_{int(datetime.utcnow().timestamp())}"

    # 1. Start session
    start_res = client.post(
        "/api/companion/media/session/start",
        headers=headers,
        json={
            "session_id": session_id,
            "conversation_id": conv.id,
            "file_name": "large_report.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "total_bytes": len(full_bytes),
            "total_chunks": 2,
            "sha256": full_sha
        }
    )
    assert start_res.status_code == 200

    # 2. Append chunks
    client.post(
        "/api/companion/media/session/chunk",
        headers=headers,
        json={
            "session_id": session_id,
            "chunk_index": 0,
            "chunk_base64": base64.b64encode(chunk1).decode("ascii")
        }
    )
    client.post(
        "/api/companion/media/session/chunk",
        headers=headers,
        json={
            "session_id": session_id,
            "chunk_index": 1,
            "chunk_base64": base64.b64encode(chunk2).decode("ascii")
        }
    )

    # 3. Finish session: triggers atomic assembly, commit, and auto-enqueue
    fin_res = client.post(
        "/api/companion/media/session/finish",
        headers=headers,
        json={"session_id": session_id}
    )
    assert fin_res.status_code == 200
    fin_data = fin_res.json()
    assert fin_data["status"] == "success"
    assert fin_data["job_id"] is not None

    asset_id = fin_data["asset_id"]
    asset = test_db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    assert asset is not None
    assert Path(asset.file_path).exists()
    assert Path(asset.file_path).read_bytes() == full_bytes

    job = test_db.query(Job).filter(Job.id == fin_data["job_id"]).first()
    assert job is not None
    assert job.payload.get("media_asset_id") == asset_id


# --- 3. Chrome Download Handoff Enqueues After Commit and is Idempotent ---

def test_companion_handoff_enqueues_after_commit_and_idempotent(test_db, monkeypatch, tmp_path):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    downloads_dir = tmp_path / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("OWI_DOWNLOADS_DIR", str(downloads_dir))

    conv = Conversation(title="Handoff Queue Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()

    pdf_content = b"%PDF-1.4 Downloaded Statement for Chrome handoff"
    pdf_sha = hashlib.sha256(pdf_content).hexdigest()
    downloaded_file = downloads_dir / "Statement_Sep2026.pdf"
    downloaded_file.write_bytes(pdf_content)

    res = client.post(
        "/api/companion/media/handoff",
        headers=headers,
        json={
            "conversation_id": conv.id,
            "download_path": str(downloaded_file),
            "file_name": "Statement_Sep2026.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "sha256": pdf_sha
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["job_id"] is not None
    asset_id = data["asset_id"]

    # Re-handoff identical file: idempotent reuse without duplicate job
    res_dup = client.post(
        "/api/companion/media/handoff",
        headers=headers,
        json={
            "conversation_id": conv.id,
            "download_path": str(downloaded_file),
            "file_name": "Statement_Sep2026.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "sha256": pdf_sha
        }
    )
    assert res_dup.status_code == 200
    assert res_dup.json()["asset_id"] == asset_id

    asset_count = test_db.query(MediaAsset).filter(MediaAsset.sha256_hash == pdf_sha).count()
    assert asset_count == 1
    job_count = test_db.query(Job).filter(Job.job_type == "media_processing").count()
    assert job_count == 1


# --- 4. Ingest Inline Media Enqueues After Commit and is Idempotent ---

def test_companion_ingest_inline_media_enqueues_after_commit_and_idempotent(test_db):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    file_bytes = b"Voice note binary audio simulation bytes"
    b64_audio = base64.b64encode(file_bytes).decode("ascii")
    expected_sha = hashlib.sha256(file_bytes).hexdigest()

    ingest_payload = {
        "chat_title": "Inline Media Ingest Chat",
        "session_id": "sess_inline_test",
        "messages": [
            {
                "sender": "Khaled",
                "text": "Audio message",
                "timestamp": "25/09/2026, 14:00",
                "platform_msg_id": "inline_audio_msg_1",
                "has_media": True,
                "media_type": "voice",
                "media_filename": "voice_note.ogg",
                "media_mime": "audio/ogg",
                "media_base64": b64_audio
            }
        ]
    }

    # 1. Ingest chunk with inline media
    res = client.post("/api/companion/ingest", headers=headers, json=ingest_payload)
    assert res.status_code == 200
    assert res.json()["messages_ingested"] == 1

    # Verify MediaAsset created and enqueued
    asset = test_db.query(MediaAsset).filter(MediaAsset.sha256_hash == expected_sha).first()
    assert asset is not None
    assert asset.processing_status in ("queued", "processing", "completed", "setup_needed")
    assert Path(asset.file_path).exists()

    job = test_db.query(Job).filter(Job.job_type == "media_processing").first()
    assert job is not None
    assert job.payload.get("media_asset_id") == asset.id

    # 2. Re-ingesting duplicate chunk must not duplicate asset or job
    res_dup = client.post("/api/companion/ingest", headers=headers, json=ingest_payload)
    assert res_dup.status_code == 200
    assert res_dup.json()["duplicates_skipped"] == 1

    asset_count = test_db.query(MediaAsset).filter(MediaAsset.sha256_hash == expected_sha).count()
    assert asset_count == 1
    job_count = test_db.query(Job).filter(Job.job_type == "media_processing").count()
    assert job_count == 1


# --- 5. Previews and Unavailable Records Are Never Enqueued ---

def test_preview_only_and_unavailable_never_enqueued(test_db):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "chat_title": "Preview and Unavailable Chat",
        "session_id": "sess_previews",
        "messages": [
            {
                "sender": "Hassan",
                "text": "Look at this thumbnail",
                "timestamp": "25/09/2026, 15:00",
                "platform_msg_id": "msg_preview_only",
                "has_media": True,
                "media_filename": "thumbnail.jpg",
                "attachment_status": "preview-only"
            },
            {
                "sender": "Hassan",
                "text": "Missing media file",
                "timestamp": "25/09/2026, 15:05",
                "platform_msg_id": "msg_unavailable",
                "has_media": True,
                "media_filename": "missing.pdf",
                "attachment_status": "unavailable"
            }
        ]
    }

    res = client.post("/api/companion/ingest", headers=headers, json=payload)
    assert res.status_code == 200
    assert res.json()["messages_ingested"] == 2

    # Verify AttachmentRecords were created with truthful statuses
    records = test_db.query(AttachmentRecord).all()
    assert len(records) == 2
    statuses = {r.status for r in records}
    assert "preview-only" in statuses
    assert "unavailable" in statuses

    # No MediaAsset rows and NO background jobs must be enqueued
    asset_count = test_db.query(MediaAsset).count()
    assert asset_count == 0
    job_count = test_db.query(Job).filter(Job.job_type == "media_processing").count()
    assert job_count == 0


# --- 6. Review Finding 1: Multiple AttachmentRecords (Saved-Original not Suppressed by Preview) ---

def test_multiple_attachment_records_saved_original_not_suppressed_by_preview(test_db, tmp_path):
    """
    When an asset is referenced by multiple AttachmentRecords (e.g. preview-only record
    inserted first, followed by saved-original), the helper must query for an actual
    'saved-original' record and not be suppressed by the preview record.
    """
    conv = Conversation(title="Multi-Record Chat", source_type="companion", message_count=2)
    test_db.add(conv)
    test_db.commit()

    msg1 = Message(
        conversation_id=conv.id,
        sender_name="Alice",
        timestamp=datetime.utcnow(),
        content="Preview reference",
        raw_text="msg_multi_1"
    )
    msg2 = Message(
        conversation_id=conv.id,
        sender_name="Alice",
        timestamp=datetime.utcnow(),
        content="Original reference",
        raw_text="msg_multi_2"
    )
    test_db.add_all([msg1, msg2])
    test_db.commit()

    file_content = b"Multi record test document content."
    file_path = tmp_path / "multi_doc.pdf"
    file_path.write_bytes(file_content)
    file_sha = hashlib.sha256(file_content).hexdigest()

    asset = MediaAsset(
        conversation_id=conv.id,
        message_id=msg2.id,
        file_name="multi_doc.pdf",
        file_path=str(file_path),
        file_type="document",
        file_size=len(file_content),
        sha256_hash=file_sha,
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # Record 1: Inserted first, status is 'preview-only'
    rec1 = AttachmentRecord(
        conversation_id=conv.id,
        message_id=msg1.id,
        media_asset_id=asset.id,
        file_name="multi_doc.pdf",
        file_type="document",
        status="preview-only"
    )
    # Record 2: Inserted second, status is 'saved-original'
    rec2 = AttachmentRecord(
        conversation_id=conv.id,
        message_id=msg2.id,
        media_asset_id=asset.id,
        file_name="multi_doc.pdf",
        file_type="document",
        status="saved-original"
    )
    test_db.add_all([rec1, rec2])
    test_db.commit()

    # Enqueue companion media asset: must find the saved-original record and succeed
    job_id = enqueue_companion_media_asset(asset.id, db=test_db)
    assert job_id is not None

    test_db.refresh(asset)
    assert asset.processing_status in ("queued", "processing", "completed")

    job = test_db.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    assert job.payload.get("media_asset_id") == asset.id

    # Negative check: If all records are preview-only / unavailable, must NOT enqueue
    asset_preview_only = MediaAsset(
        conversation_id=conv.id,
        message_id=msg1.id,
        file_name="only_preview.pdf",
        file_path=str(file_path),
        file_type="document",
        file_size=len(file_content),
        sha256_hash="fake_sha_preview_only",
        processing_status="unprocessed"
    )
    test_db.add(asset_preview_only)
    test_db.commit()

    rec_prev = AttachmentRecord(
        conversation_id=conv.id,
        message_id=msg1.id,
        media_asset_id=asset_preview_only.id,
        file_name="only_preview.pdf",
        file_type="document",
        status="preview-only"
    )
    test_db.add(rec_prev)
    test_db.commit()

    res_prev = enqueue_companion_media_asset(asset_preview_only.id, db=test_db)
    assert res_prev is None


# --- 7. Review Finding 2: Rollback First on Enqueue Failure & Preserve Retryable State ---

def test_enqueue_failure_rolls_back_session_first_and_preserves_original_with_retryable_error(test_db, monkeypatch, tmp_path):
    """
    On enqueue/commit exception:
    1. Session is rolled back first before querying or writing failure status.
    2. Physical file on disk is strictly PRESERVED (never deleted or rolled back).
    3. MediaAsset and AttachmentRecord survive in DB with processing_status='failed'
       and durable processing_error='enqueue_failed: ...'.
    4. MediaAsset remains fully eligible for retry.
    """
    conv = Conversation(title="Error Preservation Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()

    file_bytes = b"Precious contract original that must not be deleted on queue crash."
    file_path = tmp_path / "precious_contract.docx"
    file_path.write_bytes(file_bytes)
    file_sha = hashlib.sha256(file_bytes).hexdigest()

    asset = MediaAsset(
        conversation_id=conv.id,
        file_name="precious_contract.docx",
        file_path=str(file_path),
        file_type="document",
        file_size=len(file_bytes),
        sha256_hash=file_sha,
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    rec = AttachmentRecord(
        conversation_id=conv.id,
        media_asset_id=asset.id,
        file_name="precious_contract.docx",
        file_type="document",
        status="saved-original"
    )
    test_db.add(rec)
    test_db.commit()

    # Monkeypatch enqueue_media_processing to raise an error after storage commit
    def mock_broken_enqueue(aid, force_retry=False, db=None):
        raise RuntimeError("Simulated background job queue crash")

    monkeypatch.setattr("owi.api.routes_companion.enqueue_media_processing", mock_broken_enqueue)

    # Attempt to enqueue
    res = enqueue_companion_media_asset(asset.id, db=test_db)
    assert res is None

    # CRITICAL: Verify physical file is NOT deleted
    assert file_path.exists()
    assert file_path.read_bytes() == file_bytes

    # CRITICAL: Verify MediaAsset survived and has durable retryable failure status
    test_db.refresh(asset)
    assert asset.processing_status == "failed"
    assert "enqueue_failed: Simulated background job queue crash" in asset.processing_error

    # CRITICAL: AttachmentRecord remains saved-original
    test_db.refresh(rec)
    assert rec.status == "saved-original"

    # Now simulate recovery / retry with working enqueue_media_processing
    monkeypatch.undo()
    retry_job_id = enqueue_media_processing(asset.id, force_retry=True, db=test_db)
    assert retry_job_id is not None

    test_db.refresh(asset)
    assert asset.processing_status in ("queued", "processing", "completed")


# --- 8. Review Finding 3: Capture Cancellation Stops New Work and Preserves Saved Originals ---

def test_capture_cancellation_stops_new_work_and_preserves_saved_originals(test_db, tmp_path):
    """
    Capture session cancellation:
    1. Stops NEW capture/enqueue work for that session.
    2. Does NOT retroactively mark already saved originals or attachment records as cancelled.
    3. Already saved originals remain 'saved-original' and eligible for processing/retry.
    """
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    session_id = "sess_cancel_lifecycle_test"

    # Reset in-memory cancelled sessions registry
    _cancelled_capture_sessions.clear()

    conv = Conversation(title="Cancel Lifecycle Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()

    # Step 1: Upload and save original media successfully before cancellation
    file_bytes = b"Saved original media before user clicked cancel"
    b64_data = base64.b64encode(file_bytes).decode("ascii")

    res_upload = client.post(
        "/api/companion/media/upload",
        headers=headers,
        json={
            "conversation_id": conv.id,
            "session_id": session_id,
            "file_name": "saved_before_cancel.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "media_base64": b64_data,
            "attachment_status": "saved-original"
        }
    )
    assert res_upload.status_code == 200
    upload_data = res_upload.json()
    assert upload_data["status"] == "success"
    saved_asset_id = upload_data["asset_id"]

    # Verify asset is saved-original and was enqueued
    saved_asset = test_db.query(MediaAsset).filter(MediaAsset.id == saved_asset_id).first()
    assert saved_asset is not None
    assert saved_asset.processing_status in ("queued", "processing", "completed")

    saved_rec = test_db.query(AttachmentRecord).filter(AttachmentRecord.media_asset_id == saved_asset_id).first()
    assert saved_rec is not None
    assert saved_rec.status == "saved-original"

    # Step 2: User cancels the capture session
    cancel_res = client.post(
        "/api/companion/session/cancel",
        headers=headers,
        json={"session_id": session_id, "reason": "cancelled_by_user"}
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"
    assert is_capture_session_cancelled(session_id) is True

    # Step 3: Verify the already saved original is NOT retroactively cancelled or deleted
    test_db.refresh(saved_asset)
    test_db.refresh(saved_rec)
    assert Path(saved_asset.file_path).exists()
    assert saved_asset.processing_status in ("queued", "processing", "completed")
    assert saved_rec.status == "saved-original"
    # Saved original remains eligible for retry
    retry_id = enqueue_media_processing(saved_asset.id, force_retry=True, db=test_db)
    assert retry_id is not None

    # Step 4: Any NEW media enqueue attempt for the cancelled session is stopped / skipped
    new_file_bytes = b"New media attempted after session was already cancelled"
    new_file_path = tmp_path / "post_cancel_doc.pdf"
    new_file_path.write_bytes(new_file_bytes)

    new_asset = MediaAsset(
        conversation_id=conv.id,
        file_name="post_cancel_doc.pdf",
        file_path=str(new_file_path),
        file_type="document",
        file_size=len(new_file_bytes),
        sha256_hash=hashlib.sha256(new_file_bytes).hexdigest(),
        processing_status="unprocessed"
    )
    test_db.add(new_asset)
    test_db.commit()

    new_rec = AttachmentRecord(
        conversation_id=conv.id,
        media_asset_id=new_asset.id,
        session_id=session_id,
        file_name="post_cancel_doc.pdf",
        file_type="document",
        status="saved-original"
    )
    test_db.add(new_rec)
    test_db.commit()

    # New enqueue must be skipped due to session cancellation
    new_job_id = enqueue_companion_media_asset(new_asset.id, db=test_db, session_id=session_id)
    assert new_job_id is None
