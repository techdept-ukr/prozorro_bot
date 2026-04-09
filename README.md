# 🇺🇦 ProZorro Tender Analyzer Bot

Telegram-бот для аналізу тендерних закупівель з [prozorro.gov.ua](https://prozorro.gov.ua).

Надсилаєш посилання → отримуєш повний Word-документ з аналізом.

---

## 📦 Структура файлів

```
prozorro_bot/
├── bot.py                  # Telegram бот (точка входу)
├── analyzer.py             # Оркестратор аналізу
├── prozorro_client.py      # Клієнт Prozorro Public API
├── document_reader.py      # Читання PDF, DOCX, сканів (OCR)
├── report_generator.py     # Генерація Word-документа
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

---

## 🚀 Швидкий старт

### 1. Отримай API ключі

**Telegram Bot Token:**
1. Напиши [@BotFather](https://t.me/BotFather) в Telegram
2. `/newbot` → введи назву та username
3. Скопіюй токен виду `7123456789:AAF...`

**Anthropic API Key:**
1. Зареєструйся на [console.anthropic.com](https://console.anthropic.com)
2. `API Keys` → `Create Key`
3. Скопіюй ключ виду `sk-ant-...`

**ProZorro API:**  
✅ Не потрібен ключ! Використовується публічний API:  
`https://public.api.prozorro.gov.ua/api/2.5/tenders/{tender_id}`

---

### 2. Локальний запуск

```bash
git clone https://github.com/your-username/prozorro-bot.git
cd prozorro-bot

# Встанови залежності
pip install -r requirements.txt

# Встанови Tesseract OCR (для сканів)
# Ubuntu/Debian:
sudo apt-get install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus poppler-utils

# macOS:
brew install tesseract tesseract-lang poppler

# Налаштуй ключі
cp .env.example .env
# Відредагуй .env — встав свої токени

# Завантаж .env та запусти
export $(cat .env | xargs)
python bot.py
```

---

### 3. Запуск через Docker

```bash
docker build -t prozorro-bot .
docker run -d \
  -e TELEGRAM_TOKEN=your_token \
  -e ANTHROPIC_API_KEY=your_key \
  --name prozorro-bot \
  prozorro-bot
```

---

### 4. Деплой на Railway (безкоштовно)

1. Зареєструйся на [railway.app](https://railway.app)
2. `New Project` → `Deploy from GitHub repo`
3. У `Variables` додай:
   - `TELEGRAM_TOKEN` = твій токен
   - `ANTHROPIC_API_KEY` = твій ключ
4. Railway автоматично збере Docker-образ і запустить бота

---

### 5. Деплой на Render

1. [render.com](https://render.com) → `New Web Service`
2. Підключи GitHub репо
3. `Environment` → додай змінні (як у Railway)
4. `Start Command`: `python bot.py`

---

## 🤖 Як користуватись ботом

1. Знайди тендер на [prozorro.gov.ua](https://prozorro.gov.ua)
2. Скопіюй URL: `https://prozorro.gov.ua/tender/UA-2024-...`
3. Надішли боту в Telegram
4. Через 1-3 хвилини отримаєш `.docx` файл

---

## 📊 Що аналізує бот

### Розділ 1: Аналіз замовника
- Інформація про організацію (ЄДРПОУ, тип)
- Технічні вимоги та специфікації
- Індикатори корупційних ризиків
- Чи «заточені» вимоги під конкретного постачальника

### Розділ 2: Аналіз закупівлі
- Що закуповується (простою мовою)
- Відповідність ціни ринковим
- Ринкові альтернативи
- Фінансові та юридичні ризики

### Розділ 3: Аналіз учасників
- Перевірка документів кожного учасника
- МТБ: оренда авто, складів, потужності
- Кваліфікаційні критерії
- Порівняльна таблиця учасників

### Розділ 4: Загальні відомості
- Таблиця предмету закупівлі
- Зведена таблиця учасників та цін

---

## ⚙️ Технічний стек

| Компонент | Технологія |
|-----------|------------|
| Бот | python-telegram-bot 21 |
| AI аналіз | Claude claude-opus-4-5 (Anthropic) |
| Дані | Prozorro Public API (без ключа) |
| PDF | pdfplumber |
| Скани | pytesseract + Tesseract OCR (укр/рус/eng) |
| Word | python-docx |
| Деплой | Docker / Railway / Render |

---

## 🔧 Налаштування OCR

Для розпізнавання сканованих документів потрібен Tesseract:

```bash
# Перевір встановлення:
tesseract --version
tesseract --list-langs  # має бути ukr, rus, eng
```

Якщо `ukr` мови немає:
```bash
# Ubuntu:
sudo apt-get install tesseract-ocr-ukr

# або завантаж вручну:
# https://github.com/tesseract-ocr/tessdata
```

---

## 💡 Поради

- Бот найкраще працює з тендерами, де є завантажені документи
- Аналіз займає 1-3 хв залежно від кількості документів
- Файли PDF зі сканами обробляються через OCR (трохи довше)
- Максимум 5 документів на учасника (щоб не перевантажувати API)

---

## 📝 Ліцензія

MIT — використовуй вільно.
