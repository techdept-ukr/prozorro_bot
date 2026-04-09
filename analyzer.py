import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

import anthropic
from telegram import Message

from prozorro_client import ProzorroClient
from document_reader import extract_text_from_bytes
from report_generator import generate_docx_report

logger = logging.getLogger(__name__)

MAX_DOC_CHARS = 8000        # per document
MAX_TOTAL_CHARS = 60000     # total context to Claude
MAX_DOCS_PER_PARTY = 5


class TenderAnalyzer:
    def __init__(self, anthropic_api_key: str):
        self.claude = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    async def analyze(self, tender_id: str, status_msg: Optional[Message] = None) -> tuple[str, str]:
        """Full tender analysis. Returns (docx_path, short_summary)."""

        async with ProzorroClient() as client:
            # 1. Fetch tender data
            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "📡 Завантаження даних з ProZorro...",
                    parse_mode='Markdown'
                )
            tender = await client.get_tender(tender_id)

            # 2. Download documents
            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "📂 Завантаження та читання документів...",
                    parse_mode='Markdown'
                )
            all_docs = await client.get_tender_documents(tender)
            doc_texts = await self._download_and_read_docs(client, all_docs)

            # 3. Run AI analysis
            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "🤖 Аналіз штучним інтелектом (1/3 — замовник)...",
                    parse_mode='Markdown'
                )
            customer_analysis = await self._analyze_customer(tender, doc_texts)

            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "🤖 Аналіз штучним інтелектом (2/3 — закупівля)...",
                    parse_mode='Markdown'
                )
            procurement_analysis = await self._analyze_procurement(tender, doc_texts)

            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "🤖 Аналіз штучним інтелектом (3/3 — учасники)...",
                    parse_mode='Markdown'
                )
            participants_analysis = await self._analyze_participants(tender, doc_texts)

            # 4. Generate DOCX
            if status_msg:
                await status_msg.edit_text(
                    f"🔍 Аналіз тендера `{tender_id}`\n"
                    "📝 Формування Word-документа...",
                    parse_mode='Markdown'
                )

            report_data = {
                "tender_id": tender_id,
                "tender": tender,
                "customer_analysis": customer_analysis,
                "procurement_analysis": procurement_analysis,
                "participants_analysis": participants_analysis,
                "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
            }
            docx_path = generate_docx_report(report_data)

            short_summary = self._build_summary(tender, customer_analysis)
            return docx_path, short_summary

    async def _download_and_read_docs(self, client: ProzorroClient, all_docs: list[dict]) -> dict[str, list[dict]]:
        """Download docs and extract text. Returns dict keyed by source."""
        by_source: dict[str, list] = {}

        # Limit docs per party to avoid huge downloads
        source_counts: dict[str, int] = {}
        tasks = []

        for doc in all_docs:
            src = doc.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
            if source_counts[src] > MAX_DOCS_PER_PARTY:
                continue

            url = doc.get("url", "")
            title = doc.get("title", "document")
            mime = doc.get("format", "")
            tasks.append((src, title, mime, url))

        async def fetch_one(src, title, mime, url):
            content = await client.download_document(url)
            if not content:
                return src, title, "[Не вдалося завантажити документ]"
            text = extract_text_from_bytes(content, title, mime)
            return src, title, text[:MAX_DOC_CHARS]

        results = await asyncio.gather(*[fetch_one(*t) for t in tasks], return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Doc fetch error: {r}")
                continue
            src, title, text = r
            by_source.setdefault(src, []).append({"title": title, "text": text})

        return by_source

    def _build_context(self, tender: dict, doc_texts: dict) -> str:
        """Build text context for Claude from tender JSON + docs."""
        parts = []

        # Core tender info
        t = tender
        parts.append(f"""=== ДАНІ ТЕНДЕРА ===
ID: {t.get('id', '')}
Назва: {t.get('title', '')}
Статус: {t.get('status', '')}
Очікувана вартість: {t.get('value', {}).get('amount', '')} {t.get('value', {}).get('currency', 'UAH')}
Процедура: {t.get('procurementMethodType', '')}
Дата публікації: {t.get('datePublished', '')}
Дата кінця подачі: {t.get('enquiryPeriod', {}).get('endDate', '')}
Кількість лотів: {len(t.get('lots', []))}
Кількість учасників: {len(t.get('bids', []))}
""")

        # Замовник
        buyers = t.get('buyers', t.get('procuringEntity', {}))
        if isinstance(buyers, dict):
            buyers = [buyers]
        for b in (buyers or []):
            parts.append(f"ЗАМОВНИК: {b.get('name', '')} | ЄДРПОУ: {b.get('identifier', {}).get('id', '')}")

        # Предмет закупівлі (items)
        items = t.get('items', [])
        if items:
            parts.append("\n=== ПРЕДМЕТ ЗАКУПІВЛІ ===")
            for item in items[:20]:
                desc = item.get('description', '')
                qty = item.get('quantity', '')
                unit = item.get('unit', {}).get('name', '')
                cpv = item.get('classification', {}).get('id', '')
                parts.append(f"• {desc} | Кількість: {qty} {unit} | CPV: {cpv}")

        # Критерії
        criteria = t.get('criteria', [])
        if criteria:
            parts.append("\n=== КРИТЕРІЇ ===")
            for c in criteria[:10]:
                parts.append(f"• {c.get('title', '')} — {c.get('description', '')}")

        # Учасники
        bids = t.get('bids', [])
        if bids:
            parts.append("\n=== УЧАСНИКИ ===")
            for bid in bids:
                tenderer = bid.get('tenderers', [{}])[0]
                name = tenderer.get('name', 'Невідомо')
                edrpou = tenderer.get('identifier', {}).get('id', '')
                price = bid.get('value', {}).get('amount', 'н/д')
                status = bid.get('status', '')
                parts.append(f"• {name} (ЄДРПОУ: {edrpou}) | Ціна: {price} UAH | Статус: {status}")

        # Documents
        parts.append("\n=== ДОКУМЕНТИ ===")
        total_chars = sum(len(p) for p in parts)
        for source, docs in doc_texts.items():
            parts.append(f"\n--- Документи від: {source} ---")
            for d in docs:
                remaining = MAX_TOTAL_CHARS - total_chars
                if remaining < 500:
                    parts.append("[Ліміт контексту — решта документів не включена]")
                    break
                snippet = d['text'][:min(MAX_DOC_CHARS, remaining)]
                parts.append(f"[{d['title']}]\n{snippet}")
                total_chars += len(snippet)

        return "\n".join(parts)

    async def _analyze_customer(self, tender: dict, doc_texts: dict) -> str:
        context = self._build_context(tender, doc_texts)
        prompt = f"""{context}

---
Ти — досвідчений аналітик публічних закупівель України.

Зроби ДЕТАЛЬНИЙ АНАЛІЗ ЗАМОВНИКА та технічних вимог тендера:

1. **Загальна інформація про замовника**
   - Назва, ЄДРПОУ, тип організації
   - Попередні закупівлі, репутація

2. **Аналіз технічних вимог**
   - Що закуповується, технічні характеристики
   - Терміни поставки та умови
   - Кількість товару/послуг

3. **Індикатори корупційних ризиків**
   - Чи виглядають вимоги як «заточені» під конкретного виробника/постачальника?
   - Нестандартні або надмірно специфічні вимоги
   - Стислі строки, що обмежують конкуренцію

4. **Відповідність законодавству**
   - Наявність обов'язкових документів у тендерній документації
   - Порушення або ризики

5. **Висновок по замовнику**

Відповідай структуровано, на українській мові. Будь конкретним, посилайся на реальні дані з тендера.
"""
        msg = await self.claude.messages.create(
            model="claude-opus-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    async def _analyze_procurement(self, tender: dict, doc_texts: dict) -> str:
        context = self._build_context(tender, doc_texts)
        prompt = f"""{context}

---
Ти — досвідчений аналітик ринку та публічних закупівель.

Зроби ДЕТАЛЬНИЙ АНАЛІЗ ЗАКУПІВЛІ:

1. **Що закуповується**
   - Опис предмету закупівлі простою мовою
   - CPV коди та їх відповідність опису

2. **Аналіз ціни**
   - Очікувана вартість тендера
   - Чи відповідає ринковим цінам? (орієнтовно)
   - Чи є ознаки завищення ціни?
   - Якщо є ставки учасників — порівняй між собою та з очікуваною вартістю

3. **Ринковий аналіз**
   - Чи є дешевші аналоги, що відповідають ТВ?
   - Альтернативні постачальники на ринку України

4. **Ризики закупівлі**
   - Фінансові ризики
   - Ризики якості та постачання
   - Юридичні ризики
   - Ризик зриву торгів

5. **Висновок по закупівлі**
   - Загальна оцінка (прозора / підозріла / потребує перевірки)

Відповідай структуровано, на українській мові. Наводь конкретні цифри та факти.
"""
        msg = await self.claude.messages.create(
            model="claude-opus-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    async def _analyze_participants(self, tender: dict, doc_texts: dict) -> str:
        context = self._build_context(tender, doc_texts)
        prompt = f"""{context}

---
Ти — досвідчений аналітик ділової репутації та публічних закупівель.

Зроби ДЕТАЛЬНИЙ АНАЛІЗ КОЖНОГО УЧАСНИКА тендера:

Для кожного учасника проаналізуй:

1. **Загальна інформація**
   - Назва компанії, ЄДРПОУ
   - Запропонована ціна та її адекватність

2. **Документи учасника**
   - Перелік поданих документів
   - Наявність обов'язкових документів
   - Відповідність документів вимогам тендера

3. **Матеріально-технічна база**
   - Підтвердження наявності обладнання, транспорту, складів
   - Оренда vs власна власність — чи є документи?
   - Зареєстровані потужності (якщо є у документах)

4. **Кваліфікаційні критерії**
   - Досвід виконання аналогічних договорів
   - Фінансова спроможність
   - Персонал та кваліфікація

5. **Ризики учасника**
   - Відсутні або неповні документи
   - Невідповідності між документами
   - Підозрілі ознаки (фіктивна оренда, відсутність реальної діяльності тощо)

6. **Порівняльна таблиця учасників**
   Зроби порівняння всіх учасників за ключовими критеріями.

7. **Рекомендація**
   - Хто виглядає найбільш надійним і чому?

Відповідай структуровано, на українській мові.
"""
        msg = await self.claude.messages.create(
            model="claude-opus-4-5",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    def _build_summary(self, tender: dict, customer_analysis: str) -> str:
        title = tender.get('title', 'Без назви')[:80]
        amount = tender.get('value', {}).get('amount', 'н/д')
        currency = tender.get('value', {}).get('currency', 'UAH')
        bids_count = len(tender.get('bids', []))
        return (
            f"📋 **{title}**\n"
            f"💰 Очікувана вартість: {amount} {currency}\n"
            f"👥 Учасників: {bids_count}\n\n"
            f"✅ Аналіз завершено! Файл Word додається нижче."
        )
