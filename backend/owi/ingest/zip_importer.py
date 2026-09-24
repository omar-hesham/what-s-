"""
ZIP export importer for WhatsApp.
Unpacks exported archives safely, matches media attachments with messages,
computes cryptographic hashes for deduplication, and records relational entities.
"""

import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy import func
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
    # Look for _chat.txt or chat.txt first
    for exact_name in ("_chat.txt", "chat.txt"):
        candidates = list(extracted_dir.glob(f"**/{exact_name}"))
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

def is_binary_payload(file_path: Path) -> bool:
    """Check if a file cannot be decoded as text in any standard text encoding or contains null bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            if not chunk:
                return False
            for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1256", "latin-1"):
                try:
                    text_content = chunk.decode(enc)
                    if "\x00" in text_content:
                        return True
                    return False
                except UnicodeDecodeError:
                    continue
            return True
    except Exception:
        return True

class ZipImporter:
    """Safely ingests WhatsApp ZIP archives containing chats and media."""

    @classmethod
    def import_zip(
        cls, 
        zip_path: Path, 
        db: Session, 
        conversation_title: Optional[str] = None,
        force_reimport: bool = False,
        merge_into_conversation_id: Optional[int] = None
    ) -> Dict[str, Any]:
        if merge_into_conversation_id is not None:
            return cls.merge_zip(
                zip_path=zip_path,
                db=db,
                target_conversation_id=merge_into_conversation_id
            )

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

    @classmethod
    def merge_zip(
        cls,
        zip_path: Path,
        db: Session,
        target_conversation_id: int
    ) -> Dict[str, Any]:
        """
        Merge a WhatsApp text export ZIP into an existing conversation.
        Preserves target conversation identity, title, source_hash, and existing messages/derived records.
        Rejects archives containing physical media files before any database writes.
        Deduplicates messages using (timestamp, sender_name, content) with multiplicity tracking.
        Updates message_count and date range from actual rows and maintains SQLite FTS5 search index.
        """
        zip_path = Path(zip_path)
        if not zip_path.exists():
            raise FileNotFoundError(f"ZIP file not found: {zip_path}")

        target_conv = db.query(Conversation).filter(Conversation.id == target_conversation_id).first()
        if not target_conv:
            raise ValueError(f"Target conversation {target_conversation_id} not found.")

        temp_extract_dir = Path(tempfile.mkdtemp(prefix="owi_zip_merge_"))
        try:
            extracted_files, errors = safe_extract_zip(zip_path, temp_extract_dir)
            if errors:
                logger.warning(f"ZIP extraction had warnings during merge: {errors}")

            chat_file = find_chat_file(temp_extract_dir)
            if not chat_file:
                raise ValueError("No valid WhatsApp text file found in the ZIP archive.")

            # Reject physical media files or unknown binary payloads before performing any database write.
            # Allow and ignore inert text sidecars such as .md, .markdown, and other .txt entries without interpreting their contents.
            inert_text_extensions = {".md", ".markdown", ".txt"}
            ignored_filenames = {".ds_store", "thumbs.db", "desktop.ini"}

            unsupported_files: List[Path] = []
            for f in extracted_files:
                if f == chat_file:
                    continue
                if (
                    f.name.startswith((".", "._", "__"))
                    or f.name.lower() in ignored_filenames
                    or any(part.startswith((".", "._", "__")) for part in f.parts)
                ):
                    continue

                ext = f.suffix.lower()
                if ext in inert_text_extensions:
                    if is_binary_payload(f):
                        unsupported_files.append(f)
                    else:
                        # Allow and ignore inert text sidecar without interpreting contents
                        continue
                else:
                    # Actual physical media or unknown binary payload
                    unsupported_files.append(f)

            if unsupported_files:
                media_names = [f.name for f in unsupported_files]
                raise ValueError(
                    f"Merge mode does not support ZIP archives with physical media files or binary payloads "
                    f"({len(unsupported_files)} files found: {', '.join(media_names[:5])}"
                    f"{'...' if len(media_names) > 5 else ''}). "
                    f"Please provide a text-only export without media."
                )

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

            # Establish duplicate identity with multiplicity on existing messages
            existing_messages = (
                db.query(Message)
                .filter(Message.conversation_id == target_conv.id)
                .order_by(Message.timestamp.asc(), Message.id.asc())
                .all()
            )

            def _msg_key(ts: Optional[datetime], sender: Optional[str], content: Optional[str]) -> Tuple[Optional[datetime], str, str]:
                t = ts
                if t is not None:
                    if t.tzinfo is not None:
                        t = t.replace(tzinfo=None)
                    t = t.replace(microsecond=0)
                s = (sender or "").strip()
                c = (content or "").replace("\r\n", "\n").strip()
                return (t, s, c)

            existing_counts = Counter(
                _msg_key(m.timestamp, m.sender_name, m.content)
                for m in existing_messages
            )

            max_source_index = max((m.source_index for m in existing_messages if m.source_index is not None), default=0)
            participants_seen = set()
            messages_added = 0
            messages_skipped = 0

            for pmsg in parsed_messages:
                key = _msg_key(pmsg.timestamp, pmsg.sender_name, pmsg.content)
                if existing_counts[key] > 0:
                    existing_counts[key] -= 1
                    messages_skipped += 1
                    continue

                # Add new message
                if pmsg.sender_name not in ("System", "Unknown") and pmsg.sender_name not in participants_seen:
                    participants_seen.add(pmsg.sender_name)
                    existing_p = db.query(Participant).filter(Participant.name == pmsg.sender_name).first()
                    if not existing_p:
                        p_rec = Participant(
                            name=pmsg.sender_name,
                            normalized_name=pmsg.sender_name.strip().lower()
                        )
                        db.add(p_rec)

                source_idx = pmsg.source_index
                if source_idx is None or source_idx <= max_source_index:
                    source_idx = max_source_index + messages_added + 1

                msg_rec = Message(
                    conversation_id=target_conv.id,
                    sender_name=pmsg.sender_name,
                    timestamp=pmsg.timestamp,
                    content=pmsg.content,
                    message_type=pmsg.message_type,
                    raw_text=pmsg.raw_text,
                    has_attachment=pmsg.has_attachment,
                    attachment_name=pmsg.attachment_name,
                    source_index=source_idx
                )
                db.add(msg_rec)
                db.flush()
                messages_added += 1

                # Maintain SQLite FTS5 search index for inserted messages
                sync_message_fts(db.connection(), msg_rec.id, msg_rec.content or "", msg_rec.sender_name or "")

            # Recalculate message_count and date range from actual rows
            actual_count = db.query(Message).filter(Message.conversation_id == target_conv.id).count()
            actual_start = db.query(func.min(Message.timestamp)).filter(Message.conversation_id == target_conv.id).scalar()
            actual_end = db.query(func.max(Message.timestamp)).filter(Message.conversation_id == target_conv.id).scalar()

            target_conv.message_count = actual_count
            target_conv.start_date = actual_start
            target_conv.end_date = actual_end
            target_conv.updated_at = datetime.utcnow()

            db.commit()
            db.refresh(target_conv)

            logger.info(
                f"Merged archive into Conversation #{target_conv.id}: "
                f"{messages_added} added, {messages_skipped} skipped, total {actual_count} messages."
            )

            return {
                "status": "success",
                "mode": "merge",
                "conversation_id": target_conv.id,
                "title": target_conv.title,
                "messages_imported": messages_added,
                "messages_added": messages_added,
                "messages_skipped": messages_skipped,
                "total_messages": actual_count,
                "duplicate": (messages_added == 0)
            }
        finally:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)
