import aiohttp
import asyncio
import logging
import ssl
from typing import Optional

logger = logging.getLogger(__name__)


class ProzorroClient:

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Accept": "application/json"}
        )
        return self

    async def __aexit__(self, *args):
        if self.session:
            await self.session.close()

    async def get_tender(self, tender_id: str) -> dict:
        if tender_id.startswith("UA-"):
            internal_id = await self._resolve_tender_id(tender_id)
        else:
            internal_id = tender_id

        url = f"https://public.api.prozorro.gov.ua/api/2.5/tenders/{internal_id}"
        async with self.session.get(url) as resp:
            if resp.status == 404:
                raise ValueError(f"Тендер '{tender_id}' не знайдено в API")
            resp.raise_for_status()
            data = await resp.json(content_type=None)
            return data.get("data", {})

    async def _resolve_tender_id(self, tender_ua_id: str) -> str:
        """Знаходить внутрішній хеш-ID за людським UA-... ID."""

        # Варіант 1 — prozorro search API
        try:
            url = "https://prozorro.gov.ua/api/search/tenders"
            async with self.session.get(url, params={"tenderId": tender_ua_id}) as resp:
                logger.info(f"[V1] Search API status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V1] Search API response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("data", []) or data.get("items", [])
                    if items:
                        found_id = items[0].get("id")
                        logger.info(f"[V1] Found internal ID: {found_id}")
                        return found_id
        except Exception as e:
            logger.warning(f"[V1] Search API failed: {e}")

        # Варіант 2 — фільтрація по tenderID у публічному API
        try:
            url2 = (
                f"https://public.api.prozorro.gov.ua/api/2.5/tenders"
                f"?opt_fields=tenderID&tenderID={tender_ua_id}"
            )
            async with self.session.get(url2) as resp:
                logger.info(f"[V2] Filter API status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V2] Filter API response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("data", [])
                    if items:
                        found_id = items[0].get("id")
                        logger.info(f"[V2] Found internal ID: {found_id}")
                        return found_id
        except Exception as e:
            logger.warning(f"[V2] Filter API failed: {e}")

        # Варіант 3 — prozorro.gov.ua REST напряму
        try:
            url3 = f"https://prozorro.gov.ua/api/tenders/{tender_ua_id}"
            async with self.session.get(url3) as resp:
                logger.info(f"[V3] Direct API status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V3] Direct API response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    found_id = data.get("data", {}).get("id")
                    if found_id:
                        logger.info(f"[V3] Found internal ID: {found_id}")
                        return found_id
        except Exception as e:
            logger.warning(f"[V3] Direct API failed: {e}")

        # Варіант 4 — DoZorro API
        try:
            url4 = f"https://dozorro.org/api/tenders/{tender_ua_id}"
            async with self.session.get(url4) as resp:
                logger.info(f"[V4] DoZorro API status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V4] DoZorro API response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    found_id = data.get("id") or data.get("_id")
                    if found_id:
                        logger.info(f"[V4] Found internal ID: {found_id}")
                        return found_id
        except Exception as e:
            logger.warning(f"[V4] DoZorro API failed: {e}")

        raise ValueError(
            f"Тендер '{tender_ua_id}' не знайдено жодним із методів.\n"
            f"Перевір логи Railway — там буде видно відповідь API."
        )

    async def download_document(self, url: str) -> Optional[bytes]:
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
        docs = []

        for doc in tender.get("documents", []):
            docs.append({**doc, "source": "замовник", "source_type": "tender"})

        for bid in tender.get("bids", []):
            bidder_name = bid.get("tenderers", [{}])[0].get("name", "Учасник")
            for doc in bid.get("documents", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid"})
            for doc in bid.get("financialDocuments", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid_financial"})
            for doc in bid.get("eligibilityDocuments", []):
                docs.append({**doc, "source": bidder_name, "source_type": "bid_eligibility"})

        for award in tender.get("awards", []):
            for doc in award.get("documents", []):
                docs.append({**doc, "source": "рішення", "source_type": "award"})

        return docs
