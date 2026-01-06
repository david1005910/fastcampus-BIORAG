"""Docling Document Parsing Service - Enhanced PDF/Document Processing"""

import logging
import tempfile
import httpx
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedDocument:
    """Parsed document result from Docling"""
    pmid: str
    title: str
    text: str  # Full extracted text
    abstract: str
    sections: List[Dict[str, str]]  # List of {title, content} sections
    tables: List[Dict[str, Any]]  # Extracted tables
    figures: List[Dict[str, str]]  # Figure captions
    metadata: Dict[str, Any]
    parse_method: str  # "docling" or "fallback"


class DoclingService:
    """Service for enhanced document parsing using IBM Docling"""

    def __init__(self):
        self._converter = None
        self._initialized = False

    def _init_docling(self):
        """Lazy initialization of Docling converter"""
        if self._initialized:
            return

        try:
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
            self._initialized = True
            logger.info("Docling document converter initialized")
        except ImportError as e:
            logger.warning(f"Docling not available: {e}")
            self._initialized = False
        except Exception as e:
            logger.error(f"Failed to initialize Docling: {e}")
            self._initialized = False

    def is_available(self) -> bool:
        """Check if Docling is available"""
        self._init_docling()
        return self._converter is not None

    async def parse_pdf_from_url(self, pdf_url: str, pmid: str, title: str = "") -> Optional[ParsedDocument]:
        """Parse PDF from URL using Docling"""
        self._init_docling()

        if not self._converter:
            logger.warning("Docling not available, using fallback")
            return None

        try:
            # Download PDF to temp file
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(pdf_url)
                response.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(response.content)
                    tmp_path = Path(tmp.name)

            # Parse with Docling
            result = self._converter.convert(str(tmp_path))

            # Extract content
            doc = result.document

            # Get full text
            full_text = doc.export_to_markdown()

            # Extract sections
            sections = []
            for item in doc.texts:
                if hasattr(item, 'label') and hasattr(item, 'text'):
                    sections.append({
                        "title": item.label if item.label else "Content",
                        "content": item.text
                    })

            # Extract tables
            tables = []
            if hasattr(doc, 'tables'):
                for table in doc.tables:
                    tables.append({
                        "caption": getattr(table, 'caption', ''),
                        "data": table.export_to_dataframe().to_dict() if hasattr(table, 'export_to_dataframe') else {}
                    })

            # Extract figure captions
            figures = []
            if hasattr(doc, 'pictures'):
                for pic in doc.pictures:
                    if hasattr(pic, 'caption'):
                        figures.append({
                            "caption": pic.caption
                        })

            # Clean up temp file
            tmp_path.unlink()

            # Extract abstract (usually first paragraph or abstract section)
            abstract = ""
            for section in sections:
                if section["title"].lower() in ["abstract", "summary"]:
                    abstract = section["content"]
                    break
            if not abstract and sections:
                abstract = sections[0]["content"][:500]

            return ParsedDocument(
                pmid=pmid,
                title=title,
                text=full_text,
                abstract=abstract,
                sections=sections,
                tables=tables,
                figures=figures,
                metadata={"source_url": pdf_url, "parse_method": "docling"},
                parse_method="docling"
            )

        except Exception as e:
            logger.error(f"Docling PDF parsing failed for {pmid}: {e}")
            return None

    async def parse_pdf_from_bytes(self, pdf_bytes: bytes, pmid: str, title: str = "") -> Optional[ParsedDocument]:
        """Parse PDF from bytes using Docling"""
        self._init_docling()

        if not self._converter:
            return None

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = Path(tmp.name)

            result = self._converter.convert(str(tmp_path))
            doc = result.document
            full_text = doc.export_to_markdown()

            sections = []
            for item in doc.texts:
                if hasattr(item, 'label') and hasattr(item, 'text'):
                    sections.append({
                        "title": item.label if item.label else "Content",
                        "content": item.text
                    })

            tmp_path.unlink()

            abstract = ""
            for section in sections:
                if section["title"].lower() in ["abstract", "summary"]:
                    abstract = section["content"]
                    break
            if not abstract and sections:
                abstract = sections[0]["content"][:500]

            return ParsedDocument(
                pmid=pmid,
                title=title,
                text=full_text,
                abstract=abstract,
                sections=sections,
                tables=[],
                figures=[],
                metadata={"parse_method": "docling"},
                parse_method="docling"
            )

        except Exception as e:
            logger.error(f"Docling PDF parsing from bytes failed for {pmid}: {e}")
            return None

    async def enhance_paper_content(
        self,
        pmid: str,
        title: str,
        abstract: str,
        pmcid: Optional[str] = None
    ) -> ParsedDocument:
        """
        Enhance paper content by trying to get full text via PMC PDF.
        Falls back to abstract-only if PDF not available.
        """
        # Try to get PDF from PMC if we have pmcid
        if pmcid:
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"

            try:
                parsed = await self.parse_pdf_from_url(pdf_url, pmid, title)
                if parsed:
                    logger.info(f"Successfully parsed PDF for {pmid} using Docling")
                    return parsed
            except Exception as e:
                logger.warning(f"Could not parse PMC PDF for {pmid}: {e}")

        # Fallback to abstract-only
        return ParsedDocument(
            pmid=pmid,
            title=title,
            text=f"# {title}\n\n## Abstract\n\n{abstract}",
            abstract=abstract,
            sections=[{"title": "Abstract", "content": abstract}],
            tables=[],
            figures=[],
            metadata={"parse_method": "fallback"},
            parse_method="fallback"
        )


# Singleton instance
_docling_service: Optional[DoclingService] = None


def get_docling_service() -> DoclingService:
    """Get singleton Docling service instance"""
    global _docling_service
    if _docling_service is None:
        _docling_service = DoclingService()
    return _docling_service
