"""Attachment extraction and understanding.

V5.2 spec:
- PDF text extraction (PyPDF2/pdfplumber)
- Excel data extraction (openpyxl)
- LLM-based understanding for images/scans
- Attachment metadata management
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AttachmentType(str, Enum):
    """Supported attachment types."""
    PDF = "pdf"
    EXCEL = "excel"
    WORD = "word"
    IMAGE = "image"
    ZIP = "zip"
    OTHER = "other"


@dataclass
class AttachmentMetadata:
    """Metadata for an email attachment."""
    attachment_id: str = ""
    filename: str = ""
    file_type: AttachmentType = AttachmentType.OTHER
    file_size: int = 0
    mime_type: str = ""

    # Content extraction
    text_content: str = ""
    text_extracted: bool = False
    page_count: int = 0

    # LLM understanding
    llm_summary: str = ""
    llm_understood: bool = False

    # Preview
    preview_available: bool = False
    preview_path: str = ""

    # Metadata
    extracted_at: str = ""
    email_id: str = ""

    # Raw data reference
    file_path: str = ""


class AttachmentExtractor:
    """Extract and understand email attachments.

    Features:
    - PDF text extraction
    - Excel data extraction
    - Image LLM understanding
    - Metadata management
    """

    # File extension to type mapping
    EXT_MAP = {
        ".pdf": AttachmentType.PDF,
        ".xlsx": AttachmentType.EXCEL,
        ".xls": AttachmentType.EXCEL,
        ".csv": AttachmentType.EXCEL,
        ".docx": AttachmentType.WORD,
        ".doc": AttachmentType.WORD,
        ".png": AttachmentType.IMAGE,
        ".jpg": AttachmentType.IMAGE,
        ".jpeg": AttachmentType.IMAGE,
        ".gif": AttachmentType.IMAGE,
        ".webp": AttachmentType.IMAGE,
        ".zip": AttachmentType.ZIP,
    }

    def __init__(self, llm_client=None):
        self.llm = llm_client

    def classify_attachment(self, filename: str) -> AttachmentType:
        """Classify attachment by filename extension."""
        _, ext = os.path.splitext(filename.lower())
        return self.EXT_MAP.get(ext, AttachmentType.OTHER)

    def extract_pdf(self, file_path: str) -> Tuple[str, int]:
        """Extract text from PDF.

        Returns:
            (text_content, page_count)
        """
        try:
            import pdfplumber

            text_parts = []
            page_count = 0

            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages[:50]:  # Max 50 pages
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

            content = "\n\n".join(text_parts)
            return content, page_count

        except ImportError:
            # Fallback to PyPDF2
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(file_path)
                page_count = len(reader.pages)
                text_parts = []
                for page in reader.pages[:50]:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

                content = "\n\n".join(text_parts)
                return content, page_count

            except ImportError:
                logger.warning("No PDF library available (pdfplumber or PyPDF2)")
                return "", 0
        except Exception as e:
            logger.error(f"PDF extraction failed for {file_path}: {e}")
            return "", 0

    def extract_excel(self, file_path: str) -> Tuple[str, int]:
        """Extract data from Excel.

        Returns:
            (text_content, sheet_count)
        """
        try:
            import openpyxl

            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            text_parts = []
            sheet_count = len(wb.sheetnames)

            for sheet_name in wb.sheetnames[:10]:  # Max 10 sheets
                ws = wb[sheet_name]
                text_parts.append(f"=== Sheet: {sheet_name} ===")

                row_count = 0
                for row in ws.iter_rows(values_only=True):
                    if row_count >= 100:  # Max 100 rows per sheet
                        break
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        text_parts.append(" | ".join(cells))
                        row_count += 1

            wb.close()
            content = "\n".join(text_parts)
            return content, sheet_count

        except ImportError:
            logger.warning("openpyxl not available")
            return "", 0
        except Exception as e:
            logger.error(f"Excel extraction failed for {file_path}: {e}")
            return "", 0

    def extract_csv(self, file_path: str) -> str:
        """Extract data from CSV."""
        try:
            import csv

            text_parts = []
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                for i, row in enumerate(reader):
                    if i >= 200:  # Max 200 rows
                        break
                    text_parts.append(" | ".join(row))

            return "\n".join(text_parts)
        except Exception as e:
            logger.error(f"CSV extraction failed: {e}")
            return ""

    async def extract(
        self,
        file_path: str,
        filename: str,
        email_id: str = "",
    ) -> AttachmentMetadata:
        """Extract content from an attachment.

        Args:
            file_path: Path to the attachment file
            filename: Original filename
            email_id: Source email ID

        Returns:
            Attachment metadata with extracted content
        """
        file_type = self.classify_attachment(filename)
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

        metadata = AttachmentMetadata(
            attachment_id=hashlib.sha256(f"{email_id}:{filename}".encode()).hexdigest()[:16],
            filename=filename,
            file_type=file_type,
            file_size=file_size,
            email_id=email_id,
            file_path=file_path,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )

        # Extract based on type
        if file_type == AttachmentType.PDF:
            content, pages = self.extract_pdf(file_path)
            metadata.text_content = content
            metadata.text_extracted = bool(content)
            metadata.page_count = pages

        elif file_type == AttachmentType.EXCEL:
            if filename.endswith('.csv'):
                content = self.extract_csv(file_path)
                metadata.text_content = content
                metadata.text_extracted = bool(content)
                metadata.page_count = 1
            else:
                content, sheets = self.extract_excel(file_path)
                metadata.text_content = content
                metadata.text_extracted = bool(content)
                metadata.page_count = sheets

        # Truncate very long content
        if len(metadata.text_content) > 50000:
            metadata.text_content = metadata.text_content[:50000] + "\n...(truncated)"

        return metadata

    def get_stats(self) -> Dict[str, Any]:
        """Get extractor statistics."""
        return {
            "supported_types": [t.value for t in AttachmentType],
        }
