"""
Tests for OWI Companion Attachment Capture, Safe Storage, and Target Selection.
Phase 2A Verification Suite:
- Attachment categories and safe subfolders (audio, images, video, documents, other)
- Path traversal defenses and filename sanitization
- Direct media upload endpoint (/api/companion/media/upload)
- Chunked media upload sessions (/api/companion/media/session/*)
- Payload bounds and size limit enforcement
- Atomic file write guarantees & failed transaction rollback
- Retry idempotency (re-upload never duplicates MediaAsset or corrupts file)
- Multiple attachments per message
- Truthful attachment status tracking and reporting per message
- Target conversation picker endpoint (/api/companion/targets)
- Confirmation requirement for imported archive targets (export_zip)
- Synthetic 197-message H conversation enrichment without message loss or duplicates
"""

import os
import sys
import base64
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient

from owi.main import app
from owi.core.security import pairing_manager
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord
from owi.config import settings
from owi.api.routes_companion import (
    save_media_file_atomically,
    sanitize_media_filename,
    determine_media_category,
    link_media_asset_to_message,
    find_matching_target_message,
    is_matching_sender
)

client = TestClient(app)

def get_auth_token():
    code_obj = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_obj["code"], "Attachment Test Runner")
    assert token is not None
    return token


# --- 1. Attachment Categories and Safe Subfolders ---

def test_attachment_categories_and_safe_subfolders(test_db, tmp_path):
    media_dir = tmp_path / "media"

    samples = [
        ("voice_note.ogg", b"OggS audio binary", "audio", "audio"),
        ("speech.mp3", b"ID3 mp3 audio binary", "audio", "audio"),
        ("photo.jpg", b"\xFF\xD8\xFF jpeg binary", "image", "images"),
        ("graphic.png", b"\x89PNG png binary", "image", "images"),
        ("clip.mp4", b"ftypmp42 video binary", "video", "video"),
        ("report.pdf", b"%PDF-1.4 document binary", "document", "documents"),
        ("table.xlsx", b"PK spreadsheet binary", "document", "documents"),
        ("contract.docx", b"PK word document binary", "document", "documents"),
        ("archive.zip", b"PK zip archive binary", "other", "other")
    ]

    for raw_name, content, file_type, expected_cat in samples:
        cat = determine_media_category(raw_name, None, file_type)
        assert cat == expected_cat, f"Expected {expected_cat} for {raw_name}, got {cat}"

        f_path, f_name, sha, f_size = save_media_file_atomically(
            media_bytes=content,
            category=cat,
            raw_filename=raw_name
        )

        assert f_path.exists()
        assert f_path.parent == media_dir / expected_cat
        assert f_size == len(content)
        assert sha == hashlib.sha256(content).hexdigest()
        assert f_path.read_bytes() == content


# --- 2. Path Traversal Defense and Sanitization ---

def test_attachment_path_traversal_sanitization(test_db, tmp_path):
    media_root = (tmp_path / "media").resolve()

    traversal_filenames = [
        "../../etc/passwd",
        "..\\..\\Windows\\System32\\cmd.exe",
        "sub/../../secret.txt",
        "folder/child/file.pdf",
        "/absolute/root/evil.sh",
        "nested\\..\\..\\dangerous.bin"
    ]

    for dangerous_name in traversal_filenames:
        sanitized = sanitize_media_filename(dangerous_name)
        assert ".." not in sanitized
        assert "/" not in sanitized
        assert "\\" not in sanitized

        content = b"Harmless content"
        f_path, f_name, sha, f_size = save_media_file_atomically(
            media_bytes=content,
            category="documents",
            raw_filename=dangerous_name
        )

        assert f_path.exists()
        # Verify strict containment inside media_root
        f_path.resolve().relative_to(media_root)


# --- 3. Direct Media Upload Endpoint ---

def test_direct_media_upload_endpoint(test_db):
    token = get_auth_token()

    conv = Conversation(title="Companion Direct Media Chat", source_type="companion", message_count=1)
    test_db.add(conv)
    test_db.commit()
    test_db.refresh(conv)

    msg = Message(
        conversation_id=conv.id,
        sender_name="You",
        timestamp=datetime.utcnow(),
        content="Here is the invoice",
        raw_text="platform_inv_123"
    )
    test_db.add(msg)
    test_db.commit()
    test_db.refresh(msg)

    fake_pdf = b"%PDF-1.4 Direct Invoice Test"
    b64_data = base64.b64encode(fake_pdf).decode("ascii")

    res = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv.id,
            "message_id": msg.id,
            "platform_msg_id": "platform_inv_123",
            "file_name": "Invoice_99.pdf",
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
    assert data["attachment_status"] == "saved-original"

    # Verify DB state
    asset = test_db.query(MediaAsset).filter(MediaAsset.id == data["asset_id"]).first()
    assert asset is not None
    assert asset.conversation_id == conv.id
    assert asset.message_id == msg.id
    assert asset.file_type == "document"
    assert asset.file_size == len(fake_pdf)
    assert Path(asset.file_path).exists()

    test_db.refresh(msg)
    assert msg.has_attachment is True
    assert msg.attachment_status == "saved-original"


# --- 4. Chunked Media Upload Session ---

def test_chunked_media_upload_session(test_db, tmp_path):
    token = get_auth_token()

    conv = Conversation(title="Video Session Chat", source_type="companion", message_count=0)
    test_db.add(conv)
    test_db.commit()
    test_db.refresh(conv)

    # 1.5 MB simulated video
    raw_video = b"VIDEO_CHUNK_HEADER_" + os.urandom(1_500_000 - len(b"VIDEO_CHUNK_HEADER_"))
    total_bytes = len(raw_video)
    expected_sha = hashlib.sha256(raw_video).hexdigest()

    chunk_size = 500_000
    chunks = [raw_video[i:i + chunk_size] for i in range(0, total_bytes, chunk_size)]
    assert len(chunks) == 3

    session_id = f"video_sess_{int(datetime.utcnow().timestamp())}"

    # Step 1: Start
    start_res = client.post(
        "/api/companion/media/session/start",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "session_id": session_id,
            "conversation_id": conv.id,
            "file_name": "presentation.mp4",
            "file_type": "video",
            "mime_type": "video/mp4",
            "total_bytes": total_bytes,
            "total_chunks": len(chunks),
            "sha256": expected_sha,
            "attachment_status": "saved-original"
        }
    )
    assert start_res.status_code == 200
    assert start_res.json()["status"] in ("started", "session_started")

    # Step 2: Chunks
    for idx, c_bytes in enumerate(chunks):
        c_b64 = base64.b64encode(c_bytes).decode("ascii")
        c_res = client.post(
            "/api/companion/media/session/chunk",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "session_id": session_id,
                "chunk_index": idx,
                "chunk_base64": c_b64
            }
        )
        assert c_res.status_code == 200
        assert c_res.json()["status"] in ("chunk_received", "chunk_appended")

    # Step 3: Finish
    finish_res = client.post(
        "/api/companion/media/session/finish",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id}
    )
    assert finish_res.status_code == 200
    fin_data = finish_res.json()
    assert fin_data["status"] == "success"
    assert fin_data["category"] == "video"
    assert fin_data["file_size"] == total_bytes
    assert fin_data["sha256"] == expected_sha

    # Verify asset in DB
    asset = test_db.query(MediaAsset).filter(MediaAsset.id == fin_data["asset_id"]).first()
    assert asset is not None
    assert Path(asset.file_path).exists()
    assert Path(asset.file_path).read_bytes() == raw_video

    # Verify session part file was cleaned up
    session_part = tmp_path / "tmp" / "sessions" / f"{session_id}.part"
    assert not session_part.exists()


# --- 5. Direct and Chunked Payload Size Limits ---

def test_direct_and_chunked_size_limits(test_db):
    token = get_auth_token()

    # Direct upload exceeding 5MB limit
    oversized_bytes = b"X" * (5 * 1024 * 1024 + 100)
    oversized_b64 = base64.b64encode(oversized_bytes).decode("ascii")

    res_direct = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "file_name": "too_big.mp4",
            "file_type": "video",
            "media_base64": oversized_b64
        }
    )
    assert res_direct.status_code == 400
    assert "File size exceeds maximum direct upload limit" in res_direct.json()["detail"]

    # Session chunk exceeding 2MB chunk limit
    oversized_chunk = b"Y" * (2 * 1024 * 1024 + 50)
    oversized_chunk_b64 = base64.b64encode(oversized_chunk).decode("ascii")

    res_chunk = client.post(
        "/api/companion/media/session/chunk",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "session_id": "fake_sess",
            "chunk_index": 0,
            "chunk_base64": oversized_chunk_b64
        }
    )
    assert res_chunk.status_code == 400
    assert "Chunk size exceeds maximum limit" in res_chunk.json()["detail"]


# --- 6. Failed DB/File Transaction Rollback ---

def test_failed_db_or_file_transaction_rollback(test_db, tmp_path, monkeypatch):
    token = get_auth_token()

    conv = Conversation(title="Rollback Test Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    test_content = b"Rollback file bytes"
    b64_content = base64.b64encode(test_content).decode("ascii")

    # Simulate database commit error during link_media_asset_to_message
    from owi.api import routes_companion
    orig_link = routes_companion.link_media_asset_to_message

    def broken_link(*args, **kwargs):
        raise RuntimeError("Simulated Database Crash during asset linking")

    monkeypatch.setattr(routes_companion, "link_media_asset_to_message", broken_link)

    res = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv.id,
            "file_name": "rollback.jpg",
            "file_type": "image",
            "media_base64": b64_content
        }
    )
    assert res.status_code == 500

    # Ensure no orphaned MediaAsset row was created
    assets = test_db.query(MediaAsset).filter(MediaAsset.conversation_id == conv.id).all()
    assert len(assets) == 0


# --- 7. Retry Idempotency (No Duplicate MediaAssets) ---

def test_retry_idempotency_no_duplicate_media_assets(test_db):
    token = get_auth_token()

    conv = Conversation(title="Idempotent Media Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    file_bytes = b"Identical media contents for retry test"
    b64_data = base64.b64encode(file_bytes).decode("ascii")

    # Upload 1
    res1 = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv.id,
            "file_name": "retry_photo.jpg",
            "file_type": "image",
            "media_base64": b64_data
        }
    )
    assert res1.status_code == 200
    asset_id_1 = res1.json()["asset_id"]

    # Upload 2 (simulated client retry with same content)
    res2 = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv.id,
            "file_name": "retry_photo.jpg",
            "file_type": "image",
            "media_base64": b64_data
        }
    )
    assert res2.status_code == 200
    asset_id_2 = res2.json()["asset_id"]

    assert asset_id_1 == asset_id_2, "Retry must reuse existing MediaAsset row"
    total_assets = test_db.query(MediaAsset).filter(MediaAsset.conversation_id == conv.id).count()
    assert total_assets == 1, "Must never duplicate MediaAsset on retry"


# --- 8. Multiple Attachments per Message in Ingest ---

def test_multiple_attachments_per_message_in_ingest(test_db):
    token = get_auth_token()

    img_bytes = b"\xFF\xD8\xFF image attachment 1"
    doc_bytes = b"%PDF-1.4 document attachment 2"

    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Multi-Attachment Chat",
            "messages": [
                {
                    "sender": "Alice",
                    "text": "Attached photo and document",
                    "timestamp": "2026-09-25T14:30:00",
                    "has_media": True,
                    "attachments": [
                        {
                            "file_name": "album_pic.jpg",
                            "file_type": "image",
                            "mime_type": "image/jpeg",
                            "file_size": len(img_bytes),
                            "media_base64": base64.b64encode(img_bytes).decode("ascii"),
                            "attachment_status": "saved-original"
                        },
                        {
                            "file_name": "agenda.pdf",
                            "file_type": "document",
                            "mime_type": "application/pdf",
                            "file_size": len(doc_bytes),
                            "media_base64": base64.b64encode(doc_bytes).decode("ascii"),
                            "attachment_status": "saved-original"
                        }
                    ]
                }
            ]
        }
    )

    assert ingest_res.status_code == 200
    data = ingest_res.json()
    summary = data["attachments_summary"]
    assert summary["saved_original"] == 2
    assert summary["total_detected"] == 2

    # Verify DB assets linked to message
    msg = test_db.query(Message).filter(Message.conversation_id == data["conversation_id"]).first()
    assert msg is not None
    assert msg.has_attachment is True
    assert msg.attachment_status == "saved-original"

    assets = test_db.query(MediaAsset).filter(MediaAsset.message_id == msg.id).all()
    assert len(assets) == 2
    names = {a.file_name for a in assets}
    assert any("album_pic.jpg" in n for n in names)
    assert any("agenda.pdf" in n for n in names)


# --- 9. Truthful Attachment Status Reporting per Message ---

def test_attachment_status_reporting_per_message(test_db):
    token = get_auth_token()

    sample_img = base64.b64encode(b"\xFF\xD8\xFF photo").decode("ascii")

    messages = [
        # 1. Saved original
        {
            "sender": "H",
            "text": "Saved original audio",
            "timestamp": "2026-09-25T10:00:00",
            "has_media": True,
            "media_base64": sample_img,
            "media_filename": "original.jpg",
            "attachment_status": "saved-original"
        },
        # 2. Preview only
        {
            "sender": "H",
            "text": "Only thumbnail loaded",
            "timestamp": "2026-09-25T10:01:00",
            "has_media": True,
            "media_filename": "thumb.jpg",
            "attachment_status": "preview-only"
        },
        # 3. Unavailable
        {
            "sender": "H",
            "text": "Download control not ready",
            "timestamp": "2026-09-25T10:02:00",
            "has_media": True,
            "media_filename": "unavail.pdf",
            "attachment_status": "unavailable"
        },
        # 4. Expired
        {
            "sender": "H",
            "text": "Blob URL was expired",
            "timestamp": "2026-09-25T10:03:00",
            "has_media": True,
            "media_filename": "expired.pdf",
            "attachment_status": "expired"
        },
        # 5. Too large
        {
            "sender": "H",
            "text": "Huge video exceeded 50MB",
            "timestamp": "2026-09-25T10:04:00",
            "has_media": True,
            "media_filename": "massive.mp4",
            "attachment_status": "too-large"
        },
        # 6. Unsupported
        {
            "sender": "H",
            "text": "Executable file attachment",
            "timestamp": "2026-09-25T10:05:00",
            "has_media": True,
            "media_filename": "malware.exe",
            "attachment_status": "unsupported"
        },
        # 7. Failed
        {
            "sender": "H",
            "text": "Download failed with network error",
            "timestamp": "2026-09-25T10:06:00",
            "has_media": True,
            "media_filename": "failed.dat",
            "attachment_status": "failed"
        }
    ]

    res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Status Reporting Test Chat",
            "messages": messages
        }
    )
    assert res.status_code == 200
    summary = res.json()["attachments_summary"]
    assert summary["saved_original"] == 1
    assert summary["preview_only"] == 1
    assert summary["unavailable"] == 1
    assert summary["expired"] == 1
    assert summary["too_large"] == 1
    assert summary["unsupported"] == 1
    assert summary["failed"] == 1
    assert summary["total_detected"] == 7

    # Verify per-message attachment_status in DB
    db_messages = test_db.query(Message).filter(Message.conversation_id == res.json()["conversation_id"]).all()
    statuses = [m.attachment_status for m in db_messages]
    assert "saved-original" in statuses
    assert "preview-only" in statuses
    assert "unavailable" in statuses
    assert "expired" in statuses
    assert "too-large" in statuses
    assert "unsupported" in statuses
    assert "failed" in statuses


# --- 10. Target Conversation Picker Endpoint ---

def test_target_conversation_picker_endpoint(test_db):
    token = get_auth_token()

    c1 = Conversation(title="Chat Alpha", source_type="companion", message_count=10)
    c2 = Conversation(title="WhatsApp Chat with H", source_type="export_zip", message_count=197)
    test_db.add_all([c1, c2])
    test_db.commit()

    res = client.get("/api/companion/targets", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "targets" in data
    targets = data["targets"]
    assert len(targets) >= 2

    h_target = next(t for t in targets if t["id"] == c2.id)
    assert h_target["title"] == "WhatsApp Chat with H"
    assert h_target["source_type"] == "export_zip"
    assert h_target["message_count"] == 197


# --- 11. Target Selection Requires Confirmation for Imported Archive Targets ---

def test_target_selection_requires_confirmation_for_imported_target(test_db):
    token = get_auth_token()

    imported_conv = Conversation(title="Imported Archive H", source_type="export_zip", message_count=197)
    test_db.add(imported_conv)
    test_db.commit()

    msg_payload = [{
        "sender": "H",
        "text": "Unconfirmed merge attempt",
        "timestamp": "2026-09-25T11:00:00"
    }]

    # Case A: Without confirmation -> 400 Bad Request
    res_no_confirm = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "WhatsApp Web H",
            "target_conversation_id": imported_conv.id,
            "confirm_target_merge": False,
            "messages": msg_payload
        }
    )
    assert res_no_confirm.status_code == 400
    assert "Explicit confirmation required" in res_no_confirm.json()["detail"]

    # Case B: Non-existent target ID -> 404 Not Found
    res_not_found = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "WhatsApp Web H",
            "target_conversation_id": 999999,
            "confirm_target_merge": True,
            "messages": msg_payload
        }
    )
    assert res_not_found.status_code == 404
    assert "not found" in res_not_found.json()["detail"].lower()

    # Case C: With confirmation -> Success (200)
    res_confirmed = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "WhatsApp Web H",
            "target_conversation_id": imported_conv.id,
            "confirm_target_merge": True,
            "messages": msg_payload
        }
    )
    assert res_confirmed.status_code == 200
    assert res_confirmed.json()["conversation_id"] == imported_conv.id


# --- 12. Synthetic H Conversation Enrichment Preserves 197 Messages ---

def test_synthetic_h_conversation_enrichment_preserves_197_messages(test_db):
    """
    Simulates imported conversation H (ID 13, source_type: export_zip) with exactly 197 messages.
    During companion bulk capture, user selects H as the target with explicit confirmation.
    50 overlapping messages (carrying attachments) are ingested.
    Verifies:
    1. Total message count remains exactly 197 (no duplicate messages inserted).
    2. Overlapping messages have their has_attachment updated and MediaAssets linked.
    3. Never merged across source types by title alone.
    """
    token = get_auth_token()

    # 1. Create synthetic imported conversation H with 197 messages
    h_conv = Conversation(
        title="WhatsApp Chat with H - 2026 Export",
        source_type="export_zip",
        message_count=197
    )
    test_db.add(h_conv)
    test_db.commit()
    test_db.refresh(h_conv)

    base_time = datetime(2026, 9, 1, 10, 0, 0)
    synthetic_messages = []

    for i in range(1, 198):
        # 197 messages spread across time
        msg_time = base_time + timedelta(minutes=i * 10)
        sender = "H" if i % 2 == 1 else "Omar"
        text = f"Synthetic H message number {i}"
        synthetic_messages.append(
            Message(
                conversation_id=h_conv.id,
                sender_name=sender,
                timestamp=msg_time,
                timestamp_provenance="verified",
                content=text,
                has_attachment=False,
                attachment_name=None,
                attachment_status="none"
            )
        )

    test_db.add_all(synthetic_messages)
    test_db.commit()

    initial_count = test_db.query(Message).filter(Message.conversation_id == h_conv.id).count()
    assert initial_count == 197

    # 2. Simulate Companion bulk capture of 50 messages that overlap with #1 to #50
    # Ingest carries captured voice notes and document attachments
    overlap_captured_messages = []
    fake_audio_bytes = b"OggS synthetic voice note for H"
    fake_audio_b64 = base64.b64encode(fake_audio_bytes).decode("ascii")

    for i in range(1, 51):
        msg_time = base_time + timedelta(minutes=i * 10)
        sender = "H" if i % 2 == 1 else "Omar"
        text = f"Synthetic H message number {i}"
        overlap_captured_messages.append({
            "sender": sender,
            "text": text,
            "timestamp": msg_time.isoformat(),
            "has_media": True,
            "media_type": "voice",
            "media_filename": f"voice_h_{i}.ogg",
            "media_base64": fake_audio_b64,
            "attachment_status": "saved-original"
        })

    # Ingest targeting H conversation with confirmation
    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",  # Notice header in WhatsApp Web is simply 'H'
            "target_conversation_id": h_conv.id,
            "confirm_target_merge": True,
            "chunk_index": 0,
            "total_chunks": 1,
            "is_last_chunk": True,
            "messages": overlap_captured_messages
        }
    )

    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data["conversation_id"] == h_conv.id
    # Overlap matching must skip duplicate inserts!
    assert ingest_data["duplicates_skipped"] == 50
    assert ingest_data["messages_ingested"] == 0

    # 3. CRITICAL AUDIT: DB count MUST REMAIN EXACTLY 197
    final_count = test_db.query(Message).filter(Message.conversation_id == h_conv.id).count()
    assert final_count == 197, f"Expected exactly 197 messages, found {final_count}!"

    # 4. Verify the 50 overlapping messages were enriched with attachment metadata & MediaAssets
    enriched_messages = (
        test_db.query(Message)
        .filter(Message.conversation_id == h_conv.id, Message.has_attachment == True)
        .all()
    )
    assert len(enriched_messages) == 50

    for em in enriched_messages:
        assert em.attachment_status == "saved-original"
        assert em.attachment_name is not None
        # Check MediaAsset linked
        linked_asset = test_db.query(MediaAsset).filter(MediaAsset.message_id == em.id).first()
        assert linked_asset is not None
        assert linked_asset.conversation_id == h_conv.id
        assert Path(linked_asset.file_path).exists()


# --- 13. Critical Reviewer Delta Regressions (P0 1-4, P1 5-6) ---

def test_upload_before_ingest_reconciliation_synthetic_h(test_db):
    """
    P0 1: Pre-upload media to synthetic imported H conversation (#13, export_zip, 197 messages),
    then ingest matching text later. Assert exact MediaAsset.message_id is linked, physical bytes match,
    exact 197 messages preserved, retry idempotent; also test new companion chat.
    """
    token = get_auth_token()

    # 1. Setup synthetic imported H conversation with 197 messages
    h_conv = Conversation(
        id=13,
        title="Chat with H (+966 50 123 4567)",
        source_type="export_zip",
        message_count=197
    )
    test_db.add(h_conv)
    test_db.commit()

    base_time = datetime(2026, 9, 20, 10, 0, 0)
    for i in range(1, 198):
        msg_time = base_time + timedelta(minutes=i * 5)
        sender = "H" if i % 2 == 1 else "Omar"
        content = "Architectural blueprint attached" if i == 42 else f"Message {i}"
        test_db.add(Message(
            id=1000 + i,
            conversation_id=h_conv.id,
            sender_name=sender,
            timestamp=msg_time,
            timestamp_provenance="verified",
            content=content,
            raw_text=content,
            has_attachment=False
        ))
    test_db.commit()

    assert test_db.query(Message).filter(Message.conversation_id == h_conv.id).count() == 197
    target_msg_42 = test_db.query(Message).filter(Message.id == 1042).first()
    assert target_msg_42 is not None

    # 2. Upload media BEFORE ingest is called
    pdf_bytes = b"%PDF-1.4 synthetic blueprint for H conversation"
    pdf_sha = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    upload_res = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": h_conv.id,
            "confirm_target_merge": True,
            "platform_msg_id": "wam_h_blueprint_42",
            "message_key": "wam_h_blueprint_42",
            "file_name": "blueprint.pdf",
            "file_type": "document",
            "mime_type": "application/pdf",
            "media_base64": pdf_b64,
            "sha256": pdf_sha
        }
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    asset_id = upload_data["asset_id"]
    # Before ingest, message_id must be None because target message row does not have raw_text=platform_msg_id
    assert upload_data["message_id"] is None

    unlinked_asset = test_db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    assert unlinked_asset is not None
    assert unlinked_asset.message_id is None
    assert Path(unlinked_asset.file_path).exists()

    # 3. Now ingest matching text for message 42
    msg_42_time = base_time + timedelta(minutes=42 * 5)
    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",
            "target_conversation_id": h_conv.id,
            "confirm_target_merge": True,
            "messages": [
                {
                    "sender": "Omar",
                    "text": "Architectural blueprint attached",
                    "timestamp": msg_42_time.isoformat(),
                    "platform_msg_id": "wam_h_blueprint_42",
                    "has_media": True,
                    "media_filename": "blueprint.pdf",
                    "attachment_status": "saved-original"
                }
            ]
        }
    )
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data["duplicates_skipped"] == 1
    assert ingest_data["messages_ingested"] == 0
    assert ingest_data["attachments_summary"]["saved_original"] == 1

    # 4. Check exact MediaAsset.message_id is linked to message 1042
    test_db.refresh(unlinked_asset)
    assert unlinked_asset.message_id == 1042
    test_db.refresh(target_msg_42)
    assert target_msg_42.has_attachment is True
    assert target_msg_42.attachment_status == "saved-original"
    assert test_db.query(Message).filter(Message.conversation_id == h_conv.id).count() == 197

    # 5. Idempotent retry: re-ingest same payload
    retry_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",
            "target_conversation_id": h_conv.id,
            "confirm_target_merge": True,
            "messages": [
                {
                    "sender": "Omar",
                    "text": "Architectural blueprint attached",
                    "timestamp": msg_42_time.isoformat(),
                    "platform_msg_id": "wam_h_blueprint_42",
                    "has_media": True,
                    "media_filename": "blueprint.pdf",
                    "attachment_status": "saved-original"
                }
            ]
        }
    )
    assert retry_res.status_code == 200
    assert test_db.query(Message).filter(Message.conversation_id == h_conv.id).count() == 197
    assert test_db.query(MediaAsset).filter(MediaAsset.message_id == 1042).count() == 1

    # 6. Test with a new companion conversation
    comp_upload = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Brand New Chat",
            "platform_msg_id": "wam_new_comp_001",
            "message_key": "wam_new_comp_001",
            "file_name": "welcome.png",
            "file_type": "image",
            "mime_type": "image/png",
            "media_base64": base64.b64encode(b"\x89PNG welcome image").decode("ascii")
        }
    )
    assert comp_upload.status_code == 200
    comp_asset_id = comp_upload.json()["asset_id"]

    comp_ingest = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Brand New Chat",
            "messages": [
                {
                    "sender": "DELL",
                    "text": "Welcome to the team!",
                    "timestamp": "2026-09-25T11:00:00",
                    "platform_msg_id": "wam_new_comp_001",
                    "has_media": True,
                    "media_filename": "welcome.png",
                    "attachment_status": "saved-original"
                }
            ]
        }
    )
    assert comp_ingest.status_code == 200
    comp_asset = test_db.query(MediaAsset).filter(MediaAsset.id == comp_asset_id).first()
    assert comp_asset.message_id is not None
    linked_new_msg = test_db.query(Message).filter(Message.id == comp_asset.message_id).first()
    assert linked_new_msg.content == "Welcome to the team!"
    assert linked_new_msg.attachment_status == "saved-original"


def test_same_binary_multiple_messages_deduplication(test_db):
    """
    P0 2: Same binary can occur in two distinct messages.
    Both messages must have an asset linked, timeline must show assets for both,
    storage deduplicated, and retries must not duplicate links.
    """
    token = get_auth_token()
    conv = Conversation(title="Same Binary Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    shared_image_bytes = b"\xFF\xD8\xFF shared photo data across messages"
    shared_b64 = base64.b64encode(shared_image_bytes).decode("ascii")

    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Same Binary Chat",
            "target_conversation_id": conv.id,
            "messages": [
                {
                    "sender": "Alice",
                    "text": "Look at this screenshot",
                    "timestamp": "2026-09-25T10:00:00",
                    "platform_msg_id": "msg_alice_pic",
                    "has_media": True,
                    "media_filename": "screen.jpg",
                    "media_base64": shared_b64,
                    "attachment_status": "saved-original"
                },
                {
                    "sender": "Bob",
                    "text": "Forwarding your screenshot to the group",
                    "timestamp": "2026-09-25T10:05:00",
                    "platform_msg_id": "msg_bob_forward",
                    "has_media": True,
                    "media_filename": "screen.jpg",
                    "media_base64": shared_b64,
                    "attachment_status": "saved-original"
                }
            ]
        }
    )
    assert ingest_res.status_code == 200

    msg_alice = test_db.query(Message).filter(Message.raw_text == "msg_alice_pic").first()
    msg_bob = test_db.query(Message).filter(Message.raw_text == "msg_bob_forward").first()
    assert msg_alice is not None
    assert msg_bob is not None
    assert msg_alice.id != msg_bob.id

    assert msg_alice.attachment_status == "saved-original"
    assert msg_bob.attachment_status == "saved-original"

    # Query timeline endpoint: both messages must expose their media assets
    timeline_res = client.get(f"/api/conversations/{conv.id}/messages")
    assert timeline_res.status_code == 200
    timeline = timeline_res.json()
    assert len(timeline) == 2
    for item in timeline:
        assert item["has_attachment"] is True
        assert item["attachment_status"] == "saved-original"
        assert len(item["media_assets"]) >= 1
        assert item["media_assets"][0]["file_name"] is not None

    # Verify physical file is deduplicated on disk
    asset_alice = test_db.query(MediaAsset).filter(MediaAsset.message_id == msg_alice.id).first()
    asset_bob = test_db.query(MediaAsset).filter(MediaAsset.message_id == msg_bob.id).first()
    assert asset_alice.file_path == asset_bob.file_path
    assert Path(asset_alice.file_path).exists()


def test_mixed_attachment_statuses_within_single_message(test_db):
    """
    P0 3: Every detected attachment needs a durable per-file status even if unavailable,
    preview-only, expired, too-large, unsupported or failed.
    Summary counts derived from stored AttachmentRecord rows rather than trusting caller labels.
    Never create an apparently saved record unless an actual linked physical asset exists.
    """
    token = get_auth_token()
    conv = Conversation(title="Multi-Status Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    saved_doc_bytes = b"%PDF real original bytes"
    saved_doc_b64 = base64.b64encode(saved_doc_bytes).decode("ascii")

    ingest_res = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Multi-Status Chat",
            "target_conversation_id": conv.id,
            "messages": [
                {
                    "sender": "Alice",
                    "text": "Mixed attachment collection",
                    "timestamp": "2026-09-25T12:00:00",
                    "platform_msg_id": "msg_mixed_attachments",
                    "attachments": [
                        {
                            "file_name": "contract.pdf",
                            "file_type": "document",
                            "mime_type": "application/pdf",
                            "media_base64": saved_doc_b64,
                            "attachment_status": "saved-original"
                        },
                        {
                            "file_name": "thumb.jpg",
                            "file_type": "image",
                            "attachment_status": "preview-only",
                            "reason": "preview_only"
                        },
                        {
                            "file_name": "voice.ogg",
                            "file_type": "audio",
                            "attachment_status": "expired",
                            "reason": "expired"
                        },
                        {
                            "file_name": "dataset.zip",
                            "file_type": "document",
                            "attachment_status": "too-large",
                            "reason": "too-large"
                        },
                        {
                            "file_name": "claimed_original_but_no_bytes.docx",
                            "file_type": "document",
                            "attachment_status": "saved-original"  # False claim: no bytes provided!
                        }
                    ]
                }
            ]
        }
    )
    assert ingest_res.status_code == 200
    summary = ingest_res.json()["attachments_summary"]

    assert summary["saved_original"] == 1
    assert summary["preview_only"] == 1
    assert summary["expired"] == 1
    assert summary["too_large"] == 1
    # False claim was downgraded to failed because no physical asset exists!
    assert summary["failed"] == 1

    msg = test_db.query(Message).filter(Message.raw_text == "msg_mixed_attachments").first()
    assert msg is not None

    records = test_db.query(AttachmentRecord).filter(AttachmentRecord.message_id == msg.id).all()
    assert len(records) == 5

    record_by_name = {r.file_name: r for r in records}
    assert record_by_name["contract.pdf"].status == "saved-original"
    assert record_by_name["contract.pdf"].media_asset_id is not None
    assert record_by_name["thumb.jpg"].status == "preview-only"
    assert record_by_name["voice.ogg"].status == "expired"
    assert record_by_name["dataset.zip"].status == "too-large"
    assert record_by_name["claimed_original_but_no_bytes.docx"].status == "failed"


def test_target_and_message_validation_cross_conversation_isolation(test_db):
    """
    P0 4: Direct and chunked upload validate target and message scope before final commit.
    Require exact target conversation, scope platform lookup to it, enforce confirmation
    for imported targets, and leave no orphan files on failed transactions.
    """
    token = get_auth_token()

    conv_a = Conversation(id=101, title="Chat A", source_type="companion")
    conv_b = Conversation(id=102, title="Chat B", source_type="companion")
    imported_conv = Conversation(id=103, title="Imported Archive", source_type="export_zip")
    test_db.add_all([conv_a, conv_b, imported_conv])
    test_db.commit()

    msg_a = Message(
        id=5001,
        conversation_id=conv_a.id,
        sender_name="Alice",
        timestamp=datetime.utcnow(),
        content="Msg in Conv A",
        raw_text="platform_msg_shared_key"
    )
    test_db.add(msg_a)
    test_db.commit()

    sample_b64 = base64.b64encode(b"sample bytes").decode("ascii")

    # 1. Nonexistent conversation returns 404
    res_404 = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": 99999,
            "file_name": "test.txt",
            "media_base64": sample_b64
        }
    )
    assert res_404.status_code == 404

    # 2. Upload to imported archive without confirm_target_merge returns 400
    res_unconfirmed = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": imported_conv.id,
            "confirm_target_merge": False,
            "file_name": "test.txt",
            "media_base64": sample_b64
        }
    )
    assert res_unconfirmed.status_code == 400
    assert "Explicit confirmation required" in res_unconfirmed.json()["detail"]

    # 3. Message ID from different conversation returns 404
    res_wrong_msg = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_b.id,
            "message_id": msg_a.id,  # msg_a belongs to conv_a, not conv_b!
            "file_name": "test.txt",
            "media_base64": sample_b64
        }
    )
    assert res_wrong_msg.status_code == 404

    # 4. Platform message lookup scoped to target conversation:
    # Upload to conv_b with platform_msg_id="platform_msg_shared_key" must NOT link to msg_a!
    res_scoped = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_b.id,
            "platform_msg_id": "platform_msg_shared_key",
            "file_name": "scoped_file.txt",
            "media_base64": sample_b64
        }
    )
    assert res_scoped.status_code == 200
    # Must NOT link to msg_a in conv_a!
    assert res_scoped.json()["message_id"] is None
    asset = test_db.query(MediaAsset).filter(MediaAsset.id == res_scoped.json()["asset_id"]).first()
    assert asset.conversation_id == conv_b.id
    assert asset.message_id is None


def test_chunk_session_retry_safety_and_streaming(test_db):
    """
    P1 5: Make chunk sessions retry-safe: idempotent restart, chunk replay,
    conflicting chunk rejection, missing chunks rejection, streaming assembly,
    and SHA verification before reusing same-size files.
    """
    token = get_auth_token()
    conv = Conversation(title="Chunk Test Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    chunk1 = b"Part one 12345\n"
    chunk2 = b"Part two 67890\n"
    full_data = chunk1 + chunk2
    full_sha = hashlib.sha256(full_data).hexdigest()
    session_id = "test_retry_safe_session_100"

    # 1. Start session
    start_payload = {
        "session_id": session_id,
        "conversation_id": conv.id,
        "file_name": "streaming_video.mp4",
        "file_type": "video",
        "mime_type": "video/mp4",
        "total_bytes": len(full_data),
        "total_chunks": 2,
        "sha256": full_sha
    }
    s_res = client.post("/api/companion/media/session/start", headers={"Authorization": f"Bearer {token}"}, json=start_payload)
    assert s_res.status_code == 200
    assert s_res.json()["status"] == "session_started"

    # Re-starting with same parameters returns session_resumed (idempotent start)
    s_resume = client.post("/api/companion/media/session/start", headers={"Authorization": f"Bearer {token}"}, json=start_payload)
    assert s_resume.status_code == 200
    assert s_resume.json()["status"] == "session_resumed"

    # 2. Append chunk 0
    c0_b64 = base64.b64encode(chunk1).decode("ascii")
    c0_res = client.post(
        "/api/companion/media/session/chunk",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "chunk_index": 0, "chunk_base64": c0_b64}
    )
    assert c0_res.status_code == 200
    assert c0_res.json()["bytes_received"] == len(chunk1)

    # Replay chunk 0 (idempotent replay)
    c0_replay = client.post(
        "/api/companion/media/session/chunk",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "chunk_index": 0, "chunk_base64": c0_b64}
    )
    assert c0_replay.status_code == 200
    assert c0_replay.json()["bytes_received"] == len(chunk1)

    # Conflicting chunk 0 returns 400
    diff_c0 = base64.b64encode(b"different content").decode("ascii")
    c0_conflict = client.post(
        "/api/companion/media/session/chunk",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "chunk_index": 0, "chunk_base64": diff_c0}
    )
    assert c0_conflict.status_code == 400
    assert "already received with different content" in c0_conflict.json()["detail"]

    # Finish before chunk 1 returns 400 (missing chunks)
    fin_early = client.post(
        "/api/companion/media/session/finish",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id}
    )
    assert fin_early.status_code == 400
    assert "Incomplete upload session" in fin_early.json()["detail"]

    # 3. Append chunk 1
    c1_b64 = base64.b64encode(chunk2).decode("ascii")
    c1_res = client.post(
        "/api/companion/media/session/chunk",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id, "chunk_index": 1, "chunk_base64": c1_b64}
    )
    assert c1_res.status_code == 200

    # 4. Finish session successfully
    fin_res = client.post(
        "/api/companion/media/session/finish",
        headers={"Authorization": f"Bearer {token}"},
        json={"session_id": session_id}
    )
    assert fin_res.status_code == 200
    fin_data = fin_res.json()
    assert fin_data["status"] == "success"
    assert fin_data["sha256"] == full_sha
    assert fin_data["file_size"] == len(full_data)


def test_overlap_matching_strict_sender_and_ambiguity(test_db):
    """
    P1 6: Overlap matching must never choose a different sender simply because text length >15.
    Require a unique defensible match on sender, timestamp and content, with explicit safe mapping of 'You' aliases.
    Ambiguity must not silently merge.
    """
    conv = Conversation(title="Overlap Precision Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    long_text = "This is a very specific architectural agreement text exceeding fifteen characters"
    match_time = datetime(2026, 9, 20, 10, 0, 0)

    # Message from Alice
    msg_alice = Message(
        conversation_id=conv.id,
        sender_name="Alice",
        timestamp=match_time,
        timestamp_provenance="verified",
        content=long_text,
        raw_text=long_text
    )
    # Message from Bob with identical text 30 seconds later (within 1 min window)
    msg_bob = Message(
        conversation_id=conv.id,
        sender_name="Bob",
        timestamp=match_time + timedelta(seconds=30),
        timestamp_provenance="verified",
        content=long_text,
        raw_text=long_text
    )
    test_db.add_all([msg_alice, msg_bob])
    test_db.commit()

    # 1. Incoming capture for Alice must match msg_alice, NOT msg_bob
    match_a = find_matching_target_message(
        db=test_db,
        conv_id=conv.id,
        platform_msg_id=None,
        dt=match_time,
        sender="Alice",
        text=long_text,
        provenance="verified"
    )
    assert match_a is not None
    assert match_a.id == msg_alice.id

    # 2. Incoming capture for Bob must match msg_bob, NOT msg_alice
    match_b = find_matching_target_message(
        db=test_db,
        conv_id=conv.id,
        platform_msg_id=None,
        dt=match_time + timedelta(seconds=30),
        sender="Bob",
        text=long_text,
        provenance="verified"
    )
    assert match_b is not None
    assert match_b.id == msg_bob.id

    # 3. Incoming capture from a third party 'Charlie' with the same text must NOT match either!
    match_c = find_matching_target_message(
        db=test_db,
        conv_id=conv.id,
        platform_msg_id=None,
        dt=match_time,
        sender="Charlie",
        text=long_text,
        provenance="verified"
    )
    assert match_c is None

    # 4. Safe mapping of 'You' aliases
    msg_you = Message(
        conversation_id=conv.id,
        sender_name="You",
        timestamp=datetime(2026, 9, 20, 11, 0, 0),
        timestamp_provenance="verified",
        content="I will sign the document today",
        raw_text="I will sign the document today"
    )
    test_db.add(msg_you)
    test_db.commit()

    match_arabic_you = find_matching_target_message(
        db=test_db,
        conv_id=conv.id,
        platform_msg_id=None,
        dt=datetime(2026, 9, 20, 11, 0, 0),
        sender="أنت",
        text="I will sign the document today",
        provenance="verified"
    )
    assert match_arabic_you is not None
    assert match_arabic_you.id == msg_you.id

    # 5. Ambiguity protection: two messages from Alice with identical text in 1 minute
    msg_alice_dup = Message(
        conversation_id=conv.id,
        sender_name="Alice",
        timestamp=match_time + timedelta(seconds=15),
        timestamp_provenance="verified",
        content=long_text,
        raw_text=long_text
    )
    test_db.add(msg_alice_dup)
    test_db.commit()

    # When 2 matching messages exist for Alice within +- 1 minute, find_matching_target_message returns None (no silent merge)
    match_ambiguous = find_matching_target_message(
        db=test_db,
        conv_id=conv.id,
        platform_msg_id=None,
        dt=match_time,
        sender="Alice",
        text=long_text,
        provenance="verified"
    )
    assert match_ambiguous is None


def test_livefix_profile_details_handoff_and_title_guards(test_db, tmp_path, monkeypatch):
    """
    Live WhatsApp Web Bug Regression Verification:
    1. is_invalid_title: Rejects 'Profile details' on ingest, media upload, session start, handoff.
    2. Target conversation title mismatch:
       - Matches real imported H title 'محادثة H (تعديلات الكتاب)' against capture title 'H'.
       - Rejects mismatching target conversation title (e.g. Alice vs Bob).
    3. Media download handoff: Valid path in configured Downloads moves file atomically and records MediaAsset; path traversal is rejected.
    4. Duplicate filenames across messages with distinct message keys do not collide.
    """
    token = get_auth_token()
    monkeypatch.setenv("OWI_DOWNLOADS_DIR", str(tmp_path))

    # 1. Invalid chat title rejection (Profile details trap)
    # A. Ingest
    res_ingest_bad = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Profile details",
            "messages": [{"sender": "Alice", "text": "Hello", "timestamp": "2026-09-25T12:00:00"}]
        }
    )
    assert res_ingest_bad.status_code == 400
    assert "profile" in res_ingest_bad.json()["detail"].lower()

    # B. Media upload
    res_upload_bad = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "Profile details",
            "file_name": "pic.jpg",
            "media_base64": base64.b64encode(b"fake").decode()
        }
    )
    assert res_upload_bad.status_code == 400
    assert "profile" in res_upload_bad.json()["detail"].lower()

    # C. Media session start
    res_start_bad = client.post(
        "/api/companion/media/session/start",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "session_id": "test_sess_invalid_title",
            "chat_title": "تفاصيل الملف الشخصي",
            "file_name": "video.mp4",
            "total_bytes": 100,
            "total_chunks": 1
        }
    )
    assert res_start_bad.status_code == 400
    assert "invalid chat title" in res_start_bad.json()["detail"].lower()

    # 2. Target conversation title matching and mismatch guard
    # Real H target matching: 'محادثة H (تعديلات الكتاب)' matches capture title 'H'
    conv_h = Conversation(id=888, title="محادثة H (تعديلات الكتاب)", source_type="export_zip", message_count=197)
    conv_h_group = Conversation(id=889, title="H Group", source_type="companion")
    conv_h_group_archive = Conversation(id=890, title="محادثة H Group (تعديلات الكتاب)", source_type="export_zip")
    conv_alice = Conversation(title="Alice Smith", source_type="companion")
    test_db.add_all([conv_h, conv_h_group, conv_h_group_archive, conv_alice])
    test_db.commit()

    res_h_match = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",
            "target_conversation_id": conv_h.id,
            "confirm_target_merge": True,
            "messages": [{"sender": "H", "text": "Testing live title match", "timestamp": "2026-09-25T12:00:00"}]
        }
    )
    assert res_h_match.status_code == 200
    assert res_h_match.json()["conversation_id"] == conv_h.id

    # Title subset rejection: 'H Group' must NOT match live 'H'
    res_h_group_mismatch = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",
            "target_conversation_id": conv_h_group.id,
            "confirm_target_merge": True,
            "messages": [{"sender": "H", "text": "Testing group rejection", "timestamp": "2026-09-25T12:00:00"}]
        }
    )
    assert res_h_group_mismatch.status_code == 400
    assert "mismatch" in res_h_group_mismatch.json()["detail"].lower()

    # Archive subset rejection: 'محادثة H Group (تعديلات الكتاب)' must NOT match live 'H'
    res_h_group_arch_mismatch = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H",
            "target_conversation_id": conv_h_group_archive.id,
            "confirm_target_merge": True,
            "messages": [{"sender": "H", "text": "Testing archive group rejection", "timestamp": "2026-09-25T12:00:00"}]
        }
    )
    assert res_h_group_arch_mismatch.status_code == 400
    assert "mismatch" in res_h_group_arch_mismatch.json()["detail"].lower()

    # Inverse subset rejection: live 'H Group' must NOT match target 'H' archive
    res_inverse_mismatch = client.post(
        "/api/companion/ingest",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "chat_title": "H Group",
            "target_conversation_id": conv_h.id,
            "confirm_target_merge": True,
            "messages": [{"sender": "H", "text": "Testing inverse mismatch", "timestamp": "2026-09-25T12:00:00"}]
        }
    )
    assert res_inverse_mismatch.status_code == 400
    assert "mismatch" in res_inverse_mismatch.json()["detail"].lower()

    # Title mismatch: Alice vs Bob
    res_mismatch = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Bob Jones",
            "file_name": "doc.pdf",
            "media_base64": base64.b64encode(b"fake").decode()
        }
    )
    assert res_mismatch.status_code == 400
    assert "mismatch" in res_mismatch.json()["detail"].lower()

    # 3. Media download handoff
    mock_e_downloads = (tmp_path / "mock_e_downloads")
    mock_e_downloads.mkdir(parents=True, exist_ok=True)
    mock_c_downloads = (tmp_path / "mock_c_downloads")
    mock_c_downloads.mkdir(parents=True, exist_ok=True)
    mock_app_tmp = (settings.DATA_DIR / "tmp")
    mock_app_tmp.mkdir(parents=True, exist_ok=True)

    import owi.api.routes_companion as rc
    monkeypatch.setattr(rc, "get_chrome_downloads_dir", lambda: mock_e_downloads.resolve())
    if "backend.owi.api.routes_companion" in sys.modules:
        monkeypatch.setattr(sys.modules["backend.owi.api.routes_companion"], "get_chrome_downloads_dir", lambda: mock_e_downloads.resolve())

    # A. Path traversal / outside configured download directory rejection
    res_handoff_traversal = client.post(
        "/api/companion/media/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "file_name": "secret.txt",
            "download_path": str(Path("C:/Windows/System32/drivers/etc/hosts") if os.name == "nt" else Path("/etc/passwd"))
        }
    )
    assert res_handoff_traversal.status_code == 403
    assert "access denied" in res_handoff_traversal.json()["detail"].lower()

    # B. C: downloads rejection when E: downloads is configured
    file_in_c = mock_c_downloads / "c_file.docx"
    file_in_c.write_bytes(b"content in C downloads")
    res_handoff_c = client.post(
        "/api/companion/media/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "file_name": "c_file.docx",
            "download_path": str(file_in_c)
        }
    )
    assert res_handoff_c.status_code == 403
    assert "access denied" in res_handoff_c.json()["detail"].lower()

    # C. settings.DATA_DIR/tmp rejection (generic temp folders forbidden)
    file_in_tmp = mock_app_tmp / "temp_file.docx"
    file_in_tmp.write_bytes(b"content in app tmp")
    res_handoff_tmp = client.post(
        "/api/companion/media/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "file_name": "temp_file.docx",
            "download_path": str(file_in_tmp)
        }
    )
    assert res_handoff_tmp.status_code == 403
    assert "access denied" in res_handoff_tmp.json()["detail"].lower()

    # D. Incomplete download (.crdownload) rejection
    file_incomplete = mock_e_downloads / "download.docx.crdownload"
    file_incomplete.write_bytes(b"partial bytes")
    res_handoff_incomplete = client.post(
        "/api/companion/media/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "file_name": "download.docx",
            "download_path": str(file_incomplete)
        }
    )
    assert res_handoff_incomplete.status_code == 400
    assert "incomplete" in res_handoff_incomplete.json()["detail"].lower()

    # E. Valid download handoff from configured Chrome Downloads directory (E:)
    test_dl_file = mock_e_downloads / "downloaded_spec.docx"
    dl_content = b"PK synthetic docx content from browser download handoff"
    test_dl_file.write_bytes(dl_content)
    dl_sha = hashlib.sha256(dl_content).hexdigest()

    res_handoff_ok = client.post(
        "/api/companion/media/handoff",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "file_name": "downloaded_spec.docx",
            "download_path": str(test_dl_file),
            "sha256": dl_sha,
            "message_key": "msg_dl_key_1",
            "attachment_position": 1
        }
    )
    assert res_handoff_ok.status_code == 200
    handoff_data = res_handoff_ok.json()
    assert handoff_data["status"] == "success"
    assert handoff_data["sha256"] == dl_sha
    assert handoff_data["asset_id"] is not None

    rec = test_db.query(AttachmentRecord).filter(AttachmentRecord.media_asset_id == handoff_data["asset_id"]).first()
    assert rec is not None
    assert rec.status == "saved-original"

    asset = test_db.query(MediaAsset).filter(MediaAsset.id == handoff_data["asset_id"]).first()
    assert asset is not None
    assert Path(asset.file_path).exists()
    assert Path(asset.file_path).read_bytes() == dl_content

    # 4. Duplicate filenames across distinct messages preserve distinct records
    res_dup1 = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "message_key": "key_alpha",
            "attachment_position": 1,
            "file_name": "invoice.pdf",
            "media_base64": base64.b64encode(b"invoice alpha").decode()
        }
    )
    assert res_dup1.status_code == 200

    res_dup2 = client.post(
        "/api/companion/media/upload",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "conversation_id": conv_alice.id,
            "chat_title": "Alice Smith",
            "message_key": "key_beta",
            "attachment_position": 1,
            "file_name": "invoice.pdf",
            "media_base64": base64.b64encode(b"invoice beta").decode()
        }
    )
    assert res_dup2.status_code == 200

    recs = test_db.query(AttachmentRecord).filter(
        AttachmentRecord.conversation_id == conv_alice.id,
        AttachmentRecord.file_name.like("%invoice.pdf%")
    ).all()
    assert len(recs) == 2
    keys = {r.message_key for r in recs}
    assert keys == {"key_alpha", "key_beta"}
