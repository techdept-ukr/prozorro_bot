import aiohttp
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
            result = data.get("data", {})
            logger.info(f"Fetched tender tenderID={result.get('tenderID')}")
            return result

    async def _resolve_tender_id(self, tender_ua_id: str) -> str:
        """Знаходить внутрішній хеш-ID за людським UA-... ID."""

        # Варіант 1 — POST search з query по точному tenderID
        try:
            url = "https://prozorro.gov.ua/api/search/tenders"
            # Пробуємо різні поля запиту
            for payload in [
                {"query": tender_ua_id},
                {"tenderId": tender_ua_id},
                {"tenderID": tender_ua_id},
                {"id": tender_ua_id},
            ]:
                async with self.session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        items = data.get("data", [])
                        logger.info(f"[V1] payload={payload}, items={len(items)}, перший tenderID={items[0].get('tenderID') if items else 'none'}")
                        for item in items:
                            if item.get("tenderID") == tender_ua_id:
                                found_id = item.get("id")
                                logger.info(f"[V1] Знайдено! id={found_id}")
                                return found_id
        except Exception as e:
            logger.warning(f"[V1] failed: {e}")

        # Варіант 2 — публічний API з сортуванням по даті тендера (не dateModified)
        # UA-2026-03-12-014166-a -> дата 2026-03-12, шукаємо навколо неї
        try:
            # Витягуємо дату з tenderID: UA-YYYY-MM-DD-...
            parts = tender_ua_id.split("-")
            # UA + рік + місяць + день = індекси 1,2,3
            date_str = f"{parts[1]}-{parts[2]}-{parts[3]}"
            logger.info(f"[V2] Шукаємо тендер від дати: {date_str}")

            # Беремо offset від дати публікації
            import datetime
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            # offset в секундах від epoch
            offset_ts = target_date.timestamp()

            url2 = "https://public.api.prozorro.gov.ua/api/2.5/tenders"
            # Шукаємо з offset трохи раніше дати тендера
            params = {
                "offset": str(offset_ts),
                "limit": "100",
                "opt_fields": "tenderID",
            }
            async with self.session.get(url2, params=params) as resp:
                logger.info(f"[V2] status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = data.get("data", [])
                    logger.info(f"[V2] items: {len(items)}, перший: {items[0].get('tenderID') if items else 'none'}")
                    for item in items:
                        if item.get("tenderID") == tender_ua_id:
                            found_id = item.get("id")
                            logger.info(f"[V2] Знайдено! id={found_id}")
                            return found_id
                    # Беремо ще кілька сторінок навколо цієї дати
                    next_offset = data.get("next_page", {}).get("offset")
                    for _ in range(5):
                        if not next_offset:
                            break
                        params["offset"] = str(next_offset)
                        async with self.session.get(url2, params=params) as resp2:
                            if resp2.status != 200:
                                break
                            data2 = await resp2.json(content_type=None)
                            items2 = data2.get("data", [])
                            logger.info(f"[V2+] items: {len(items2)}, перший: {items2[0].get('tenderID') if items2 else 'none'}")
                            for item in items2:
                                if item.get("tenderID") == tender_ua_id:
                                    found_id = item.get("id")
                                    logger.info(f"[V2+] Знайдено! id={found_id}")
                                    return found_id
                            next_offset = data2.get("next_page", {}).get("offset")
        except Exception as e:
            logger.warning(f"[V2] failed: {e}")

        # Варіант 3 — GET prozorro.gov.ua з query параметром
        try:
            url3 = "https://prozorro.gov.ua/api/tenders"
            for params in [
                {"tenderId": tender_ua_id},
                {"tenderID": tender_ua_id},
                {"query": tender_ua_id},
            ]:
                async with self.session.get(url3, params=params) as resp:
                    logger.info(f"[V3] params={params}, status={resp.status}")
                    text = await resp.text()
                    logger.info(f"[V3] response: {text[:300]}")
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        items = data.get("data", []) or data.get("items", [])
                        for item in items:
                            if item.get("tenderID") == tender_ua_id:
                                found_id = item.get("id")
                                logger.info(f"[V3] Знайдено! id={found_id}")
                                return found_id
        except Exception as e:
            logger.warning(f"[V3] failed: {e}")

        raise ValueError(
            f"Тендер '{tender_ua_id}' не знайдено.\n"
            f"Деталі в логах Railway."
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
