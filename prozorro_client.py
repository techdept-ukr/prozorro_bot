import aiohttp
import logging
import ssl
import datetime
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

            # КРИТИЧНА ПЕРЕВІРКА — переконуємось що це саме той тендер
            actual_tender_id = result.get("tenderID", "")
            if tender_id.startswith("UA-") and actual_tender_id != tender_id:
                raise ValueError(
                    f"Помилка: запитували тендер '{tender_id}', "
                    f"але API повернув '{actual_tender_id}'. "
                    f"Внутрішній ID: {internal_id}"
                )

            logger.info(f"✅ Підтверджено: tenderID={actual_tender_id}, internal={internal_id}")
            return result

    async def _resolve_tender_id(self, tender_ua_id: str) -> str:
        """Знаходить внутрішній хеш-ID за людським UA-YYYY-MM-DD-XXXXXX-a."""

        # Витягуємо дату з ID: UA-2026-03-12-014166-a -> 2026-03-12
        try:
            parts = tender_ua_id.split("-")
            # формат: UA - YYYY - MM - DD - NUMBER - a
            year, month, day = parts[1], parts[2], parts[3]
            date_str = f"{year}-{month}-{day}"
            target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            logger.info(f"Шукаємо тендер {tender_ua_id}, дата: {date_str}")
        except Exception as e:
            raise ValueError(f"Не вдалося розпарсити дату з ID '{tender_ua_id}': {e}")

        # Шукаємо по публічному API з offset по даті
        # Перебираємо сторінки навколо дати публікації
        url = "https://public.api.prozorro.gov.ua/api/2.5/tenders"

        # Спробуємо offset = timestamp початку дня
        offsets_to_try = [
            target_date.timestamp(),
            (target_date + datetime.timedelta(days=1)).timestamp(),
            (target_date - datetime.timedelta(days=1)).timestamp(),
            (target_date + datetime.timedelta(days=2)).timestamp(),
            (target_date - datetime.timedelta(days=2)).timestamp(),
        ]

        for start_offset in offsets_to_try:
            try:
                params = {
                    "offset": str(start_offset),
                    "limit": "100",
                    "opt_fields": "tenderID",
                }
                offset = start_offset
                for page in range(8):
                    params["offset"] = str(offset)
                    async with self.session.get(url, params=params) as resp:
                        if resp.status != 200:
                            break
                        data = await resp.json(content_type=None)
                        items = data.get("data", [])
                        if not items:
                            break

                        first_id = items[0].get("tenderID", "")
                        last_id = items[-1].get("tenderID", "")
                        logger.info(f"offset={offset:.0f} | {first_id} ... {last_id}")

                        for item in items:
                            if item.get("tenderID") == tender_ua_id:
                                found_id = item.get("id")
                                logger.info(f"✅ Знайдено! {tender_ua_id} → {found_id}")
                                return found_id

                        next_offset = data.get("next_page", {}).get("offset")
                        if not next_offset or next_offset == offset:
                            break
                        offset = next_offset

            except Exception as e:
                logger.warning(f"offset {start_offset} failed: {e}")
                continue

        raise ValueError(
            f"❌ Тендер '{tender_ua_id}' не знайдено в Prozorro API.\n\n"
            f"Можливі причини:\n"
            f"• Тендер видалено або скасовано\n"
            f"• Тендер не пройшов публікацію\n"
            f"• Спробуй ще раз через кілька хвилин"
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
