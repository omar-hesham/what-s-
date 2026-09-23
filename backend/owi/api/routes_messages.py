"""
Messages and Media Streaming API routes.
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from owi.db.database import get_db
from owi.db.models import Message, MediaAsset, Transcript, DocumentRecord

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
