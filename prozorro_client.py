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

        # Варіант 1 — POST search API
        try:
            url = "https://prozorro.gov.ua/api/search/tenders"
            payload = {"tenderId": tender_ua_id}
            async with self.session.post(url, json=payload) as resp:
                logger.info(f"[V1] POST Search status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V1] POST Search response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("data", []) or data.get("items", [])
                    for item in items:
                        if item.get("tenderID") == tender_ua_id:
                            found_id = item.get("id")
                            logger.info(f"[V1] Found: {found_id}")
                            return found_id
        except Exception as e:
            logger.warning(f"[V1] failed: {e}")

        # Варіант 2 — пряме звернення через prozorro.gov.ua/api/tenders/UA-...
        try:
            url2 = f"https://prozorro.gov.ua/api/tenders/{tender_ua_id}"
            async with self.session.get(url2) as resp:
                logger.info(f"[V2] Direct status: {resp.status}")
                text = await resp.text()
                logger.info(f"[V2] Direct response: {text[:500]}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    found_id = data.get("data", {}).get("id")
                    if found_id:
                        logger.info(f"[V2] Found: {found_id}")
                        return found_id
        except Exception as e:
            logger.warning(f"[V2] failed: {e}")

        # Варіант 3 — перебір сторінок публічного API з пошуком по tenderID
        try:
            url3 = "https://public.api.prozorro.gov.ua/api/2.5/tenders"
            params = {"descending": "1", "limit": "100", "opt_fields": "tenderID"}
            # Шукаємо у свіжих тендерах (останні 3 сторінки)
            offset = None
            for page in range(3):
                if offset:
                    params["offset"] = offset
                async with self.session.get(
