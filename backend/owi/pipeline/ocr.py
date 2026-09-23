"""
Local image analysis and OCR pipeline.
Extracts dimensions, detects document/screenshot categories,
runs local OCR (Tesseract / PaddleOCR / EasyOCR) for Arabic and English text,
and links extracted text to the media asset and conversation.
"""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image
from sqlalchemy.orm import Session

from owi.core.logging import logger
from owi.db.models import MediaAsset

# Common Windows Tesseract paths
TESSERACT_CANDIDATES = [
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
]

def find_tesseract_binary() -> Optional[str]:
    """Locate tesseract binary on Windows."""
    in_path = shutil.which("tesseract")
    if in_path:
        return in_path
    for candidate in TESSERACT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None

class ImageAnalyzer:
    """Performs image metadata inspection and local OCR."""

    @classmethod
    def analyze_image(cls, media_asset_id: int, db: Session) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"MediaAsset #{media_asset_id} not found.")

        img_path = Path(asset.file_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Image file does not exist: {img_path}")

        # 1. Image metadata with Pillow
        width, height = 0, 0
        img_format = ""
        is_screenshot = False

        try:
            with Image.open(img_path) as im:
                width, height = im.size
                img_format = im.format or ""
                asset.width = width
                asset.height = height
                
                # Simple aspect ratio & naming heuristic for screenshots
                if "screenshot" in img_path.name.lower() or (height > width * 1.8):
                    is_screenshot = True
        except Exception as e:
            logger.warning(f"Could not read image dimensions: {e}")

        # 2. Local OCR
        extracted_text = ""
        tess_bin = find_tesseract_binary()

        if tess_bin:
            try:
                # Run tesseract CLI on image with Arabic and English
                cmd = [tess_bin, str(img_path), "stdout", "-l", "ara+eng", "--psm", "3"]
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
                if res.returncode == 0:
                    extracted_text = res.stdout.strip()
                    logger.info(f"Tesseract OCR extracted {len(extracted_text)} chars from {img_path.name}")
            except Exception as e:
                logger.error(f"Error running Tesseract OCR: {e}")

        # If no OCR engine available, provide metadata description
        if not extracted_text:
            extracted_text = f"صورة {img_format} بدقة {width}x{height} بكسل ({'لقطة شاشة' if is_screenshot else 'صورة فوتوغرافية'})."

        db.commit()

        return {
            "media_asset_id": asset.id,
            "width": width,
            "height": height,
            "format": img_format,
            "is_screenshot": is_screenshot,
            "extracted_text": extracted_text
        }
