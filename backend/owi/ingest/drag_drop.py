"""
Drag and Drop ingestion handler.
Allows dragging single or multiple files (audio, video, images, PDF, DOCX, XLSX, TXT, CSV, ZIP)
to attach to an existing conversation or create a new workspace project.
"""

import shutil
from pathlib import Path
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.security import sanitize_filename
from owi.core.hashing import compute_sha256
from owi.db.models import Conversation, Message, MediaAsset
from owi.ingest.whatsapp_parser import detect_attachment_type
from owi.ingest.zip_importer import ZipImporter

class DragDropIngester:
    """Ingests standalone files dropped into the interface."""

    @classmethod
    def ingest_file(
        cls, 
        file_path: Path, 
        db: Session, 
        conversation_id: Optional[int] = None
    ) -> Dict[str, Any]:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # If it's a ZIP file, delegate to ZipImporter
        if file_path.suffix.lower() == ".zip":
            return ZipImporter.import_zip(file_path, db)

        file_type = detect_attachment_type(file_path.name)
        file_hash = compute_sha256(file_path)

        # Target folder
        dest_sub = "documents"
        if file_type == "voice":
            dest_sub = "audio"
        elif file_type == "image":
            dest_sub = "images"
        elif file_type == "video":
            dest_sub = "video"

        safe_name = f"drag_{sanitize_filename(file_path.name)}"
        dest_path = settings.DATA_DIR / "media" / dest_sub / safe_name
        shutil.copy2(file_path, dest_path)

        # If no conversation is provided, create a standalone container conversation
        if not conversation_id:
            conv = Conversation(
                title=f"Dropped Files - {file_path.name}",
                source_type="drag_drop",
                source_hash=file_hash,
                message_count=1
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
            conversation_id = conv.id

        # Create a container message for this dropped file
        msg = Message(
            conversation_id=conversation_id,
            sender_name="User",
            timestamp=file_path.stat().st_mtime,
            content=f"Imported file: {file_path.name}",
            message_type=file_type,
            has_attachment=True,
            attachment_name=file_path.name
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        asset = MediaAsset(
            conversation_id=conversation_id,
            message_id=msg.id,
            file_name=file_path.name,
            file_type=file_type,
            file_size=file_path.stat().st_size,
            file_path=str(dest_path.as_posix()),
            sha256_hash=file_hash
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        return {
            "status": "success",
            "media_asset_id": asset.id,
            "conversation_id": conversation_id,
            "file_name": asset.file_name,
            "file_type": asset.file_type
        }
