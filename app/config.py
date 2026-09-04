# config.py — читаем настройки из файла .env
# Все остальные файлы будут импортировать переменные отсюда

import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Ищем .env в папке bridge/ (на уровень выше от app/)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Telegram ---
TG_BOT_TOKEN = os.environ["TG_BOT_TOKEN"]

# --- MAX ---
MAX_BOT_TOKEN = os.environ["MAX_BOT_TOKEN"]         # токен бота MAX
# С осени 2026 MAX просит platform-api2.max.ru вместо platform-api.max.ru
MAX_API_URL = os.environ.get(
    "MAX_API_URL",
    "https://platform-api2.max.ru",
).rstrip("/")

# --- Redis ---
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")  # адрес Redis
MSG_TTL = 7200                                       # 2 часа в секундах — время жизни связки сообщений

# --- Безопасность ---
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # заголовок X-Max-Bot-Api-Secret (рекомендуется API MAX)

# --- MAX: long polling vs webhook (с 11.05.2026 long polling жёстко лимитирован; для production — webhook) ---


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off", ""):
        return default
    return default


MAX_USE_WEBHOOK = _env_bool("MAX_USE_WEBHOOK", False)
# Полный публичный URL для POST /subscriptions (должен совпадать с маршрутом HTTP-сервера бота)
MAX_WEBHOOK_PUBLIC_URL = os.environ.get("MAX_WEBHOOK_PUBLIC_URL", "").strip()
MAX_WEBHOOK_LISTEN_HOST = os.environ.get("MAX_WEBHOOK_LISTEN_HOST", "0.0.0.0")
MAX_WEBHOOK_LISTEN_PORT = int(os.environ.get("MAX_WEBHOOK_LISTEN_PORT", "8080"))


def max_api_webhook_secret_ok(secret: str) -> bool:
    """Правила MAX API для поля secret в POST /subscriptions."""
    if not secret:
        return True
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]{5,256}", secret))
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
