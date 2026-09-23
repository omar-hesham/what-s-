"""
Conversations API routes: listing, uploading, analyzing, and deleting.
"""

import shutil
import tempfile
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from owi.db.database import get_db
from owi.db.models import Conversation, Message, MediaAsset, Task, Property
from owi.db.migrations import sync_message_fts
from owi.ingest.whatsapp_parser import WhatsAppParser
from owi.ingest.zip_importer import ZipImporter
from owi.ai.local_nlp import LocalNLPEngine
from owi.templates.property_stone import PropertyStoneEngine
from owi.templates.research import ResearchEngine
from owi.core.hashing import compute_sha256
from owi.core.logging import logger

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])

@router.get("")
def list_conversations(
    skip: int = 0, 
    limit: int = 50, 
    db: Session = Depends(get_db)
):
    """List all imported conversations."""
    conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).offset(skip).limit(limit).all()
    res = []
    for c in conversations:
        res.append({
            "id": c.id,
            "title": c.title,
            "source_type": c.source_type,
            "message_count": c.message_count,
            "start_date": c.start_date.isoformat() if c.start_date else None,
            "end_date": c.end_date.isoformat() if c.end_date else None,
            "summary": c.summary,
            "created_at": c.created_at.isoformat() if c.created_at else None
        })
    return res

@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Get single conversation details and participants."""
    c = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Distinct participants
    senders = db.query(Message.sender_name).filter(
        Message.conversation_id == conversation_id,
        Message.sender_name.notin_(["System", "Unknown"])
    ).distinct().all()
    participants = [s[0] for s in senders]

    # Counts
    tasks_count = db.query(Task).filter(Task.conversation_id == conversation_id).count()
    properties_count = db.query(Property).filter(Property.conversation_id == conversation_id).count()

    return {
        "id": c.id,
        "title": c.title,
        "source_type": c.source_type,
        "message_count": c.message_count,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "summary": c.summary,
        "detailed_summary": c.detailed_summary,
        "participants": participants,
        "tasks_count": tasks_count,
        "properties_count": properties_count,
        "created_at": c.created_at.isoformat() if c.created_at else None
    }

@router.post("/import/text")
async def import_text_export(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    force_reimport: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Import a raw WhatsApp .txt chat export file."""
    content = await file.read()
    raw_text = content.decode("utf-8", errors="replace")
    
    parsed = WhatsAppParser.parse_chat_text(raw_text)
    if not parsed:
        raise HTTPException(status_code=400, detail="Could not parse any valid WhatsApp messages from file.")

    conv_title = title or Path(file.filename).stem.replace("WhatsApp Chat - ", "")
    text_hash = compute_sha256(content)

    existing = db.query(Conversation).filter(Conversation.source_hash == text_hash).first()
    if existing and not force_reimport:
        return {
            "status": "already_imported",
            "conversation_id": existing.id,
            "title": existing.title,
            "message_count": existing.message_count,
            "duplicate": True
        }

    conv = Conversation(
        title=conv_title,
        source_type="export_txt",
        source_hash=text_hash,
        start_date=parsed[0].timestamp if parsed else None,
        end_date=parsed[-1].timestamp if parsed else None,
        message_count=len(parsed)
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    for pmsg in parsed:
        m = Message(
            conversation_id=conv.id,
            sender_name=pmsg.sender_name,
            timestamp=pmsg.timestamp,
            content=pmsg.content,
            message_type=pmsg.message_type,
            raw_text=pmsg.raw_text,
            has_attachment=pmsg.has_attachment,
            attachment_name=pmsg.attachment_name,
            source_index=pmsg.source_index
        )
        db.add(m)
        db.flush()
        # Sync to SQLite FTS5 search
        sync_message_fts(db.connection(), m.id, m.content or "", m.sender_name or "")

    db.commit()

    # Automatically trigger NLP & domain extraction
    LocalNLPEngine.analyze_conversation(conv.id, db)
    PropertyStoneEngine.extract_from_conversation(conv.id, db)
    ResearchEngine.extract_from_conversation(conv.id, db)

    return {
        "status": "success",
        "conversation_id": conv.id,
        "title": conv.title,
        "messages_imported": len(parsed)
    }

@router.post("/import/zip")
async def import_zip_export(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Import a WhatsApp exported ZIP archive containing chat and media."""
    # Write to a safe temporary file
    temp_zip = Path(tempfile.mktemp(suffix=".zip"))
    try:
        with open(temp_zip, "wb") as f:
            while chunk := await file.read(65536):
                f.write(chunk)

        result = ZipImporter.import_zip(temp_zip, db, conversation_title=title)
        
        # Trigger analysis if imported
        if result.get("status") == "success" and "conversation_id" in result:
            cid = result["conversation_id"]
            LocalNLPEngine.analyze_conversation(cid, db)
            PropertyStoneEngine.extract_from_conversation(cid, db)
            ResearchEngine.extract_from_conversation(cid, db)

        return result
    finally:
        if temp_zip.exists():
            temp_zip.unlink(missing_ok=True)

@router.post("/{conversation_id}/analyze")
def trigger_analysis(conversation_id: int, db: Session = Depends(get_db)):
    """Run/re-run AI and domain knowledge extractions on a conversation."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    nlp_res = LocalNLPEngine.analyze_conversation(conversation_id, db)
    prop_res = PropertyStoneEngine.extract_from_conversation(conversation_id, db)
    res_res = ResearchEngine.extract_from_conversation(conversation_id, db)

    return {
        "status": "completed",
        "conversation_id": conversation_id,
        "nlp": nlp_res,
        "property_extracted": prop_res is not None,
        "research_items_extracted": len(res_res)
    }

@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Delete a conversation, all its derived records, and associated media files."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Clean up SQLite FTS5 records
    msg_ids = [m[0] for m in db.query(Message.id).filter(Message.conversation_id == conversation_id).all()]
    if msg_ids:
        try:
            for i in range(0, len(msg_ids), 500):
                batch = msg_ids[i:i + 500]
                placeholders = ",".join(str(mid) for mid in batch)
                db.execute(text(f"DELETE FROM messages_fts WHERE message_id IN ({placeholders});"))
        except Exception as fts_err:
            logger.warning(f"Could not delete FTS records for conversation {conversation_id}: {fts_err}")

    # Remove media files from disk
    media_assets = db.query(MediaAsset).filter(MediaAsset.conversation_id == conversation_id).all()
    for asset in media_assets:
        try:
            p = Path(asset.file_path)
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Could not delete media file {asset.file_path}: {e}")

    db.delete(conv)
    db.commit()

    return {"status": "deleted", "conversation_id": conversation_id}
