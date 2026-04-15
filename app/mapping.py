# mapping.py — связки ID сообщений в Redis
# Когда сообщение из TG отправлено в MAX, сохраняем:
#   TG:86 → MAX:mid.123   и   MAX:mid.123 → TG:86
# Через 2 часа записи сами удалятся (TTL)

import redis.asyncio as redis
from config import REDIS_URL, MSG_TTL

# Подключаемся к Redis (Memurai на вашем компьютере)
# decode_responses=True — чтобы Redis отдавал обычные строки, а не байты
pool = redis.from_url(REDIS_URL, decode_responses=True)


def _map_prefix(connector_key: str | None) -> str:
    safe_key = connector_key or "default"
    return f"map:{safe_key}"


async def save_mapping(connector_key: str | None, tg_msg_id: int, max_msg_id: str) -> None:
    """Сохранить связку: TG-сообщение ↔ MAX-сообщение в рамках одного коннектора."""
    prefix = _map_prefix(connector_key)
    tg_key = f"{prefix}:TG:{tg_msg_id}"
    max_key = f"{prefix}:MAX:{max_msg_id}"

    await pool.set(tg_key, max_msg_id, ex=MSG_TTL)
    await pool.set(max_key, str(tg_msg_id), ex=MSG_TTL)


async def get_max_id(connector_key: str | None, tg_msg_id: int) -> str | None:
    """По ID сообщения из TG найти парное ID в MAX в рамках одного коннектора."""
    prefix = _map_prefix(connector_key)
    return await pool.get(f"{prefix}:TG:{tg_msg_id}")


async def get_tg_id(connector_key: str | None, max_msg_id: str) -> int | None:
    """По ID сообщения из MAX найти парное ID в TG в рамках одного коннектора."""
    prefix = _map_prefix(connector_key)
    result = await pool.get(f"{prefix}:MAX:{max_msg_id}")
    return int(result) if result else None


async def is_processed(update_id: int | str, connector_key: str | None = None) -> bool:
    """Проверяем: мы уже обработали это событие? Защита от дублей."""
    key = f"processed:{connector_key}:{update_id}" if connector_key else f"processed:{update_id}"
    result = await pool.set(key, "1", ex=60, nx=True)
    return result is None  # True = уже обработано, False = новое


# --- Кэш названий топиков ---
# Топик создаётся редко, а сообщения идут постоянно.
# Поэтому сохраняем название один раз и используем долго.

async def save_topic_name(chat_id: int, thread_id: int, name: str) -> None:
    """Сохранить название топика в Redis (без TTL — живёт пока Redis работает)."""
    key = f"topic:{chat_id}:{thread_id}"
    await pool.set(key, name)


async def get_topic_name(chat_id: int, thread_id: int) -> str | None:
    """Получить название топика из кэша."""
    key = f"topic:{chat_id}:{thread_id}"
    return await pool.get(key)


# --- Маркер MAX (для восстановления после перезапуска) ---
# MAX отдаёт обновления с позиции marker.
# Если бот упал, при перезапуске нужно знать, где остановились.
# Сохраняем marker в Redis — он переживёт перезапуск.

async def save_max_marker(marker: int) -> None:
    """Сохранить маркер MAX в Redis (без TTL — живёт всегда)."""
    await pool.set("max:marker", str(marker))


async def get_max_marker() -> int | None:
    """Загрузить маркер MAX из Redis.
    Возвращает число или None (если бот запускается впервые).
    """
    result = await pool.get("max:marker")
    return int(result) if result else None
