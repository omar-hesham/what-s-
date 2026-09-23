"""
WhatsApp Web Companion API routes.
Authenticated bridge for user-initiated browser captures.
Requires X-OWI-Token header to prevent unauthorized access from arbitrary web pages.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from owi.core.security import verify_companion_token
from owi.db.database import get_db
from owi.db.models import Conversation, Message
from owi.ai.local_nlp import LocalNLPEngine

router = APIRouter(prefix="/api/companion", tags=["WhatsApp Web Companion"])

class CompanionMessageItem(BaseModel):
    sender: str
    text: str
    timestamp: Optional[str] = None
    has_media: bool = False
    media_url: Optional[str] = None

class CompanionIngestRequest(BaseModel):
    chat_title: str
    messages: List[CompanionMessageItem]

@router.post("/ingest")
def ingest_companion_selection(
    req: CompanionIngestRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """
    Ingest user-selected messages sent from WhatsApp Web browser companion extension.
    Protected by localhost authentication token.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages selected for capture.")

    # Find or create companion conversation
    conv = db.query(Conversation).filter(
        Conversation.title == req.chat_title,
        Conversation.source_type == "companion"
    ).first()

    if not conv:
        conv = Conversation(
            title=req.chat_title,
            source_type="companion",
            message_count=0
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    added_count = 0
    for m in req.messages:
        dt = datetime.utcnow()
        if m.timestamp:
            try:
                dt = datetime.fromisoformat(m.timestamp)
            except Exception:
                pass

        msg_rec = Message(
            conversation_id=conv.id,
            sender_name=m.sender,
            timestamp=dt,
            content=m.text,
            message_type="voice" if m.has_media and "audio" in (m.media_url or "") else ("image" if m.has_media else "text"),
            has_attachment=m.has_media,
            attachment_name=m.media_url
        )
        db.add(msg_rec)
        added_count += 1

    conv.message_count += added_count
    db.commit()

    # Trigger NLP extraction on the conversation
    LocalNLPEngine.analyze_conversation(conv.id, db)

    return {
        "status": "success",
        "conversation_id": conv.id,
        "chat_title": conv.title,
        "messages_ingested": added_count
    }
