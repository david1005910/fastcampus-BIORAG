"""PMC (PubMed Central) Service for PDF access"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class PMCPaperInfo:
    """PDF availability information for a paper"""
    pmid: str
    pmcid: Optional[str] = None
    has_pdf: bool = False
    pdf_url: Optional[str] = None
    is_open_access: bool = False


class PMCService:
    """Service for accessing PubMed Central (PMC) resources"""

    PMC_ID_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
    # Updated to new PMC domain (old www.ncbi.nlm.nih.gov redirects to pmc.ncbi.nlm.nih.gov)
    PMC_PDF_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/articles/"

    def __init__(self, email: str = "bio-rag@example.com"):
        self.email = email

    async def _convert_pmid_to_pmcid(self, pmids: List[str]) -> Dict[str, Optional[str]]:
        """Convert PMIDs to PMCIDs using NCBI ID Converter"""
        result = {pmid: None for pmid in pmids}

        if not pmids:
            return result

        try:
            params = {
                "ids": ",".join(pmids),
                "format": "json",
                "tool": "bio-rag",
                "email": self.email
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.PMC_ID_CONVERTER_URL, params=params) as response:
                    if response.status != 200:
                        logger.warning(f"PMC ID converter returned status {response.status}")
                        return result

                    data = await response.json()
                    records = data.get("records", [])

                    for record in records:
                        pmid = record.get("pmid")
                        pmcid = record.get("pmcid")
                        if pmid and pmcid:
                            # Convert PMID to string for consistent key matching
                            result[str(pmid)] = pmcid

        except Exception as e:
            logger.error(f"Error converting PMIDs to PMCIDs: {e}")

        return result

    async def _check_open_access(self, pmcids: List[str]) -> Dict[str, Dict]:
        """Check open access status for PMCIDs"""
        result = {}

        if not pmcids:
            return result

        try:
            params = {
                "id": ",".join(pmcids),
                "format": "json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.PMC_OA_URL, params=params) as response:
                    if response.status != 200:
                        logger.warning(f"PMC OA check returned status {response.status}")
                        return result

                    data = await response.json()
                    records = data.get("records", [])

                    for record in records:
                        pmcid = record.get("id")
                        if pmcid:
                            pdf_link = None
                            for link in record.get("links", []):
                                if link.get("format") == "pdf":
                                    pdf_link = link.get("href")
                                    break

                            result[pmcid] = {
                                "is_open_access": True,
                                "pdf_url": pdf_link
                            }

        except Exception as e:
            logger.error(f"Error checking open access: {e}")

        return result

    async def get_pdf_info(self, pmids: List[str]) -> Dict[str, PMCPaperInfo]:
        """Get PDF availability info for multiple papers"""
        result = {}

        # Convert PMIDs to PMCIDs
        pmcid_map = await self._convert_pmid_to_pmcid(pmids)

        # Get PMCIDs that exist
        valid_pmcids = [pmcid for pmcid in pmcid_map.values() if pmcid]

        # Check open access for valid PMCIDs
        oa_info = await self._check_open_access(valid_pmcids)

        # Build results
        for pmid in pmids:
            pmcid = pmcid_map.get(pmid)

            if pmcid:
                oa_data = oa_info.get(pmcid, {})
                pdf_url = oa_data.get("pdf_url")

                # If no direct OA PDF, construct PMC article URL
                if not pdf_url and pmcid:
                    pdf_url = f"{self.PMC_PDF_BASE_URL}{pmcid}/pdf/"

                result[pmid] = PMCPaperInfo(
                    pmid=pmid,
                    pmcid=pmcid,
                    has_pdf=True,
                    pdf_url=pdf_url,
                    is_open_access=oa_data.get("is_open_access", False)
                )
            else:
                result[pmid] = PMCPaperInfo(
                    pmid=pmid,
                    pmcid=None,
                    has_pdf=False,
                    pdf_url=None,
                    is_open_access=False
                )

        return result

    async def get_single_pdf_info(self, pmid: str) -> PMCPaperInfo:
        """Get PDF availability info for a single paper"""
        result = await self.get_pdf_info([pmid])
        return result.get(pmid, PMCPaperInfo(pmid=pmid))

    async def download_pdf(self, pmid: str) -> Tuple[Optional[bytes], str]:
        """
        Download PDF for a paper

        Returns:
            Tuple of (pdf_bytes, filename_or_error)
            If pdf_bytes is None, the second value is an error message
        """
        info = await self.get_single_pdf_info(pmid)

        if not info.has_pdf or not info.pdf_url:
            return None, f"PDF not available for PMID {pmid}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(info.pdf_url) as response:
                    if response.status != 200:
                        return None, f"Failed to download PDF: HTTP {response.status}"

                    content_type = response.headers.get("Content-Type", "")
                    if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                        return None, f"Response is not a PDF: {content_type}"

                    pdf_bytes = await response.read()
                    filename = f"{info.pmcid or pmid}.pdf"

                    return pdf_bytes, filename

        except Exception as e:
            logger.error(f"Error downloading PDF for PMID {pmid}: {e}")
            return None, f"Download failed: {str(e)}"


# Singleton instance
_pmc_service: Optional[PMCService] = None


def get_pmc_service(email: str = "bio-rag@example.com") -> PMCService:
    """Get or create the PMC service instance"""
    global _pmc_service
    if _pmc_service is None:
        _pmc_service = PMCService(email=email)
    return _pmc_service
