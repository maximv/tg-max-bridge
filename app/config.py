# config.py — читаем настройки из файла .env
# Все остальные файлы будут импортировать переменные отсюда

import os
from pathlib import Path
from dotenv import load_dotenv

# Ищем .env в папке bridge/ (на уровень выше от app/)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Telegram ---
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]

# --- MAX ---
MAX_BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]         # токен бота MAX
MAX_API_URL = "https://platform-api.max.ru"          # базовый адрес API MAX

# --- Redis ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")  # адрес Redis
MSG_TTL = 7200                                       # 2 часа в секундах — время жизни связки сообщений

# --- Безопасность ---
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # секрет для webhook (пригодится позже)
ADMIN_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip()
]
# ↑ Берём строку из .env, разрезаем по запятой (на случай
#   если админов несколько), убираем пробелы, превращаем в числа.
#   Получается список ID администраторов

# --- Коннекторы ---
# Путь к JSON с массивом соответствий TG <-> MAX.
CONNECTORS_FILE = os.environ.get("CONNECTORS_FILE", str(BASE_DIR / "connectors.json"))

# --- Rate Limiting ---
TG_SEND_INTERVAL = 3.5  # секунды между сообщениями в TG (защита от бана)
