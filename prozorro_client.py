import aiohttp
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

PROZORRO_PUBLIC_API = "https://public.api.prozorro.gov.ua/api/2.5"
PROZORRO_DS_BASE = "https://public-docs.prozorro.gov.ua/get"

class ProzorroClient:
    """Client for Prozorro Public API (no API key required for reading)."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Accept": "application/json"}
        )
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def get_tender(self, tender_id: str) -> dict:
        """Fetch full tender data by ID."""
        url = f"{PROZORRO_PUBLIC_API}/tenders/{tender_id}"
        async with self.session.get(url) as resp:
            if resp.status == 404:
                raise ValueError(f"Тендер '{tender_id}' не знайдено")
            resp.raise_for_status()
            data = await resp.json()
            return data.get("data", {})

    async def download_document(self, url: str) -> Optional[bytes]:
        """Download a document from Prozorro DS."""
        try:
            async with self.session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.warning(f"Failed to download doc: HTTP {resp.status} — {url}")
                return None
        except Exception as e:
            logger.warning(f"Error downloading document {url}: {e}")
            return None

    async def get_tender_documents(self, tender: dict) -> list[dict]:
        """Extract all documents from tender data (tender + awards + bids)."""
        docs = []

        # Tender-level documents
        for doc in tender.get("documents", []):
            docs.append({**doc, "source": "замовник", "source_type": "tender"})

        # Bid documents (participants)
        for bid in tender.get("bids", []):
            bidder_name = bid.get("tenderers", [{}])[0].get("name", "Учасник")
            for doc in bid.get("documents", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid"})
            for doc in bid.get("financialDocuments", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid_financial"})
            for doc in bid.get("eligibilityDocuments", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid_eligibility"})

        # Award documents
        for award in tender.get("awards", []):
            for doc in award.get("documents", []):
                docs.append({**doc, "source": "рішення", "source_type": "award"})

        return docs
