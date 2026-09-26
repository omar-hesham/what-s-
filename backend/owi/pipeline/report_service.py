"""
Deterministic Evidence Inventory and Forensic Report Service for OWI.
Produces structured JSON inventories and factual Markdown reports without AI models or remote calls.
Strictly local-first, privacy-safe (no raw disk paths or tokens exposed), and provenance-grounded.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from sqlalchemy import func
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.core.hashing import compute_sha256
from owi.core.security import is_safe_path
from owi.db.models import Conversation, Message, MediaAsset, AttachmentRecord, Transcript, TranscriptSegment, DocumentRecord
from owi.ingest.whatsapp_parser import detect_attachment_type

# Omitted WhatsApp media placeholder detection patterns (multi-locale, Android, iOS, Web)
OMITTED_PLACEHOLDER_REGEX = re.compile(
    r"""(?ix)
    ^\s*<?\s*(?:
        voice\s+(?:message|note)|
        audio|
        image|photo|picture|
        video|
        document|file|
        sticker|
        gif|
        media
    )\s+omitted\s*>?\s*$
    |
    ^\s*<attached:\s*(?P<att_name>[^>]+)>\s*$
    |
    ^\s*(?P<file_att>[^\n]+?)\s+\((?:file\s+attached|ملف\s+مرفق)\)\s*$
    |
    ^\s*<?\s*(?:
        تم\s+استبعاد\s+(?:الصوت|الصورة|الفيديو|المستند|الوسائط)|
        ملف\s+(?:مرفق|محذوف)|
        صوت\s+مستبعد|
        صورة\s+مستبعدة|
        فيديو\s+مستبعد|
        مستبعد|مفقود
    )\s*>?\s*$
    """
)

from datetime import tzinfo, timedelta

class EgyptTzFallback(tzinfo):
    """Accurate Egyptian Daylight Saving Time (DST) timezone for Africa/Cairo."""
    def utcoffset(self, dt):
        if dt is None:
            return timedelta(hours=2)
        # Egypt DST: UTC+3 from last Friday of April to last Thursday of October; UTC+2 otherwise.
        if 5 <= dt.month <= 9:
            return timedelta(hours=3)
        elif dt.month in (11, 12, 1, 2, 3):
            return timedelta(hours=2)
        elif dt.month == 4:
            last_fri = 30 - ((datetime(dt.year, 4, 30).weekday() - 4) % 7)
            return timedelta(hours=3) if dt.day >= last_fri else timedelta(hours=2)
        elif dt.month == 10:
            last_thu = 31 - ((datetime(dt.year, 10, 31).weekday() - 3) % 7)
            return timedelta(hours=2) if dt.day > last_thu else timedelta(hours=3)
        return timedelta(hours=2)

    def dst(self, dt):
        offset = self.utcoffset(dt)
        return timedelta(hours=1) if offset == timedelta(hours=3) else timedelta(0)

    def tzname(self, dt):
        offset = self.utcoffset(dt)
        return "EEST" if offset == timedelta(hours=3) else "EET"

def get_source_timezone(tz_name: Optional[str] = None):
    name = tz_name or getattr(settings, "REPORT_TIMEZONE", "Africa/Cairo")
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(name)
    except Exception as e:
        if name in ("Africa/Cairo", "Egypt"):
            return EgyptTzFallback()
        raise ValueError(f"Configured timezone '{name}' is unavailable on this system: {e}")

def parse_filter_datetime(dt_val: Union[datetime, str, None], target_tz_name: Optional[str] = None) -> Optional[datetime]:
    """
    Parse incoming filter date/time string strictly.
    Contract: Database source timestamps are naive LOCAL wall times in source timezone (default Africa/Cairo).
    - If input is timezone-aware, convert to target local timezone and strip tzinfo.
    - If input is naive, preserve local wall time directly.
    Raises ValueError with static message if string cannot be parsed into a valid datetime.
    """
    if dt_val is None:
        return None

    src_tz = get_source_timezone(target_tz_name)

    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is not None:
            return dt_val.astimezone(src_tz).replace(tzinfo=None)
        return dt_val

    s = str(dt_val).strip()
    if not s:
        return None

    # Handle ISO 8601 with trailing 'Z' or offset
    if s.endswith("Z") or s.endswith("z"):
        s_iso = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s_iso)
            return dt.astimezone(src_tz).replace(tzinfo=None)
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(src_tz).replace(tzinfo=None)
        return dt
    except ValueError:
        pass

    # Standard formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y"
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass

    # Static error message without echoing invalid input
    raise ValueError("Invalid date format. Expected valid ISO 8601 string.")

def is_safe_media_path(file_path_str: Optional[str]) -> bool:
    """Ensure physical file path is strictly inside settings.DATA_DIR."""
    if not file_path_str:
        return False
    try:
        data_root = settings.DATA_DIR.resolve()
        p = Path(file_path_str).resolve()
        # Enforce relative_to data_root so symlinks/parent traversal cannot escape
        p.relative_to(data_root)
        return is_safe_path(data_root, p)
    except Exception:
        return False

def detect_omitted_placeholder(content: Optional[str]) -> Optional[Dict[str, str]]:
    """
    Check if a message content string is an omitted media placeholder.
    Returns metadata dict if placeholder, None otherwise.
    """
    if not content:
        return None
    clean = content.strip()
    m = OMITTED_PLACEHOLDER_REGEX.match(clean)
    if not m:
        return None

    lower = clean.lower()
    file_type = "document"
    suggested_name = "omitted_attachment"

    if "voice" in lower or "audio" in lower or "صوت" in lower:
        file_type = "audio"
        suggested_name = "voice_message_omitted.opus"
    elif "image" in lower or "photo" in lower or "picture" in lower or "صورة" in lower:
        file_type = "image"
        suggested_name = "image_omitted.jpg"
    elif "video" in lower or "فيديو" in lower:
        file_type = "video"
        suggested_name = "video_omitted.mp4"
    elif "document" in lower or "مستند" in lower:
        file_type = "document"
        suggested_name = "document_omitted.pdf"

    if m.groupdict().get("att_name"):
        suggested_name = m.group("att_name").strip()
        file_type = detect_attachment_type(suggested_name)
    elif m.groupdict().get("file_att"):
        suggested_name = m.group("file_att").strip()
        file_type = detect_attachment_type(suggested_name)

    return {
        "file_name": suggested_name,
        "file_type": file_type,
        "raw_placeholder": clean
    }

def format_timestamp(dt: Optional[datetime]) -> Optional[str]:
    """Format datetime into standard ISO-8601 string."""
    return dt.isoformat() if dt else None

def format_seconds(seconds: Optional[float]) -> str:
    """Format floating point seconds into mm:ss.mmm for forensic audio/video playback."""
    if seconds is None:
        return "00:00.000"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:06.3f}"

def escape_markdown_cell(val: Any) -> str:
    """Escape pipe characters and collapse newlines for safe Markdown table cells."""
    if val is None:
        return "N/A"
    return str(val).replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()

def sanitize_header_text(val: Any) -> str:
    """Sanitize title or header text to prevent markdown injection."""
    if val is None:
        return ""
    s = str(val).replace("\r", " ").replace("\n", " ").strip()
    s = re.sub(r'^[#>\-\*]+\s*', '', s)
    return s or "Untitled"


class ReportService:
    """
    Deterministic evidence inventory and forensic reporting service.
    Completely model-free, verifiable, and provenance-grounded.
    """

    @classmethod
    def evaluate_capture_coverage(
        cls,
        conv: Conversation,
        messages: List[Message],
        db: Session
    ) -> Dict[str, Any]:
        """
        Evaluate capture coverage truthfully.
        RULE: Never claim complete WhatsApp capture from DB message count alone;
        absence of durable verified capture-session coverage means unknown or partial coverage.
        Observed session IDs are reported separately from verified complete sessions.
        """
        source = (conv.source_type or "").lower()

        # Non-companion exports (export_txt, export_zip, etc.) never have verified session coverage
        if source != "companion":
            return {
                "status": "unknown",
                "is_complete": False,
                "reason": (
                    "Complete WhatsApp capture cannot be claimed solely from database message count. "
                    "Absence of durable verified capture-session coverage confirms coverage is unknown or partial."
                ),
                "observed_session_ids": [],
                "verified_session_id": None,
                "db_message_count": len(messages),
                "source_type": conv.source_type
            }

        # Check for unverified timestamps in messages
        unverified_count = sum(1 for m in messages if m.timestamp_provenance == "unverified_fallback")

        # Collect distinct observed session_ids
        observed_sessions = sorted(list({
            ar.session_id for m in messages for ar in m.attachment_records if ar.session_id
        }))

        if unverified_count > 0:
            return {
                "status": "partial",
                "is_complete": False,
                "reason": f"Capture session contains {unverified_count} unverified fallback timestamps.",
                "observed_session_ids": observed_sessions,
                "verified_session_id": None,
                "db_message_count": len(messages),
                "source_type": conv.source_type
            }

        # Unless a durable verified session record certifies full bounds traversal without interruption:
        return {
            "status": "partial",
            "is_complete": False,
            "reason": (
                "Absence of durable verified capture-session coverage. "
                "Complete WhatsApp capture cannot be claimed solely from database message count."
            ),
            "observed_session_ids": observed_sessions,
            "verified_session_id": None,
            "db_message_count": len(messages),
            "source_type": conv.source_type
        }

    @classmethod
    def build_inventory(
        cls,
        conversation_id: int,
        db: Session,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sender: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Build an exhaustive, per-attachment evidence inventory for a conversation.
        Verifies physical files on disk and SHA-256 hashes against path escapes.
        Identifies missing originals, placeholders, preview-only items, and derived text.
        Groups duplicate physical hashes without losing message or attachment identities.
        """
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            raise ValueError(f"Conversation #{conversation_id} not found.")

        # Build message query with filters
        msg_query = db.query(Message).filter(Message.conversation_id == conversation_id)
        if date_from:
            msg_query = msg_query.filter(Message.timestamp >= date_from)
        if date_to:
            msg_query = msg_query.filter(Message.timestamp <= date_to)
        if sender:
            # Prevent SQL wildcard injection: match literal sender name case-insensitively
            msg_query = msg_query.filter(func.lower(Message.sender_name) == sender.strip().lower())

        messages = msg_query.order_by(Message.timestamp.asc(), Message.id.asc()).all()

        inventory_items: List[Dict[str, Any]] = []
        item_counter = 0

        # Physical hash tracker for grouping duplicates
        # Keyed strictly by ACTUAL physical SHA256 of verified files (not wrong/stale recorded hashes)
        hash_groups: Dict[str, Dict[str, Any]] = {}

        # Scan each message for all attachments
        for m in messages:
            seen_attachment_record_ids: Set[int] = set()
            seen_media_asset_ids: Set[int] = set()

            # 1. Durable AttachmentRecord rows linked to this message
            for att_rec in m.attachment_records:
                seen_attachment_record_ids.add(att_rec.id)
                asset = att_rec.media_asset or (
                    db.query(MediaAsset).filter(MediaAsset.id == att_rec.media_asset_id).first()
                    if att_rec.media_asset_id else None
                )
                if asset:
                    seen_media_asset_ids.add(asset.id)

                inv_item = cls._inspect_attachment_item(
                    item_id=f"inv_{item_counter + 1}",
                    conversation_id=conv.id,
                    message=m,
                    attachment_record=att_rec,
                    media_asset=asset,
                    db=db
                )
                inventory_items.append(inv_item)
                item_counter += 1
                cls._record_hash_group(hash_groups, inv_item)

            # 2. MediaAsset rows on this message not linked via an AttachmentRecord
            for asset in m.media_assets:
                if asset.id in seen_media_asset_ids:
                    continue
                seen_media_asset_ids.add(asset.id)

                inv_item = cls._inspect_attachment_item(
                    item_id=f"inv_{item_counter + 1}",
                    conversation_id=conv.id,
                    message=m,
                    attachment_record=None,
                    media_asset=asset,
                    db=db
                )
                inventory_items.append(inv_item)
                item_counter += 1
                cls._record_hash_group(hash_groups, inv_item)

            # 3. Exactly ONE unresolved attachment identity per source message if no records/assets exist
            if not seen_attachment_record_ids and not seen_media_asset_ids:
                placeholder_info = detect_omitted_placeholder(m.content)
                if placeholder_info:
                    # Single omitted placeholder identity (retains detected voice/image/video/doc type)
                    inv_item = {
                        "inventory_id": f"inv_{item_counter + 1}",
                        "conversation_id": conv.id,
                        "message_id": m.id,
                        "message_timestamp": format_timestamp(m.timestamp),
                        "message_sender": m.sender_name,
                        "attachment_record_id": None,
                        "media_asset_id": None,
                        "file_name": placeholder_info["file_name"],
                        "file_type": placeholder_info["file_type"],
                        "mime_type": None,
                        "file_size": 0,
                        "sha256": None,
                        "record_sha256": None,
                        "asset_sha256": None,
                        "hash_conflict": False,
                        "durable_status": "unavailable",
                        "physical_availability": "not_applicable",
                        "integrity_status": "unavailable",
                        "acquisition_provenance": "omitted_placeholder",
                        "physical_status": "omitted_placeholder",
                        "file_exists": False,
                        "hash_verified": False,
                        "actual_sha256": None,
                        "processing_status": "unsupported",
                        "processing_method": None,
                        "processing_error": f"Placeholder in export: '{placeholder_info['raw_placeholder']}'",
                        "has_derived_text": False,
                        "derived_type": None,
                        "derived_text": None,
                        "derived_char_count": 0,
                        "is_machine_generated": False,
                        "is_placeholder": True,
                        "is_thumbnail_only": False,
                        "media_download_url": None
                    }
                    inventory_items.append(inv_item)
                    item_counter += 1
                elif m.has_attachment or m.attachment_name:
                    fname = m.attachment_name or "unspecified_attachment"
                    inv_item = {
                        "inventory_id": f"inv_{item_counter + 1}",
                        "conversation_id": conv.id,
                        "message_id": m.id,
                        "message_timestamp": format_timestamp(m.timestamp),
                        "message_sender": m.sender_name,
                        "attachment_record_id": None,
                        "media_asset_id": None,
                        "file_name": fname,
                        "file_type": detect_attachment_type(fname),
                        "mime_type": None,
                        "file_size": 0,
                        "sha256": None,
                        "record_sha256": None,
                        "asset_sha256": None,
                        "hash_conflict": False,
                        "durable_status": m.attachment_status or "unavailable",
                        "physical_availability": "missing",
                        "integrity_status": "unavailable",
                        "acquisition_provenance": "metadata_only",
                        "physical_status": "missing_on_disk",
                        "file_exists": False,
                        "hash_verified": False,
                        "actual_sha256": None,
                        "processing_status": "unprocessed",
                        "processing_method": None,
                        "processing_error": "Attachment metadata reference exists without physical file.",
                        "has_derived_text": False,
                        "derived_type": None,
                        "derived_text": None,
                        "derived_char_count": 0,
                        "is_machine_generated": False,
                        "is_placeholder": False,
                        "is_thumbnail_only": False,
                        "media_download_url": None
                    }
                    inventory_items.append(inv_item)
                    item_counter += 1

        # Summary calculations
        total_attachments = len(inventory_items)
        verified_count = sum(1 for it in inventory_items if it["physical_status"] == "verified_original")
        computed_only_count = sum(1 for it in inventory_items if it["physical_status"] == "computed_only")
        missing_count = sum(1 for it in inventory_items if it["physical_status"] == "missing_on_disk")
        mismatch_count = sum(1 for it in inventory_items if it["physical_status"] == "hash_mismatch")
        path_rejected_count = sum(1 for it in inventory_items if it["physical_status"] == "path_rejected")
        preview_count = sum(1 for it in inventory_items if it["physical_status"] == "preview_only")
        omitted_count = sum(1 for it in inventory_items if it["physical_status"] in ("omitted_placeholder", "unavailable", "expired", "too_large", "unsupported"))
        derived_text_count = sum(1 for it in inventory_items if it["has_derived_text"])
        unprocessed_failed_count = sum(1 for it in inventory_items if it["processing_status"] in ("unprocessed", "queued", "processing", "failed", "setup_needed"))

        # Physical bytes: compute unique vs total referenced from physical files
        total_physical_bytes = sum(it["file_size"] for it in inventory_items if it["file_exists"])
        unique_physical_bytes = sum(grp["file_size"] for grp in hash_groups.values() if grp.get("file_exists", False))

        coverage_info = cls.evaluate_capture_coverage(conv, messages, db)

        first_ts = format_timestamp(messages[0].timestamp) if messages else None
        last_ts = format_timestamp(messages[-1].timestamp) if messages else None

        duplicate_groups_list = [
            grp for grp in hash_groups.values() if grp["reference_count"] > 1
        ]
        duplicate_groups_list.sort(key=lambda g: g["reference_count"], reverse=True)

        return {
            "conversation_id": conv.id,
            "conversation_title": conv.title,
            "source_type": conv.source_type,
            "source_timestamp_timezone": getattr(settings, "REPORT_TIMEZONE", "Africa/Cairo"),
            "date_contract": "Database source timestamps are naive LOCAL wall times in source timezone. Timezone-aware query parameters are converted to source timezone and normalized to naive wall times. Timezone-naive parameters are matched directly.",
            "capture_coverage": coverage_info,
            "date_range": {
                "start": first_ts,
                "end": last_ts
            },
            "summary": {
                "total_messages_scanned": len(messages),
                "total_attachments_detected": total_attachments,
                "distinct_physical_hashes": len(hash_groups),
                "verified_physical_files": verified_count,
                "computed_only_files": computed_only_count,
                "missing_physical_files": missing_count,
                "hash_mismatches": mismatch_count,
                "path_rejected_files": path_rejected_count,
                "preview_only_attachments": preview_count,
                "unavailable_or_omitted": omitted_count,
                "processed_with_derived_text": derived_text_count,
                "unprocessed_or_failed": unprocessed_failed_count,
                "total_physical_bytes": total_physical_bytes,
                "unique_physical_bytes": unique_physical_bytes
            },
            "inventory": inventory_items,
            "duplicate_hash_groups": duplicate_groups_list
        }

    @classmethod
    def _inspect_attachment_item(
        cls,
        item_id: str,
        conversation_id: int,
        message: Message,
        attachment_record: Optional[AttachmentRecord],
        media_asset: Optional[MediaAsset],
        db: Session
    ) -> Dict[str, Any]:
        """Inspect and verify a single attachment instance against database records and physical disk."""
        fname = (
            (attachment_record.file_name if attachment_record else None) or
            (media_asset.file_name if media_asset else None) or
            message.attachment_name or
            "unnamed_media"
        )
        ftype = (
            (attachment_record.file_type if attachment_record else None) or
            (media_asset.file_type if media_asset else None) or
            detect_attachment_type(fname)
        )
        # Normalization: normalize plural types to canonical singular for report only
        if ftype == "images":
            ftype = "image"
        elif ftype == "documents":
            ftype = "document"
        mime = (
            (attachment_record.mime_type if attachment_record else None) or
            (media_asset.mime_type if media_asset else None)
        )
        recorded_size = (
            (attachment_record.file_size if attachment_record else None) or
            (media_asset.file_size if media_asset else 0) or 0
        )

        record_sha = (attachment_record.sha256_hash or "").strip().lower() if attachment_record else None
        asset_sha = (media_asset.sha256_hash or "").strip().lower() if media_asset else None

        # Expose discrepancy between attachment record sha and asset sha
        hash_conflict = bool(record_sha and asset_sha and record_sha != asset_sha)

        durable_status = (
            (attachment_record.status if attachment_record else None) or
            message.attachment_status or
            ("saved-original" if media_asset else "none")
        )

        file_exists = False
        actual_sha256 = None
        hash_verified = False
        physical_availability = "missing"
        integrity_status = "unavailable"
        acquisition_provenance = "preview_only" if durable_status == "preview-only" else "original"
        physical_status = "unavailable"
        safe_download_url = None
        proc_error = (media_asset.processing_error if media_asset else None) or (attachment_record.reason if attachment_record else None)

        if media_asset and media_asset.file_path:
            raw_path_str = media_asset.file_path
            # Security: Verify source paths stay strictly within configured media storage before hashing
            if not is_safe_media_path(raw_path_str):
                physical_availability = "path_escaped"
                integrity_status = "error"
                physical_status = "path_rejected"
                proc_error = "Path escape rejected: target file path is outside authorized media storage."
            else:
                p = Path(raw_path_str)
                if p.exists() and p.is_file():
                    file_exists = True
                    physical_availability = "available"
                    recorded_size = p.stat().st_size
                    try:
                        actual_sha256 = compute_sha256(p).lower()
                        # Determine integrity against recorded checksum
                        expected_sha = record_sha or asset_sha
                        if expected_sha:
                            if actual_sha256 == expected_sha:
                                hash_verified = True
                                integrity_status = "verified"
                            else:
                                hash_verified = False
                                integrity_status = "mismatch"
                        else:
                            # An unset expected hash is computed_only, not historically verified_original
                            hash_verified = False
                            integrity_status = "computed_only"
                            acquisition_provenance = "computed_only"

                        # Determine physical_status
                        # DEFECT 1 FIX: Preserve preview-only regardless of hash
                        if durable_status == "preview-only":
                            physical_status = "preview_only"
                            acquisition_provenance = "preview_only"
                        elif integrity_status == "mismatch":
                            physical_status = "hash_mismatch"
                        elif integrity_status == "computed_only":
                            physical_status = "computed_only"
                        else:
                            physical_status = "verified_original"

                        safe_download_url = f"/api/media/{media_asset.id}/file"
                    except Exception as read_err:
                        integrity_status = "error"
                        physical_status = "read_error"
                        proc_error = f"Physical file read error: {type(read_err).__name__}"
                else:
                    file_exists = False
                    physical_availability = "missing"
                    integrity_status = "unavailable"
                    if durable_status == "preview-only":
                        physical_status = "preview_only"
                        acquisition_provenance = "preview_only"
                    else:
                        physical_status = "missing_on_disk"
        else:
            file_exists = False
            physical_availability = "not_applicable" if durable_status in ("unavailable", "expired") else "missing"
            integrity_status = "unavailable"
            if durable_status == "preview-only":
                physical_status = "preview_only"
                acquisition_provenance = "preview_only"
            elif durable_status == "expired":
                physical_status = "expired"
            elif durable_status == "too-large":
                physical_status = "too_large"
            elif durable_status == "unsupported":
                physical_status = "unsupported"
            elif durable_status == "failed":
                physical_status = "failed"
            else:
                physical_status = "unavailable"

        # Check for derived text (Transcript, DocumentRecord, OCR)
        has_derived_text = False
        derived_type = None
        derived_text = None
        is_machine_generated = False

        if media_asset and durable_status != "preview-only":
            # 1. Audio/video speech transcript
            if media_asset.transcript and media_asset.transcript.full_text:
                has_derived_text = True
                derived_type = "transcript"
                derived_text = media_asset.transcript.full_text
                is_machine_generated = True

            # 2. Document record (PDF, DOCX, XLSX, TXT, CSV, or Image/Video OCR)
            elif media_asset.document_record and media_asset.document_record.extracted_text:
                has_derived_text = True
                doc_t = (media_asset.document_record.doc_type or "").lower()
                if doc_t in ("image_ocr", "ocr"):
                    derived_type = "image_ocr"
                    is_machine_generated = True
                elif doc_t == "video_ocr":
                    derived_type = "video_ocr"
                    is_machine_generated = True
                else:
                    derived_type = "document"
                    is_machine_generated = False
                derived_text = media_asset.document_record.extracted_text

        # Determine processing method/status/error
        proc_status = media_asset.processing_status if media_asset else (
            "unsupported" if durable_status in ("unavailable", "expired", "too-large", "unsupported") else "unprocessed"
        )
        proc_method = media_asset.processing_method if media_asset else None

        return {
            "inventory_id": item_id,
            "conversation_id": conversation_id,
            "message_id": message.id,
            "message_timestamp": format_timestamp(message.timestamp),
            "message_sender": message.sender_name,
            "attachment_record_id": attachment_record.id if attachment_record else None,
            "media_asset_id": media_asset.id if media_asset else None,
            "file_name": fname,
            "file_type": ftype,
            "mime_type": mime,
            "file_size": recorded_size,
            "sha256": actual_sha256 or record_sha or asset_sha,
            "record_sha256": record_sha,
            "asset_sha256": asset_sha,
            "hash_conflict": hash_conflict,
            "durable_status": durable_status,
            "physical_availability": physical_availability,
            "integrity_status": integrity_status,
            "acquisition_provenance": acquisition_provenance,
            "physical_status": physical_status,
            "file_exists": file_exists,
            "hash_verified": hash_verified,
            "actual_sha256": actual_sha256,
            "processing_status": proc_status,
            "processing_method": proc_method,
            "processing_error": proc_error,
            "has_derived_text": has_derived_text,
            "derived_type": derived_type,
            "derived_text": derived_text,
            "derived_char_count": len(derived_text) if derived_text else 0,
            "is_machine_generated": is_machine_generated,
            "is_placeholder": False,
            "is_thumbnail_only": (durable_status == "preview-only"),
            "media_download_url": safe_download_url
        }

    @classmethod
    def _record_hash_group(cls, hash_groups: Dict[str, Dict[str, Any]], inv_item: Dict[str, Any]):
        """
        Group items strictly by actual physical SHA256 (not stale recorded mismatched sha).
        Preserves all source references.
        """
        # DEFECT 1 FIX: Only group verified physical files by their actual computed SHA
        sha = inv_item.get("actual_sha256") if inv_item.get("file_exists") else None
        if not sha:
            return

        ref_entry = {
            "conversation_id": inv_item["conversation_id"],
            "message_id": inv_item["message_id"],
            "timestamp": inv_item["message_timestamp"],
            "sender": inv_item["message_sender"],
            "attachment_name": inv_item["file_name"],
            "attachment_record_id": inv_item["attachment_record_id"],
            "media_asset_id": inv_item["media_asset_id"]
        }

        if sha not in hash_groups:
            hash_groups[sha] = {
                "sha256": sha,
                "file_name": inv_item["file_name"],
                "file_type": inv_item["file_type"],
                "file_size": inv_item["file_size"],
                "file_exists": inv_item["file_exists"],
                "reference_count": 1,
                "references": [ref_entry]
            }
        else:
            hash_groups[sha]["reference_count"] += 1
            hash_groups[sha]["references"].append(ref_entry)

    @classmethod
    def build_report(
        cls,
        conversation_id: int,
        db: Session,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sender: Optional[str] = None,
        keywords: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Build the comprehensive deterministic evidence report.
        Extracts ordered chronological evidence from actual message text, local transcripts (with segment times),
        image OCR, document records, and processed video data.
        Cites conversation/message/asset IDs, timestamps, and physical integrity status next to every excerpt.
        Both video transcript and video OCR retain separate source content.
        Applies deterministic keyword filtering if supplied.
        Produces full JSON structure and complete rendered Markdown report.
        """
        # 1. Build the full evidence inventory first
        inventory_data = cls.build_inventory(
            conversation_id=conversation_id,
            db=db,
            date_from=date_from,
            date_to=date_to,
            sender=sender
        )

        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()

        # 2. Query messages for chronological evidence
        msg_query = db.query(Message).filter(Message.conversation_id == conversation_id)
        if date_from:
            msg_query = msg_query.filter(Message.timestamp >= date_from)
        if date_to:
            msg_query = msg_query.filter(Message.timestamp <= date_to)
        if sender:
            # Prevent SQL wildcard injection
            msg_query = msg_query.filter(func.lower(Message.sender_name) == sender.strip().lower())

        messages = msg_query.order_by(Message.timestamp.asc(), Message.id.asc()).all()

        evidence_items: List[Dict[str, Any]] = []

        # Clean keywords for deterministic filtering
        clean_keywords = [k.strip().lower() for k in keywords if k and k.strip()] if keywords else []

        # Create quick map of asset physical status from inventory
        asset_status_map = {
            it["media_asset_id"]: it for it in inventory_data["inventory"] if it.get("media_asset_id")
        }

        for m in messages:
            # A. Source Message Text
            # Exclude raw placeholders from counted analyzed text
            is_placeholder = bool(detect_omitted_placeholder(m.content))
            has_substantive_text = bool(m.content and m.content.strip() and not is_placeholder)

            if has_substantive_text:
                text_content = m.content.strip()
                if not clean_keywords or any(kw in text_content.lower() for kw in clean_keywords):
                    evidence_items.append({
                        "citation": {
                            "conversation_id": conv.id,
                            "message_id": m.id,
                            "media_asset_id": None,
                            "timestamp": format_timestamp(m.timestamp),
                            "sender": m.sender_name
                        },
                        "source_origin": "source_message",
                        "evidence_type": "message_text",
                        "label": "Source Message Text",
                        "is_machine_generated": False,
                        "physical_status": "not_applicable",
                        "integrity_status": "not_applicable",
                        "historical_derived_notice": None,
                        "duration_seconds": None,
                        "segments": [],
                        "text": text_content
                    })

            # DEFECT 5 FIX: Collect all media assets linked via Message OR via AttachmentRecord
            # Asset's attachment-record-only relationship must not lose derived evidence
            assets_on_msg: List[MediaAsset] = list(m.media_assets)
            for ar in m.attachment_records:
                if ar.media_asset and ar.media_asset not in assets_on_msg:
                    assets_on_msg.append(ar.media_asset)
                elif ar.media_asset_id:
                    fetched = db.query(MediaAsset).filter(MediaAsset.id == ar.media_asset_id).first()
                    if fetched and fetched not in assets_on_msg:
                        assets_on_msg.append(fetched)

            for asset in assets_on_msg:
                # Look up physical status from inventory
                inv_meta = asset_status_map.get(asset.id, {})
                phys_status = inv_meta.get("physical_status", "unavailable")
                integ_status = inv_meta.get("integrity_status", "unavailable")

                # Cite historical derived notice next to each item when source is missing or mismatched
                hist_notice = None
                if phys_status == "missing_on_disk":
                    hist_notice = "Historical derived text retained; underlying source file is currently absent from storage."
                elif phys_status == "hash_mismatch":
                    hist_notice = "Historical derived text retained; underlying source file has a cryptographic checksum mismatch."
                elif phys_status == "path_rejected":
                    hist_notice = "Historical derived text retained; underlying source file path was rejected as unsafe."
                elif phys_status == "preview_only":
                    hist_notice = "Derived text from preview/thumbnail; full original media was not retained."
                elif inv_meta.get("hash_conflict"):
                    hist_notice = "Historical derived text retained; checksum discrepancy between record and media asset."
                elif phys_status == "computed_only":
                    hist_notice = "Derived text retained; file has no recorded baseline checksum to verify against."
                elif phys_status == "read_error":
                    hist_notice = "Historical derived text retained; underlying physical file could not be read from disk."

                # 1. Audio / Voice / Video Speech Transcript
                if asset.transcript and asset.transcript.full_text:
                    t_text = asset.transcript.full_text.strip()
                    if not clean_keywords or any(kw in t_text.lower() for kw in clean_keywords):
                        segments_data = [
                            {
                                "start": seg.start_time,
                                "end": seg.end_time,
                                "start_formatted": format_seconds(seg.start_time),
                                "end_formatted": format_seconds(seg.end_time),
                                "text": seg.text.strip(),
                                "speaker": seg.speaker
                            }
                            for seg in asset.transcript.segments
                        ]
                        evidence_items.append({
                            "citation": {
                                "conversation_id": conv.id,
                                "message_id": m.id,
                                "media_asset_id": asset.id,
                                "timestamp": format_timestamp(m.timestamp),
                                "sender": m.sender_name
                            },
                            "source_origin": "derived",
                            "evidence_type": "transcript",
                            "label": "Machine-generated ASR (unreviewed)",
                            "is_machine_generated": True,
                            "physical_status": phys_status,
                            "integrity_status": integ_status,
                            "historical_derived_notice": hist_notice,
                            "duration_seconds": asset.transcript.duration_seconds or asset.duration_seconds,
                            "model_used": asset.transcript.model_used,
                            "language_detected": asset.transcript.language_detected,
                            "segments": segments_data,
                            "text": t_text
                        })

                # 2. Document Record (Document Extraction or Image/Video OCR)
                # DEFECT 5 FIX: Must NOT be an elif — both video transcript and video OCR must retain separate source content!
                if asset.document_record and asset.document_record.extracted_text:
                    d_text = asset.document_record.extracted_text.strip()
                    if not clean_keywords or any(kw in d_text.lower() for kw in clean_keywords):
                        doc_t = (asset.document_record.doc_type or "").lower()
                        if doc_t in ("image_ocr", "ocr"):
                            etype = "image_ocr"
                            label = "Machine-generated OCR (unreviewed)"
                            is_machine = True
                        elif doc_t == "video_ocr":
                            etype = "video_ocr"
                            label = "Machine-generated Video OCR (unreviewed)"
                            is_machine = True
                        else:
                            etype = "document"
                            label = f"Document Record Extraction ({asset.document_record.doc_type.upper()})"
                            is_machine = False

                        evidence_items.append({
                            "citation": {
                                "conversation_id": conv.id,
                                "message_id": m.id,
                                "media_asset_id": asset.id,
                                "timestamp": format_timestamp(m.timestamp),
                                "sender": m.sender_name
                            },
                            "source_origin": "derived",
                            "evidence_type": etype,
                            "label": label,
                            "is_machine_generated": is_machine,
                            "physical_status": phys_status,
                            "integrity_status": integ_status,
                            "historical_derived_notice": hist_notice,
                            "duration_seconds": None,
                            "doc_type": asset.document_record.doc_type,
                            "page_count": asset.document_record.page_count,
                            "title": asset.document_record.title,
                            "segments": [],
                            "text": d_text
                        })

        # 3. Missing & Unprocessed Appendix
        # DEFECT 3 FIX: Include EVERY nonverified/unprocessed state
        inv_list = inventory_data["inventory"]
        missing_appendix = {
            "missing_physical_files": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "reason": "Physical file is absent on disk storage."
                }
                for it in inv_list if it["physical_status"] == "missing_on_disk"
            ],
            "hash_mismatches": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "recorded_sha256": it.get("record_sha256") or it.get("asset_sha256") or "unknown",
                    "actual_sha256": it["actual_sha256"],
                    "reason": "Cryptographic SHA256 checksum mismatch (corrupted or altered file)."
                }
                for it in inv_list if it["physical_status"] == "hash_mismatch"
            ],
            "asset_record_hash_conflicts": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "record_sha256": it["record_sha256"],
                    "asset_sha256": it["asset_sha256"],
                    "reason": "AttachmentRecord checksum differs from MediaAsset recorded checksum."
                }
                for it in inv_list if it.get("hash_conflict")
            ],
            "path_escapes": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "reason": "Path escape rejected: file location is outside authorized media storage."
                }
                for it in inv_list if it["physical_status"] == "path_rejected"
            ],
            "omitted_placeholders": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "placeholder_text": it["processing_error"]
                }
                for it in inv_list if it["physical_status"] == "omitted_placeholder"
            ],
            "preview_only": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "reason": "Only preview thumbnail was captured; full original media was not retained."
                }
                for it in inv_list if it["physical_status"] == "preview_only" or it["durable_status"] == "preview-only"
            ],
            "unavailable_or_unsupported": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "durable_status": it["durable_status"],
                    "reason": it["processing_error"] or f"Attachment durable status is {it['durable_status']}."
                }
                for it in inv_list if it["durable_status"] in ("unavailable", "expired", "too-large", "unsupported", "failed")
                and it["physical_status"] not in ("omitted_placeholder", "preview_only")
            ],
            "failed_processing": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "media_asset_id": it["media_asset_id"],
                    "file_name": it["file_name"],
                    "processing_error": it["processing_error"]
                }
                for it in inv_list if it["processing_status"] == "failed"
            ],
            "unprocessed": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "media_asset_id": it["media_asset_id"],
                    "file_name": it["file_name"],
                    "status": it["processing_status"]
                }
                for it in inv_list if it["processing_status"] in ("unprocessed", "queued", "processing", "setup_needed")
            ],
            "computed_only": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "actual_sha256": it.get("actual_sha256"),
                    "reason": "File exists on disk but has no recorded baseline checksum to verify against."
                }
                for it in inv_list if it["physical_status"] == "computed_only"
            ],
            "read_errors": [
                {
                    "inventory_id": it["inventory_id"],
                    "message_id": it["message_id"],
                    "timestamp": it["message_timestamp"],
                    "sender": it["message_sender"],
                    "file_name": it["file_name"],
                    "reason": it.get("processing_error") or "Physical file read error on disk."
                }
                for it in inv_list if it["physical_status"] == "read_error"
            ]
        }

        report_payload = {
            "report_metadata": {
                "report_title": f"WhatsApp Evidence Inventory & Forensic Report: {sanitize_header_text(conv.title)}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "conversation_id": conv.id,
                "conversation_title": conv.title,
                "source_type": conv.source_type,
                "source_timestamp_timezone": getattr(settings, "REPORT_TIMEZONE", "Africa/Cairo"),
                "date_contract": "Database source timestamps are naive LOCAL wall times in source timezone. Timezone-aware query parameters are converted to source timezone and normalized to naive wall times. Timezone-naive parameters are matched directly.",
                "date_range": inventory_data["date_range"],
                "filter_applied": {
                    "date_from": format_timestamp(date_from),
                    "date_to": format_timestamp(date_to),
                    "sender": sender,
                    "keywords": clean_keywords
                },
                "disclaimer": "Machine-generated derived data (ASR/OCR) is unreviewed. Report generated deterministically without AI models."
            },
            "capture_coverage": inventory_data["capture_coverage"],
            "inventory_summary": inventory_data["summary"],
            "inventory": inventory_data["inventory"],
            "duplicate_hash_groups": inventory_data["duplicate_hash_groups"],
            "evidence": evidence_items,
            "missing_unprocessed_appendix": missing_appendix
        }

        # Render Markdown report representation
        report_payload["markdown"] = cls.render_markdown(report_payload)

        return report_payload

    @classmethod
    def render_markdown(cls, report_dict: Dict[str, Any]) -> str:
        """Render deterministic, high-readability Markdown representation of evidence report."""
        meta = report_dict["report_metadata"]
        cov = report_dict["capture_coverage"]
        summ = report_dict["inventory_summary"]
        dups = report_dict["duplicate_hash_groups"]
        evidence = report_dict["evidence"]
        appendix = report_dict["missing_unprocessed_appendix"]

        clean_title = sanitize_header_text(meta['report_title'])
        obs_sessions = ", ".join(cov.get('observed_session_ids') or []) or "None"

        md_lines = [
            f"# {clean_title}",
            f"**Generated At:** {meta['generated_at']} UTC | **Conversation ID:** #{meta['conversation_id']}",
            f"**Source Format:** `{meta['source_type']}` | **Date Span:** {meta['date_range']['start'] or 'N/A'} to {meta['date_range']['end'] or 'N/A'}",
            "",
            "> **LEGAL & FORENSIC DISCLAIMER:** Derived speech transcripts (ASR) and optical character recognition (OCR)",
            "> are machine-generated and unreviewed. This report operates purely deterministically on grounded local records",
            "> without probabilistic generative model assertions or cloud inferences.",
            "",
            "---",
            "## 1. WhatsApp Capture Coverage Assessment",
            f"- **Coverage Status:** `{cov['status'].upper()}`",
            f"- **Verified Complete:** `{'YES' if cov['is_complete'] else 'NO (Partial / Unknown)'}`",
            f"- **Technical Assessment:** {cov['reason']}",
            f"- **Messages Recorded in DB:** {cov['db_message_count']:,}",
            f"- **Verified Capture Session ID:** `None (Unverified session)`",
            f"- **Observed Session IDs:** `{obs_sessions}`",
            "",
            "---",
            "## 2. Evidence Inventory & Asset Metrics",
            f"| Metric | Count / Volume |",
            f"| :--- | :--- |",
            f"| Total Messages Scanned | {summ['total_messages_scanned']:,} |",
            f"| Total Attachments Detected | {summ['total_attachments_detected']:,} |",
            f"| Distinct Physical SHA256 Hashes | {summ['distinct_physical_hashes']:,} |",
            f"| Verified Physical Originals on Disk | {summ['verified_physical_files']:,} |",
            f"| Computed-Only Files (No Prior Checksum) | {summ.get('computed_only_files', 0):,} |",
            f"| Missing Originals on Disk | {summ['missing_physical_files']:,} |",
            f"| Cryptographic Hash Mismatches | {summ['hash_mismatches']:,} |",
            f"| Path Escapes Rejected | {summ.get('path_rejected_files', 0):,} |",
            f"| Preview-Only (Thumbnails Without Full Original) | {summ['preview_only_attachments']:,} |",
            f"| Unavailable / Export-Omitted Placeholders | {summ['unavailable_or_omitted']:,} |",
            f"| Processed Assets with Extracted Derived Text | {summ['processed_with_derived_text']:,} |",
            f"| Unprocessed / Pipeline Failed Assets | {summ['unprocessed_or_failed']:,} |",
            f"| Total Physical Bytes Stored | {summ['total_physical_bytes']:,} bytes |",
            f"| Unique Physical Bytes (Content-Addressed) | {summ['unique_physical_bytes']:,} bytes |",
            ""
        ]

        # Duplicate hash groups table
        if dups:
            md_lines.extend([
                "### Content-Addressed Duplicate Physical Assets",
                "The following physical files share identical cryptographic SHA256 hashes across multiple messages:",
                "",
                "| SHA256 (Prefix) | File Name | Size (Bytes) | Occurrences | Referencing Message IDs |",
                "| :--- | :--- | :--- | :--- | :--- |"
            ])
            for d in dups:
                ref_ids = ", ".join(f"#{r['message_id']}" for r in d["references"])
                sha_prefix = f"`{d['sha256'][:16]}...`"
                md_lines.append(f"| {sha_prefix} | {escape_markdown_cell(d['file_name'])} | {d['file_size']:,} | {d['reference_count']} | {ref_ids} |")
            md_lines.append("")

        # Chronological Evidence Log
        md_lines.extend([
            "---",
            "## 3. Chronological Evidence Log",
            f"Total evidence excerpts: **{len(evidence):,}**"
        ])
        if meta["filter_applied"].get("keywords"):
            md_lines.append(f"*Filtered deterministically by keywords:* `{', '.join(meta['filter_applied']['keywords'])}`")
        md_lines.append("")

        if not evidence:
            md_lines.append("*No evidence records matched the specified filter criteria.*")
        else:
            for idx, ev in enumerate(evidence, start=1):
                cit = ev["citation"]
                ast_str = f" | Asset #{cit['media_asset_id']}" if cit.get("media_asset_id") else ""
                md_lines.append(f"#### Excerpt {idx} — [Conv #{cit['conversation_id']} | Msg #{cit['message_id']}{ast_str} | {cit['timestamp']} UTC | Sender: {cit['sender']}]")
                md_lines.append(f"**Classification:** `{ev['label']}`")

                if ev.get("historical_derived_notice"):
                    md_lines.append(f"> ⚠️ **Integrity Warning:** {ev['historical_derived_notice']}")

                if ev["evidence_type"] == "transcript":
                    dur_str = f" ({ev['duration_seconds']:.1f}s)" if ev.get("duration_seconds") else ""
                    md_lines.append(f"*Local ASR Model:* `{ev.get('model_used', 'whisper')}` | *Detected Language:* `{ev.get('language_detected', 'unknown')}`{dur_str}")
                    if ev.get("segments"):
                        md_lines.append("**Timed Speech Segments:**")
                        for s in ev["segments"]:
                            spk_str = f" ({s['speaker']})" if s.get("speaker") else ""
                            md_lines.append(f"- `[{s['start_formatted']} --> {s['end_formatted']}]`{spk_str}: {s['text']}")
                    else:
                        md_lines.append(f"> {ev['text']}")

                elif ev["evidence_type"] in ("image_ocr", "video_ocr"):
                    md_lines.append(f"> {ev['text']}")

                elif ev["evidence_type"] == "document":
                    md_lines.append(f"*Document Title:* `{sanitize_header_text(ev.get('title'))}` | *Format:* `{ev.get('doc_type', '').upper()}` | *Pages:* {ev.get('page_count', 1)}")
                    md_lines.append(f"> {ev['text']}")

                else:
                    # Source message text
                    md_lines.append(f"> {ev['text']}")

                md_lines.append("")

        # Appendix
        md_lines.extend([
            "---",
            "## 4. Appendix: Missing, Omitted & Unprocessed Assets",
            ""
        ])

        # Missing physical
        if appendix["missing_physical_files"]:
            md_lines.append("### A. Missing Physical Files (Record Exists, File Absent from Disk)")
            for m_item in appendix["missing_physical_files"]:
                md_lines.append(f"- **Msg #{m_item['message_id']}** ({m_item['timestamp']} by {m_item['sender']}): `{m_item['file_name']}` — *{m_item['reason']}*")
            md_lines.append("")

        # Hash mismatches
        if appendix["hash_mismatches"]:
            md_lines.append("### B. Cryptographic Hash Mismatches (Integrity Failure)")
            for h_item in appendix["hash_mismatches"]:
                md_lines.append(f"- **Msg #{h_item['message_id']}** ({h_item['timestamp']}): `{h_item['file_name']}` — Expected `{h_item['recorded_sha256'][:16]}...`, Got `{h_item['actual_sha256'][:16]}...`")
            md_lines.append("")

        # Hash conflicts
        if appendix.get("asset_record_hash_conflicts"):
            md_lines.append("### C. Checksum Discrepancies Between Record and Asset")
            for c_item in appendix["asset_record_hash_conflicts"]:
                md_lines.append(f"- **Msg #{c_item['message_id']}** ({c_item['timestamp']}): `{c_item['file_name']}` — Record SHA `{c_item['record_sha256'][:16]}...` != Asset SHA `{c_item['asset_sha256'][:16]}...`")
            md_lines.append("")

        # Path escapes
        if appendix.get("path_escapes"):
            md_lines.append("### D. Security Violations: Path Escapes Rejected")
            for pe_item in appendix["path_escapes"]:
                md_lines.append(f"- **Msg #{pe_item['message_id']}** ({pe_item['timestamp']}): `{pe_item['file_name']}` — *{pe_item['reason']}*")
            md_lines.append("")

        # Omitted placeholders
        if appendix["omitted_placeholders"]:
            md_lines.append("### E. Export-Omitted Placeholders (Omitted in Source Export)")
            for o_item in appendix["omitted_placeholders"]:
                md_lines.append(f"- **Msg #{o_item['message_id']}** ({o_item['timestamp']} by {o_item['sender']}): `{o_item['file_name']}` — *{o_item['placeholder_text']}*")
            md_lines.append("")

        # Preview-only
        if appendix["preview_only"]:
            md_lines.append("### F. Preview-Only Attachments (Thumbnail Retained, Original Missing)")
            for p_item in appendix["preview_only"]:
                md_lines.append(f"- **Msg #{p_item['message_id']}** ({p_item['timestamp']}): `{p_item['file_name']}` — *{p_item['reason']}*")
            md_lines.append("")

        # Unavailable / unsupported
        if appendix.get("unavailable_or_unsupported"):
            md_lines.append("### G. Unavailable or Unsupported Attachments")
            for uo_item in appendix["unavailable_or_unsupported"]:
                md_lines.append(f"- **Msg #{uo_item['message_id']}** ({uo_item['timestamp']}): `{uo_item['file_name']}` (`{uo_item['durable_status']}`) — *{uo_item['reason']}*")
            md_lines.append("")

        # Failed processing
        if appendix["failed_processing"]:
            md_lines.append("### H. Pipeline Processing Failures")
            for f_item in appendix["failed_processing"]:
                md_lines.append(f"- **Asset #{f_item['media_asset_id']}** (`{f_item['file_name']}`): Error: `{f_item['processing_error']}`")
            md_lines.append("")

        # Unprocessed
        if appendix["unprocessed"]:
            md_lines.append("### I. Unprocessed Assets Awaiting Pipeline Run")
            for u_item in appendix["unprocessed"]:
                md_lines.append(f"- **Asset #{u_item['media_asset_id']}** (`{u_item['file_name']}`): Status `{u_item['status']}`")
            md_lines.append("")

        # Computed-only files
        if appendix.get("computed_only"):
            md_lines.append("### J. Computed-Only Files (No Prior Baseline Checksum)")
            for co_item in appendix["computed_only"]:
                act_sha = co_item.get("actual_sha256") or "unknown"
                sha_str = f" (SHA256: `{act_sha[:16]}...`)" if act_sha != "unknown" else ""
                md_lines.append(f"- **Msg #{co_item['message_id']}** ({co_item['timestamp']}): `{co_item['file_name']}`{sha_str} — *{co_item['reason']}*")
            md_lines.append("")

        # Read errors
        if appendix.get("read_errors"):
            md_lines.append("### K. Disk Read Errors (Access / Read Failed)")
            for re_item in appendix["read_errors"]:
                md_lines.append(f"- **Msg #{re_item['message_id']}** ({re_item['timestamp']}): `{re_item['file_name']}` — *{re_item['reason']}*")
            md_lines.append("")

        inv_list = report_dict.get("inventory", [])
        # Verified banner: require all inventory items verified and none hash_conflict/unprocessed
        has_any_issues = any(
            bool(lst) for lst in appendix.values()
        ) or any(
            it["physical_status"] != "verified_original" for it in inv_list
        ) or any(
            it.get("hash_conflict") for it in inv_list
        ) or any(
            it["processing_status"] != "completed" for it in inv_list
        ) or (summ["total_attachments_detected"] == 0)

        if not has_any_issues and summ["verified_physical_files"] > 0:
            md_lines.append("*All inventoried attachments are physically verified, intact, and processed without missing items.*")
            md_lines.append("")

        return "\n".join(md_lines)
