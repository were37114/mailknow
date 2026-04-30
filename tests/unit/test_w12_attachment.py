"""Tests for W12: Attachment extraction + metadata."""

import pytest
from unittest.mock import MagicMock, patch

from core.attachment.extractor import (
    AttachmentExtractor,
    AttachmentType,
    AttachmentMetadata,
)


class TestAttachmentExtractor:
    """Test attachment extraction pipeline."""

    @pytest.fixture
    def extractor(self):
        return AttachmentExtractor()

    def test_classify_pdf(self, extractor):
        assert extractor.classify_attachment("report.pdf") == AttachmentType.PDF

    def test_classify_excel(self, extractor):
        assert extractor.classify_attachment("data.xlsx") == AttachmentType.EXCEL
        assert extractor.classify_attachment("data.xls") == AttachmentType.EXCEL
        assert extractor.classify_attachment("data.csv") == AttachmentType.EXCEL

    def test_classify_word(self, extractor):
        assert extractor.classify_attachment("doc.docx") == AttachmentType.WORD
        assert extractor.classify_attachment("doc.doc") == AttachmentType.WORD

    def test_classify_image(self, extractor):
        assert extractor.classify_attachment("photo.png") == AttachmentType.IMAGE
        assert extractor.classify_attachment("photo.jpg") == AttachmentType.IMAGE
        assert extractor.classify_attachment("photo.jpeg") == AttachmentType.IMAGE

    def test_classify_zip(self, extractor):
        assert extractor.classify_attachment("archive.zip") == AttachmentType.ZIP

    def test_classify_unknown(self, extractor):
        assert extractor.classify_attachment("data.bin") == AttachmentType.OTHER
        assert extractor.classify_attachment("noext") == AttachmentType.OTHER

    def test_attachment_metadata_model(self):
        meta = AttachmentMetadata(
            attachment_id="att1",
            filename="report.pdf",
            file_type=AttachmentType.PDF,
            file_size=1024000,
            mime_type="application/pdf",
        )
        assert meta.filename == "report.pdf"
        assert meta.file_type == AttachmentType.PDF
        assert not meta.text_extracted

    def test_attachment_metadata_with_content(self):
        meta = AttachmentMetadata(
            filename="budget.xlsx",
            file_type=AttachmentType.EXCEL,
            text_content="Sheet1: 预算数据",
            text_extracted=True,
            page_count=3,
        )
        assert meta.text_extracted is True
        assert "预算" in meta.text_content

    def test_attachment_metadata_llm_summary(self):
        meta = AttachmentMetadata(
            filename="contract.pdf",
            file_type=AttachmentType.PDF,
            llm_summary="这是一份采购合同，金额5万元",
            llm_understood=True,
        )
        assert meta.llm_understood is True
        assert "合同" in meta.llm_summary
