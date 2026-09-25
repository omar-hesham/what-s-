"""
Messages and Media Streaming API routes.
Includes streaming file serving, authenticated attachments, background local processing,
and durable asset state inspection.
"""

import hashlib
import secrets
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.core.security import sanitize_filename, verify_session_or_token
from owi.core.queue import enqueue_media_processing, job_queue
from owi.db.database import get_db
from owi.db.models import Message, MediaAsset, Transcript, DocumentRecord, AttachmentRecord
from owi.db.migrations import sync_message_fts
from owi.ingest.whatsapp_parser import detect_attachment_type
from owi.pipeline.audio import AudioTranscriber
from owi.pipeline.ocr import ImageAnalyzer
from owi.pipeline.document import DocumentProcessor
from owi.pipeline.video import VideoProcessor

router = APIRouter(tags=["Messages & Media"])

@router.get("/api/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    message_type: Optional[str] = Query(None, description="Filter: text, voice, image, video, document"),
    sender: Optional[str] = Query(None),
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Retrieve chronological messages with associated media assets, transcripts, and documents."""
    q = db.query(Message).filter(Message.conversation_id == conversation_id)
    if message_type:
        q = q.filter(Message.message_type == message_type)
    if sender:
        q = q.filter(Message.sender_name == sender)

    messages = q.order_by(Message.timestamp.asc()).offset(offset).limit(limit).all()

    res = []
    for m in messages:
        assets_data = []
        for a in m.media_assets:
            transcript_info = None
            if a.transcript:
                transcript_info = {
                    "id": a.transcript.id,
                    "language": a.transcript.language_detected,
                    "full_text": a.transcript.full_text,
                    "duration": a.transcript.duration_seconds,
                    "model_used": a.transcript.model_used,
                    "segments": [
                        {
                            "start": s.start_time,
                            "end": s.end_time,
                            "text": s.text,
                            "speaker": s.speaker
                        }
                        for s in a.transcript.segments
                    ]
                }

            doc_info = None
            if a.document_record:
                doc_info = {
                    "id": a.document_record.id,
                    "title": a.document_record.title,
                    "doc_type": a.document_record.doc_type,
                    "page_count": a.document_record.page_count,
                    "extracted_text": a.document_record.extracted_text[:400]
                }

            assets_data.append({
                "id": a.id,
                "file_name": a.file_name,
                "file_type": a.file_type,
                "file_size": a.file_size,
                "sha256": a.sha256_hash,
                "sha256_hash": a.sha256_hash,
                "duration_seconds": a.duration_seconds,
                "width": a.width,
                "height": a.height,
                "processing_status": a.processing_status or "unprocessed",
                "processing_error": a.processing_error,
                "processing_attempts": a.processing_attempts or 0,
                "processing_method": a.processing_method,
                "processed_at": a.processed_at.isoformat() if a.processed_at else None,
                "transcript": transcript_info,
                "document": doc_info
            })

        att_records_data = []
        for att in m.attachment_records:
            att_records_data.append({
                "id": att.id,
                "file_name": att.file_name,
                "file_type": att.file_type,
                "mime_type": att.mime_type,
                "file_size": att.file_size,
                "status": att.status,
                "reason": att.reason,
                "media_asset_id": att.media_asset_id,
                "sha256": att.sha256_hash,
                "sha256_hash": att.sha256_hash
            })

        res.append({
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender_name": m.sender_name,
            "timestamp": m.timestamp.isoformat(),
            "content": m.content,
            "message_type": m.message_type,
            "has_attachment": m.has_attachment,
            "attachment_name": m.attachment_name,
            "attachment_status": m.attachment_status,
            "source_index": m.source_index,
            "media_assets": assets_data,
            "attachments": att_records_data
        })
    return res

@router.get("/api/media/{media_asset_id}/file")
def get_media_file(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Serve physical media file (audio, image, video, document) with local streaming support."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    p = Path(asset.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Physical file missing from storage: {p.name}")

    return FileResponse(
        path=p,
        filename=asset.file_name,
        media_type=asset.mime_type
    )

@router.post("/api/messages/{message_id}/attach")
async def attach_media_to_message(
    message_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """
    Attach a physical media file (voice note, image, video, document) to a message.
    Streams upload in bounded chunks (max 100MB) without loading whole file in RAM.
    Computes SHA256 checksum on the fly and enqueues local processing.
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    safe_name = sanitize_filename(file.filename or "attachment")
    media_type = detect_attachment_type(safe_name)
    dest_sub = "documents"
    if media_type == "voice":
        dest_sub = "audio"
    elif media_type == "image":
        dest_sub = "images"
    elif media_type == "video":
        dest_sub = "video"

    temp_dir = settings.DATA_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_filename = f"upload_{msg.conversation_id}_{msg.id}_{secrets.token_hex(8)}.tmp"
    temp_path = temp_dir / temp_filename

    hasher = hashlib.sha256()
    total_bytes = 0
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB limit

    try:
        with open(temp_path, "wb") as f:
            while chunk := await file.read(65536):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Attachment size exceeds 100MB maximum limit."
                    )
                hasher.update(chunk)
                f.write(chunk)
    except HTTPException:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to save attachment: {e}")

    if total_bytes == 0:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file content")

    file_hash = hasher.hexdigest()

    # Content-addressed, collision-resistant destination filename
    stored_name = f"{msg.conversation_id}_{msg.id}_{file_hash[:12]}_{safe_name}"
    media_dir = settings.DATA_DIR / "media" / dest_sub
    media_dir.mkdir(parents=True, exist_ok=True)
    dest_path = media_dir / stored_name

    # Atomic move from temp to permanent storage
    try:
        shutil.move(str(temp_path), str(dest_path))
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Failed to finalize attachment storage: {e}")

    asset = MediaAsset(
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        file_name=safe_name,
        file_path=str(dest_path),
        file_type=media_type,
        file_size=total_bytes,
        mime_type=file.content_type,
        sha256_hash=file_hash,
        processing_status="unprocessed"
    )
    db.add(asset)
    msg.has_attachment = True
    msg.attachment_name = safe_name
    msg.attachment_status = "saved-original"
    if msg.message_type == "text" or not msg.message_type:
        msg.message_type = media_type

    # Create or update durable AttachmentRecord keyed by (conversation_id, message_id, sha256_hash)
    att_rec = db.query(AttachmentRecord).filter(
        AttachmentRecord.conversation_id == msg.conversation_id,
        AttachmentRecord.message_id == msg.id,
        AttachmentRecord.sha256_hash == file_hash
    ).first()
    if not att_rec:
        att_rec = AttachmentRecord(
            conversation_id=msg.conversation_id,
            message_id=msg.id,
            file_name=safe_name,
            file_type=media_type,
            mime_type=file.content_type,
            file_size=total_bytes,
            sha256_hash=file_hash,
            status="saved-original"
        )
        db.add(att_rec)
    else:
        att_rec.status = "saved-original"
        att_rec.file_name = safe_name
        att_rec.file_size = total_bytes
        att_rec.mime_type = file.content_type

    db.commit()
    db.refresh(asset)
    att_rec.media_asset_id = asset.id
    db.commit()

    # Enqueue background local processing idempotently
    job_id = enqueue_media_processing(asset.id, db=db)

    return {
        "status": "attached",
        "asset_id": asset.id,
        "message_id": msg.id,
        "file_name": safe_name,
        "file_type": media_type,
        "file_size": total_bytes,
        "sha256": file_hash,
        "sha256_hash": file_hash,
        "job_id": job_id,
        "processing_status": asset.processing_status
    }

@router.post("/api/media/{media_asset_id}/process")
def process_media_asset_endpoint(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Trigger background or immediate local processing for a media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    job_id = enqueue_media_processing(media_asset_id, force_retry=False, db=db)
    return {"status": asset.processing_status or "queued", "media_asset_id": media_asset_id, "job_id": job_id}

@router.get("/api/media/{media_asset_id}/status")
def get_media_asset_status(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Get durable processing status and provenance for a media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    return {
        "id": asset.id,
        "file_name": asset.file_name,
        "file_type": asset.file_type,
        "sha256": asset.sha256_hash,
        "sha256_hash": asset.sha256_hash,
        "processing_status": asset.processing_status or "unprocessed",
        "processing_error": asset.processing_error,
        "processing_attempts": asset.processing_attempts or 0,
        "processing_method": asset.processing_method,
        "processed_at": asset.processed_at.isoformat() if asset.processed_at else None,
        "duration_seconds": asset.duration_seconds,
        "has_transcript": bool(asset.transcript),
        "has_document": bool(asset.document_record)
    }

@router.post("/api/media/{media_asset_id}/retry")
def retry_media_asset_processing(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Reset error and re-enqueue processing for a failed, setup_needed, or completed asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    job_id = enqueue_media_processing(media_asset_id, force_retry=True, db=db)
    return {"status": "re-queued", "media_asset_id": media_asset_id, "job_id": job_id}

@router.post("/api/media/{media_asset_id}/transcribe")
def transcribe_media_asset(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Trigger or re-run transcription on an audio asset."""
    try:
        res = AudioTranscriber.transcribe(media_asset_id, db)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/media/{media_asset_id}/analyze")
def analyze_media_asset(
    media_asset_id: int,
    db: Session = Depends(get_db),
    user_auth: bool = Depends(verify_session_or_token)
):
    """Run local pipeline analysis (OCR, document extraction, speech transcription) on an asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    p = Path(asset.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Physical file missing")

    f_type = (asset.file_type or "").lower()
    if f_type in ("image", "photo"):
        res = ImageAnalyzer.analyze_image(media_asset_id, db)
    elif f_type in ("document", "doc"):
        res = DocumentProcessor.process_document(media_asset_id, db)
    elif f_type in ("voice", "audio"):
        res = AudioTranscriber.transcribe(media_asset_id, db)
    elif f_type in ("video",):
        res = VideoProcessor.process_video(media_asset_id, db)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for analysis: {asset.file_type}")

    return {"status": "success", "result": res}
