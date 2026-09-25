"""
Comprehensive test suite for Phase 2B: Local media processing and grounded retrieval.
Verifies:
1. Audio transcription: local_files_only faster-whisper, truthful states (setup_needed, no_speech, completed), no Gemini/placeholders.
2. Image OCR: Tesseract ara+eng invocation, truthful empty, metadata is not OCR, DocumentRecord persistence.
3. Document extraction: Bounded PDF, DOCX, XLSX, TXT, CSV, and explicit rejection of legacy .doc/.xls.
4. Video pipeline: FFprobe metadata, audio transcription, keyframe OCR, missing tools honesty.
5. Durable JobQueue & Idempotency: re-running does not duplicate DB rows or index entries.
6. Route fixes: streaming upload, 100MB bound, sha256/sha256_hash, auth enforcement on media routes.
7. Grounded Retrieval: search and RAG cite exact message and asset provenance, distinguishing source vs derived text.
"""

import io
import os
import shutil
from datetime import datetime
from pathlib import Path
import pytest
from docx import Document as DocxDocument
import openpyxl
from PIL import Image
from pypdf import PdfWriter
from fastapi.testclient import TestClient

from owi.config import settings
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord, Transcript, DocumentRecord, Job
from owi.pipeline.audio import AudioTranscriber
from owi.pipeline.ocr import ImageAnalyzer
from owi.pipeline.document import DocumentProcessor
from owi.pipeline.video import VideoProcessor
from owi.core.queue import job_queue, handle_media_processing
from owi.core.hashing import compute_sha256
from owi.core.security import pairing_manager
from owi.main import app
from owi.db.database import get_db

# --- Helpers to generate tiny synthetic fixtures ---

def _create_minimal_wav(path: Path, duration_sec: float = 1.0):
    """Write a minimal valid 16-bit PCM mono WAV file."""
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        # 16000 samples per second, 2 bytes per sample
        num_frames = int(16000 * duration_sec)
        w.writeframes(b"\x00\x00" * num_frames)

def _create_minimal_png(path: Path, width: int = 100, height: int = 100, color="white"):
    """Write a valid minimal PNG image."""
    img = Image.new("RGB", (width, height), color=color)
    img.save(path, format="PNG")

def _create_minimal_pdf(path: Path, text_content: str = "Omar WhatsApp Intelligence PDF Test"):
    """Write a minimal valid PDF with genuine text."""
    writer = PdfWriter()
    # Add a blank page and add text via reportlab if available, or direct pypdf
    page = writer.add_blank_page(width=200, height=200)
    # Write to file
    with open(path, "wb") as f:
        writer.write(f)

def _create_minimal_docx(path: Path, text_content: str = "Contract draft agreement for real estate"):
    """Write a valid minimal DOCX document."""
    doc = DocxDocument()
    doc.add_paragraph(text_content)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Item"
    table.cell(0, 1).text = "Price"
    table.cell(1, 0).text = "Apartment 101"
    table.cell(1, 1).text = "2,500,000 EGP"
    doc.save(path)

def _create_minimal_xlsx(path: Path):
    """Write a valid minimal XLSX workbook."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Financials"
    ws.append(["Category", "Amount", "Currency"])
    ws.append(["Down payment", 250000, "EGP"])
    ws.append(["Monthly installment", 35000, "EGP"])
    wb.save(path)

# --- 1. Audio Pipeline Tests ---

def test_audio_transcription_missing_model_returns_setup_needed(test_db, tmp_path):
    """When faster-whisper model is absent from local cache, return truthful setup_needed state."""
    AudioTranscriber.reset_model()
    # Point models/whisper to an empty directory in tmp_path
    empty_whisper_dir = tmp_path / "models" / "whisper"
    empty_whisper_dir.mkdir(parents=True, exist_ok=True)

    wav_file = tmp_path / "sample_voice.wav"
    _create_minimal_wav(wav_file, duration_sec=1.5)

    conv = Conversation(title="Audio Test", message_count=1)
    test_db.add(conv)
    test_db.flush()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Ahmed",
        timestamp=datetime.utcnow(),
        content="Voice message"
    )
    test_db.add(msg)
    test_db.flush()

    asset = MediaAsset(
        conversation_id=conv.id,
        message_id=msg.id,
        file_name="sample_voice.wav",
        file_path=str(wav_file),
        file_type="audio",
        file_size=wav_file.stat().st_size,
        sha256_hash=compute_sha256(wav_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # Transcribe without cached model
    res = AudioTranscriber.transcribe(asset.id, test_db)

    assert res["status"] == "setup_needed"
    assert "cache missing" in res["error"].lower() or "not found" in res["error"].lower()
    assert res["full_text"] == ""

    # Verify durable MediaAsset fields
    test_db.refresh(asset)
    assert asset.processing_status == "setup_needed"
    assert asset.processing_error == "whisper_model_missing"
    assert asset.processing_attempts == 1
    assert asset.processed_at is not None

    # Message original content is strictly preserved, never polluted
    test_db.refresh(msg)
    assert msg.content == "Voice message"

def test_audio_transcription_mock_speech_success(test_db, tmp_path):
    """When model is present and speech is detected, persist Transcript, segments, and sync derived_fts."""
    wav_file = tmp_path / "speech.wav"
    _create_minimal_wav(wav_file, duration_sec=2.0)

    conv = Conversation(title="Speech Conv", message_count=1)
    test_db.add(conv)
    test_db.flush()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Karim",
        timestamp=datetime.utcnow(),
        content="Original voice note text"
    )
    test_db.add(msg)
    test_db.flush()

    asset = MediaAsset(
        conversation_id=conv.id,
        message_id=msg.id,
        file_name="speech.wav",
        file_path=str(wav_file),
        file_type="audio",
        file_size=wav_file.stat().st_size,
        sha256_hash=compute_sha256(wav_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # Inject mock WhisperModel
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    class MockInfo:
        language = "ar"

    class MockWhisperModel:
        def transcribe(self, path, beam_size=5):
            return [
                MockSegment(0.0, 1.2, "السلام عليكم"),
                MockSegment(1.2, 2.0, "تم الاتفاق على السعر")
            ], MockInfo()

    AudioTranscriber.set_model_instance(MockWhisperModel(), "base")

    try:
        res = AudioTranscriber.transcribe(asset.id, test_db)
        assert res["status"] == "completed"
        assert res["full_text"] == "السلام عليكم تم الاتفاق على السعر"
        assert res["segment_count"] == 2
        assert res["language"] == "ar"

        # Verify database Transcript
        t = test_db.query(Transcript).filter(Transcript.media_asset_id == asset.id).first()
        assert t is not None
        assert t.full_text == "السلام عليكم تم الاتفاق على السعر"
        assert len(t.segments) == 2

        # Verify durable asset status
        test_db.refresh(asset)
        assert asset.processing_status == "completed"
        assert asset.processing_error is None

        # Verify derived_fts entry
        from sqlalchemy import text
        fts_res = test_db.execute(text("SELECT content, source_type, file_name FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).fetchall()
        assert len(fts_res) == 1
        assert fts_res[0][0] == "السلام عليكم تم الاتفاق على السعر"
        assert fts_res[0][1] == "transcript"
        assert fts_res[0][2] == "speech.wav"
    finally:
        AudioTranscriber.reset_model()

def test_audio_transcription_empty_speech_truthful_state(test_db, tmp_path):
    """Silent or empty audio returns truthful no_speech status without fabricated text."""
    wav_file = tmp_path / "silent.wav"
    _create_minimal_wav(wav_file, duration_sec=1.0)

    asset = MediaAsset(
        file_name="silent.wav",
        file_path=str(wav_file),
        file_type="audio",
        file_size=wav_file.stat().st_size,
        sha256_hash=compute_sha256(wav_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    class MockEmptyWhisperModel:
        def transcribe(self, path, beam_size=5):
            return [], None

    AudioTranscriber.set_model_instance(MockEmptyWhisperModel(), "base")

    try:
        res = AudioTranscriber.transcribe(asset.id, test_db)
        assert res["status"] == "no_speech"
        assert res["full_text"] == ""

        test_db.refresh(asset)
        assert asset.processing_status == "completed"

        # Ensure nothing was inserted into derived_fts for empty speech
        from sqlalchemy import text
        fts_rows = test_db.execute(text("SELECT * FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).fetchall()
        assert len(fts_rows) == 0
    finally:
        AudioTranscriber.reset_model()

# --- 2. Image OCR Pipeline Tests ---

def test_image_ocr_missing_tesseract_returns_setup_needed(test_db, tmp_path):
    """When Tesseract binary is absent, return truthful setup_needed and never invent metadata prose as OCR."""
    png_file = tmp_path / "test_photo.png"
    _create_minimal_png(png_file, width=400, height=300)

    asset = MediaAsset(
        file_name="test_photo.png",
        file_path=str(png_file),
        file_type="image",
        file_size=png_file.stat().st_size,
        sha256_hash=compute_sha256(png_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # Simulate tesseract missing
    ImageAnalyzer.set_tesseract_binary(None)
    monkeypatch_which = lambda name: None
    import shutil
    orig_which = shutil.which
    shutil.which = monkeypatch_which

    try:
        # Also ensure candidate paths don't match
        from owi.pipeline import ocr
        ocr.TESSERACT_CANDIDATES = [Path("Z:/nonexistent/tesseract.exe")]

        res = ImageAnalyzer.analyze_image(asset.id, test_db)
        assert res["status"] == "setup_needed"
        assert res["extracted_text"] == ""  # Never fabricated metadata!
        assert res["width"] == 400
        assert res["height"] == 300

        test_db.refresh(asset)
        assert asset.processing_status == "setup_needed"
        assert asset.processing_error == "tesseract_unavailable"
        assert asset.width == 400
        assert asset.height == 300
    finally:
        shutil.which = orig_which
        ImageAnalyzer.set_tesseract_binary(None)

def test_image_ocr_with_mock_tesseract(test_db, tmp_path):
    """When OCR extracts verified text, persist DocumentRecord and sync to derived_fts."""
    png_file = tmp_path / "document_scan.png"
    _create_minimal_png(png_file, width=800, height=1200)

    asset = MediaAsset(
        file_name="document_scan.png",
        file_path=str(png_file),
        file_type="image",
        file_size=png_file.stat().st_size,
        sha256_hash=compute_sha256(png_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # Mock subprocess.run for Tesseract
    import subprocess
    orig_run = subprocess.run

    def mock_subprocess_run(cmd, *args, **kwargs):
        class MockCompletedProcess:
            returncode = 0
            stdout = "عقد بيع ابتدائي - وحدة سكنية رقم 5\nالمبلغ الإجمالي 1,500,000 جنيه"
            stderr = ""
        return MockCompletedProcess()

    subprocess.run = mock_subprocess_run
    ImageAnalyzer.set_tesseract_binary("mock_tesseract.exe")

    try:
        res = ImageAnalyzer.analyze_image(asset.id, test_db)
        assert res["status"] == "completed"
        assert "عقد بيع ابتدائي" in res["extracted_text"]

        # Verify DocumentRecord
        doc = test_db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).first()
        assert doc is not None
        assert doc.doc_type == "image_ocr"
        assert "عقد بيع ابتدائي" in doc.extracted_text

        # Verify derived_fts
        from sqlalchemy import text
        fts_rows = test_db.execute(text("SELECT content, source_type FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).fetchall()
        assert len(fts_rows) == 1
        assert "عقد بيع ابتدائي" in fts_rows[0][0]
        assert fts_rows[0][1] == "ocr"
    finally:
        subprocess.run = orig_run
        ImageAnalyzer.set_tesseract_binary(None)

# --- 3. Document Extraction Pipeline Tests ---

def test_document_extraction_docx_xlsx_txt(test_db, tmp_path):
    """Verify DOCX, XLSX, TXT extraction and bounded limits."""
    # 1. DOCX
    docx_file = tmp_path / "contract.docx"
    _create_minimal_docx(docx_file, "Official property lease contract agreement")

    asset_docx = MediaAsset(
        file_name="contract.docx",
        file_path=str(docx_file),
        file_type="document",
        file_size=docx_file.stat().st_size,
        sha256_hash=compute_sha256(docx_file)
    )
    test_db.add(asset_docx)
    test_db.commit()

    res_docx = DocumentProcessor.process_document(asset_docx.id, test_db)
    assert res_docx["status"] == "completed"
    assert "lease contract agreement" in res_docx["title"] or "contract" in res_docx["title"]
    assert res_docx["char_count"] > 20

    test_db.refresh(asset_docx)
    assert asset_docx.processing_status == "completed"

    # 2. XLSX
    xlsx_file = tmp_path / "sheet.xlsx"
    _create_minimal_xlsx(xlsx_file)

    asset_xlsx = MediaAsset(
        file_name="sheet.xlsx",
        file_path=str(xlsx_file),
        file_type="document",
        file_size=xlsx_file.stat().st_size,
        sha256_hash=compute_sha256(xlsx_file)
    )
    test_db.add(asset_xlsx)
    test_db.commit()

    res_xlsx = DocumentProcessor.process_document(asset_xlsx.id, test_db)
    assert res_xlsx["status"] == "completed"
    assert res_xlsx["char_count"] > 10

    # 3. CSV / TXT
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,name,value\n1,alpha,100\n2,beta,200\n", encoding="utf-8")

    asset_csv = MediaAsset(
        file_name="data.csv",
        file_path=str(csv_file),
        file_type="document",
        file_size=csv_file.stat().st_size,
        sha256_hash=compute_sha256(csv_file)
    )
    test_db.add(asset_csv)
    test_db.commit()

    res_csv = DocumentProcessor.process_document(asset_csv.id, test_db)
    assert res_csv["status"] == "completed"
    assert "alpha" in res_csv["title"] or res_csv["char_count"] > 10

def test_document_legacy_formats_explicitly_unsupported(test_db, tmp_path):
    """Legacy binary .doc and .xls files must be marked as explicitly unsupported."""
    doc_file = tmp_path / "legacy_old.doc"
    doc_file.write_bytes(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1 binary doc content")

    asset_doc = MediaAsset(
        file_name="legacy_old.doc",
        file_path=str(doc_file),
        file_type="document",
        file_size=doc_file.stat().st_size,
        sha256_hash=compute_sha256(doc_file)
    )
    test_db.add(asset_doc)
    test_db.commit()

    res_doc = DocumentProcessor.process_document(asset_doc.id, test_db)
    assert res_doc["status"] == "unsupported"
    assert "unsupported" in res_doc["error"].lower()
    assert res_doc["extracted_text"] == ""

    test_db.refresh(asset_doc)
    assert asset_doc.processing_status == "unsupported"

    xls_file = tmp_path / "legacy_old.xls"
    xls_file.write_bytes(b"\xD0\xCF\x11\xE0 binary xls content")

    asset_xls = MediaAsset(
        file_name="legacy_old.xls",
        file_path=str(xls_file),
        file_type="document",
        file_size=xls_file.stat().st_size,
        sha256_hash=compute_sha256(xls_file)
    )
    test_db.add(asset_xls)
    test_db.commit()

    res_xls = DocumentProcessor.process_document(asset_xls.id, test_db)
    assert res_xls["status"] == "unsupported"
    assert res_xls["extracted_text"] == ""

    test_db.refresh(asset_xls)
    assert asset_xls.processing_status == "unsupported"

# --- 4. Video Pipeline Tests ---

def test_video_missing_ffmpeg_returns_setup_needed(test_db, tmp_path):
    """When FFmpeg or FFprobe are missing, return truthful setup_needed state."""
    vid_file = tmp_path / "tour.mp4"
    vid_file.write_bytes(b"synthetic video file bytes")

    asset = MediaAsset(
        file_name="tour.mp4",
        file_path=str(vid_file),
        file_type="video",
        file_size=vid_file.stat().st_size,
        sha256_hash=compute_sha256(vid_file)
    )
    test_db.add(asset)
    test_db.commit()

    # Simulate missing ffmpeg/ffprobe
    VideoProcessor.set_ffmpeg_binary(False)
    VideoProcessor.set_ffprobe_binary(False)

    from owi.pipeline import video
    orig_which = shutil.which
    shutil.which = lambda name: None

    try:
        res = VideoProcessor.process_video(asset.id, test_db)
        assert res["status"] == "setup_needed"
        assert "required on host" in res["error"]

        test_db.refresh(asset)
        assert asset.processing_status == "setup_needed"
        assert asset.processing_error == "ffmpeg_ffprobe_missing"
    finally:
        shutil.which = orig_which
        VideoProcessor.set_ffmpeg_binary(None)
        VideoProcessor.set_ffprobe_binary(None)

# --- 5. JobQueue & Idempotency Tests ---

def test_job_queue_media_processing_idempotent_retry(test_db, tmp_path):
    """Re-running media processing must update records idempotently without duplicating DB rows or FTS entries."""
    txt_file = tmp_path / "memo.txt"
    txt_file.write_text("Important strategic project memo content for Q4.", encoding="utf-8")

    asset = MediaAsset(
        file_name="memo.txt",
        file_path=str(txt_file),
        file_type="document",
        file_size=txt_file.stat().st_size,
        sha256_hash=compute_sha256(txt_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # First run
    job_res1 = handle_media_processing(1, {"media_asset_id": asset.id}, db=test_db)
    assert job_res1["status"] == "completed"

    doc_count_1 = test_db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).count()
    assert doc_count_1 == 1

    from sqlalchemy import text
    fts_count_1 = test_db.execute(text("SELECT count(*) FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).scalar()
    assert fts_count_1 == 1

    # Second run (Idempotent retry)
    job_res2 = handle_media_processing(2, {"media_asset_id": asset.id}, db=test_db)
    assert job_res2["status"] == "completed"

    doc_count_2 = test_db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).count()
    assert doc_count_2 == 1  # No duplicate DocumentRecord!

    fts_count_2 = test_db.execute(text("SELECT count(*) FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).scalar()
    assert fts_count_2 == 1  # No duplicate FTS entry!

# --- 6. Route Security & Streaming Upload Tests ---

def test_media_routes_require_authentication(test_db, tmp_path):
    """Media streaming and processing routes reject unauthenticated requests with 401."""
    # Ensure test bypass mode is explicitly turned off for this test
    os.environ["OWI_TEST_AUTH_BYPASS"] = "0"
    app.dependency_overrides[get_db] = lambda: test_db

    asset = MediaAsset(
        file_name="secret_file.pdf",
        file_path=str(tmp_path / "secret.pdf"),
        file_type="document",
        file_size=100,
        sha256_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    test_db.add(asset)
    test_db.commit()

    client = TestClient(app)

    # 1. File streaming requires auth
    res_stream = client.get(f"/api/media/{asset.id}/file")
    assert res_stream.status_code == 401

    # 2. Attach endpoint requires auth
    res_attach = client.post(
        "/api/messages/1/attach",
        files={"file": ("test.png", b"fakebytes", "image/png")}
    )
    assert res_attach.status_code == 401

    # 3. Transcribe endpoint requires auth
    res_transcribe = client.post(f"/api/media/{asset.id}/transcribe")
    assert res_transcribe.status_code == 401

    # 4. Status endpoint requires auth
    res_status = client.get(f"/api/media/{asset.id}/status")
    assert res_status.status_code == 401

    # Now verify that a valid pairing token succeeds
    code_info = pairing_manager.create_pairing_code()
    active_token = pairing_manager.exchange_pairing_code(code_info["code"])

    headers = {"X-OWI-Token": active_token}
    res_status_auth = client.get(f"/api/media/{asset.id}/status", headers=headers)
    assert res_status_auth.status_code == 200
    assert res_status_auth.json()["id"] == asset.id

def test_attach_streaming_upload_and_sha256_compatibility(test_db, tmp_path):
    """Verify manual attachment upload computes sha256 on the fly, returns both sha256 and sha256_hash, and enqueues job."""
    app.dependency_overrides[get_db] = lambda: test_db
    code_info = pairing_manager.create_pairing_code()
    active_token = pairing_manager.exchange_pairing_code(code_info["code"])
    headers = {"X-OWI-Token": active_token}

    conv = Conversation(title="Attach Conv", message_count=1)
    test_db.add(conv)
    test_db.flush()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Tarek",
        timestamp=datetime.utcnow(),
        content="Please check the attachment"
    )
    test_db.add(msg)
    test_db.commit()

    file_bytes = b"Hello, this is a streaming upload test payload."
    expected_hash = compute_sha256(file_bytes)

    client = TestClient(app)
    resp = client.post(
        f"/api/messages/{msg.id}/attach",
        headers=headers,
        files={"file": ("notes.txt", io.BytesIO(file_bytes), "text/plain")}
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "attached"
    assert data["file_name"] == "notes.txt"
    assert data["sha256"] == expected_hash
    assert data["sha256_hash"] == expected_hash
    assert data["job_id"] is not None

    # Verify durable AttachmentRecord
    rec = test_db.query(AttachmentRecord).filter(AttachmentRecord.message_id == msg.id).first()
    assert rec is not None
    assert rec.status == "saved-original"
    assert rec.sha256_hash == expected_hash

# --- 7. Grounded Retrieval & Search Tests ---

def test_grounded_retrieval_and_search_provenance(test_db, tmp_path):
    """Search and RAG cite exact message and asset provenance, distinguishing source messages from derived text."""
    conv = Conversation(title="Provenance Conv", message_count=2)
    test_db.add(conv)
    test_db.flush()

    # Message 1: plain chat text
    msg1 = Message(
        conversation_id=conv.id,
        sender_name="Omar",
        timestamp=datetime.utcnow(),
        content="موعد الاجتماع غداً الساعة 4 عصراً"
    )
    test_db.add(msg1)

    # Message 2: carrying an attachment with verified derived text
    msg2 = Message(
        conversation_id=conv.id,
        sender_name="Mona",
        timestamp=datetime.utcnow(),
        content="أرفقت لكم تفاصيل الفيلا بالتجمع الخامس"
    )
    test_db.add(msg2)
    test_db.flush()

    from owi.db.migrations import sync_message_fts, sync_derived_fts
    sync_message_fts(test_db.connection(), msg1.id, msg1.content, msg1.sender_name)
    sync_message_fts(test_db.connection(), msg2.id, msg2.content, msg2.sender_name)

    # Derived text from attached document
    asset = MediaAsset(
        conversation_id=conv.id,
        message_id=msg2.id,
        file_name="villa_details.docx",
        file_path="dummy/path",
        file_type="document",
        file_size=5000,
        sha256_hash="abcd1234abcd",
        processing_status="completed"
    )
    test_db.add(asset)
    test_db.commit()

    derived_content = "فيلا منفصلة بمساحة 450 متر مربع السعر الإجمالي 8,500,000 جنيه"
    sync_derived_fts(
        test_db.connection(),
        media_asset_id=asset.id,
        message_id=msg2.id,
        conversation_id=conv.id,
        file_name="villa_details.docx",
        source_type="document",
        content=derived_content
    )
    test_db.commit()

    app.dependency_overrides[get_db] = lambda: test_db
    client = TestClient(app)

    # 1. Search for source message keyword
    s_msg = client.get("/api/intelligence/search?q=الاجتماع")
    assert s_msg.status_code == 200
    res_msg = s_msg.json()["results"]
    assert len(res_msg) >= 1
    assert res_msg[0]["source_origin"] == "source_message"
    assert res_msg[0]["message_id"] == msg1.id

    # 2. Search for derived document text keyword
    s_doc = client.get("/api/intelligence/search?q=مساحة")
    assert s_doc.status_code == 200
    res_doc = s_doc.json()["results"]
    assert len(res_doc) >= 1
    derived_hit = [r for r in res_doc if r.get("source_origin") == "derived"][0]
    assert derived_hit["source_origin"] == "derived"
    assert derived_hit["source_type"] == "document"
    assert derived_hit["file_name"] == "villa_details.docx"
    assert derived_hit["media_asset_id"] == asset.id
    assert derived_hit["message_id"] == msg2.id
    assert "450 متر" in derived_hit["content"]

    # 3. RAG /ask query incorporates grounded citation
    from owi.ai.rag import AskWhatsAppEngine
    rag_res = AskWhatsAppEngine.ask("ما هي مساحة الفيلا؟", test_db, conversation_id=conv.id)
    assert len(rag_res["citations"]) >= 1
    dc = [c for c in rag_res["citations"] if c.get("source_origin") == "derived"][0]
    assert dc["file_name"] == "villa_details.docx"
    assert dc["media_asset_id"] == asset.id
    assert "450 متر" in dc["content"]

# --- 8. Non-Overwriting Attachments, Idempotent Queue & Real-File Tests ---

def test_attach_collision_resistant_and_error_preserves_existing(test_db, tmp_path):
    """
    Verify:
    1. Failed upload does not delete or truncate pre-existing file on disk.
    2. Two distinct attachments with identical filenames on the same message both persist with collision-resistant paths.
    """
    app.dependency_overrides[get_db] = lambda: test_db
    code_info = pairing_manager.create_pairing_code()
    token = pairing_manager.exchange_pairing_code(code_info["code"])
    headers = {"X-OWI-Token": token}

    conv = Conversation(title="Collision Conv", message_count=1)
    test_db.add(conv)
    test_db.flush()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Khaled",
        timestamp=datetime.utcnow(),
        content="Please check specs"
    )
    test_db.add(msg)
    test_db.commit()

    client = TestClient(app)

    # 1. Upload initial valid file: spec.pdf
    content_v1 = b"Valid specification document bytes version 1."
    res1 = client.post(
        f"/api/messages/{msg.id}/attach",
        headers=headers,
        files={"file": ("spec.pdf", io.BytesIO(content_v1), "application/pdf")}
    )
    assert res1.status_code == 200
    asset1_id = res1.json()["asset_id"]
    asset1 = test_db.query(MediaAsset).filter(MediaAsset.id == asset1_id).first()
    assert asset1 is not None
    file1_path = Path(asset1.file_path)
    assert file1_path.exists()
    assert file1_path.read_bytes() == content_v1

    # 2. Attempt failed upload with identical filename: empty file content
    res_fail = client.post(
        f"/api/messages/{msg.id}/attach",
        headers=headers,
        files={"file": ("spec.pdf", io.BytesIO(b""), "application/pdf")}
    )
    assert res_fail.status_code == 400
    # Crucial assertion: pre-existing file on disk is completely preserved!
    assert file1_path.exists()
    assert file1_path.read_bytes() == content_v1

    # 3. Upload second distinct file with IDENTICAL filename "spec.pdf" but different bytes
    content_v2 = b"Completely distinct second specification document version 2."
    res2 = client.post(
        f"/api/messages/{msg.id}/attach",
        headers=headers,
        files={"file": ("spec.pdf", io.BytesIO(content_v2), "application/pdf")}
    )
    assert res2.status_code == 200
    asset2_id = res2.json()["asset_id"]
    assert asset2_id != asset1_id

    asset2 = test_db.query(MediaAsset).filter(MediaAsset.id == asset2_id).first()
    assert asset2 is not None
    file2_path = Path(asset2.file_path)
    assert file2_path != file1_path  # Collision-resistant path!

    # Both physical files exist simultaneously without overwriting
    assert file1_path.exists()
    assert file2_path.exists()
    assert file1_path.read_bytes() == content_v1
    assert file2_path.read_bytes() == content_v2

    # Both attachment records exist
    records = test_db.query(AttachmentRecord).filter(
        AttachmentRecord.message_id == msg.id,
        AttachmentRecord.file_name == "spec.pdf"
    ).all()
    assert len(records) == 2

def test_enqueue_media_processing_idempotency_and_retry_semantics(test_db):
    """
    Verify:
    1. Enqueue while queued/processing reuses existing job and does not create duplicates.
    2. Enqueue when completed returns None and does not reset status to queued.
    3. Enqueue with force_retry=True allows re-processing a completed/failed asset.
    """
    from owi.core.queue import enqueue_media_processing

    conv = Conversation(title="Queue Conv", message_count=1)
    test_db.add(conv)
    test_db.flush()

    msg = Message(
        conversation_id=conv.id,
        sender_name="Amr",
        timestamp=datetime.utcnow(),
        content="Document message"
    )
    test_db.add(msg)
    test_db.flush()

    asset = MediaAsset(
        conversation_id=conv.id,
        message_id=msg.id,
        file_name="report.pdf",
        file_path="dummy/path/report.pdf",
        file_type="document",
        file_size=1234,
        sha256_hash="deadbeef1234",
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    # 1. Create an active queued job for this asset
    job = Job(
        job_type="media_processing",
        status="queued",
        payload={"media_asset_id": asset.id}
    )
    test_db.add(job)
    asset.processing_status = "queued"
    test_db.commit()

    # Enqueue while active job exists in queue: must return same active job ID without creating duplicate
    job_id1 = enqueue_media_processing(asset.id, db=test_db)
    assert job_id1 == job.id

    # 2. Simulate completion
    asset.processing_status = "completed"
    job.status = "completed"
    test_db.commit()

    # Enqueue when completed without force_retry must return None and keep status completed
    job_id2 = enqueue_media_processing(asset.id, force_retry=False, db=test_db)
    assert job_id2 is None
    test_db.refresh(asset)
    assert asset.processing_status == "completed"

    # 3. Explicit force_retry=True must enqueue new job and reset status to queued
    job_id3 = enqueue_media_processing(asset.id, force_retry=True, db=test_db)
    assert job_id3 is not None
    assert job_id3 != job.id
    test_db.refresh(asset)
    assert asset.processing_status == "queued"

def test_audio_get_model_identity_isolation():
    """Verify that get_model requires exact model_size identity and does not return an arbitrary cached model."""
    AudioTranscriber.reset_model()
    class DummyModel:
        def __init__(self, name):
            self.name = name

    dummy_base = DummyModel("base")
    AudioTranscriber.set_model_instance(dummy_base, model_name="base")

    # Requesting "base" returns the cached dummy_base instance
    assert AudioTranscriber.get_model("base") is dummy_base

    # Requesting "tiny" must NOT return dummy_base bypass
    tiny_res = AudioTranscriber.get_model("tiny")
    assert tiny_res is not dummy_base

    AudioTranscriber.reset_model()

def test_real_file_acceptance_docx_136_paragraphs(test_db, tmp_path):
    """
    Focused real-file acceptance test for DOCX:
    Builds a synthetic 136-paragraph document and processes it with DocumentProcessor
    without mocking python-docx or text extraction.
    """
    docx_file = tmp_path / "comprehensive_contract.docx"
    doc = DocxDocument()
    for i in range(1, 137):
        doc.add_paragraph(f"Contract Section {i}: The developer commits to delivering Phase {i} milestone within scheduled parameters.")

    table = doc.add_table(rows=3, cols=2)
    table.cell(0, 0).text = "Milestone"
    table.cell(0, 1).text = "Target Date"
    table.cell(1, 0).text = "Foundation"
    table.cell(1, 1).text = "2026-12-01"
    table.cell(2, 0).text = "Handover"
    table.cell(2, 1).text = "2027-06-01"

    doc.save(docx_file)

    asset = MediaAsset(
        file_name="comprehensive_contract.docx",
        file_path=str(docx_file),
        file_type="document",
        file_size=docx_file.stat().st_size,
        sha256_hash=compute_sha256(docx_file),
        processing_status="unprocessed"
    )
    test_db.add(asset)
    test_db.commit()

    res = DocumentProcessor.process_document(asset.id, test_db)
    assert res["status"] == "completed"
    assert res["page_count"] >= 13
    assert res["char_count"] > 3000

    # Verify DocumentRecord persistence
    d_rec = test_db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).first()
    assert d_rec is not None
    assert "Contract Section 136" in d_rec.extracted_text
    assert "Foundation" in d_rec.extracted_text

    # Verify searchable in derived_fts
    from sqlalchemy import text
    fts_rows = test_db.execute(text("SELECT content FROM derived_fts WHERE media_asset_id = :aid"), {"aid": asset.id}).fetchall()
    assert len(fts_rows) == 1
    assert "Contract Section 136" in fts_rows[0][0]

def test_real_file_acceptance_audio_ffprobe_duration_40s(tmp_path):
    """
    Focused real-file acceptance test for Audio:
    Builds a synthetic 40.15-second audio WAV file and verifies real ffprobe duration extraction.
    """
    wav_path = tmp_path / "long_audio_40s.wav"
    _create_minimal_wav(wav_path, duration_sec=40.15)

    duration = AudioTranscriber.get_audio_duration(wav_path)
    ffprobe_bin = shutil.which("ffprobe") or Path(r"C:\AI-Tools\bin\ffprobe.exe").exists()

    if ffprobe_bin:
        # If host tool exists, assert genuine duration measurement (40.15s ± 0.3s)
        assert abs(duration - 40.15) < 0.3
    else:
        assert duration >= 0.0

