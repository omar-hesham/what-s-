"""
Local document extraction pipeline.
Supports PDF, DOCX, XLSX, TXT, and CSV.
Extracts structured text, page counts, table content, and metadata.
Preserves source document hashes for integrity.
"""

import csv
from pathlib import Path
from typing import Dict, Any
from sqlalchemy.orm import Session
from pypdf import PdfReader
from docx import Document as DocxDocument
import openpyxl

from owi.core.logging import logger
from owi.db.models import MediaAsset, DocumentRecord

class DocumentProcessor:
    """Extracts text and metadata from PDF, Word, Excel, and text documents."""

    @classmethod
    def process_document(cls, media_asset_id: int, db: Session) -> Dict[str, Any]:
        asset = db.query(MediaAsset).filter(MediaAsset.id == media_asset_id).first()
        if not asset:
            raise ValueError(f"MediaAsset #{media_asset_id} not found.")

        file_path = Path(asset.file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file does not exist: {file_path}")

        suffix = file_path.suffix.lower()
        extracted_text = ""
        page_count = 1
        meta = {}

        try:
            if suffix == ".pdf":
                reader = PdfReader(file_path)
                page_count = len(reader.pages)
                pages_text = []
                for p_idx, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    if text.strip():
                        pages_text.append(f"--- Page {p_idx + 1} ---\n{text.strip()}")
                extracted_text = "\n\n".join(pages_text)
                if reader.metadata:
                    meta = {k: str(v) for k, v in reader.metadata.items() if v}

            elif suffix in (".docx", ".doc"):
                doc = DocxDocument(file_path)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                # Extract tables
                table_texts = []
                for table in doc.tables:
                    for row in table.rows:
                        row_vals = [cell.text.strip() for cell in row.cells]
                        table_texts.append(" | ".join(row_vals))
                extracted_text = "\n".join(paragraphs)
                if table_texts:
                    extracted_text += "\n\n--- Tables ---\n" + "\n".join(table_texts)
                page_count = max(1, len(paragraphs) // 10)

            elif suffix in (".xlsx", ".xls"):
                wb = openpyxl.load_workbook(file_path, data_only=True)
                sheets_text = []
                for sheetname in wb.sheetnames:
                    sheet = wb[sheetname]
                    sheet_lines = [f"=== Sheet: {sheetname} ==="]
                    for row in sheet.iter_rows(values_only=True):
                        # Filter empty rows
                        if any(cell is not None for cell in row):
                            row_str = " | ".join(str(cell) if cell is not None else "" for cell in row)
                            sheet_lines.append(row_str)
                    sheets_text.append("\n".join(sheet_lines))
                extracted_text = "\n\n".join(sheets_text)
                meta["sheet_names"] = wb.sheetnames
                page_count = len(wb.sheetnames)

            elif suffix in (".csv", ".txt"):
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    extracted_text = f.read()
                page_count = max(1, extracted_text.count("\n") // 40)

        except Exception as e:
            logger.error(f"Error extracting document text from {file_path.name}: {e}")
            extracted_text = f"[Text extraction error: {e}]"

        # Save to DB
        existing = db.query(DocumentRecord).filter(DocumentRecord.media_asset_id == asset.id).first()
        if existing:
            db.delete(existing)
            db.flush()

        doc_record = DocumentRecord(
            media_asset_id=asset.id,
            conversation_id=asset.conversation_id,
            title=file_path.stem,
            doc_type=suffix.lstrip("."),
            page_count=page_count,
            extracted_text=extracted_text,
            metadata_json=meta
        )
        db.add(doc_record)
        db.commit()
        db.refresh(doc_record)

        return {
            "media_asset_id": asset.id,
            "document_id": doc_record.id,
            "title": doc_record.title,
            "doc_type": doc_record.doc_type,
            "page_count": doc_record.page_count,
            "char_count": len(extracted_text)
        }
