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
        """
        tender_id може бути:
        - UA-2026-03-12-014166-a  (людський ID з URL)
        - або внутрішній хеш (32 символи)
        """
        # Якщо це людський ID (UA-...) — шукаємо через search API
        if tender_id.startswith("UA-"):
            internal_id = await self._resolve_tender_id(tender_id)
        else:
            internal_id = tender_id

        url = f"https://public.api.prozorro.gov.ua/api/2.5/tenders/{internal_id}"
        async with self.session.get(url) as resp:
            if resp.status == 404:
                raise ValueError(f"Тендер '{tender_id}' не знайдено в API")
            resp.raise_for_status()
            data = await resp.json()
            return data.get("data", {})

    async def _resolve_tender_id(self, tender_ua_id: str) -> str:
        """Знаходить внутрішній хеш-ID за людським UA-... ID через пошук."""
        # Prozorro search API
        search_url = "https://prozorro.gov.ua/api/search/tenders"
        params = {"tenderId": tender_ua_id}
        
        try:
            async with self.session.get(search_url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", []) or data.get("items", [])
                    if items:
                        return items[0].get("id", tender_ua_id)
        except Exception as e:
            logger.warning(f"Search API failed: {e}")

        # Запасний варіант — пряме звернення через prozorro.gov.ua
        try:
            url2 = f"https://prozorro.gov.ua/api/tenders/{tender_ua_id}"
            async with self.session.get(url2) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("id", tender_ua_id)
        except Exception as e:
            logger.warning(f"Direct API failed: {e}")

        # Ще один запасний — DoZorro / BI API
        try:
            bi_url = f"https://bi.prozorro.org/api/tenders/{tender_ua_id}"
            async with self.session.get(bi_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    internal = data.get("id") or data.get("_id")
                    if internal:
                        return internal
        except Exception as e:
            logger.warning(f"BI API failed: {e}")

        # Якщо нічого не знайшли — повертаємо як є
        raise ValueError(
            f"Тендер '{tender_ua_id}' не знайдено.\n\n"
            f"Спробуй відкрити тендер на prozorro.gov.ua, "
            f"натисни F12 → Network → знайди запит до API → скопіюй внутрішній ID (32 символи)"
        )

    async def download_document(self, url: str) -> Optional[bytes]:
        try:
            async with self.session.get(url, allow_redirects=True) as resp:
                if resp.status == 200:
                    return await resp.read()
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
