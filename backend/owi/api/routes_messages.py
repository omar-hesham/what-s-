"""
Messages and Media Streaming API routes.
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.core.security import sanitize_filename
from owi.core.hashing import compute_sha256
from owi.db.database import get_db
from owi.db.models import Message, MediaAsset, Transcript, DocumentRecord
from owi.db.migrations import sync_message_fts
from owi.ingest.whatsapp_parser import detect_attachment_type
from owi.pipeline.audio import AudioTranscriber
from owi.ai.gemini_service import GeminiService

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
                "duration_seconds": a.duration_seconds,
                "width": a.width,
                "height": a.height,
                "transcript": transcript_info,
                "document": doc_info
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
            "source_index": m.source_index,
            "media_assets": assets_data
        })
    return res

@router.get("/api/media/{media_asset_id}/file")
def get_media_file(media_asset_id: int, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
):
    """Attach a physical media file (voice note, image, document) to a message."""
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file content")

    safe_name = sanitize_filename(file.filename or "attachment")
    media_type = detect_attachment_type(safe_name)
    dest_sub = "documents"
    if media_type == "voice":
        dest_sub = "audio"
    elif media_type == "image":
        dest_sub = "images"
    elif media_type == "video":
        dest_sub = "video"

    stored_name = f"{msg.conversation_id}_{msg.id}_{safe_name}"
    dest_path = settings.DATA_DIR / "media" / dest_sub / stored_name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(content)

    file_hash = compute_sha256(dest_path)
    asset = MediaAsset(
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        file_name=safe_name,
        file_path=str(dest_path),
        file_type=media_type,
        file_size=len(content),
        mime_type=file.content_type,
        sha256=file_hash
    )
    db.add(asset)
    msg.has_attachment = True
    msg.attachment_name = safe_name
    if msg.message_type == "text" or not msg.message_type:
        msg.message_type = media_type
    db.commit()
    db.refresh(asset)

    # Automatically transcribe voice notes
    transcript_result = None
    if media_type == "voice":
        try:
            transcript_result = AudioTranscriber.transcribe(asset.id, db)
            if transcript_result.get("full_text"):
                msg.content = transcript_result["full_text"]
                sync_message_fts(db.connection(), msg.id, msg.content, msg.sender_name or "")
                db.commit()
        except Exception as e:
            logger.warning(f"Voice auto-transcription notice: {e}")

    # Automatically analyze images with Gemini if available
    image_analysis = None
    if media_type == "image" and GeminiService.is_configured():
        try:
            image_res = GeminiService.analyze_image(dest_path)
            if image_res.get("success") and image_res.get("text"):
                image_analysis = image_res["text"]
                # Append OCR/analysis to message content for full searchability
                if not msg.content or "<" in msg.content or "[" in msg.content:
                    msg.content = f"[{safe_name}]\n{image_analysis}"
                else:
                    msg.content += f"\n\n[تحليل الصورة]:\n{image_analysis}"
                sync_message_fts(db.connection(), msg.id, msg.content, msg.sender_name or "")
                db.commit()
        except Exception as e:
            logger.warning(f"Image auto-analysis notice: {e}")

    return {
        "status": "attached",
        "asset_id": asset.id,
        "message_id": msg.id,
        "file_name": safe_name,
        "file_type": media_type,
        "file_size": len(content),
        "transcript": transcript_result,
        "image_analysis": image_analysis
    }

@router.post("/api/media/{media_asset_id}/transcribe")
def transcribe_media_asset(media_asset_id: int, db: Session = Depends(get_db)):
    """Trigger or re-run transcription on an audio asset."""
    try:
        res = AudioTranscriber.transcribe(media_asset_id, db)
        return {"status": "success", "result": res}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/media/{media_asset_id}/analyze")
def analyze_media_asset(media_asset_id: int, db: Session = Depends(get_db)):
    """Run multimodal analysis (OCR, summary) on an image or document asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    p = Path(asset.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Physical file missing")

    if not GeminiService.is_configured():
        raise HTTPException(status_code=400, detail="Gemini API is not configured.")

    if asset.file_type == "image":
        res = GeminiService.analyze_image(p)
    elif asset.file_type == "document":
        res = GeminiService.analyze_document(p)
    elif asset.file_type == "voice":
        res = GeminiService.transcribe_audio(p)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type for analysis: {asset.file_type}")

    if not res.get("success"):
        raise HTTPException(status_code=500, detail=res.get("error", "Analysis failed"))

    # If linked to a message, update message content and FTS
    if asset.message_id and res.get("text"):
        msg = db.query(Message).filter(Message.id == asset.message_id).first()
        if msg:
            msg.content = (msg.content or "") + f"\n\n[تحليل {asset.file_name}]:\n{res['text']}"
            sync_message_fts(db.connection(), msg.id, msg.content, msg.sender_name or "")
            db.commit()

    return {"status": "success", "result": res}
