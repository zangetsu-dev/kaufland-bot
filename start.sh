#!/bin/bash

# Обновление и установка зависимостей системы
apt-get update && apt-get install -y poppler-utils tesseract-ocr

# Запуск бота
python3 kaufland_bot_dialog.py

