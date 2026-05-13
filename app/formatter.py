# formatter.py — оформление сообщений
# Добавляет имя автора, убирает Markdown/HTML разметку, делает цитаты

import re


def get_display_name_tg(user) -> str:
    """Получить читаемое имя пользователя Telegram.
    Порядок: Имя Фамилия → Имя → @username → user_id
    """
    parts = []
    if user.first_name:
        parts.append(user.first_name)
    if user.last_name:
        parts.append(user.last_name)
    if parts:
        return " ".join(parts)          # "Иван Иванов" или просто "Иван"
    if user.username:
        return f"@{user.username}"      # "@ivan123"
    return str(user.id)                 # "882646417" — крайний случай


def get_display_name_max(sender: dict) -> str:
    """Получить читаемое имя пользователя MAX.
    Порядок: name → username → user_id
    """
    if sender.get("name"):
        return sender["name"]
    if sender.get("username"):
        return f"@{sender['username']}"
    return str(sender.get("user_id", "Unknown"))


def strip_markup(text: str) -> str:
    """Снять только HTML-теги, оставив остальной текст как есть.

    Markdown-символы (`*`, `_`, `` ` ``, `~`) НЕ удаляем: бот отправляет
    сообщения без parse_mode (plain text), а MAX API без поля `format`
    тоже трактует тело как обычный текст. Поэтому такие символы — это
    часть исходного текста (snake_case, user_id, __init__ и т.п.),
    а не разметка, и их вырезание ломало смысл сообщений.

    Пример: <b>жирный</b> → жирный, snake_case → snake_case.
    """
    return re.sub(r"<[^>]+>", "", text).strip()


def format_tg_to_max(user, text: str, topic_name: str = None) -> str:
    """Оформить сообщение из TG для отправки в MAX.
    Результат: '👤 Иван Иванов (TG): текст сообщения'
    """
    name = get_display_name_tg(user)
    clean = strip_markup(text) if text else ""

    prefix = f"👤 {name} (TG)"

    # Если сообщение из топика — добавляем метку
    if topic_name:
        prefix = f"[📌 {topic_name}] {prefix}"

    if clean:
        return f"{prefix}: {clean}"
    return prefix  # если текст пустой (например, только файл)


def format_max_to_tg(sender: dict, text: str) -> str:
    """Оформить сообщение из MAX для отправки в TG.
    Результат: '👤 Иван Иванов (MAX): текст сообщения'
    """
    name = get_display_name_max(sender)
    clean = strip_markup(text) if text else ""

    prefix = f"👤 {name} (MAX)"

    if clean:
        return f"{prefix}: {clean}"
    return prefix


def format_quote(original_text: str, max_length: int = 100) -> str:
    """Сделать цитату из оригинального сообщения.
    Используется когда reply-оригинал старше 2 часов и нет в Redis.
    Результат: '> Иван: текст оригинала...\n'
    """
    if not original_text:
        return ""
    # Обрезаем если слишком длинный
    if len(original_text) > max_length:
        original_text = original_text[:max_length] + "…"
    return f"┃ {original_text}\n"
