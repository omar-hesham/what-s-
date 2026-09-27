"""
Local image analysis and OCR pipeline.
Extracts dimensions and image metadata via Pillow.
Runs local Tesseract OCR with Arabic and English language support.
Metadata is strictly kept as metadata; never fabricated as OCR text.
Saves extracted text to DocumentRecord and indexes verified text in derived_fts.
"""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
from sqlalchemy.orm import Session

from owi.config import settings
from owi.core.logging import logger
from owi.db.models import MediaAsset, DocumentRecord
from owi.db.migrations import sync_derived_fts, remove_derived_fts

# Common Windows Tesseract paths
TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]

def find_tesseract_binary() -> Optional[str]:
    """Locate tesseract binary on Windows or PATH."""
    in_path = shutil.which("tesseract")
    if in_path:
        return in_path
    for candidate in TESSERACT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None

def find_tessdata_dir() -> Optional[Path]:
    """Check for custom or workspace tessdata directory."""
    candidate = settings.DATA_DIR / "models" / "tessdata"
    if candidate.exists() and (candidate / "ara.traineddata").exists() or (candidate / "eng.traineddata").exists():
        return candidate
    return None

class ImageAnalyzer:
    """Performs image metadata inspection and local OCR."""

    _custom_tesseract_binary: Any = None

    @classmethod
    def set_tesseract_binary(cls, binary_path: Any):
        """Inject a custom or mock tesseract binary path for testing, or False to disable."""
        cls._custom_tesseract_binary = binary_path

    @classmethod
    def get_tesseract_binary(cls) -> Optional[str]:
        if cls._custom_tesseract_binary is False or cls._custom_tesseract_binary == "":
            return None
        if cls._custom_tesseract_binary is not None:
            return str(cls._custom_tesseract_binary)
        return find_tesseract_binary()

    @classmethod
    def analyze_image(cls, media_asset_id: int, db: Session) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"MediaAsset #{media_asset_id} not found.")

        img_path = Path(asset.file_path)
        if not img_path.exists():
            asset.processing_status = "failed"
            asset.processing_error = "file_not_found"
            asset.processing_attempts = (asset.processing_attempts or 0) + 1
            asset.processed_at = datetime.utcnow()
            db.commit()
            raise FileNotFoundError(f"Image file does not exist: {img_path}")

        asset.processing_attempts = (asset.processing_attempts or 0) + 1
        asset.processing_status = "processing"
        db.commit()

        # 1. Genuine Image metadata with Pillow
        width, height = 0, 0
        img_format = ""
        is_screenshot = False

        try:
            with Image.open(img_path) as im:
                width, height = im.size
                img_format = im.format or ""
                asset.width = width
                asset.height = height
                
                # Aspect ratio & naming heuristic for screenshots
                if "screenshot" in img_path.name.lower() or (height > width * 1.8):
                    is_screenshot = True
        except Exception as e:
            logger.warning(f"Could not read image dimensions: {e}")

        # 2. Local Tesseract OCR (metadata is NEVER OCR)
        extracted_text = ""
        tess_bin = cls.get_tesseract_binary()

        if not tess_bin:
            # Tesseract tool not installed/available
            asset.processing_status = "setup_needed"
            asset.processing_error = "tesseract_unavailable"
            asset.processing_method = "tesseract-ocr"
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                "status": "setup_needed",
                "error": "Tesseract-OCR binary not installed on host.",
                "width": width,
                "height": height,
                "format": img_format,
                "is_screenshot": is_screenshot,
                "extracted_text": ""
            }

        tessdata_dir = find_tessdata_dir()
        cmd = [tess_bin, str(img_path), "stdout", "-l", "ara+eng", "--psm", "3"]
        if tessdata_dir:
            cmd.extend(["--tessdata-dir", str(tessdata_dir)])

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if res.returncode == 0:
                extracted_text = (res.stdout or "").strip()
                logger.info(f"Tesseract OCR extracted {len(extracted_text)} chars from {img_path.name}")
            else:
                err_msg = res.stderr.strip()
                logger.warning(f"Tesseract returned code {res.returncode}: {err_msg}")
                # If language data is missing, mark setup_needed
                if "ara" in err_msg.lower() or "tessdata" in err_msg.lower() or "traineddata" in err_msg.lower():
                    asset.processing_status = "setup_needed"
                    asset.processing_error = f"tessdata_missing: {err_msg[:100]}"
                    asset.processed_at = datetime.utcnow()
                    db.commit()
                    return {
                        "media_asset_id": asset.id,
                        "status": "setup_needed",
                        "error": err_msg,
                        "width": width,
                        "height": height,
                        "format": img_format,
                        "is_screenshot": is_screenshot,
                        "extracted_text": ""
                    }
        except subprocess.TimeoutExpired:
            logger.error(f"Tesseract OCR timed out on {img_path.name}")
            asset.processing_status = "failed"
            asset.processing_error = "ocr_timeout"
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                "status": "failed",
                "error": "OCR processing timed out",
                "width": width,
                "height": height,
                "format": img_format,
                "is_screenshot": is_screenshot,
                "extracted_text": ""
            }
        except Exception as e:
            logger.error(f"Error running Tesseract OCR: {e}")
            asset.processing_status = "failed"
            asset.processing_error = f"ocr_error: {str(e)[:100]}"
            asset.processed_at = datetime.utcnow()
            db.commit()
            return {
                "media_asset_id": asset.id,
                "status": "failed",
                "error": str(e),
                "width": width,
                "height": height,
                "format": img_format,
                "is_screenshot": is_screenshot,
                "extracted_text": ""
            }

        # 3. Durable persistence & indexing (Truthful: metadata is not OCR)
        asset.processing_status = "completed"
        asset.processing_method = "tesseract-ara+eng"
        asset.processing_error = None
        asset.processed_at = datetime.utcnow()

        # Idempotently update or create DocumentRecord for OCR text
        doc_record = db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).first()
        if not doc_record:
            doc_record = DocumentRecord(
                media_asset_id=asset.id,
                conversation_id=asset.conversation_id,
                title=img_path.stem,
                doc_type="image_ocr",
                page_count=1,
                extracted_text=extracted_text,
                metadata_json={
                    "width": width,
                    "height": height,
                    "format": img_format,
                    "is_screenshot": is_screenshot
                }
            )
            db.add(doc_record)
        else:
            doc_record.extracted_text = extracted_text
            doc_record.doc_type = "image_ocr"
            doc_record.metadata_json = {
                "width": width,
                "height": height,
                "format": img_format,
                "is_screenshot": is_screenshot
            }

        db.flush()

        if extracted_text:
            # Sync verified OCR text to full-text search index
            sync_derived_fts(
                db.connection(),
                media_asset_id=asset.id,
                message_id=asset.message_id,
                conversation_id=asset.conversation_id,
                file_name=asset.file_name,
                source_type="ocr",
                content=extracted_text
            )
        else:
            remove_derived_fts(db.connection(), asset.id)

        db.commit()

        return {
            "media_asset_id": asset.id,
            "document_id": doc_record.id,
            "status": "completed",
            "width": width,
            "height": height,
            "format": img_format,
            "is_screenshot": is_screenshot,
            "extracted_text": extracted_text,
            "char_count": len(extracted_text)
        }
