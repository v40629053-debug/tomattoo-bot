#!/usr/bin/env bash
set -e
echo "Установка зависимостей..."
pip install -r requirements.txt
echo "Запуск бота..."
python bot.py
