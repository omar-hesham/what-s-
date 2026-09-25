"""
WhatsApp Web Companion API routes.
Authenticated bridge for user-initiated browser captures.
Uses scoped, revocable pairing credentials.
"""

import base64
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.security import verify_companion_token, verify_session_or_token, pairing_manager
from owi.core.logging import logger
from owi.db.database import get_db
from owi.db.models import Conversation, Message, MediaAsset
from owi.ai.local_nlp import LocalNLPEngine

router = APIRouter(prefix="/api/companion", tags=["WhatsApp Web Companion"])

ARABIC_INDIC_DIGITS = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"
}

BIDI_CHARS_PATTERN = re.compile(r'[\u200e\u200f\u202a-\u202e\u202f\u00a0\ufeff\u061c]')

ALLOWED_STAGES = {
    "init", "pairing", "scroll_up", "scroll_down", "ingest_chunk", "cancel", "summary", "general"
}

ALLOWED_CODES = {
    "START", "STEP", "SUCCESS", "PARTIAL", "CANCELLED",
    "BOUND_REACHED", "TOP_REACHED", "BOTTOM_REACHED",
    "CHUNK_INGESTED", "CHUNK_POST_SUCCESS", "CHUNK_POST_FAILED",
    "ERR_NETWORK", "ERR_AUTH", "ERR_PAYLOAD", "ERR_SELECTOR",
    "ERR_TIMEOUT", "ERR_STALL", "ERR_PARSE", "UNPAIRED", "INFO"
}

ALLOWED_STATIC_DETAILS = {
    "history_exhausted_before_from_bound",
    "history_exhausted_before_to_bound",
    "scroll_attempts_exhausted",
    "traversal_stalled",
    "cancelled_by_user",
    "chat_navigation_detected",
    "first_visible_anchor_not_found",
    "zero_messages_captured",
    "unparseable_timestamp_present",
    "unverified_timestamps_present",
    "chunk_ingest_failed",
    "payload_too_large",
    "backend_unreachable",
    "auth_rejected",
    "ok"
}

def normalize_digits_and_bidi(text_val: str) -> str:
    cleaned = BIDI_CHARS_PATTERN.sub(" ", text_val)
    for ar_digit, en_digit in ARABIC_INDIC_DIGITS.items():
        cleaned = cleaned.replace(ar_digit, en_digit)
    return cleaned.strip()

def parse_companion_timestamp(ts: Optional[str], default_day_first: bool = True) -> Optional[datetime]:
    if not ts:
        return None
    cleaned = normalize_digits_and_bidi(ts).strip()
    if not cleaned:
        return None

    # 1. Try ISO format (validate calendar bounds strictly)
    try:
        iso_str = cleaned.replace("Z", "+00:00")
        return datetime.fromisoformat(iso_str)
    except Exception:
        pass

    # 2. Normalize Arabic AM/PM
    cleaned = re.sub(r'[\u0635]\.?$', 'AM', cleaned)
    cleaned = re.sub(r'[\u0645]\.?$', 'PM', cleaned)
    cleaned = re.sub(r'[\u0635]\b', 'AM', cleaned)
    cleaned = re.sub(r'[\u0645]\b', 'PM', cleaned)
    cleaned = cleaned.replace("صباحاً", "AM").replace("صباحا", "AM")
    cleaned = cleaned.replace("مساءً", "PM").replace("مساء", "PM")

    # WhatsApp common formats: "[10:45 AM, 9/23/2026]" or "10:45, 23/9/2026"
    cleaned = cleaned.strip("[]")

    date_match = re.search(r'(\d{1,4}[/\-\.]\d{1,2}[/\-\.]\d{1,4})', cleaned)
    time_match = re.search(r'(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)', cleaned, re.IGNORECASE)

    # Time-only strings without date must NOT silently use today's date
    if not date_match:
        return None

    date_part = date_match.group(1).replace(".", "/").replace("-", "/")
    parts = [int(p) for p in date_part.split("/") if p.isdigit()]
    if len(parts) != 3:
        return None

    p1, p2, p3 = parts
    if p1 > 1000:
        year, month, day = p1, p2, p3
    else:
        year = p3 if p3 > 100 else (2000 + p3 if p3 < 70 else 1900 + p3)
        if p1 > 12:
            day, month = p1, p2
        elif p2 > 12:
            month, day = p1, p2
        else:
            if default_day_first:
                day, month = p1, p2
            else:
                month, day = p1, p2

    hour, minute, second = 0, 0, 0
    if time_match:
        t_str = time_match.group(1).strip()
        is_pm = "PM" in t_str.upper()
        is_am = "AM" in t_str.upper()
        t_clean = re.sub(r'(?i)\s*(AM|PM)', '', t_str).strip()
        t_parts = [int(p) for p in t_clean.split(":") if p.isdigit()]
        if t_parts:
            hour = t_parts[0]
            minute = t_parts[1] if len(t_parts) > 1 else 0
            second = t_parts[2] if len(t_parts) > 2 else 0
            if is_pm and hour < 12:
                hour += 12
            elif is_am and hour == 12:
                hour = 0

    try:
        # Strict validation: datetime() raises ValueError for impossible dates like 31/02
        return datetime(year, month, day, hour, minute, second)
    except Exception:
        return None

def sanitize_diagnostic_entry(entry_dict: Dict[str, Any]) -> Dict[str, Any]:
    raw_stage = str(entry_dict.get("stage", "general")).strip().lower()
    stage = raw_stage if raw_stage in ALLOWED_STAGES else "general"

    raw_code = str(entry_dict.get("code", "INFO")).strip().upper()
    code = raw_code if raw_code in ALLOWED_CODES else "INFO"

    count_val = entry_dict.get("count", 0)
    try:
        count = max(0, int(count_val))
    except Exception:
        count = 0

    raw_details = str(entry_dict.get("details", "")).strip().lower()
    # Details must strictly match allowlisted static reason codes; free-form text is rejected
    clean_details = raw_details if raw_details in ALLOWED_STATIC_DETAILS else None

    ts = entry_dict.get("timestamp")
    if not ts or not isinstance(ts, str):
        ts = datetime.utcnow().isoformat() + "Z"
    else:
        ts = str(ts)[:35]

    return {
        "timestamp": ts,
        "stage": stage,
        "code": code,
        "count": count,
        "details": clean_details
    }

def get_diagnostics_log_path() -> Path:
    log_dir = settings.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "companion_diagnostics.jsonl"

def append_diagnostic_logs(entries: List[Dict[str, Any]]):
    log_path = get_diagnostics_log_path()
    lines_to_add = [json.dumps(e, ensure_ascii=False) + "\n" for e in entries]
    try:
        if log_path.exists() and log_path.stat().st_size > 500_000:
            with open(log_path, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()
            if len(existing_lines) > 500:
                existing_lines = existing_lines[-400:]
            with open(log_path, "w", encoding="utf-8") as f:
                f.writelines(existing_lines)
    except Exception:
        pass

    with open(log_path, "a", encoding="utf-8") as f:
        f.writelines(lines_to_add)

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
    timestamp: Optional[str] = None  # Exact message timestamp from DOM (ISO or display)
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
    session_id: Optional[str] = None
    chunk_index: Optional[int] = 0
    total_chunks: Optional[int] = 1
    is_last_chunk: Optional[bool] = True
    completeness_status: Optional[str] = "complete"  # "complete" or "partial"
    partial_reason: Optional[str] = None
    date_order: Optional[str] = "DD/MM/YYYY"

class DiagnosticItem(BaseModel):
    timestamp: Optional[str] = None
    stage: str
    code: str
    count: Optional[int] = 0
    details: Optional[str] = None

class DiagnosticBatchRequest(BaseModel):
    entries: List[DiagnosticItem]

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
    skipped_count = 0
    unverified_count = 0
    now_utc = datetime.utcnow()
    day_first = True if not req.date_order else req.date_order.upper().startswith("DD")

    for m in req.messages:
        # Preserve real message timestamp if supplied, with robust parsing
        parsed_dt = parse_companion_timestamp(m.timestamp, default_day_first=day_first)
        if not parsed_dt and m.capture_timestamp:
            parsed_dt = parse_companion_timestamp(m.capture_timestamp, default_day_first=day_first)

        if parsed_dt:
            dt = parsed_dt
            provenance = "verified"
        else:
            # Explicit unverified fallback: never pretend capture time is a verified WhatsApp timestamp
            dt = now_utc
            provenance = "unverified_fallback"
            unverified_count += 1

        # De-duplicate identical platform message IDs or content hash within conversation
        msg_id_key = m.platform_msg_id
        if not msg_id_key:
            # Stable representation for unverified fallback ensures retry idempotency
            dt_repr = dt.isoformat() if provenance == "verified" else "unverified_fallback"
            h = hashlib.sha256(f"{m.sender}|{dt_repr}|{m.text}".encode("utf-8")).hexdigest()[:24]
            msg_id_key = f"synth_{h}"

        existing = db.query(Message).filter(
            Message.conversation_id == conv.id,
            Message.raw_text == msg_id_key
        ).first()
        if existing:
            skipped_count += 1
            continue

        msg_type = m.media_type or ("image" if m.has_media else "text")

        msg_rec = Message(
            conversation_id=conv.id,
            sender_name=m.sender,
            timestamp=dt,
            timestamp_provenance=provenance,
            content=m.text,
            message_type=msg_type,
            raw_text=msg_id_key,
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

    if added_count > 0:
        # Trigger NLP extraction on the conversation
        LocalNLPEngine.analyze_conversation(conv.id, db)

    # Record structured backend diagnostic log entry for chunk
    try:
        clean_detail = req.partial_reason if (req.partial_reason in ALLOWED_STATIC_DETAILS) else "ok"
        append_diagnostic_logs([
            sanitize_diagnostic_entry({
                "stage": "ingest_chunk",
                "code": "CHUNK_INGESTED",
                "count": added_count,
                "details": clean_detail
            })
        ])
    except Exception:
        pass

    effective_status = req.completeness_status or "complete"
    effective_reason = req.partial_reason
    if unverified_count > 0:
        effective_status = "partial"
        effective_reason = effective_reason or "unverified_timestamps_present"

    return {
        "status": "success",
        "conversation_id": conv.id,
        "chat_title": conv.title,
        "messages_ingested": added_count,
        "duplicates_skipped": skipped_count,
        "unverified_timestamps": unverified_count,
        "session_id": req.session_id,
        "chunk_index": req.chunk_index,
        "total_chunks": req.total_chunks,
        "is_last_chunk": req.is_last_chunk,
        "completeness_status": effective_status,
        "partial_reason": effective_reason
    }

# --- Diagnostic Endpoints ---

@router.post("/diagnostics")
def record_companion_diagnostics(
    req: DiagnosticBatchRequest,
    authenticated: bool = Depends(verify_companion_token)
):
    """
    Store bounded structured diagnostic error logs from browser companion.
    Strictly allowlists stage/code and rejects arbitrary user text, tokens, or titles.
    """
    entries_to_process = req.entries[:50]
    clean_entries = [sanitize_diagnostic_entry(e.model_dump()) for e in entries_to_process]
    append_diagnostic_logs(clean_entries)
    return {"status": "recorded", "count": len(clean_entries)}

@router.get("/diagnostics")
def get_companion_diagnostics(
    authenticated: bool = Depends(verify_session_or_token),
    limit: int = 100
):
    """
    Retrieve bounded diagnostic entries from data/logs for troubleshooting.
    """
    log_path = get_diagnostics_log_path()
    if not log_path.exists():
        return {"entries": []}
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        entries = []
        effective_limit = max(1, min(limit, 100))
        for line in lines[-effective_limit:]:
            line_str = line.strip()
            if line_str:
                try:
                    entries.append(json.loads(line_str))
                except Exception:
                    pass
        return {"entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read diagnostic logs: {e}")
