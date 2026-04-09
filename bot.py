import asyncio
import logging
import os
import re
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from analyzer import TenderAnalyzer

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

analyzer = TenderAnalyzer(anthropic_api_key=ANTHROPIC_API_KEY)

PROZORRO_URL_PATTERN = re.compile(
    r'prozorro\.gov\.ua/(?:uk/|en/)?tender/([A-Za-z0-9\-]+)'
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привіт! Я бот для аналізу тендерів ProZorro.\n\n"
        "Надішли мені посилання на тендер з prozorro.gov.ua, і я зроблю повний аналіз:\n"
        "• 📋 Аналіз замовника та технічних вимог\n"
        "• 💰 Аналіз закупівлі та ринкових цін\n"
        "• 👥 Аналіз учасників та їх документів\n\n"
        "Приклад: https://prozorro.gov.ua/tender/UA-2024-01-01-000001-a"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Як використовувати бота:\n\n"
        "1. Скопіюй посилання на тендер з prozorro.gov.ua\n"
        "2. Надішли його в цей чат\n"
        "3. Очікуй — аналіз займає 1-3 хвилини\n"
        "4. Отримай .docx файл з повним аналізом\n\n"
        "⚠️ Підтримуються тендери у відкритому доступі"
    )

async def analyze_tender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    match = PROZORRO_URL_PATTERN.search(text)
    
    if not match:
        await update.message.reply_text(
            "❌ Не знайдено посилання на тендер ProZorro.\n"
            "Приклад правильного посилання:\n"
            "https://prozorro.gov.ua/tender/UA-2024-01-01-000001-a"
        )
        return

    tender_id = match.group(1)
    status_msg = await update.message.reply_text(
        f"🔍 Починаю аналіз тендера `{tender_id}`...\n"
        "⏳ Це займе 1-3 хвилини. Будь ласка, зачекай.",
        parse_mode='Markdown'
    )

    try:
        await status_msg.edit_text(
            f"🔍 Аналіз тендера `{tender_id}`\n"
            "📡 Завантаження даних з ProZorro API...",
            parse_mode='Markdown'
        )
        
        docx_path, summary = await analyzer.analyze(tender_id, status_msg)

        await status_msg.edit_text(
            f"✅ Аналіз завершено!\n\n{summary}"
        )

        with open(docx_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"Аналіз_тендера_{tender_id}.docx",
                caption="📄 Повний аналіз тендера у форматі Word"
            )

        os.remove(docx_path)

    except Exception as e:
        logger.error(f"Error analyzing tender {tender_id}: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ Помилка при аналізі тендера:\n{str(e)}\n\n"
            "Перевір правильність посилання або спробуй пізніше."
        )

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN не встановлено!")
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY не встановлено!")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze_tender))

    logger.info("Бот запущено...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
