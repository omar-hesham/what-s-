"""
WhatsApp Web Companion API routes.
Authenticated bridge for user-initiated browser captures.
Uses scoped, revocable pairing credentials.
"""

import base64
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.security import verify_companion_token, verify_session_or_token, pairing_manager
from owi.core.logging import logger
from owi.db.database import get_db
from owi.db.models import Conversation, Message, MediaAsset
from owi.ai.local_nlp import LocalNLPEngine

router = APIRouter(prefix="/api/companion", tags=["WhatsApp Web Companion"])

class PairingCodeRequest(BaseModel):
    client_name: Optional[str] = "WhatsApp Web Companion"

class PairingExchangeRequest(BaseModel):
    pairing_code: Optional[str] = None
    code: Optional[str] = None
    client_name: Optional[str] = None
    device_name: Optional[str] = None

class CompanionMessageItem(BaseModel):
    sender: str
    text: str
    timestamp: Optional[str] = None  # Exact message timestamp from DOM
    capture_timestamp: Optional[str] = None
    is_outgoing: bool = False
    platform_msg_id: Optional[str] = None
    has_media: bool = False
    media_type: Optional[str] = "text"  # text, image, voice, video, document
    media_filename: Optional[str] = None
    media_mime: Optional[str] = None
    media_base64: Optional[str] = None  # Actual accessible binary data from page session
    media_status: Optional[str] = "available"  # available, omitted, missing, unsupported

class CompanionIngestRequest(BaseModel):
    chat_title: str
    messages: List[CompanionMessageItem]
    url: Optional[str] = None
    page_title: Optional[str] = None
    is_generic_webpage: bool = False

# --- Pairing Flow Endpoints ---

@router.api_route("/pairing/code", methods=["GET", "POST"])
def generate_pairing_code(
    authenticated: bool = Depends(verify_session_or_token)
):
    """Generate a temporary 6-digit pairing code displayed in the OWI app UI."""
    return pairing_manager.create_pairing_code()

@router.post("/pairing/pair")
def exchange_pairing_code(req: PairingExchangeRequest):
    """
    Exchange temporary pairing code for a persistent revocable bearer token.
    Called once by the browser extension during setup.
    """
    code_val = req.code or req.pairing_code
    if not code_val:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing pairing code."
        )
    client_name = req.device_name or req.client_name or "WhatsApp Web Companion"
    token = pairing_manager.exchange_pairing_code(code_val, client_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired pairing code."
        )
    return {
        "status": "paired",
        "token": token,
        "token_type": "Bearer"
    }

@router.get("/pairings")
def list_paired_extensions(authenticated: bool = Depends(verify_session_or_token)):
    """List active paired extensions in the settings UI."""
    return pairing_manager.list_pairings()

@router.api_route("/pairing/revoke", methods=["POST", "DELETE"])
@router.delete("/pairings/{token_prefix}")
def revoke_paired_extension(
    token_prefix: Optional[str] = None,
    token: Optional[str] = None,
    authenticated: bool = Depends(verify_session_or_token)
):
    """Revoke a paired extension's access."""
    target = token or token_prefix
    if not target:
        raise HTTPException(status_code=400, detail="Missing token to revoke")
    success = pairing_manager.revoke_token(target)
    if not success:
        raise HTTPException(status_code=404, detail="Pairing token not found")
    return {"status": "revoked"}

# --- Ingestion Endpoint ---

@router.post("/ingest")
def ingest_companion_selection(
    req: CompanionIngestRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """
    Ingest user-selected messages sent from WhatsApp Web browser companion extension.
    Protected by scoped companion pairing token.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages provided for capture.")

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
    now_utc = datetime.utcnow()

    for m in req.messages:
        # Preserve real message timestamp if supplied, otherwise fallback to capture or current time
        dt = now_utc
        if m.timestamp:
            try:
                dt = datetime.fromisoformat(m.timestamp)
            except Exception:
                pass
        elif m.capture_timestamp:
            try:
                dt = datetime.fromisoformat(m.capture_timestamp)
            except Exception:
                pass

        # De-duplicate identical platform message IDs within conversation
        if m.platform_msg_id:
            existing = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.raw_text == m.platform_msg_id
            ).first()
            if existing:
                continue

        msg_type = m.media_type or ("image" if m.has_media else "text")

        msg_rec = Message(
            conversation_id=conv.id,
            sender_name=m.sender,
            timestamp=dt,
            content=m.text,
            message_type=msg_type,
            raw_text=m.platform_msg_id or m.text,
            has_attachment=m.has_media,
            attachment_name=m.media_filename
        )
        db.add(msg_rec)
        db.flush()

        # Sync to full-text search index (FTS5)
        try:
            db.execute(
                text("INSERT INTO messages_fts (message_id, content, sender_name) VALUES (:id, :content, :sender)"),
                {"id": msg_rec.id, "content": msg_rec.content, "sender": msg_rec.sender_name}
            )
        except Exception:
            pass

        # Handle real binary media bytes if captured from browser
        if m.has_media and m.media_base64:
            try:
                media_bytes = base64.b64decode(m.media_base64)
                sha = hashlib.sha256(media_bytes).hexdigest()
                
                # Determine folder
                cat = "images" if msg_type == "image" else ("audio" if msg_type == "voice" else "documents")
                safe_name = f"browser_{sha[:10]}_{m.media_filename or 'media.dat'}"
                dest_path = settings.DATA_DIR / "media" / cat / safe_name
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(dest_path, "wb") as f:
                    f.write(media_bytes)

                media_asset = MediaAsset(
                    conversation_id=conv.id,
                    message_id=msg_rec.id,
                    file_name=m.media_filename or safe_name,
                    file_type="audio" if msg_type == "voice" else ("image" if msg_type == "image" else "document"),
                    mime_type=m.media_mime or "application/octet-stream",
                    file_size=len(media_bytes),
                    file_path=str(dest_path),
                    sha256_hash=sha
                )
                db.add(media_asset)
            except Exception as e:
                logger.warning(f"Could not store captured companion media: {e}")

        added_count += 1

    conv.message_count = (conv.message_count or 0) + added_count
    db.commit()

    # Trigger NLP extraction on the conversation
    LocalNLPEngine.analyze_conversation(conv.id, db)

    return {
        "status": "success",
        "conversation_id": conv.id,
        "chat_title": conv.title,
        "messages_ingested": added_count
    }
