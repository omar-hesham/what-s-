"""
WhatsApp Web Companion API routes.
Authenticated bridge for user-initiated browser captures.
Uses scoped, revocable pairing credentials.
"""

import os
import sys
import time
import base64
import hashlib
import json
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Set
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.security import (
    verify_companion_token,
    verify_session_or_token,
    pairing_manager,
    sanitize_filename
)
from owi.core.logging import logger
from owi.db.database import get_db, SessionLocal
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord, Job
from owi.ai.local_nlp import LocalNLPEngine
from owi.core.queue import enqueue_media_processing, job_queue

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
    "older_messages_button_unexhausted",
    "clicked_older_messages_button",
    "auth_rejected",
    "ok"
}

MAX_MEDIA_FILE_BYTES = 50 * 1024 * 1024  # 50 MB max media file
MAX_MEDIA_DIRECT_BYTES = 5 * 1024 * 1024  # 5 MB max direct upload
MAX_CHUNK_BYTES = 2 * 1024 * 1024  # 2 MB max single chunk
MAX_CHUNKS_PER_SESSION = 500

VALID_ATTACHMENT_STATUSES = {
    "saved-original",
    "preview-only",
    "unavailable",
    "expired",
    "too-large",
    "failed",
    "unsupported",
    "none"
}

MIME_CATEGORY_MAP = {
    # Audio
    "audio/ogg": "audio", "audio/opus": "audio", "audio/mpeg": "audio",
    "audio/mp3": "audio", "audio/wav": "audio", "audio/m4a": "audio",
    "audio/aac": "audio", "audio/webm": "audio",
    # Images
    "image/jpeg": "images", "image/jpg": "images", "image/png": "images",
    "image/webp": "images", "image/gif": "images", "image/svg+xml": "images",
    # Video
    "video/mp4": "video", "video/webm": "video", "video/3gpp": "video",
    "video/quicktime": "video", "video/x-msvideo": "video", "video/x-matroska": "video",
    # Documents
    "application/pdf": "documents",
    "application/msword": "documents",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "documents",
    "application/vnd.ms-excel": "documents",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "documents",
    "application/vnd.ms-powerpoint": "documents",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "documents",
    "text/plain": "documents", "text/csv": "documents", "application/zip": "other"
}

EXTENSION_CATEGORY_MAP = {
    # Audio
    ".ogg": "audio", ".opus": "audio", ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".aac": "audio",
    # Images
    ".jpg": "images", ".jpeg": "images", ".png": "images", ".webp": "images", ".gif": "images", ".svg": "images",
    # Video
    ".mp4": "video", ".webm": "video", ".3gp": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    # Documents
    ".pdf": "documents", ".docx": "documents", ".doc": "documents",
    ".xlsx": "documents", ".xls": "documents", ".pptx": "documents", ".ppt": "documents",
    ".txt": "documents", ".csv": "documents", ".zip": "other"
}

def sanitize_media_filename(raw_name: Optional[str], default_ext: str = ".dat") -> str:
    """Sanitize raw media filename and strictly prevent path traversal."""
    if not raw_name:
        return f"media{default_ext}"
    clean = raw_name.replace("/", "_").replace("\\", "_")
    clean = re.sub(r'\.\.+', '_', clean)
    clean = sanitize_filename(clean)
    if not clean or clean.startswith("."):
        clean = f"media_{clean}" if clean else f"media{default_ext}"
    return clean

def determine_media_category(filename: str, mime_type: Optional[str] = None, suggested_type: Optional[str] = None) -> str:
    """Classify media into safe subfolders: audio, images, video, documents, other."""
    ext = Path(filename).suffix.lower()
    if mime_type and mime_type.lower() in MIME_CATEGORY_MAP:
        return MIME_CATEGORY_MAP[mime_type.lower()]
    if ext in EXTENSION_CATEGORY_MAP:
        return EXTENSION_CATEGORY_MAP[ext]
    if suggested_type in ("audio", "voice"):
        return "audio"
    if suggested_type == "image":
        return "images"
    if suggested_type == "video":
        return "video"
    if suggested_type == "document":
        return "documents"
    return "other"

def save_media_file_atomically(
    media_bytes: bytes,
    category: str,
    raw_filename: str,
    expected_sha256: Optional[str] = None
) -> Tuple[Path, str, str, int]:
    """
    Safely and atomically writes media bytes to disk:
    - Sanitizes filename preventing path traversal
    - Classifies into safe subfolder (audio/images/video/documents/other)
    - Verifies path is strictly inside settings.DATA_DIR / "media"
    - Computes SHA256 and verifies against expected_sha256
    - Writes to a temporary file first, then atomically replaces to final path
    - Idempotent: If file already exists and hash matches, reuses without corrupting
    """
    if len(media_bytes) > MAX_MEDIA_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size ({MAX_MEDIA_FILE_BYTES} bytes)"
        )

    computed_sha = hashlib.sha256(media_bytes).hexdigest()
    if expected_sha256 and expected_sha256.strip().lower() != computed_sha.lower():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SHA256 checksum mismatch")

    safe_name = sanitize_media_filename(raw_filename)
    final_name = f"browser_{computed_sha[:10]}_{safe_name}"

    safe_cat = category if category in ("audio", "images", "video", "documents", "other") else "other"
    media_root = (settings.DATA_DIR / "media").resolve()
    media_dir = (media_root / safe_cat).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)

    final_path = (media_dir / final_name).resolve()
    try:
        final_path.relative_to(media_root)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media destination path")

    if final_path.exists() and final_path.stat().st_size == len(media_bytes):
        existing_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
        if existing_sha.lower() == computed_sha.lower():
            return final_path, final_name, computed_sha, len(media_bytes)

    temp_dir = settings.DATA_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=temp_dir, prefix="owi_upload_", suffix=".tmp", delete=False) as tf:
        tf.write(media_bytes)
        temp_file = Path(tf.name)

    try:
        temp_file.replace(final_path)
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink(missing_ok=True)
        raise e

    return final_path, final_name, computed_sha, len(media_bytes)

def link_media_asset_to_message(
    db: Session,
    conversation_id: Optional[int],
    message_id: Optional[int],
    final_path: Path,
    file_name: str,
    category: str,
    mime_type: Optional[str],
    file_size: int,
    sha256_hash: str,
    message_key: Optional[str] = None,
    attachment_position: Optional[int] = None
) -> MediaAsset:
    """
    Idempotently links a MediaAsset to a Message and Conversation:
    - If MediaAsset already linked to this message_id with same sha256, reuses it.
    - If unlinked MediaAsset exists in this conversation matching this message_key, links it.
    - If message_id is None, finds or creates an unlinked MediaAsset specifically for this message_key.
      Avoids attaching multiple distinct messages with identical bytes to the first message.
    - Updates Message has_attachment=True, attachment_name=file_name, attachment_status='saved-original'.
    """
    existing_asset = None
    if message_id:
        existing_asset = db.query(MediaAsset).filter(
            MediaAsset.conversation_id == conversation_id,
            MediaAsset.message_id == message_id,
            MediaAsset.sha256_hash == sha256_hash
        ).first()

        if not existing_asset and message_key:
            rec = db.query(AttachmentRecord).filter(
                AttachmentRecord.conversation_id == conversation_id,
                AttachmentRecord.message_key == message_key,
                AttachmentRecord.message_id == None
            ).first()
            if rec and rec.media_asset_id:
                unlinked = db.query(MediaAsset).filter(
                    MediaAsset.id == rec.media_asset_id,
                    MediaAsset.message_id == None
                ).first()
                if unlinked:
                    unlinked.message_id = message_id
                    db.flush()
                    existing_asset = unlinked

        if not existing_asset:
            unlinked_candidates = db.query(MediaAsset).filter(
                MediaAsset.conversation_id == conversation_id,
                MediaAsset.message_id == None,
                MediaAsset.sha256_hash == sha256_hash
            ).all()
            for cand in unlinked_candidates:
                cand_rec = db.query(AttachmentRecord).filter(
                    AttachmentRecord.media_asset_id == cand.id
                ).first()
                if not cand_rec or not cand_rec.message_key or (message_key and cand_rec.message_key == message_key):
                    cand.message_id = message_id
                    db.flush()
                    existing_asset = cand
                    break
    else:
        if message_key:
            rec_q = db.query(AttachmentRecord).filter(
                AttachmentRecord.conversation_id == conversation_id,
                AttachmentRecord.message_key == message_key,
                AttachmentRecord.message_id == None
            )
            if attachment_position is not None:
                rec_q = rec_q.filter(AttachmentRecord.attachment_position == attachment_position)
            elif sha256_hash:
                rec_q = rec_q.filter(AttachmentRecord.sha256_hash == sha256_hash)
            existing_rec = rec_q.first()
            if existing_rec and existing_rec.media_asset_id:
                existing_asset = db.query(MediaAsset).filter(
                    MediaAsset.id == existing_rec.media_asset_id,
                    MediaAsset.message_id == None
                ).first()
        else:
            existing_asset = db.query(MediaAsset).filter(
                MediaAsset.conversation_id == conversation_id,
                MediaAsset.message_id == None,
                MediaAsset.sha256_hash == sha256_hash
            ).first()

    if existing_asset:
        if message_id:
            msg = db.query(Message).filter(Message.id == message_id).first()
            if msg:
                msg.has_attachment = True
                if not msg.attachment_name:
                    msg.attachment_name = file_name
                msg.attachment_status = "saved-original"
                db.flush()
        return existing_asset

    asset = MediaAsset(
        conversation_id=conversation_id,
        message_id=message_id,
        file_name=file_name,
        file_type="audio" if category == "audio" else ("image" if category == "images" else ("video" if category == "video" else ("document" if category == "documents" else "other"))),
        mime_type=mime_type or "application/octet-stream",
        file_size=file_size,
        file_path=str(final_path),
        sha256_hash=sha256_hash
    )
    db.add(asset)
    db.flush()

    if message_id:
        msg = db.query(Message).filter(Message.id == message_id).first()
        if msg:
            msg.has_attachment = True
            if not msg.attachment_name:
                msg.attachment_name = file_name
            msg.attachment_status = "saved-original"
            db.flush()

    return asset

def record_attachment_status(
    db: Session,
    conversation_id: int,
    message_id: Optional[int],
    file_name: str,
    file_type: str,
    status: str,
    session_id: Optional[str] = None,
    message_key: Optional[str] = None,
    attachment_position: Optional[int] = None,
    mime_type: Optional[str] = None,
    file_size: int = 0,
    sha256_hash: Optional[str] = None,
    media_asset_id: Optional[int] = None,
    reason: Optional[str] = None
) -> AttachmentRecord:
    """
    Durable per-file attachment capture record.
    Keyed by target conversation + capture session + message key + attachment position/id.
    Never marks saved-original unless an actual physical media_asset_id exists and file exists.
    """
    clean_status = status if status in VALID_ATTACHMENT_STATUSES else "unavailable"
    if clean_status == "saved-original" and not media_asset_id:
        clean_status = "failed"
        reason = reason or "missing_media_asset"

    query = db.query(AttachmentRecord).filter(
        AttachmentRecord.conversation_id == conversation_id
    )
    existing = None
    if message_id is not None:
        if media_asset_id is not None:
            existing = query.filter(
                AttachmentRecord.message_id == message_id,
                AttachmentRecord.media_asset_id == media_asset_id
            ).first()
        if not existing and attachment_position is not None:
            existing = query.filter(
                AttachmentRecord.message_id == message_id,
                AttachmentRecord.attachment_position == attachment_position
            ).first()
        if not existing:
            existing = query.filter(
                AttachmentRecord.message_id == message_id,
                AttachmentRecord.file_name == file_name
            ).first()
    elif message_key is not None:
        if media_asset_id is not None:
            existing = query.filter(
                AttachmentRecord.message_key == message_key,
                AttachmentRecord.media_asset_id == media_asset_id
            ).first()
        if not existing and attachment_position is not None:
            existing = query.filter(
                AttachmentRecord.message_key == message_key,
                AttachmentRecord.attachment_position == attachment_position
            ).first()
        if not existing:
            existing = query.filter(
                AttachmentRecord.message_key == message_key,
                AttachmentRecord.file_name == file_name
            ).first()
    else:
        if media_asset_id is not None:
            existing = query.filter(AttachmentRecord.media_asset_id == media_asset_id).first()
        if not existing:
            existing = query.filter(AttachmentRecord.file_name == file_name).first()

    if existing:
        if message_id is not None and not existing.message_id:
            existing.message_id = message_id
        if media_asset_id is not None and not existing.media_asset_id:
            existing.media_asset_id = media_asset_id
        if sha256_hash:
            existing.sha256_hash = sha256_hash
        if file_size:
            existing.file_size = file_size
        if session_id and not existing.session_id:
            existing.session_id = session_id
        if message_key and not existing.message_key:
            existing.message_key = message_key
        if attachment_position is not None and existing.attachment_position is None:
            existing.attachment_position = attachment_position
        if file_name and existing.file_name != file_name and not existing.file_name.startswith("browser_"):
            existing.file_name = file_name
        elif existing.file_name.startswith("browser_") and not file_name.startswith("browser_"):
            existing.file_name = file_name
        if clean_status == "saved-original" or existing.status != "saved-original":
            existing.status = clean_status
            existing.reason = reason
        db.flush()
        return existing

    rec = AttachmentRecord(
        conversation_id=conversation_id,
        message_id=message_id,
        media_asset_id=media_asset_id,
        session_id=session_id,
        message_key=message_key,
        attachment_position=attachment_position,
        file_name=file_name,
        file_type=file_type,
        mime_type=mime_type,
        file_size=file_size,
        sha256_hash=sha256_hash,
        status=clean_status,
        reason=reason
    )
    db.add(rec)
    db.flush()
    return rec

# --- Capture Session Management & Cancellation Tracking ---
_cancelled_capture_sessions: Set[str] = set()

def is_capture_session_cancelled(session_id: Optional[str]) -> bool:
    """Check if a capture session has been flagged as cancelled to stop new capture/enqueue work."""
    if not session_id:
        return False
    return session_id in _cancelled_capture_sessions

def mark_capture_session_cancelled(session_id: str) -> None:
    """
    Flag a capture session as cancelled to stop NEW capture and enqueue work.
    Preserves all already saved originals, attachment records, and queued/completed processing.
    Already saved originals remain valid and eligible for processing/retry.
    """
    if session_id:
        _cancelled_capture_sessions.add(session_id)

def enqueue_companion_media_asset(
    asset_id: int,
    db: Session,
    session_id: Optional[str] = None
) -> Optional[int]:
    """
    Safely and idempotently enqueues a committed companion MediaAsset for background processing:
    - Never enqueues previews, unavailable/expired/failed records, or missing files.
    - Never enqueues before DB transaction is committed (caller must commit first).
    - Respects capture session cancellation (never enqueues if session was cancelled).
    - Deduplicates: prevents duplicate processing jobs if already active or completed.
    - On enqueue failure: preserves saved original and records durable error/status for retry; never rolls back or deletes file.
    """
    try:
        asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
        if not asset:
            logger.warning(f"enqueue_companion_media_asset: MediaAsset #{asset_id} not found")
            return None

        # Guard 1: Physical file must exist on disk
        if not asset.file_path or not Path(asset.file_path).exists():
            logger.info(f"MediaAsset #{asset_id} has no valid physical file on disk. Skipping enqueue.")
            return None

        # Guard 2: Respect capture session cancellation (stop new enqueue work for cancelled sessions)
        if session_id and is_capture_session_cancelled(session_id):
            logger.info(f"Capture session '{session_id}' was cancelled. Skipping new enqueue for MediaAsset #{asset_id}.")
            return None

        # Guard 3: Must have at least one valid 'saved-original' attachment record linked to this asset.
        # Avoid suppressing a saved-original if another record (e.g. preview-only or unavailable) is also present.
        saved_rec = db.query(AttachmentRecord).filter(
            AttachmentRecord.media_asset_id == asset_id,
            AttachmentRecord.status == "saved-original"
        ).first()
        if not saved_rec:
            logger.info(f"MediaAsset #{asset_id} has no linked 'saved-original' attachment record. Skipping enqueue.")
            return None

        # Enqueue background processing idempotently
        job_id = enqueue_media_processing(asset.id, force_retry=False, db=db)
        return job_id
    except Exception as e:
        logger.error(f"Failed to enqueue MediaAsset #{asset_id} for processing: {e}", exc_info=True)
        # Roll back failed transaction first to clear any broken session state
        try:
            db.rollback()
        except Exception:
            pass
        # On enqueue failure: preserve saved original & persist durable status for retry
        try:
            asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
            if asset:
                asset.processing_status = "failed"
                asset.processing_error = f"enqueue_failed: {str(e)}"
                db.commit()
        except Exception as db_err:
            logger.error(f"Could not persist enqueue failure status on MediaAsset #{asset_id}: {db_err}")
            try:
                db.rollback()
            except Exception:
                pass
        return None

YOU_SENDER_ALIASES = {"you", "أنت", "me", "انا", "أنا"}

INVALID_CHAT_TITLES = {
    "profile details",
    "تفاصيل الملف الشخصي",
    "contact info",
    "معلومات جهة الاتصال",
    "group info",
    "معلومات المجموعة",
    "chat details",
    "تفاصيل الدردشة"
}

def is_invalid_title(t: Optional[str]) -> bool:
    if not t:
        return True
    cleaned = normalize_digits_and_bidi(t).strip().lower()
    return cleaned in INVALID_CHAT_TITLES

def extract_title_core_tokens(title: str) -> Set[str]:
    norm = normalize_digits_and_bidi(title).strip().lower()
    norm = re.sub(r'\(.*?\)', ' ', norm)
    norm = re.sub(r'\+?\d[\d\s\-]{6,}\d', ' ', norm)
    words = re.findall(r'[\w]+', norm, flags=re.UNICODE)
    filler = {
        "whatsapp", "chat", "with", "imported", "archive", "export", "zip",
        "web", "conversation", "محادثة", "مع", "واتساب", "أرشيف", "تصدير",
        "دردشة", "رسائل", "messages"
    }
    core = {w for w in words if w not in filler and not w.isdigit()}
    return core

def is_matching_chat_title(t1: Optional[str], t2: Optional[str]) -> bool:
    """
    Strict title matching with narrow imported archive alias support:
    1. Exact match (case/whitespace/bidi-normalized).
    2. Strict group rejection: If one title refers to a group ('group' or 'مجموعة')
       and the other does not, they are NEVER matched.
    3. Narrow imported archive alias match:
       One title is an archive alias of the other, e.g.:
       - "محادثة H (تعديلات الكتاب)" vs "H"
       - "WhatsApp Chat with H - 2026 Export" vs "H"
       - "Imported Archive H" vs "WhatsApp Web H"
       Specifically:
       - Strips known archive prefixes ("whatsapp chat with ", "chat with ", "imported archive ", "whatsapp web ", "محادثة مع ", "محادثة ", etc.)
       - Strips trailing parenthetical notes "(...)" at the end (unless indicating group)
       - Strips trailing export / archive tags (" - 2026 Export", " - Export", " - Archive", " - تصدير", etc.)
       The remaining name segment MUST EXACTLY EQUAL the live title (or both alias segments match).
       Arbitrary subset/shared-token matches (e.g. "H Group" vs "H") are strictly REJECTED.
    """
    if not t1 or not t2:
        return False
    n1 = normalize_digits_and_bidi(t1).strip().strip('"\'').lower()
    n2 = normalize_digits_and_bidi(t2).strip().strip('"\'').lower()
    if n1 == n2:
        return True

    # Strict: Reject match if one is a group and the other is not
    group_indicators = ("group", "مجموعة")
    is_g1 = any(gi in n1 for gi in group_indicators)
    is_g2 = any(gi in n2 for gi in group_indicators)
    if is_g1 != is_g2:
        return False

    def extract_archive_name_segment(title_str: str) -> str:
        s = normalize_digits_and_bidi(title_str).strip().strip('"\'').lower()
        # Strip trailing parenthetical notes at end (e.g. (تعديلات الكتاب))
        s = re.sub(r'\(.*?\)\s*$', '', s).strip()
        # Strip trailing export / archive tags (e.g. - 2026 Export, - Export, - Archive, - تصدير)
        s = re.sub(r'\s*[-–—]\s*(?:\d{2,4}\s*)?(?:export|archive|تصدير|أرشيف|backup|نسخة).*$', '', s, flags=re.IGNORECASE).strip()
        s = re.sub(r'\s*[-–—]\s*(?:export|archive|تصدير|أرشيف|backup|نسخة)(?:\s*\d{2,4})?.*$', '', s, flags=re.IGNORECASE).strip()
        prefixes = [
            "whatsapp chat with ", "whatsapp chat - ", "whatsapp chat ",
            "chat with ", "imported archive ", "archive with ", "archive - ", "archive ",
            "whatsapp web ",
            "محادثة مع ", "محادثة ", "دردشة مع ", "دردشة ", "رسائل مع ", "رسائل ",
            "أرشيف محادثة مع ", "أرشيف محادثة ", "أرشيف دردشة مع ", "أرشيف دردشة ", "أرشيف "
        ]
        for pfx in prefixes:
            if s.startswith(pfx):
                s = s[len(pfx):].strip()
                break
        # Re-check trailing parenthetical / export suffix in case prefix was stripped first
        s = re.sub(r'\(.*?\)\s*$', '', s).strip()
        s = re.sub(r'\s*[-–—]\s*(?:\d{2,4}\s*)?(?:export|archive|تصدير|أرشيف|backup|نسخة).*$', '', s, flags=re.IGNORECASE).strip()
        return s

    seg1 = extract_archive_name_segment(t1)
    seg2 = extract_archive_name_segment(t2)

    if seg1 and seg1 == n2:
        return True
    if seg2 and seg2 == n1:
        return True
    if seg1 and seg2 and seg1 == seg2 and (seg1 != n1 or seg2 != n2):
        return True

    return False


def is_matching_sender(s1: str, s2: str) -> bool:
    norm1 = (s1 or "").strip().lower()
    norm2 = (s2 or "").strip().lower()
    if not norm1 or not norm2:
        return False
    if norm1 == norm2:
        return True
    if norm1 in YOU_SENDER_ALIASES and norm2 in YOU_SENDER_ALIASES:
        return True
    return False

def find_matching_target_message(
    db: Session,
    conv_id: int,
    platform_msg_id: Optional[str],
    dt: datetime,
    sender: str,
    text: str,
    provenance: str
) -> Optional[Message]:
    """
    Defensible overlap matching for imported conversations (e.g. export_zip H #13):
    1. Exact platform_msg_id (raw_text == platform_msg_id)
    2. Exact synthetic key (raw_text == synth_key)
    3. Defensible overlap matching: timestamp within +- 1 minute, strict sender match with 'You' alias mapping, content match.
       Ambiguity (multiple candidates matching) must NOT silently merge!
    """
    if platform_msg_id:
        existing = db.query(Message).filter(
            Message.conversation_id == conv_id,
            Message.raw_text == platform_msg_id
        ).first()
        if existing:
            return existing

    # Synthetic hash check
    dt_repr = dt.isoformat() if provenance == "verified" else "unverified_fallback"
    h = hashlib.sha256(f"{sender}|{dt_repr}|{text}".encode("utf-8")).hexdigest()[:24]
    synth_key = f"synth_{h}"
    existing_synth = db.query(Message).filter(
        Message.conversation_id == conv_id,
        Message.raw_text == synth_key
    ).first()
    if existing_synth:
        return existing_synth

    # Overlap matching for text-imported chats (like ZIP export H)
    if provenance == "verified":
        min_dt = dt.replace(second=0, microsecond=0)
        candidates = db.query(Message).filter(
            Message.conversation_id == conv_id,
            Message.timestamp >= min_dt - timedelta(minutes=1),
            Message.timestamp <= min_dt + timedelta(minutes=1)
        ).all()

        norm_text = text.strip().replace("\r\n", "\n")
        matched = []
        for c in candidates:
            c_text = (c.content or "").strip().replace("\r\n", "\n")
            if c_text == norm_text and is_matching_sender(c.sender_name or "", sender):
                matched.append(c)

        if len(matched) == 1:
            return matched[0]
        # Ambiguous if > 1, or no match if 0

    return None

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

class CompanionAttachmentItem(BaseModel):
    file_name: str
    file_type: str = "document"  # audio, image, video, document, other
    mime_type: Optional[str] = None
    file_size: Optional[int] = 0
    media_base64: Optional[str] = None
    sha256: Optional[str] = None
    attachment_position: Optional[int] = None
    attachment_status: Optional[str] = "saved-original"
    reason: Optional[str] = None

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
    attachment_status: Optional[str] = None
    attachments: Optional[List[CompanionAttachmentItem]] = None

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
    target_conversation_id: Optional[int] = None
    confirm_target_merge: Optional[bool] = False

class MediaUploadDirectRequest(BaseModel):
    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
    platform_msg_id: Optional[str] = None
    message_key: Optional[str] = None
    session_id: Optional[str] = None
    attachment_position: Optional[int] = None
    confirm_target_merge: Optional[bool] = False
    chat_title: Optional[str] = None
    file_name: str
    file_type: Optional[str] = "document"
    mime_type: Optional[str] = "application/octet-stream"
    media_base64: str
    sha256: Optional[str] = None
    attachment_status: Optional[str] = "saved-original"
    reason: Optional[str] = None

class MediaSessionStartRequest(BaseModel):
    session_id: str
    capture_session_id: Optional[str] = None
    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
    platform_msg_id: Optional[str] = None
    message_key: Optional[str] = None
    attachment_position: Optional[int] = None
    confirm_target_merge: Optional[bool] = False
    restart: Optional[bool] = False
    chat_title: Optional[str] = None
    file_name: str
    file_type: Optional[str] = "document"
    mime_type: Optional[str] = "application/octet-stream"
    total_bytes: int
    total_chunks: int
    sha256: Optional[str] = None
    attachment_status: Optional[str] = "saved-original"
    reason: Optional[str] = None

class MediaSessionChunkRequest(BaseModel):
    session_id: str
    chunk_index: int
    chunk_base64: str

class MediaSessionFinishRequest(BaseModel):
    session_id: str

class MediaDownloadHandoffRequest(BaseModel):
    download_path: str
    file_name: str
    file_type: Optional[str] = "document"
    mime_type: Optional[str] = "application/octet-stream"
    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
    platform_msg_id: Optional[str] = None
    message_key: Optional[str] = None
    attachment_position: Optional[int] = None
    session_id: Optional[str] = None
    confirm_target_merge: Optional[bool] = False
    chat_title: Optional[str] = None
    sha256: Optional[str] = None
    attachment_status: Optional[str] = "saved-original"
    reason: Optional[str] = None

class CaptureSessionCancelRequest(BaseModel):
    session_id: str
    reason: Optional[str] = "cancelled_by_user"

def get_system_downloads_dir() -> Path:
    """
    Resolve the configured system Downloads folder.
    On Windows, queries the Windows Known Folder API (FOLDERID_Downloads: {374DE290-123F-4565-9164-39C4925E467B})
    and User Shell Folders registry, correctly handling redirected user directories (e.g. E:\\Users\\DELL\\Downloads).
    Falls back to Path.home() / "Downloads" on other platforms or if unconfigured.
    Can also be overridden by OWI_DOWNLOADS_DIR environment variable for test isolation.
    """
    env_dir = os.environ.get("OWI_DOWNLOADS_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.exists() and p.is_dir():
            return p

    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
                expanded = os.path.expandvars(val)
                p = Path(expanded).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

        try:
            import ctypes
            from ctypes import wintypes
            guid_str = "{374DE290-123F-4565-9164-39C4925E467B}"
            class GUID(ctypes.Structure):
                _fields_ = [
                    ('Data1', wintypes.DWORD),
                    ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD),
                    ('Data4', wintypes.BYTE * 8)
                ]
            iid = GUID()
            ctypes.windll.ole32.IIDFromString(guid_str, ctypes.byref(iid))
            p_path = wintypes.LPWSTR()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(iid), 0, None, ctypes.byref(p_path)) == 0:
                p = Path(p_path.value).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

    return (Path.home() / "Downloads").resolve()

def get_chrome_downloads_dir() -> Path:
    """
    Resolve the configured Chrome Downloads folder for browser download handoff.
    Priority:
    1. settings.CHROME_DOWNLOADS_DIR or settings.DOWNLOADS_DIR (set directly or via OWI_CHROME_DOWNLOADS_DIR / OWI_DOWNLOADS_DIR).
    2. Environment variable OWI_CHROME_DOWNLOADS_DIR or OWI_DOWNLOADS_DIR.
    3. Persistent deployment config file: settings.DATA_DIR / "chrome_downloads_dir.txt".
    4. Host default known folder via get_system_downloads_dir().
    """
    if getattr(settings, "CHROME_DOWNLOADS_DIR", None):
        p = Path(settings.CHROME_DOWNLOADS_DIR).resolve()
        if p.exists() and p.is_dir():
            return p

    if getattr(settings, "DOWNLOADS_DIR", None):
        p = Path(settings.DOWNLOADS_DIR).resolve()
        if p.exists() and p.is_dir():
            return p

    env_chrome = os.environ.get("OWI_CHROME_DOWNLOADS_DIR") or os.environ.get("OWI_DOWNLOADS_DIR")
    if env_chrome:
        p = Path(env_chrome).resolve()
        if p.exists() and p.is_dir():
            return p

    cfg_file = settings.DATA_DIR / "chrome_downloads_dir.txt"
    if cfg_file.exists():
        try:
            line = cfg_file.read_text(encoding="utf-8").strip()
            if line:
                p = Path(line).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

    return get_system_downloads_dir()

def validate_download_path(path_str: str) -> Path:
    if not path_str or not isinstance(path_str, str):
        raise HTTPException(status_code=400, detail="Missing or invalid download path")

    raw_p = Path(path_str)
    if raw_p.is_symlink():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Symlinks are not allowed for download handoff")

    p = raw_p.resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail="Downloaded file not found on disk")
    if not p.is_file():
        raise HTTPException(status_code=400, detail="Downloaded path is not a regular file")
    if p.is_symlink():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Symlinks are not allowed for download handoff")

    suffix_lower = p.suffix.lower()
    if suffix_lower in {".crdownload", ".tmp", ".part", ".download"}:
        raise HTTPException(status_code=400, detail="Incomplete or temporary download file cannot be handed off")

    downloads_root = get_chrome_downloads_dir()

    # STRICT: File MUST be inside the configured Chrome Downloads directory!
    # settings.DATA_DIR / "tmp" and arbitrary temp folders are strictly FORBIDDEN!
    try:
        p.relative_to(downloads_root)
    except ValueError:
        logger.warning(f"Rejected unauthorized download handoff path outside configured Chrome Downloads directory: {p} (configured: {downloads_root})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: file path is not within the configured Chrome Downloads directory ({downloads_root})"
        )

    file_size = p.stat().st_size
    if file_size > MAX_MEDIA_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size ({MAX_MEDIA_FILE_BYTES} bytes)"
        )

    return p


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

# --- Target Picker Endpoint ---

@router.get("/targets")
def list_available_targets(
    authenticated: bool = Depends(verify_session_or_token),
    db: Session = Depends(get_db)
):
    """
    List existing conversations in OWI that can be selected as capture targets.
    Exposes conversation ID, title, source_type, message_count, and timestamps.
    """
    convs = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
    res = []
    for c in convs:
        res.append({
            "id": c.id,
            "title": c.title,
            "source_type": c.source_type,
            "message_count": c.message_count or 0,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None
        })
    return {"targets": res}

@router.post("/session/cancel")
@router.post("/cancel")
def cancel_companion_capture_session(
    req: CaptureSessionCancelRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """
    Cancel an active capture session to stop new capture/enqueue work.
    Preserves all already saved originals, attachment records, and queued/completed processing.
    """
    mark_capture_session_cancelled(req.session_id)
    return {
        "status": "cancelled",
        "session_id": req.session_id,
        "reason": req.reason or "cancelled_by_user"
    }

# --- Media Upload Endpoints (Direct and Chunked Session) ---

def get_media_session_dir() -> Path:
    s_dir = (settings.DATA_DIR / "tmp" / "sessions").resolve()
    s_dir.mkdir(parents=True, exist_ok=True)
    return s_dir

@router.post("/media/upload")
def upload_companion_media_direct(
    req: MediaUploadDirectRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """
    Direct authenticated media upload for bounded files.
    Validates MIME, sanitizes filename (preventing path traversal),
    computes/verifies SHA256, writes atomically to safe subfolder,
    and idempotently links MediaAsset to the Message/Conversation.
    """
    if not req.media_base64:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing media binary payload")

    try:
        media_bytes = base64.b64decode(req.media_base64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 payload")

    if len(media_bytes) > MAX_MEDIA_DIRECT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum direct upload limit ({MAX_MEDIA_DIRECT_BYTES} bytes). Use chunked session upload."
        )

    # Validate chat title is not an invalid UI element
    if req.chat_title and is_invalid_title(req.chat_title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chat title '{req.chat_title}'. Real conversation title must be provided."
        )

    # Validate target conversation & confirmation before writing file (P0 4)
    conv = None
    if req.conversation_id is not None:
        target = db.query(Conversation).filter(Conversation.id == req.conversation_id).first()
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target conversation ID {req.conversation_id} not found."
            )
        if target.source_type != "companion" and not req.confirm_target_merge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Explicit confirmation required to merge into imported conversation '{target.title}' (ID {target.id}, {target.source_type})."
            )
        if req.chat_title and not is_matching_chat_title(target.title, req.chat_title):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target conversation title mismatch: selected target '{target.title}' (ID {target.id}) does not match capture chat title '{req.chat_title}'."
            )
        conv = target
    elif req.chat_title:
        conv = db.query(Conversation).filter(
            Conversation.title == req.chat_title,
            Conversation.source_type == "companion"
        ).first()

    if not conv:
        if req.chat_title:
            conv = Conversation(
                title=req.chat_title,
                source_type="companion",
                message_count=0
            )
            db.add(conv)
            db.flush()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target conversation must be specified or chat_title provided."
            )

    msg = None
    if req.message_id is not None:
        msg = db.query(Message).filter(
            Message.id == req.message_id,
            Message.conversation_id == conv.id
        ).first()
        if not msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Message ID {req.message_id} not found in conversation {conv.id}."
            )
    elif req.platform_msg_id:
        msg = db.query(Message).filter(
            Message.raw_text == req.platform_msg_id,
            Message.conversation_id == conv.id
        ).first()

    category = determine_media_category(req.file_name, req.mime_type, req.file_type)
    computed_sha = hashlib.sha256(media_bytes).hexdigest()
    safe_name = sanitize_media_filename(req.file_name)
    final_name_expected = f"browser_{computed_sha[:10]}_{safe_name}"
    media_root = (settings.DATA_DIR / "media").resolve()
    media_dir = (media_root / category).resolve()
    final_path_check = (media_dir / final_name_expected).resolve()
    file_existed_before = final_path_check.exists()

    final_path, final_name, sha, file_size = save_media_file_atomically(
        media_bytes=media_bytes,
        category=category,
        raw_filename=req.file_name,
        expected_sha256=req.sha256
    )

    try:
        asset = link_media_asset_to_message(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            final_path=final_path,
            file_name=final_name,
            category=category,
            mime_type=req.mime_type,
            file_size=file_size,
            sha256_hash=sha,
            message_key=req.message_key or req.platform_msg_id,
            attachment_position=req.attachment_position
        )
        rec = record_attachment_status(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            file_name=req.file_name,
            file_type=category,
            status="saved-original",
            session_id=req.session_id,
            message_key=req.message_key or req.platform_msg_id,
            attachment_position=req.attachment_position,
            mime_type=req.mime_type,
            file_size=file_size,
            sha256_hash=sha,
            media_asset_id=asset.id,
            reason=req.reason
        )
        db.commit()
    except Exception as e:
        db.rollback()
        if not file_existed_before and final_path.exists():
            final_path.unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Failed to persist uploaded media: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to persist media asset: {e}")

    # Enqueue background processing idempotently after DB/file transaction is committed
    job_id = enqueue_companion_media_asset(
        asset_id=asset.id,
        db=db,
        session_id=req.session_id
    )

    return {
        "status": "success",
        "asset_id": asset.id,
        "message_id": msg.id if msg else None,
        "conversation_id": conv.id,
        "file_name": final_name,
        "category": category,
        "file_size": file_size,
        "sha256": sha,
        "attachment_status": "saved-original",
        "job_id": job_id,
        "processing_status": asset.processing_status
    }

@router.post("/media/session/start")
def start_media_upload_session(
    req: MediaSessionStartRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """Start chunked upload session for large media files."""
    if req.total_bytes > MAX_MEDIA_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size ({MAX_MEDIA_FILE_BYTES} bytes)"
        )
    if req.total_chunks > MAX_CHUNKS_PER_SESSION or req.total_chunks <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid total_chunks (must be between 1 and 500)")

    safe_session_id = re.sub(r'[^a-zA-Z0-9_\-]', '', req.session_id)
    if not safe_session_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session_id")

    # Validate chat title is not an invalid UI element
    if req.chat_title and is_invalid_title(req.chat_title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chat title '{req.chat_title}'. Real conversation title must be provided."
        )

    # Validate target conversation & confirmation before starting session (P0 4)
    if req.conversation_id is not None:
        target = db.query(Conversation).filter(Conversation.id == req.conversation_id).first()
        if not target:
            raise HTTPException(status_code=404, detail=f"Target conversation ID {req.conversation_id} not found.")
        if target.source_type != "companion" and not req.confirm_target_merge:
            raise HTTPException(
                status_code=400,
                detail=f"Explicit confirmation required to merge into imported conversation '{target.title}' (ID {target.id}, {target.source_type})."
            )
        if req.chat_title and not is_matching_chat_title(target.title, req.chat_title):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target conversation title mismatch: selected target '{target.title}' (ID {target.id}) does not match capture chat title '{req.chat_title}'."
            )
        if req.message_id is not None:
            msg = db.query(Message).filter(Message.id == req.message_id, Message.conversation_id == target.id).first()
            if not msg:
                raise HTTPException(status_code=404, detail=f"Message ID {req.message_id} not found in conversation {target.id}.")

    s_dir = get_media_session_dir()
    session_dir = s_dir / safe_session_id
    meta_file = session_dir / "meta.json"
    chunks_dir = session_dir / "chunks"

    if session_dir.exists():
        if req.restart:
            shutil.rmtree(session_dir, ignore_errors=True)
            session_dir.mkdir(parents=True, exist_ok=True)
            chunks_dir.mkdir(parents=True, exist_ok=True)
        elif meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    existing_meta = json.load(f)
                if (existing_meta.get("file_name") == req.file_name and
                    existing_meta.get("total_bytes") == req.total_bytes and
                    existing_meta.get("total_chunks") == req.total_chunks and
                    (existing_meta.get("sha256") or "").lower() == (req.sha256 or "").lower()):
                    return {"status": "session_resumed", "session_id": safe_session_id}
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Active upload session exists with different parameters. Pass restart=true to restart."
                    )
            except json.JSONDecodeError:
                shutil.rmtree(session_dir, ignore_errors=True)
                session_dir.mkdir(parents=True, exist_ok=True)
                chunks_dir.mkdir(parents=True, exist_ok=True)
    else:
        session_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir.mkdir(parents=True, exist_ok=True)

    session_info = req.model_dump()
    session_info["received_chunks"] = []
    session_info["bytes_received"] = 0

    tmp_meta = tempfile.NamedTemporaryFile(dir=session_dir, prefix="meta_", suffix=".tmp", delete=False, mode="w", encoding="utf-8")
    json.dump(session_info, tmp_meta)
    tmp_meta.close()
    Path(tmp_meta.name).replace(meta_file)

    return {"status": "session_started", "session_id": safe_session_id}

@router.post("/media/session/chunk")
def append_media_session_chunk(
    req: MediaSessionChunkRequest,
    authenticated: bool = Depends(verify_companion_token)
):
    """Append a binary chunk to an active upload session with idempotency check."""
    try:
        chunk_bytes = base64.b64decode(req.chunk_base64)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid base64 chunk payload")

    if len(chunk_bytes) > MAX_CHUNK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Chunk size exceeds maximum limit ({MAX_CHUNK_BYTES} bytes)"
        )

    safe_session_id = re.sub(r'[^a-zA-Z0-9_\-]', '', req.session_id)
    s_dir = get_media_session_dir()
    session_dir = s_dir / safe_session_id
    meta_file = session_dir / "meta.json"
    chunks_dir = session_dir / "chunks"

    if not session_dir.exists() or not meta_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found or expired")

    with open(meta_file, "r", encoding="utf-8") as f:
        session_info = json.load(f)

    total_chunks = session_info.get("total_chunks", 1)
    if req.chunk_index < 0 or req.chunk_index >= total_chunks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid chunk_index {req.chunk_index}; session expects 0 to {total_chunks - 1}")

    chunk_file = chunks_dir / f"chunk_{req.chunk_index:05d}.part"
    if chunk_file.exists():
        if chunk_file.stat().st_size == len(chunk_bytes) and chunk_file.read_bytes() == chunk_bytes:
            return {
                "status": "chunk_appended",
                "session_id": safe_session_id,
                "chunk_index": req.chunk_index,
                "bytes_received": session_info["bytes_received"]
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chunk {req.chunk_index} already received with different content"
            )

    if session_info["bytes_received"] + len(chunk_bytes) > MAX_MEDIA_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Total upload size exceeds maximum allowed")

    tmp_chunk = tempfile.NamedTemporaryFile(dir=session_dir, prefix="chk_", suffix=".tmp", delete=False)
    tmp_chunk.write(chunk_bytes)
    tmp_chunk.close()
    Path(tmp_chunk.name).replace(chunk_file)

    if req.chunk_index not in session_info["received_chunks"]:
        session_info["received_chunks"].append(req.chunk_index)
        session_info["bytes_received"] += len(chunk_bytes)

    tmp_meta = tempfile.NamedTemporaryFile(dir=session_dir, prefix="meta_", suffix=".tmp", delete=False, mode="w", encoding="utf-8")
    json.dump(session_info, tmp_meta)
    tmp_meta.close()
    Path(tmp_meta.name).replace(meta_file)

    return {
        "status": "chunk_appended",
        "session_id": safe_session_id,
        "chunk_index": req.chunk_index,
        "bytes_received": session_info["bytes_received"]
    }

@router.post("/media/session/finish")
def finish_media_upload_session(
    req: MediaSessionFinishRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """Finalize upload session: stream chunks, verify SHA256, atomically move to storage, link to message."""
    safe_session_id = re.sub(r'[^a-zA-Z0-9_\-]', '', req.session_id)
    s_dir = get_media_session_dir()
    session_dir = s_dir / safe_session_id
    meta_file = session_dir / "meta.json"
    chunks_dir = session_dir / "chunks"

    if not session_dir.exists() or not meta_file.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found or incomplete")

    with open(meta_file, "r", encoding="utf-8") as f:
        session_info = json.load(f)

    total_chunks = session_info.get("total_chunks", 1)
    missing = [idx for idx in range(total_chunks) if not (chunks_dir / f"chunk_{idx:05d}.part").exists()]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incomplete upload session: missing {len(missing)} chunks"
        )

    # Validate target conversation & confirmation (P0 4)
    conv = None
    if session_info.get("conversation_id") is not None:
        target = db.query(Conversation).filter(Conversation.id == session_info["conversation_id"]).first()
        if not target:
            raise HTTPException(status_code=404, detail="Target conversation not found.")
        if target.source_type != "companion" and not session_info.get("confirm_target_merge"):
            raise HTTPException(
                status_code=400,
                detail=f"Explicit confirmation required to merge into imported conversation '{target.title}' (ID {target.id}, {target.source_type})."
            )
        conv = target
    elif session_info.get("chat_title"):
        conv = db.query(Conversation).filter(
            Conversation.title == session_info["chat_title"],
            Conversation.source_type == "companion"
        ).first()

    if not conv:
        if session_info.get("chat_title"):
            conv = Conversation(
                title=session_info["chat_title"],
                source_type="companion",
                message_count=0
            )
            db.add(conv)
            db.flush()
        else:
            raise HTTPException(status_code=400, detail="Target conversation must be specified or chat_title provided.")

    msg = None
    if session_info.get("message_id") is not None:
        msg = db.query(Message).filter(
            Message.id == session_info["message_id"],
            Message.conversation_id == conv.id
        ).first()
        if not msg:
            raise HTTPException(status_code=404, detail=f"Message ID {session_info['message_id']} not found in conversation {conv.id}.")
    elif session_info.get("platform_msg_id"):
        msg = db.query(Message).filter(
            Message.raw_text == session_info["platform_msg_id"],
            Message.conversation_id == conv.id
        ).first()

    # Stream assemble chunks into temp file while computing SHA256 (P1 5)
    temp_dir = settings.DATA_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_assembled = tempfile.NamedTemporaryFile(dir=temp_dir, prefix="owi_assembled_", suffix=".tmp", delete=False)

    hasher = hashlib.sha256()
    total_bytes_written = 0

    try:
        for idx in range(total_chunks):
            chk_path = chunks_dir / f"chunk_{idx:05d}.part"
            with open(chk_path, "rb") as cf:
                while True:
                    block = cf.read(65536)
                    if not block:
                        break
                    total_bytes_written += len(block)
                    if total_bytes_written > MAX_MEDIA_FILE_BYTES:
                        temp_assembled.close()
                        Path(temp_assembled.name).unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File exceeds maximum allowed size ({MAX_MEDIA_FILE_BYTES} bytes)"
                        )
                    hasher.update(block)
                    temp_assembled.write(block)
        temp_assembled.close()
    except Exception as e:
        temp_assembled.close()
        Path(temp_assembled.name).unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Failed to assemble media chunks: {e}")

    total_bytes_declared = session_info.get("total_bytes")
    if total_bytes_declared is not None and total_bytes_written != total_bytes_declared:
        Path(temp_assembled.name).unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Assembled file size ({total_bytes_written} bytes) does not match declared total_bytes ({total_bytes_declared} bytes)"
        )

    computed_sha = hasher.hexdigest()
    expected_sha = session_info.get("sha256")
    if not expected_sha:
        Path(temp_assembled.name).unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing required expected SHA256 checksum for chunked session")
    if expected_sha.strip().lower() != computed_sha.lower():
        Path(temp_assembled.name).unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SHA256 checksum mismatch")

    category = determine_media_category(
        session_info.get("file_name", "media.dat"),
        session_info.get("mime_type"),
        session_info.get("file_type")
    )
    safe_name = sanitize_media_filename(session_info.get("file_name", "media.dat"))
    final_name = f"browser_{computed_sha[:10]}_{safe_name}"

    media_root = (settings.DATA_DIR / "media").resolve()
    media_dir = (media_root / category).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)

    final_path = (media_dir / final_name).resolve()
    try:
        final_path.relative_to(media_root)
    except ValueError:
        Path(temp_assembled.name).unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid media destination path")

    file_reused = False
    if final_path.exists() and final_path.stat().st_size == total_bytes_written:
        existing_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
        if existing_sha.lower() == computed_sha.lower():
            Path(temp_assembled.name).unlink(missing_ok=True)
            file_reused = True

    if not file_reused:
        Path(temp_assembled.name).replace(final_path)

    try:
        asset = link_media_asset_to_message(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            final_path=final_path,
            file_name=final_name,
            category=category,
            mime_type=session_info.get("mime_type"),
            file_size=total_bytes_written,
            sha256_hash=computed_sha,
            message_key=session_info.get("message_key") or session_info.get("platform_msg_id"),
            attachment_position=session_info.get("attachment_position")
        )
        rec = record_attachment_status(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            file_name=session_info.get("file_name", "media.dat"),
            file_type=category,
            status="saved-original",
            session_id=session_info.get("capture_session_id") or safe_session_id,
            message_key=session_info.get("message_key") or session_info.get("platform_msg_id"),
            attachment_position=session_info.get("attachment_position"),
            mime_type=session_info.get("mime_type"),
            file_size=total_bytes_written,
            sha256_hash=computed_sha,
            media_asset_id=asset.id,
            reason=session_info.get("reason")
        )
        db.commit()

        shutil.rmtree(session_dir, ignore_errors=True)

        cap_session_id = session_info.get("capture_session_id") or safe_session_id
        job_id = enqueue_companion_media_asset(
            asset_id=asset.id,
            db=db,
            session_id=cap_session_id
        )

        return {
            "status": "success",
            "asset_id": asset.id,
            "message_id": msg.id if msg else None,
            "conversation_id": conv.id,
            "file_name": final_name,
            "category": category,
            "file_size": total_bytes_written,
            "sha256": computed_sha,
            "attachment_status": "saved-original",
            "job_id": job_id,
            "processing_status": asset.processing_status
        }
    except Exception as e:
        db.rollback()
        if not file_reused and final_path.exists():
            final_path.unlink(missing_ok=True)
        shutil.rmtree(session_dir, ignore_errors=True)
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Failed to finish media upload session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload session finalization failed: {e}")

@router.post("/media/handoff")
def handoff_companion_media_download(
    req: MediaDownloadHandoffRequest,
    authenticated: bool = Depends(verify_companion_token),
    db: Session = Depends(get_db)
):
    """
    Scoped Chrome downloads handoff for WhatsApp Web attachments.
    Validates that download_path is strictly within authorized user Downloads folder.
    Limits file size, verifies SHA256, binds to message key + attachment position + selected conversation.
    Atomically copies file into data/media subfolder and links MediaAsset & AttachmentRecord.
    Never reads arbitrary paths or transmits to cloud.
    """
    safe_source_path = validate_download_path(req.download_path)

    file_size = safe_source_path.stat().st_size
    if file_size > MAX_MEDIA_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size ({MAX_MEDIA_FILE_BYTES} bytes)"
        )

    if req.chat_title and is_invalid_title(req.chat_title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chat title '{req.chat_title}'. Real conversation title must be provided."
        )

    conv = None
    if req.conversation_id is not None:
        target = db.query(Conversation).filter(Conversation.id == req.conversation_id).first()
        if not target:
            raise HTTPException(status_code=404, detail=f"Target conversation ID {req.conversation_id} not found.")
        if target.source_type != "companion" and not req.confirm_target_merge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Explicit confirmation required to merge into imported conversation '{target.title}' (ID {target.id}, {target.source_type})."
            )
        if req.chat_title and not is_matching_chat_title(target.title, req.chat_title):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target conversation title mismatch: selected target '{target.title}' (ID {target.id}) does not match capture chat title '{req.chat_title}'."
            )
        conv = target
    elif req.chat_title:
        conv = db.query(Conversation).filter(
            Conversation.title == req.chat_title,
            Conversation.source_type == "companion"
        ).first()

    if not conv:
        if req.chat_title:
            conv = Conversation(title=req.chat_title, source_type="companion", message_count=0)
            db.add(conv)
            db.flush()
        else:
            raise HTTPException(status_code=400, detail="Target conversation must be specified or chat_title provided.")

    msg = None
    if req.message_id is not None:
        msg = db.query(Message).filter(Message.id == req.message_id, Message.conversation_id == conv.id).first()
        if not msg:
            raise HTTPException(status_code=404, detail=f"Message ID {req.message_id} not found in conversation {conv.id}.")
    elif req.platform_msg_id:
        msg = db.query(Message).filter(Message.raw_text == req.platform_msg_id, Message.conversation_id == conv.id).first()

    media_bytes = safe_source_path.read_bytes()
    category = determine_media_category(req.file_name, req.mime_type, req.file_type)

    final_path, final_name, sha, f_size = save_media_file_atomically(
        media_bytes=media_bytes,
        category=category,
        raw_filename=req.file_name,
        expected_sha256=req.sha256
    )

    try:
        asset = link_media_asset_to_message(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            final_path=final_path,
            file_name=final_name,
            category=category,
            mime_type=req.mime_type,
            file_size=f_size,
            sha256_hash=sha,
            message_key=req.message_key or req.platform_msg_id,
            attachment_position=req.attachment_position
        )
        rec = record_attachment_status(
            db=db,
            conversation_id=conv.id,
            message_id=msg.id if msg else None,
            file_name=req.file_name,
            file_type=category,
            status="saved-original",
            session_id=req.session_id,
            message_key=req.message_key or req.platform_msg_id,
            attachment_position=req.attachment_position,
            mime_type=req.mime_type,
            file_size=f_size,
            sha256_hash=sha,
            media_asset_id=asset.id,
            reason=req.reason
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to persist media handoff asset: {e}")

    # Enqueue background processing idempotently after DB/file transaction is committed
    job_id = enqueue_companion_media_asset(
        asset_id=asset.id,
        db=db,
        session_id=req.session_id
    )

    return {
        "status": "success",
        "asset_id": asset.id,
        "message_id": msg.id if msg else None,
        "conversation_id": conv.id,
        "file_name": final_name,
        "category": category,
        "file_size": f_size,
        "sha256": sha,
        "attachment_status": "saved-original",
        "job_id": job_id,
        "processing_status": asset.processing_status
    }

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
    Supports deliberate target conversation selection and defensible overlap matching.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="No messages provided for capture.")

    # Validate chat title is not an invalid UI string
    if req.chat_title and is_invalid_title(req.chat_title):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chat title '{req.chat_title}'. WhatsApp Web UI profile/contact element detected instead of actual conversation title."
        )

    # 1. Target Conversation Selection
    conv = None
    if req.target_conversation_id is not None:
        target = db.query(Conversation).filter(Conversation.id == req.target_conversation_id).first()
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target conversation ID {req.target_conversation_id} not found."
            )
        if target.source_type != "companion" and not req.confirm_target_merge:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Explicit confirmation required to merge into imported conversation '{target.title}' (ID {target.id}, {target.source_type})."
            )
        if req.chat_title and not is_matching_chat_title(target.title, req.chat_title):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target conversation title mismatch: selected target '{target.title}' (ID {target.id}) does not match capture chat title '{req.chat_title}'."
            )
        conv = target
    else:
        # Find or create companion conversation (NEVER match across source types by title alone!)
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

    touched_message_ids = []
    candidate_asset_ids_to_enqueue: List[int] = []

    for m in req.messages:
        parsed_dt = parse_companion_timestamp(m.timestamp, default_day_first=day_first)
        if not parsed_dt and m.capture_timestamp:
            parsed_dt = parse_companion_timestamp(m.capture_timestamp, default_day_first=day_first)

        if parsed_dt:
            dt = parsed_dt
            provenance = "verified"
        else:
            dt = now_utc
            provenance = "unverified_fallback"
            unverified_count += 1

        msg_id_key = m.platform_msg_id
        if not msg_id_key:
            dt_repr = dt.isoformat() if provenance == "verified" else "unverified_fallback"
            h = hashlib.sha256(f"{m.sender}|{dt_repr}|{m.text}".encode("utf-8")).hexdigest()[:24]
            msg_id_key = f"synth_{h}"

        # Match existing message: platform_msg_id OR defensible overlap matching
        existing = find_matching_target_message(
            db=db,
            conv_id=conv.id,
            platform_msg_id=m.platform_msg_id,
            dt=dt,
            sender=m.sender,
            text=m.text,
            provenance=provenance
        )

        target_msg = None
        if existing:
            skipped_count += 1
            target_msg = existing
        else:
            msg_type = m.media_type or ("image" if m.has_media else "text")
            target_msg = Message(
                conversation_id=conv.id,
                sender_name=m.sender,
                timestamp=dt,
                timestamp_provenance=provenance,
                content=m.text,
                message_type=msg_type,
                raw_text=msg_id_key,
                has_attachment=m.has_media or bool(m.attachments),
                attachment_name=m.media_filename,
                attachment_status=m.attachment_status or "none"
            )
            db.add(target_msg)
            db.flush()

            # Sync to full-text search index (FTS5)
            try:
                db.execute(
                    text("INSERT INTO messages_fts (message_id, content, sender_name) VALUES (:id, :content, :sender)"),
                    {"id": target_msg.id, "content": target_msg.content, "sender": target_msg.sender_name}
                )
            except Exception:
                pass

            added_count += 1

        touched_message_ids.append(target_msg.id)

        # 1. Reconcile pending media previously uploaded for this message (P0 1 & P0 5)
        candidate_keys = {k for k in [m.platform_msg_id, msg_id_key, getattr(existing, "raw_text", None)] if k}
        pending_recs = []
        if candidate_keys:
            pending_recs = db.query(AttachmentRecord).filter(
                AttachmentRecord.conversation_id == conv.id,
                AttachmentRecord.message_key.in_(candidate_keys),
                AttachmentRecord.message_id == None
            ).all()

        for prec in pending_recs:
            prec.message_id = target_msg.id
            if prec.media_asset_id:
                asset = db.query(MediaAsset).filter(MediaAsset.id == prec.media_asset_id).first()
                if asset:
                    asset.message_id = target_msg.id
                    if Path(asset.file_path).exists():
                        target_msg.has_attachment = True
                        if not target_msg.attachment_name:
                            target_msg.attachment_name = prec.file_name or asset.file_name
                        target_msg.attachment_status = "saved-original"
                        prec.status = "saved-original"
                        candidate_asset_ids_to_enqueue.append(asset.id)
                    else:
                        prec.status = "failed"
                        prec.reason = "missing_physical_file"
            db.flush()

        if candidate_keys:
            unlinked_assets = db.query(MediaAsset).filter(
                MediaAsset.conversation_id == conv.id,
                MediaAsset.message_id == None
            ).all()
            for ua in unlinked_assets:
                matching_rec = db.query(AttachmentRecord).filter(
                    AttachmentRecord.media_asset_id == ua.id,
                    AttachmentRecord.message_key.in_(candidate_keys)
                ).first()
                if matching_rec:
                    ua.message_id = target_msg.id
                    matching_rec.message_id = target_msg.id
                    if Path(ua.file_path).exists():
                        target_msg.has_attachment = True
                        if not target_msg.attachment_name:
                            target_msg.attachment_name = matching_rec.file_name or ua.file_name
                        target_msg.attachment_status = "saved-original"
                        matching_rec.status = "saved-original"
                        candidate_asset_ids_to_enqueue.append(ua.id)
                    db.flush()

        has_media_content = m.has_media or bool(m.media_base64) or bool(m.attachments)
        if has_media_content:
            target_msg.has_attachment = True
            if m.media_filename and not target_msg.attachment_name:
                target_msg.attachment_name = m.media_filename

        # 2. Process multi-attachment payload (m.attachments) (P0 3 & P0 5)
        if m.attachments:
            for att_idx, att in enumerate(m.attachments, start=1):
                cat = determine_media_category(att.file_name, att.mime_type, att.file_type)
                att_item_status = att.attachment_status or "unavailable"
                asset_id = None
                sha_val = att.sha256
                f_size = att.file_size or 0
                f_name = att.file_name
                reason = att.reason
                att_pos = att.attachment_position or att_idx

                if att.media_base64:
                    try:
                        att_bytes = base64.b64decode(att.media_base64)
                        f_path, saved_f_name, sha_val, f_size = save_media_file_atomically(
                            media_bytes=att_bytes,
                            category=cat,
                            raw_filename=att.file_name,
                            expected_sha256=att.sha256
                        )
                        asset = link_media_asset_to_message(
                            db=db,
                            conversation_id=conv.id,
                            message_id=target_msg.id,
                            final_path=f_path,
                            file_name=saved_f_name,
                            category=cat,
                            mime_type=att.mime_type,
                            file_size=f_size,
                            sha256_hash=sha_val,
                            message_key=m.platform_msg_id,
                            attachment_position=att_pos
                        )
                        asset_id = asset.id
                        att_item_status = "saved-original"
                        if Path(f_path).exists():
                            candidate_asset_ids_to_enqueue.append(asset.id)
                    except Exception as e:
                        logger.warning(f"Could not store multi-attachment media: {e}")
                        att_item_status = "failed"
                        reason = reason or "save_failed"
                else:
                    existing_asset = None
                    matching_rec = db.query(AttachmentRecord).filter(
                        AttachmentRecord.conversation_id == conv.id,
                        AttachmentRecord.message_id == target_msg.id,
                        AttachmentRecord.attachment_position == att_pos
                    ).first()
                    if matching_rec and matching_rec.media_asset_id:
                        existing_asset = db.query(MediaAsset).filter(MediaAsset.id == matching_rec.media_asset_id).first()

                    if not existing_asset and sha_val:
                        existing_asset = db.query(MediaAsset).filter(
                            MediaAsset.conversation_id == conv.id,
                            MediaAsset.message_id == target_msg.id,
                            MediaAsset.sha256_hash == sha_val
                        ).first()
                    if not existing_asset and att.file_name:
                        existing_asset = db.query(MediaAsset).filter(
                            MediaAsset.conversation_id == conv.id,
                            MediaAsset.message_id == target_msg.id,
                            MediaAsset.file_name.like(f"%{att.file_name}")
                        ).first()

                    if existing_asset and Path(existing_asset.file_path).exists():
                        asset_id = existing_asset.id
                        sha_val = existing_asset.sha256_hash
                        f_size = existing_asset.file_size
                        att_item_status = "saved-original"
                        candidate_asset_ids_to_enqueue.append(existing_asset.id)
                    else:
                        if att_item_status == "saved-original":
                            att_item_status = "failed"
                            reason = reason or "missing_physical_file"

                record_attachment_status(
                    db=db,
                    conversation_id=conv.id,
                    message_id=target_msg.id,
                    file_name=att.file_name,
                    file_type=cat,
                    status=att_item_status,
                    session_id=req.session_id,
                    message_key=m.platform_msg_id,
                    attachment_position=att_pos,
                    mime_type=att.mime_type,
                    file_size=f_size,
                    sha256_hash=sha_val,
                    media_asset_id=asset_id,
                    reason=reason
                )

        # 3. Single media payload (m.media_base64)
        elif m.media_base64:
            orig_name = m.media_filename or "media.dat"
            try:
                m_bytes = base64.b64decode(m.media_base64)
                cat = determine_media_category(orig_name, m.media_mime, m.media_type)
                f_path, f_name, sha, f_size = save_media_file_atomically(
                    media_bytes=m_bytes,
                    category=cat,
                    raw_filename=orig_name
                )
                asset = link_media_asset_to_message(
                    db=db,
                    conversation_id=conv.id,
                    message_id=target_msg.id,
                    final_path=f_path,
                    file_name=f_name,
                    category=cat,
                    mime_type=m.media_mime,
                    file_size=f_size,
                    sha256_hash=sha,
                    message_key=m.platform_msg_id,
                    attachment_position=1
                )
                record_attachment_status(
                    db=db,
                    conversation_id=conv.id,
                    message_id=target_msg.id,
                    file_name=orig_name,
                    file_type=cat,
                    status="saved-original",
                    session_id=req.session_id,
                    message_key=m.platform_msg_id,
                    attachment_position=1,
                    mime_type=m.media_mime,
                    file_size=f_size,
                    sha256_hash=sha,
                    media_asset_id=asset.id
                )
                target_msg.attachment_status = "saved-original"
                if Path(f_path).exists():
                    candidate_asset_ids_to_enqueue.append(asset.id)
            except Exception as e:
                logger.warning(f"Could not store captured companion media: {e}")
                record_attachment_status(
                    db=db,
                    conversation_id=conv.id,
                    message_id=target_msg.id,
                    file_name=orig_name,
                    file_type="document",
                    status="failed",
                    session_id=req.session_id,
                    message_key=m.platform_msg_id,
                    attachment_position=1,
                    mime_type=m.media_mime,
                    reason="save_failed"
                )
                target_msg.attachment_status = "failed"

        # 4. Media declared without base64
        elif has_media_content:
            orig_name = m.media_filename or "media.dat"
            cat = determine_media_category(orig_name, m.media_mime, m.media_type)
            existing_asset = db.query(MediaAsset).filter(
                MediaAsset.conversation_id == conv.id,
                MediaAsset.message_id == target_msg.id
            ).first()

            if existing_asset and Path(existing_asset.file_path).exists():
                status_val = "saved-original"
                asset_id = existing_asset.id
                f_size = existing_asset.file_size
                sha_val = existing_asset.sha256_hash
                f_name = orig_name
                candidate_asset_ids_to_enqueue.append(existing_asset.id)
            else:
                status_val = m.attachment_status or "preview-only"
                if status_val == "saved-original":
                    status_val = "failed"
                asset_id = None
                f_size = 0
                sha_val = None
                f_name = orig_name

            record_attachment_status(
                db=db,
                conversation_id=conv.id,
                message_id=target_msg.id,
                file_name=f_name,
                file_type=cat,
                status=status_val,
                session_id=req.session_id,
                message_key=m.platform_msg_id,
                attachment_position=1,
                mime_type=m.media_mime,
                file_size=f_size,
                sha256_hash=sha_val,
                media_asset_id=asset_id
            )
            target_msg.attachment_status = status_val

        # Never report saved-original on a Message until its asset is actually linked
        if target_msg.attachment_status == "saved-original":
            has_real_asset = False
            for ma in target_msg.media_assets:
                if Path(ma.file_path).exists():
                    has_real_asset = True
                    break
            if not has_real_asset:
                target_msg.attachment_status = "failed"

    # Calculate attachments_summary from actual durable AttachmentRecord rows (P0 3)
    attachment_counts = {
        "saved_original": 0,
        "preview_only": 0,
        "unavailable": 0,
        "expired": 0,
        "too_large": 0,
        "failed": 0,
        "unsupported": 0
    }
    if touched_message_ids:
        records = db.query(AttachmentRecord).filter(
            AttachmentRecord.conversation_id == conv.id,
            AttachmentRecord.message_id.in_(touched_message_ids)
        ).all()
        for r in records:
            if r.status == "saved-original":
                attachment_counts["saved_original"] += 1
            elif r.status == "preview-only":
                attachment_counts["preview_only"] += 1
            elif r.status == "unavailable":
                attachment_counts["unavailable"] += 1
            elif r.status == "expired":
                attachment_counts["expired"] += 1
            elif r.status == "too-large":
                attachment_counts["too_large"] += 1
            elif r.status == "failed":
                attachment_counts["failed"] += 1
            elif r.status == "unsupported":
                attachment_counts["unsupported"] += 1

    # Recalculate message_count accurately from actual rows in DB
    conv.message_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
    conv.updated_at = datetime.utcnow()
    db.commit()

    if added_count > 0:
        LocalNLPEngine.analyze_conversation(conv.id, db)

    # Check for capture session cancellation
    session_cancelled = False
    if req.session_id and (
        req.partial_reason == "cancelled_by_user" or
        (req.completeness_status or "").lower() in ("cancelled", "cancel")
    ):
        mark_capture_session_cancelled(req.session_id)
        session_cancelled = True

    if not session_cancelled:
        # Enqueue background processing idempotently after DB/file transaction is committed
        for aid in dict.fromkeys(candidate_asset_ids_to_enqueue):
            enqueue_companion_media_asset(
                asset_id=aid,
                db=db,
                session_id=req.session_id
            )

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
        "source_type": conv.source_type,
        "messages_ingested": added_count,
        "duplicates_skipped": skipped_count,
        "unverified_timestamps": unverified_count,
        "session_id": req.session_id,
        "chunk_index": req.chunk_index,
        "total_chunks": req.total_chunks,
        "is_last_chunk": req.is_last_chunk,
        "completeness_status": effective_status,
        "partial_reason": effective_reason,
        "attachments_summary": {
            "total_detected": sum(attachment_counts.values()),
            **attachment_counts
        }
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
