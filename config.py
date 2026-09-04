# -*- coding: utf-8 -*-
"""
Конфигурация Telegram-бота кулинарной школы ToMattoo.

Секреты (токен Telegram, вебхук Битрикс24) читаются из переменных окружения
(Environment Variables). В коде их НЕТ — так безопасно деплоить на Render.

Локальный запуск: создайте файл `.env` рядом с этим файлом (шаблон — `.env.example`)
содержимое вида:
    TELEGRAM_BOT_TOKEN=...
    BITRIX24_WEBHOOK_BASE=...
    BITRIX24_USER_ID=1
    BITRIX24_SOURCE_ID=TG
"""

import os


def _load_dotenv():
    """Подгружает переменные из файла .env (для локального запуска бота)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip().lstrip("\ufeff")
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)


_load_dotenv()


def _get(name, default=None):
    return os.environ.get(name, default)


# ---------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN", "")

# ---------------------------------------------------------------
# Битрикс24
# ---------------------------------------------------------------
# База вебхука (без метода)
BITRIX24_WEBHOOK_BASE = _get("BITRIX24_WEBHOOK_BASE", "")
# Метод создания лида — ВАЖНО с расширением .json
BITRIX24_METHOD = "crm.lead.add.json"
# Полный URL метода
BITRIX24_LEAD_ADD_URL = BITRIX24_WEBHOOK_BASE + BITRIX24_METHOD
# ID ответственного в Битрикс24
BITRIX24_USER_ID = _get("BITRIX24_USER_ID", "1")
# Источник заявки в CRM
BITRIX24_SOURCE_ID = _get("BITRIX24_SOURCE_ID", "TG")


# ---------------------------------------------------------------
# Пути к ресурсам
# ---------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG_PATH = os.path.join(BASE_DIR, "resources", "catalog.pdf")
FOUNDER_PHOTO_PATH = os.path.join(BASE_DIR, "resources", "founder.jpg")

# Путь к лендингу (короткая ссылка через spoo.me)
SITE_URL = "https://spoo.me/E8k7Vnd"
