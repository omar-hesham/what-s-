"""
ZIP export importer for WhatsApp.
Unpacks exported archives safely, matches media attachments with messages,
computes cryptographic hashes for deduplication, and records relational entities.
"""

import shutil
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.security import safe_extract_zip, sanitize_filename
from owi.core.hashing import compute_sha256
from owi.core.logging import logger
from owi.db.models import Conversation, Message, MediaAsset, Participant
from owi.db.migrations import sync_message_fts
from owi.ingest.whatsapp_parser import WhatsAppParser, ParsedMessage, detect_attachment_type

def find_chat_file(extracted_dir: Path) -> Optional[Path]:
    """Find the main WhatsApp text export file inside extracted directory."""
    # Look for _chat.txt or any *.txt file
    candidates = list(extracted_dir.glob("**/_chat.txt"))
    if candidates:
        return candidates[0]
    txt_files = list(extracted_dir.glob("**/*.txt"))
    if txt_files:
        # Prefer the largest text file or one containing 'chat' in name
        for f in txt_files:
            if "chat" in f.name.lower() or "whatsapp" in f.name.lower():
                return f
        return max(txt_files, key=lambda f: f.stat().st_size)
    return None

class ZipImporter:
    """Safely ingests WhatsApp ZIP archives containing chats and media."""

    @classmethod
    def import_zip(
        cls, 
        zip_path: Path, 
        db: Session, 
        conversation_title: Optional[str] = None,
        force_reimport: bool = False
    ) -> Dict[str, Any]:
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        archive_hash = compute_sha256(zip_path)
        
        # Deduplication check
        existing = db.query(Conversation).filter(Conversation.source_hash == archive_hash).first()
        if existing and not force_reimport:
            logger.info(f"Archive {zip_path.name} already imported as Conversation #{existing.id}. Returning existing.")
            return {
                "status": "already_imported",
                "conversation_id": existing.id,
                "title": existing.title,
                "message_count": existing.message_count,
                "duplicate": True
            }

        temp_extract_dir = Path(tempfile.mkdtemp(prefix="owi_zip_"))
        try:
            extracted_files, errors = safe_extract_zip(zip_path, temp_extract_dir)
            if errors:
                logger.warning(f"ZIP extraction had warnings: {errors}")

            chat_file = find_chat_file(temp_extract_dir)
            if not chat_file:
                raise ValueError("No valid WhatsApp text file found in the ZIP archive.")

            # Read chat content (try UTF-8, then fallback to utf-8-sig or latin-1)
            raw_text = ""
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "cp1256", "latin-1"):
                try:
                    with open(chat_file, "r", encoding=encoding) as f:
                        raw_text = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if not raw_text:
                raise ValueError("Could not read text content from chat export file.")

            parsed_messages = WhatsAppParser.parse_chat_text(raw_text)
            if not parsed_messages:
                raise ValueError("No valid messages could be parsed from the chat file.")

            # Create or update Conversation
            title = conversation_title or zip_path.stem.replace("WhatsApp Chat - ", "").replace("WhatsApp Chat with ", "").strip()
            if not title:
                title = "Imported WhatsApp Conversation"

            conv = Conversation(
                title=title,
                source_type="export_zip",
                source_hash=archive_hash,
                start_date=parsed_messages[0].timestamp if parsed_messages else None,
                end_date=parsed_messages[-1].timestamp if parsed_messages else None,
                message_count=len(parsed_messages)
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)

            # Map media files in the archive by filename
            media_map: Dict[str, Path] = {}
            for f in extracted_files:
                if f != chat_file:
                    media_map[f.name.lower()] = f

            # Track participants
            participants_seen = set()

            # Insert messages and attach media
            messages_created = 0
            media_created = 0

            for pmsg in parsed_messages:
                # Track participant
                if pmsg.sender_name not in ("System", "Unknown") and pmsg.sender_name not in participants_seen:
                    participants_seen.add(pmsg.sender_name)
                    existing_p = db.query(Participant).filter(Participant.name == pmsg.sender_name).first()
                    if not existing_p:
                        p_rec = Participant(
                            name=pmsg.sender_name,
                            normalized_name=pmsg.sender_name.strip().lower()
                        )
                        db.add(p_rec)

                msg_rec = Message(
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
                db.add(msg_rec)
                db.flush()  # get msg_rec.id
                messages_created += 1

                # Sync to SQLite FTS5 search
                sync_message_fts(db.connection(), msg_rec.id, msg_rec.content, msg_rec.sender_name)

                # If message has an attachment, link the file
                if pmsg.attachment_name:
                    att_clean = pmsg.attachment_name.strip().lower()
                    matched_file = media_map.get(att_clean)
                    
                    # Fuzzy match if exact match not found
                    if not matched_file:
                        for fn, fp in media_map.items():
                            if att_clean in fn or fn in att_clean:
                                matched_file = fp
                                break

                    if matched_file and matched_file.exists():
                        media_type = detect_attachment_type(matched_file.name)
                        dest_sub = "documents"
                        if media_type == "voice":
                            dest_sub = "audio"
                        elif media_type == "image":
                            dest_sub = "images"
                        elif media_type == "video":
                            dest_sub = "video"

                        media_hash = compute_sha256(matched_file)
                        safe_name = f"{conv.id}_{msg_rec.id}_{sanitize_filename(matched_file.name)}"
                        dest_path = settings.DATA_DIR / "media" / dest_sub / safe_name
                        
                        shutil.copy2(matched_file, dest_path)

                        asset = MediaAsset(
                            conversation_id=conv.id,
                            message_id=msg_rec.id,
                            file_name=matched_file.name,
                            file_type=media_type,
                            file_size=matched_file.stat().st_size,
                            file_path=str(dest_path.as_posix()),
                            sha256_hash=media_hash
                        )
                        db.add(asset)
                        media_created += 1

            conv.message_count = messages_created
            db.commit()

            return {
                "status": "success",
                "conversation_id": conv.id,
                "title": conv.title,
                "messages_imported": messages_created,
                "media_files_linked": media_created,
                "duplicate": False
            }

        finally:
            # Clean up temporary extraction folder
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
