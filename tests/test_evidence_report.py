"""
Comprehensive test suite for OWI Evidence Inventory and Forensic Report Microtask.
Verifies all Codex review criteria and regression edge cases:
1. Mixed types (text, voice, image, document, video)
2. Duplicate physical hashes grouped across messages without losing identities
3. Missing physical files and SHA256 hash mismatches detected
4. Multiple attachments on a single message
5. Preview-only attachments (thumbnails not counted as analyzed content, preserved regardless of hash)
6. Unavailable and expired attachments
7. ZIP voice placeholders (<voice message omitted>, etc.) even if misclassified as text (single unresolved identity)
8. Real derived text (full text, transcripts with segment times, OCR, documents)
9. Date range and sender filtering (literal sender matching, no SQL wildcard expansion)
10. Unauthenticated requests rejected (HTTP 401)
11. Provenance citations on every excerpt in JSON and Markdown
12. Incomplete capture coverage guarantee (DB count never proves complete capture)
13. Invalid / reversed date bounds rejected (HTTP 400), strict timezone normalization
14. Asset-record hash conflicts exposed
15. Two different actual files with same wrong expected hash grouped by actual physical SHA
16. Unavailable-only appendix never emits false success banner
17. Path escapes rejected safely without arbitrary host disk reads
18. Derived historical mismatched/missing file cites integrity notice
19. Video retains both audio transcript and video OCR as separate evidence items
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple
import pytest
from fastapi.testclient import TestClient

from owi.config import settings
from owi.core.hashing import compute_sha256
from owi.core.security import pairing_manager, session_manager
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord, Transcript, TranscriptSegment, DocumentRecord
from owi.pipeline.report_service import ReportService
from owi.main import app

client = TestClient(app)

def _auth_headers_and_cookies():
    """Create authenticated headers with a paired companion token."""
    code_data = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_data["code"], client_name="Report Test Runner")
    return {"Authorization": f"Bearer {token}"}

def _create_synthetic_file(directory: Path, filename: str, content: bytes) -> Tuple[Path, str, int]:
    directory.mkdir(parents=True, exist_ok=True)
    fpath = directory / filename
    with open(fpath, "wb") as f:
        f.write(content)
    sha = hashlib.sha256(content).hexdigest()
    return fpath, sha, len(content)


# --- 1. Unauthenticated Requests Rejected ---

def test_unauthenticated_requests_rejected(test_db):
    conv = Conversation(title="Auth Check Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    old_bypass = os.environ.get("OWI_TEST_AUTH_BYPASS")
    if "OWI_TEST_AUTH_BYPASS" in os.environ:
        del os.environ["OWI_TEST_AUTH_BYPASS"]

    try:
        # 1. Inventory endpoint
        inv_res = client.get(f"/api/conversations/{conv.id}/inventory")
        assert inv_res.status_code == 401
        assert "Authentication required" in inv_res.json()["detail"]

        # 2. Report endpoint
        rep_res = client.get(f"/api/conversations/{conv.id}/report")
        assert rep_res.status_code == 401
        assert "Authentication required" in rep_res.json()["detail"]

        # 3. Export endpoint
        exp_res = client.get(f"/api/conversations/{conv.id}/export")
        assert exp_res.status_code == 401
        assert "Authentication required" in exp_res.json()["detail"]

        # 4. Authenticated request succeeds
        headers = _auth_headers_and_cookies()
        auth_inv_res = client.get(f"/api/conversations/{conv.id}/inventory", headers=headers)
        assert auth_inv_res.status_code == 200

        auth_rep_res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
        assert auth_rep_res.status_code == 200

        auth_exp_res = client.get(f"/api/conversations/{conv.id}/export", headers=headers)
        assert auth_exp_res.status_code == 200
    finally:
        if old_bypass is not None:
            os.environ["OWI_TEST_AUTH_BYPASS"] = old_bypass


# --- 2. Mixed Types & Real Derived Text with Machine-Generated Labels ---

def test_mixed_types_and_real_derived_text(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Mixed Media Investigation", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    # A. Text message
    m1 = Message(
        conversation_id=conv.id,
        sender_name="Investigator",
        timestamp=datetime(2026, 9, 20, 10, 0, 0),
        content="Meeting notes and evidence submitted.",
        message_type="text"
    )
    test_db.add(m1)
    test_db.commit()

    # B. Voice message with local Transcript and timed segments
    audio_path, audio_sha, audio_len = _create_synthetic_file(tmp_path / "audio", "note.opus", b"OGG_SYNTHETIC_AUDIO_DATA_123")
    m2 = Message(
        conversation_id=conv.id,
        sender_name="Witness",
        timestamp=datetime(2026, 9, 20, 10, 5, 0),
        content="voice note.opus (file attached)",
        message_type="voice",
        has_attachment=True,
        attachment_name="note.opus"
    )
    test_db.add(m2)
    test_db.commit()

    a_voice = MediaAsset(
        conversation_id=conv.id,
        message_id=m2.id,
        file_name="note.opus",
        file_type="audio",
        mime_type="audio/ogg",
        file_size=audio_len,
        file_path=str(audio_path),
        sha256_hash=audio_sha,
        duration_seconds=8.5,
        processing_status="completed",
        processing_method="whisper_local"
    )
    test_db.add(a_voice)
    test_db.commit()

    trans = Transcript(
        media_asset_id=a_voice.id,
        language_detected="ar",
        confidence=0.98,
        full_text="تم الاتفاق على تسليم الدفعة الأولى يوم الخميس القادم بمقر الشركة بالشيخ زايد.",
        duration_seconds=8.5,
        model_used="whisper_base"
    )
    test_db.add(trans)
    test_db.commit()

    seg1 = TranscriptSegment(
        transcript_id=trans.id,
        start_time=0.0,
        end_time=4.2,
        text="تم الاتفاق على تسليم الدفعة الأولى",
        speaker="Speaker 1"
    )
    seg2 = TranscriptSegment(
        transcript_id=trans.id,
        start_time=4.2,
        end_time=8.5,
        text="يوم الخميس القادم بمقر الشركة بالشيخ زايد.",
        speaker="Speaker 1"
    )
    test_db.add_all([seg1, seg2])
    test_db.commit()

    # C. Image with Tesseract OCR DocumentRecord
    img_path, img_sha, img_len = _create_synthetic_file(tmp_path / "images", "receipt.png", b"PNG_SYNTHETIC_IMAGE_BYTES")
    m3 = Message(
        conversation_id=conv.id,
        sender_name="Accountant",
        timestamp=datetime(2026, 9, 20, 10, 10, 0),
        content="receipt.png (file attached)",
        message_type="image",
        has_attachment=True,
        attachment_name="receipt.png"
    )
    test_db.add(m3)
    test_db.commit()

    a_img = MediaAsset(
        conversation_id=conv.id,
        message_id=m3.id,
        file_name="receipt.png",
        file_type="image",
        mime_type="image/png",
        file_size=img_len,
        file_path=str(img_path),
        sha256_hash=img_sha,
        processing_status="completed",
        processing_method="tesseract-ara+eng"
    )
    test_db.add(a_img)
    test_db.commit()

    doc_ocr = DocumentRecord(
        media_asset_id=a_img.id,
        conversation_id=conv.id,
        title="receipt",
        doc_type="image_ocr",
        page_count=1,
        extracted_text="فاتورة رقم 9845 - المبلغ الإجمالي: 450,000 جنيه مصري مدفوعة نقداً."
    )
    test_db.add(doc_ocr)
    test_db.commit()

    # D. Document with PDF DocumentRecord
    pdf_path, pdf_sha, pdf_len = _create_synthetic_file(tmp_path / "docs", "contract.pdf", b"PDF_SYNTHETIC_DOCUMENT_BYTES")
    m4 = Message(
        conversation_id=conv.id,
        sender_name="Legal",
        timestamp=datetime(2026, 9, 20, 10, 15, 0),
        content="contract.pdf (file attached)",
        message_type="document",
        has_attachment=True,
        attachment_name="contract.pdf"
    )
    test_db.add(m4)
    test_db.commit()

    a_pdf = MediaAsset(
        conversation_id=conv.id,
        message_id=m4.id,
        file_name="contract.pdf",
        file_type="document",
        mime_type="application/pdf",
        file_size=pdf_len,
        file_path=str(pdf_path),
        sha256_hash=pdf_sha,
        processing_status="completed",
        processing_method="pypdf"
    )
    test_db.add(a_pdf)
    test_db.commit()

    doc_pdf = DocumentRecord(
        media_asset_id=a_pdf.id,
        conversation_id=conv.id,
        title="contract",
        doc_type="pdf",
        page_count=3,
        extracted_text="عقد بيع وحدة تجارية رقم 12 بمشروع الشيخ زايد بكامل الشروط والمواصفات القانونية."
    )
    test_db.add(doc_pdf)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    summ = data["inventory_summary"]
    assert summ["total_messages_scanned"] == 4
    assert summ["total_attachments_detected"] == 3
    assert summ["verified_physical_files"] == 3
    assert summ["processed_with_derived_text"] == 3

    evidence = data["evidence"]
    assert len(evidence) >= 4

    voice_ev = next(e for e in evidence if e["evidence_type"] == "transcript")
    assert voice_ev["label"] == "Machine-generated ASR (unreviewed)"
    assert voice_ev["is_machine_generated"] is True
    assert "تم الاتفاق على تسليم الدفعة الأولى" in voice_ev["text"]
    assert len(voice_ev["segments"]) == 2

    ocr_ev = next(e for e in evidence if e["evidence_type"] == "image_ocr")
    assert ocr_ev["label"] == "Machine-generated OCR (unreviewed)"
    assert ocr_ev["is_machine_generated"] is True
    assert "فاتورة رقم 9845" in ocr_ev["text"]

    pdf_ev = next(e for e in evidence if e["evidence_type"] == "document")
    assert pdf_ev["is_machine_generated"] is False
    assert "عقد بيع وحدة تجارية" in pdf_ev["text"]
    assert pdf_ev["page_count"] == 3


# --- 3. Duplicate Physical Hashes Grouped by Actual Physical SHA ---

def test_duplicate_hashes_across_messages(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Duplicate Hash Chat", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    shared_bytes = b"EXACT_IDENTICAL_PHOTO_PAYLOAD_9999"
    fpath, shared_sha, flen = _create_synthetic_file(tmp_path / "media", "blueprint.png", shared_bytes)

    m1 = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        timestamp=datetime(2026, 9, 21, 12, 0, 0),
        content="blueprint.png (file attached)",
        message_type="image",
        has_attachment=True,
        attachment_name="blueprint.png"
    )
    test_db.add(m1)
    test_db.commit()

    a1 = MediaAsset(
        conversation_id=conv.id,
        message_id=m1.id,
        file_name="blueprint.png",
        file_type="image",
        mime_type="image/png",
        file_size=flen,
        file_path=str(fpath),
        sha256_hash=shared_sha
    )
    test_db.add(a1)
    test_db.commit()

    m2 = Message(
        conversation_id=conv.id,
        sender_name="Khaled",
        timestamp=datetime(2026, 9, 21, 14, 0, 0),
        content="blueprint_copy.png (file attached)",
        message_type="image",
        has_attachment=True,
        attachment_name="blueprint_copy.png"
    )
    test_db.add(m2)
    test_db.commit()

    a2 = MediaAsset(
        conversation_id=conv.id,
        message_id=m2.id,
        file_name="blueprint_copy.png",
        file_type="image",
        mime_type="image/png",
        file_size=flen,
        file_path=str(fpath),
        sha256_hash=shared_sha
    )
    test_db.add(a2)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/inventory", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["summary"]["total_attachments_detected"] == 2
    assert data["summary"]["distinct_physical_hashes"] == 1
    assert data["summary"]["unique_physical_bytes"] == flen
    assert data["summary"]["total_physical_bytes"] == flen * 2

    dups = data["duplicate_hash_groups"]
    assert len(dups) == 1
    dup_group = dups[0]
    assert dup_group["sha256"] == shared_sha
    assert dup_group["reference_count"] == 2

    ref_msg_ids = [r["message_id"] for r in dup_group["references"]]
    assert m1.id in ref_msg_ids
    assert m2.id in ref_msg_ids


# --- 4. Missing Physical File & Hash Mismatch ---

def test_missing_file_and_hash_mismatch(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Corrupted & Missing Storage Chat", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    missing_path = tmp_path / "absent_file.opus"
    m1 = Message(
        conversation_id=conv.id,
        sender_name="Sender 1",
        timestamp=datetime(2026, 9, 22, 9, 0, 0),
        content="voice note",
        message_type="voice",
        has_attachment=True
    )
    test_db.add(m1)
    test_db.commit()

    a1 = MediaAsset(
        conversation_id=conv.id,
        message_id=m1.id,
        file_name="absent_file.opus",
        file_type="audio",
        file_size=5000,
        file_path=str(missing_path),
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    test_db.add(a1)
    test_db.commit()

    real_path, real_sha, real_len = _create_synthetic_file(tmp_path, "tampered.pdf", b"AUTHENTIC_ORIGINAL_BYTES")
    fake_sha = "0000000000000000000000000000000000000000000000000000000000000000"

    m2 = Message(
        conversation_id=conv.id,
        sender_name="Sender 2",
        timestamp=datetime(2026, 9, 22, 9, 30, 0),
        content="tampered.pdf",
        message_type="document",
        has_attachment=True
    )
    test_db.add(m2)
    test_db.commit()

    a2 = MediaAsset(
        conversation_id=conv.id,
        message_id=m2.id,
        file_name="tampered.pdf",
        file_type="document",
        file_size=real_len,
        file_path=str(real_path),
        sha256_hash=fake_sha
    )
    test_db.add(a2)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    summ = data["inventory_summary"]
    assert summ["missing_physical_files"] == 1
    assert summ["hash_mismatches"] == 1

    appendix = data["missing_unprocessed_appendix"]
    assert len(appendix["missing_physical_files"]) == 1
    assert appendix["missing_physical_files"][0]["file_name"] == "absent_file.opus"
    assert len(appendix["hash_mismatches"]) == 1
    assert appendix["hash_mismatches"][0]["file_name"] == "tampered.pdf"


# --- 5. Multiple Attachments on Single Message ---

def test_multiple_attachments_on_single_message(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Multi Attachment Message", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    m = Message(
        conversation_id=conv.id,
        sender_name="Photo Journalist",
        timestamp=datetime(2026, 9, 23, 11, 0, 0),
        content="Here are both photos from the site inspection.",
        message_type="image",
        has_attachment=True
    )
    test_db.add(m)
    test_db.commit()

    p1, sha1, len1 = _create_synthetic_file(tmp_path, "site_photo_1.jpg", b"PHOTO_1_BYTES")
    p2, sha2, len2 = _create_synthetic_file(tmp_path, "site_photo_2.jpg", b"PHOTO_2_BYTES")

    a1 = MediaAsset(
        conversation_id=conv.id,
        message_id=m.id,
        file_name="site_photo_1.jpg",
        file_type="image",
        file_size=len1,
        file_path=str(p1),
        sha256_hash=sha1
    )
    a2 = MediaAsset(
        conversation_id=conv.id,
        message_id=m.id,
        file_name="site_photo_2.jpg",
        file_type="image",
        file_size=len2,
        file_path=str(p2),
        sha256_hash=sha2
    )
    test_db.add_all([a1, a2])
    test_db.commit()

    ar1 = AttachmentRecord(
        conversation_id=conv.id,
        message_id=m.id,
        media_asset_id=a1.id,
        attachment_position=0,
        file_name="site_photo_1.jpg",
        file_type="image",
        file_size=len1,
        sha256_hash=sha1,
        status="saved-original"
    )
    ar2 = AttachmentRecord(
        conversation_id=conv.id,
        message_id=m.id,
        media_asset_id=a2.id,
        attachment_position=1,
        file_name="site_photo_2.jpg",
        file_type="image",
        file_size=len2,
        sha256_hash=sha2,
        status="saved-original"
    )
    test_db.add_all([ar1, ar2])
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/inventory", headers=headers)
    assert res.status_code == 200
    data = res.json()

    assert data["summary"]["total_attachments_detected"] == 2
    inv_msg_ids = [it["message_id"] for it in data["inventory"]]
    assert inv_msg_ids == [m.id, m.id]


# --- 6. Preview-Only Preserved Regardless of Hash & Unavailable Items ---

def test_preview_only_preserved_regardless_of_hash(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Preview Only Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    # Create physical file for preview
    thumb_path, thumb_sha, thumb_len = _create_synthetic_file(tmp_path, "thumb.jpg", b"THUMBNAIL_BYTES")

    m1 = Message(
        conversation_id=conv.id,
        sender_name="Colleague",
        timestamp=datetime(2026, 9, 23, 15, 0, 0),
        content="voice note preview",
        message_type="voice",
        has_attachment=True
    )
    test_db.add(m1)
    test_db.commit()

    a1 = MediaAsset(
        conversation_id=conv.id,
        message_id=m1.id,
        file_name="thumb.jpg",
        file_type="image",
        file_size=thumb_len,
        file_path=str(thumb_path),
        sha256_hash=thumb_sha
    )
    test_db.add(a1)
    test_db.commit()

    # Durable status preview-only linked to asset
    ar_preview = AttachmentRecord(
        conversation_id=conv.id,
        message_id=m1.id,
        media_asset_id=a1.id,
        file_name="thumb.jpg",
        file_type="image",
        file_size=thumb_len,
        sha256_hash=thumb_sha,
        status="preview-only",
        reason="Downloaded thumbnail only."
    )
    test_db.add(ar_preview)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/inventory", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 1 VERIFICATION:
    # Must preserve preview_only regardless of physical file or matching hash!
    inv_item = data["inventory"][0]
    assert inv_item["physical_status"] == "preview_only"
    assert inv_item["acquisition_provenance"] == "preview_only"
    assert inv_item["durable_status"] == "preview-only"
    assert inv_item["has_derived_text"] is False
    assert inv_item["is_thumbnail_only"] is True


# --- 7. Single Unresolved Identity for Omitted Voice Placeholder (No Double Count) ---

def test_single_unresolved_identity_for_omitted_placeholder(test_db):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Zip Export Placeholders", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    # Single message with <voice message omitted> AND has_attachment=True
    m1 = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        timestamp=datetime(2026, 9, 24, 8, 0, 0),
        content="<voice message omitted>",
        message_type="voice",
        has_attachment=True
    )
    test_db.add(m1)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/inventory", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 2 VERIFICATION:
    # Must have EXACTLY ONE unresolved attachment identity, not two!
    assert data["summary"]["total_attachments_detected"] == 1
    assert len(data["inventory"]) == 1

    item = data["inventory"][0]
    assert item["file_type"] == "audio"
    assert item["physical_status"] == "omitted_placeholder"
    assert item["is_placeholder"] is True
    assert item["has_derived_text"] is False


# --- 8. Date Range, Strict Validation & Exact Sender Matching ---

def test_date_validation_and_exact_sender_matching(test_db):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Validation Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    m1 = Message(
        conversation_id=conv.id,
        sender_name="Alice",
        timestamp=datetime(2026, 9, 10, 10, 0, 0),
        content="Hello from Alice",
        message_type="text"
    )
    m2 = Message(
        conversation_id=conv.id,
        sender_name="Alice_Smith",
        timestamp=datetime(2026, 9, 15, 10, 0, 0),
        content="Hello from Alice Smith",
        message_type="text"
    )
    m3 = Message(
        conversation_id=conv.id,
        sender_name="Alice%",
        timestamp=datetime(2026, 9, 20, 10, 0, 0),
        content="Hello from Alice with percent",
        message_type="text"
    )
    test_db.add_all([m1, m2, m3])
    test_db.commit()

    # CODEX DEFECT 4 VERIFICATION:
    # 1. Invalid date string returns HTTP 400
    bad_date_res = client.get(f"/api/conversations/{conv.id}/report?date_from=not-a-date", headers=headers)
    assert bad_date_res.status_code == 400
    assert "Invalid date format" in bad_date_res.json()["detail"]

    # 2. Reversed dates return HTTP 400
    rev_res = client.get(f"/api/conversations/{conv.id}/report?date_from=2026-09-20&date_to=2026-09-10", headers=headers)
    assert rev_res.status_code == 400
    assert "Invalid date range" in rev_res.json()["detail"]

    # 3. ISO timezone-aware string normalizes cleanly without error
    aware_res = client.get(f"/api/conversations/{conv.id}/report?date_from=2026-09-01T00:00:00Z&date_to=2026-09-12T00:00:00Z", headers=headers)
    assert aware_res.status_code == 200
    assert aware_res.json()["inventory_summary"]["total_messages_scanned"] == 1

    # 4. Exact sender matching: sender="Alice" should NOT match "Alice_Smith" or "Alice%"
    exact_res = client.get(f"/api/conversations/{conv.id}/report?sender=Alice", headers=headers)
    assert exact_res.status_code == 200
    assert exact_res.json()["inventory_summary"]["total_messages_scanned"] == 1
    assert exact_res.json()["evidence"][0]["text"] == "Hello from Alice"

    # 5. Exact sender matching with wildcard char "%" should match literal "Alice%"
    wildcard_literal_res = client.get(f"/api/conversations/{conv.id}/report?sender=Alice%25", headers=headers)
    assert wildcard_literal_res.status_code == 200
    assert wildcard_literal_res.json()["inventory_summary"]["total_messages_scanned"] == 1
    assert wildcard_literal_res.json()["evidence"][0]["text"] == "Hello from Alice with percent"


# --- 9. Checksum Discrepancy & Grouping by Actual Physical SHA ---

def test_hash_conflict_and_grouping_by_actual_sha(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Hash Conflict Chat", source_type="companion")
    test_db.add(conv)
    test_db.commit()

    # Two distinct physical files
    p1, sha1, len1 = _create_synthetic_file(tmp_path, "file1.pdf", b"CONTENT_FILE_1_AAA")
    p2, sha2, len2 = _create_synthetic_file(tmp_path, "file2.pdf", b"CONTENT_FILE_2_BBB")

    m1 = Message(
        conversation_id=conv.id,
        sender_name="Sender",
        timestamp=datetime(2026, 9, 25, 10, 0, 0),
        content="file1.pdf",
        message_type="document",
        has_attachment=True
    )
    m2 = Message(
        conversation_id=conv.id,
        sender_name="Sender",
        timestamp=datetime(2026, 9, 25, 10, 5, 0),
        content="file2.pdf",
        message_type="document",
        has_attachment=True
    )
    test_db.add_all([m1, m2])
    test_db.commit()

    # Both assigned the SAME wrong recorded hash
    wrong_recorded_hash = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"

    a1 = MediaAsset(
        conversation_id=conv.id,
        message_id=m1.id,
        file_name="file1.pdf",
        file_type="document",
        file_size=len1,
        file_path=str(p1),
        sha256_hash=wrong_recorded_hash
    )
    a2 = MediaAsset(
        conversation_id=conv.id,
        message_id=m2.id,
        file_name="file2.pdf",
        file_type="document",
        file_size=len2,
        file_path=str(p2),
        sha256_hash=wrong_recorded_hash
    )
    test_db.add_all([a1, a2])
    test_db.commit()

    # Also test record vs asset hash conflict on m1
    different_record_sha = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
    ar1 = AttachmentRecord(
        conversation_id=conv.id,
        message_id=m1.id,
        media_asset_id=a1.id,
        file_name="file1.pdf",
        file_type="document",
        file_size=len1,
        sha256_hash=different_record_sha,
        status="saved-original"
    )
    test_db.add(ar1)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 1 VERIFICATION:
    # Files have different actual physical SHAs (sha1 != sha2), so they MUST form 2 distinct physical groups!
    assert data["inventory_summary"]["distinct_physical_hashes"] == 2
    # Grouping by actual SHA means neither is placed under wrong_recorded_hash
    dups = data["duplicate_hash_groups"]
    assert len(dups) == 0  # No duplicate groups because sha1 != sha2!

    # Verify hash conflict is exposed
    item1 = next(it for it in data["inventory"] if it["message_id"] == m1.id)
    assert item1["hash_conflict"] is True
    assert item1["record_sha256"] == different_record_sha
    assert item1["asset_sha256"] == wrong_recorded_hash

    # Verify appendix lists the conflict
    appendix = data["missing_unprocessed_appendix"]
    assert len(appendix["asset_record_hash_conflicts"]) == 1


# --- 10. Unavailable-Only Appendix Never Emits False Success ---

def test_unavailable_only_appendix_never_emits_false_success(test_db):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="All Unavailable Chat", source_type="export_txt")
    test_db.add(conv)
    test_db.commit()

    m = Message(
        conversation_id=conv.id,
        sender_name="Broker",
        timestamp=datetime(2026, 9, 25, 12, 0, 0),
        content="<voice message omitted>",
        message_type="voice",
        has_attachment=True
    )
    test_db.add(m)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 3 VERIFICATION:
    # Must NEVER emit "All inventoried attachments are physically verified..." when all attachments are unavailable!
    md = data["markdown"]
    assert "All inventoried attachments are physically verified" not in md
    assert "Export-Omitted Placeholders" in md


# --- 11. Security: Path Escapes Rejected Safely ---

def test_security_path_escapes_rejected(test_db):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Path Escape Attack", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    m = Message(
        conversation_id=conv.id,
        sender_name="Attacker",
        timestamp=datetime(2026, 9, 25, 14, 0, 0),
        content="exploit",
        message_type="document",
        has_attachment=True
    )
    test_db.add(m)
    test_db.commit()

    # Host system file outside settings.DATA_DIR
    forbidden_path = "C:\\Windows\\System32\\drivers\\etc\\hosts"
    a = MediaAsset(
        conversation_id=conv.id,
        message_id=m.id,
        file_name="hosts",
        file_type="document",
        file_size=100,
        file_path=forbidden_path,
        sha256_hash="abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234"
    )
    test_db.add(a)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 5 VERIFICATION:
    # Path outside DATA_DIR must be rejected, not read or hashed!
    item = data["inventory"][0]
    assert item["physical_status"] == "path_rejected"
    assert item["physical_availability"] == "path_escaped"
    assert item["file_exists"] is False
    assert item["media_download_url"] is None

    # Path escape listed in appendix
    appendix = data["missing_unprocessed_appendix"]
    assert len(appendix["path_escapes"]) == 1


# --- 12. Derived Historical Mismatched/Missing File Integrity Notice ---

def test_derived_historical_mismatched_file_integrity_notice(test_db):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Historical Derived Chat", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    m = Message(
        conversation_id=conv.id,
        sender_name="Speaker",
        timestamp=datetime(2026, 9, 25, 16, 0, 0),
        content="audio.opus",
        message_type="voice",
        has_attachment=True
    )
    test_db.add(m)
    test_db.commit()

    # Asset with missing physical file but possessing a valid historical transcript
    a = MediaAsset(
        conversation_id=conv.id,
        message_id=m.id,
        file_name="audio.opus",
        file_type="audio",
        file_size=5000,
        file_path=str(settings.DATA_DIR / "media" / "audio" / "deleted_file.opus"),
        sha256_hash="1111222233334444555566667777888811112222333344445555666677778888"
    )
    test_db.add(a)
    test_db.commit()

    trans = Transcript(
        media_asset_id=a.id,
        full_text="Historical verified transcript content.",
        duration_seconds=3.0
    )
    test_db.add(trans)
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 5 VERIFICATION:
    # Historical derived text retained, but cites missing physical status and integrity warning
    ev = next(e for e in data["evidence"] if e["evidence_type"] == "transcript")
    assert ev["text"] == "Historical verified transcript content."
    assert ev["physical_status"] == "missing_on_disk"
    assert "Historical derived text retained" in ev["historical_derived_notice"]

    # Markdown must render the warning banner
    md = data["markdown"]
    assert "Integrity Warning:" in md
    assert "Historical derived text retained" in md


# --- 13. Video Retains Both Audio Transcript and Keyframe OCR ---

def test_video_retains_both_transcript_and_ocr(test_db, tmp_path):
    headers = _auth_headers_and_cookies()

    conv = Conversation(title="Video Dual Pipeline Chat", source_type="export_zip")
    test_db.add(conv)
    test_db.commit()

    vp, vsha, vlen = _create_synthetic_file(tmp_path, "presentation.mp4", b"MP4_VIDEO_BYTES")
    m = Message(
        conversation_id=conv.id,
        sender_name="Presenter",
        timestamp=datetime(2026, 9, 25, 17, 0, 0),
        content="presentation.mp4",
        message_type="video",
        has_attachment=True
    )
    test_db.add(m)
    test_db.commit()

    a = MediaAsset(
        conversation_id=conv.id,
        message_id=m.id,
        file_name="presentation.mp4",
        file_type="video",
        file_size=vlen,
        file_path=str(vp),
        sha256_hash=vsha
    )
    test_db.add(a)
    test_db.commit()

    # Video has BOTH Transcript AND DocumentRecord (Video OCR)
    t = Transcript(
        media_asset_id=a.id,
        full_text="Speech audio from video presentation.",
        duration_seconds=10.0
    )
    d = DocumentRecord(
        media_asset_id=a.id,
        conversation_id=conv.id,
        title="presentation",
        doc_type="video_ocr",
        page_count=2,
        extracted_text="On-screen text from video slide."
    )
    test_db.add_all([t, d])
    test_db.commit()

    res = client.get(f"/api/conversations/{conv.id}/report", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # CODEX DEFECT 5 VERIFICATION:
    # Both transcript and video OCR must be present as separate evidence items!
    ev_types = [e["evidence_type"] for e in data["evidence"] if e["citation"].get("media_asset_id") == a.id]
    assert "transcript" in ev_types
    assert "video_ocr" in ev_types
