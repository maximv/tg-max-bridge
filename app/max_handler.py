# max_handler.py — обработка событий из MAX
# Режимы: GET /updates (long polling) или HTTPS webhook (POST /subscriptions) — рекомендуется API.

import asyncio
import httpx
from urllib.parse import urlparse

from aiohttp import web
from config import (
    MAX_BOT_TOKEN,
    MAX_API_URL,
    ADMIN_IDS,
    WEBHOOK_SECRET,
    max_api_webhook_secret_ok,
    MAX_WEBHOOK_PUBLIC_URL,
    MAX_WEBHOOK_LISTEN_HOST,
    MAX_WEBHOOK_LISTEN_PORT,
)
from ca_bundle import get_verify_path
from connectors import get_connector_for_max, pair_from_max, disconnect_from_max
from formatter import format_max_to_tg, format_quote, get_display_name_max
from tg_sender import enqueue_message
from media import get_max_media_info, format_size, MAX_FILE_LIMIT
from max_sender import send_text as max_send_text, get_client as get_max_client
from mapping import get_tg_id, is_processed, save_max_marker, get_max_marker

_marker: int | None = None


def parse_connect_secret(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.lower().startswith("/connect"):
        return None
    parts = stripped.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def parse_disconnect_secret(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.lower().startswith("/disconnect"):
        return None
    parts = stripped.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _sender_user_id(sender: dict) -> int | None:
    for key in ("user_id", "id"):
        value = sender.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _extract_user_id(candidate: object) -> int | None:
    if isinstance(candidate, int):
        return candidate
    if isinstance(candidate, str):
        try:
            return int(candidate)
        except ValueError:
            return None
    if isinstance(candidate, dict):
        for key in ("user_id", "id"):
            value = candidate.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
    return None


async def is_max_group_admin(chat_id: int, sender: dict) -> bool:
    user_id = _sender_user_id(sender)
    if user_id is None:
        return False

    # Быстрые локальные признаки админа/владельца в update payload.
    if sender.get("is_admin") is True or sender.get("is_owner") is True:
        return True
    role = str(sender.get("role", "")).lower()
    if role in {"admin", "administrator", "owner"}:
        return True

    http = await get_max_client()
    try:
        # 1) owner_id в информации о чате
        chat_resp = await http.get(
            f"{MAX_API_URL}/chats/{chat_id}",
            headers={"Authorization": MAX_BOT_TOKEN},
        )
        if chat_resp.status_code == 200:
            chat_data = chat_resp.json()
            owner_id = _extract_user_id(chat_data.get("owner_id"))
            if owner_id == user_id:
                return True

        # 2) список админов (формат может отличаться)
        admins_resp = await http.get(
            f"{MAX_API_URL}/chats/{chat_id}/admins",
            headers={"Authorization": MAX_BOT_TOKEN},
        )
        if admins_resp.status_code == 200:
            data = admins_resp.json()
            pools = []
            for key in ("admins", "participants", "users", "items", "members"):
                value = data.get(key)
                if isinstance(value, list):
                    pools.append(value)
            if not pools and isinstance(data, list):
                pools.append(data)

            for group in pools:
                for admin in group:
                    admin_id = _extract_user_id(admin)
                    if admin_id == user_id:
                        return True
    except Exception:
        return False
    return False


def get_all_images(attachments: list) -> list[dict]:
    """Вернуть список всех изображений из вложений MAX.
    Каждый элемент: {"url": "...", "file_size": 0}
    """
    images = []
    for att in attachments:
        if att.get("type") == "image":
            payload = att.get("payload", {})
            url = payload.get("url", "")
            if url:
                images.append({
                    "url": url,
                    "file_size": payload.get("file_size", 0),
                })
    return images


def _max_webhook_path_from_public_url(public_url: str) -> str:
    """Путь для aiohttp (без хоста)."""
    p = urlparse(public_url).path
    if not p:
        return "/"
    return p.rstrip("/") or "/"


async def delete_all_max_subscriptions(http: httpx.AsyncClient) -> None:
    """Удалить все подписки webhook у бота (для переключения режима или перед регистрацией)."""
    try:
        subs = await http.get(
            f"{MAX_API_URL}/subscriptions",
            headers={"Authorization": MAX_BOT_TOKEN},
        )
        if subs.status_code != 200:
            return
        for sub in subs.json().get("subscriptions", []):
            sub_url = sub.get("url", "")
            if not sub_url:
                continue
            await http.delete(
                f"{MAX_API_URL}/subscriptions",
                params={"url": sub_url},
                headers={"Authorization": MAX_BOT_TOKEN},
            )
            print(f"[MAX] Удалил подписку webhook: {sub_url}")
    except Exception as e:
        print(f"[MAX] Не удалось очистить подписки: {e}")


async def register_max_webhook_subscription() -> None:
    if not max_api_webhook_secret_ok(WEBHOOK_SECRET):
        raise ValueError(
            "WEBHOOK_SECRET должен быть 5–256 символов [a-zA-Z0-9_-] (требование MAX API) "
            "или оставьте пустым."
        )
    path = _max_webhook_path_from_public_url(MAX_WEBHOOK_PUBLIC_URL)
    body: dict = {
        "url": MAX_WEBHOOK_PUBLIC_URL,
        "update_types": ["message_created", "message_edited"],
    }
    if WEBHOOK_SECRET:
        body["secret"] = WEBHOOK_SECRET
    async with httpx.AsyncClient(timeout=30.0, verify=get_verify_path()) as http:
        await delete_all_max_subscriptions(http)
        resp = await http.post(
            f"{MAX_API_URL}/subscriptions",
            headers={
                "Authorization": MAX_BOT_TOKEN,
                "Content-Type": "application/json",
            },
            json=body,
        )
        if not resp.is_success:
            print(f"[MAX WEBHOOK] Ошибка POST /subscriptions: {resp.status_code} {resp.text}")
            resp.raise_for_status()
    print(f"[MAX WEBHOOK] Подписка зарегистрирована: {MAX_WEBHOOK_PUBLIC_URL} (path={path})")


async def shutdown_max_subscriptions() -> None:
    async with httpx.AsyncClient(timeout=30.0, verify=get_verify_path()) as http:
        await delete_all_max_subscriptions(http)


async def max_webhook_http_handler(request: web.Request) -> web.Response:
    if WEBHOOK_SECRET:
        if request.headers.get("X-Max-Bot-Api-Secret") != WEBHOOK_SECRET:
            return web.Response(status=403, text="forbidden")
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")
    if not isinstance(data, dict):
        return web.Response(status=400, text="expected object")

    marker = data.get("marker")
    if marker is not None:
        try:
            await save_max_marker(int(marker))
        except (TypeError, ValueError):
            pass

    try:
        await handle_update(data)
    except Exception as e:
        print(f"[MAX WEBHOOK] Ошибка обработки: {e}")
        return web.Response(status=500, text="handler error")
    return web.Response(status=200)


async def run_max_webhook_server() -> None:
    path = _max_webhook_path_from_public_url(MAX_WEBHOOK_PUBLIC_URL)
    app = web.Application()
    app.router.add_post(path, max_webhook_http_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        MAX_WEBHOOK_LISTEN_HOST,
        MAX_WEBHOOK_LISTEN_PORT,
    )
    await site.start()
    print(
        f"[MAX WEBHOOK] HTTP слушает http://{MAX_WEBHOOK_LISTEN_HOST}:"
        f"{MAX_WEBHOOK_LISTEN_PORT}{path}"
    )
    await register_max_webhook_subscription()
    block = asyncio.Event()
    try:
        await block.wait()
    except asyncio.CancelledError:
        print("[MAX WEBHOOK] Остановка сервера...")
        raise
    finally:
        await runner.cleanup()


async def notify_admin_large_file(sender_name: str, file_name: str,
                                  file_size: int, source: str) -> None:
    """Уведомить админа в личку о большом файле."""
    size_str = format_size(file_size)
    if source == "TG":
        where = "в TG-группе"
        action = "Перекиньте вручную в MAX"
    else:
        where = "в MAX-группе"
        action = "Перекиньте вручную в TG"

    text = (
        f"📦 Большой файл {where}!\n"
        f"От: {sender_name}\n"
        f"Файл: {file_name} ({size_str})\n"
        f"{action}"
    )

    for admin_id in ADMIN_IDS:
        await enqueue_message(
            chat_id=admin_id,
            text=text,
        )


async def poll_max() -> None:
    global _marker

    saved_marker = await get_max_marker()
    if saved_marker is not None:
        _marker = saved_marker
        print(f"[MAX POLL] Восстановил маркер из Redis: {_marker}")
        print(f"[MAX POLL] Сообщения за время простоя будут обработаны")
    else:
        print(f"[MAX POLL] Первый запуск — маркера нет, начинаю с текущего момента")

    print("[MAX POLL] Запущен, слушаю события из MAX...")

    async with httpx.AsyncClient(timeout=60.0, verify=get_verify_path()) as http:

        await delete_all_max_subscriptions(http)

        while True:
            try:
                params = {
                    "timeout": 30,
                    "limit": 100,
                    "types": "message_created,message_edited",
                }
                if _marker is not None:
                    params["marker"] = _marker

                resp = await http.get(
                    f"{MAX_API_URL}/updates",
                    params=params,
                    headers={"Authorization": MAX_BOT_TOKEN},
                )
                resp.raise_for_status()
                data = resp.json()

                new_marker = data.get("marker")
                if new_marker is not None:
                    _marker = new_marker
                    await save_max_marker(_marker)

                for update in data.get("updates", []):
                    await handle_update(update)

            except httpx.ReadTimeout:
                continue

            except asyncio.CancelledError:
                print("[MAX POLL] Остановлен")
                break

            except Exception as e:
                print(f"[MAX POLL] Ошибка: {e}")
                await asyncio.sleep(3)


async def handle_update(update: dict) -> None:
    update_type = update.get("update_type")

    if update_type == "message_created":
        await handle_message_created(update)
    elif update_type == "message_edited":
        await handle_message_edited(update)


async def handle_message_created(update: dict) -> None:
    """Новое сообщение в MAX → переслать в TG."""

    message = update.get("message", {})
    body = message.get("body", {})
    sender = message.get("sender", {})
    recipient = message.get("recipient", {})
    text = body.get("text") or ""

    chat_id = recipient.get("chat_id")
    if sender.get("is_bot"):
        return

    mid = body.get("mid", "")
    connector = get_connector_for_max(chat_id)
    connect_secret = parse_connect_secret(text)
    if connect_secret is not None:
        if not await is_max_group_admin(chat_id, sender):
            await max_send_text(chat_id=chat_id, text="Только администратор группы может выполнять /connect.")
            return
        secret = connect_secret
        if not secret:
            await max_send_text(chat_id=chat_id, text="Использование: /connect <секрет>")
            return
        try:
            result = pair_from_max(secret, chat_id)
            await max_send_text(chat_id=chat_id, text=result.message)
            if result.completed and result.connector.tg_group_id is not None:
                await enqueue_message(
                    chat_id=result.connector.tg_group_id,
                    text="Связь установлена.",
                    message_thread_id=result.connector.tg_topic_id,
                )
        except Exception as e:
            await max_send_text(chat_id=chat_id, text=f"Ошибка привязки: {e}")
        return

    disconnect_secret = parse_disconnect_secret(text)
    if disconnect_secret is not None:
        if not await is_max_group_admin(chat_id, sender):
            await max_send_text(chat_id=chat_id, text="Только администратор группы может выполнять /disconnect.")
            return
        try:
            secret = disconnect_secret
            if not secret:
                if not connector:
                    await max_send_text(chat_id=chat_id, text="Для этой MAX-группы нет активной связи.")
                    return
                secret = connector.name
            result = disconnect_from_max(secret, chat_id)
            await max_send_text(chat_id=chat_id, text=result.message)
            if result.connector.tg_group_id is not None:
                await enqueue_message(
                    chat_id=result.connector.tg_group_id,
                    text="Связь отключена.",
                    message_thread_id=result.connector.tg_topic_id,
                )
        except Exception as e:
            await max_send_text(chat_id=chat_id, text=f"Ошибка отключения: {e}")
        return

    if not connector:
        return

    if await is_processed(f"max:{mid}", connector.key):
        return

    attachments = body.get("attachments", [])
    media_info = get_max_media_info(attachments)

    if not text and not media_info:
        return

    # Игнорируемые типы: аудио
    if media_info and media_info["type"] in ("audio",):
        return

    formatted = format_max_to_tg(sender, text)

    # Reply
    reply_to_tg_id = None
    link = message.get("link")
    if link and link.get("type") == "reply":
        original_mid = link.get("message", {}).get("mid")
        if original_mid:
            reply_to_tg_id = await get_tg_id(connector.key, original_mid)

            if not reply_to_tg_id:
                original_text = link.get("message", {}).get("body", {}).get("text", "")
                quote = format_quote(original_text)
                if quote:
                    formatted = quote + formatted

    # Альбом: несколько фото в одном сообщении MAX
    all_images = get_all_images(attachments)
    if len(all_images) > 1:
        # Собираем все URL через запятую — передаём в очередь
        urls = ",".join(img["url"] for img in all_images)
        await enqueue_message(
            chat_id=connector.tg_group_id,
            text=formatted,
            reply_to=reply_to_tg_id,
            message_thread_id=connector.tg_topic_id,
            max_msg_id=mid,
            action="media_group",
            media_url=urls,
            connector_key=connector.key,
        )
        name = sender.get("name", "?")
        print(f"[MAX→TG] Альбом ({len(all_images)} фото) {name}: {text[:50]}")
        return

    # Одиночное медиа: фото, файл или видео
    if media_info and media_info["type"] in ("image", "file", "video"):
        file_size = media_info.get("file_size", 0)
        file_url = media_info.get("url", "")

        if file_size > MAX_FILE_LIMIT:
            # Заглушка + уведомление админу
            size_str = format_size(file_size)
            file_name = media_info.get("file_name", "файл")
            formatted += f"\n📎 {file_name} ({size_str})"
            await enqueue_message(
                chat_id=connector.tg_group_id, text=formatted,
                reply_to=reply_to_tg_id, message_thread_id=connector.tg_topic_id,
                max_msg_id=mid,
                connector_key=connector.key,
            )
            sender_name = get_display_name_max(sender)
            await notify_admin_large_file(sender_name, file_name, file_size, "MAX")
        elif file_url:
            media_type = "photo" if media_info["type"] == "image" else "document"
            await enqueue_message(
                chat_id=connector.tg_group_id, text=formatted,
                reply_to=reply_to_tg_id, message_thread_id=connector.tg_topic_id,
                max_msg_id=mid, action="media",
                media_url=file_url, media_type=media_type,
                media_name=media_info.get("file_name"),
                connector_key=connector.key,
            )
        else:
            await enqueue_message(
                chat_id=connector.tg_group_id, text=formatted,
                reply_to=reply_to_tg_id, message_thread_id=connector.tg_topic_id,
                max_msg_id=mid,
                connector_key=connector.key,
            )
    else:
        await enqueue_message(
            chat_id=connector.tg_group_id, text=formatted,
            reply_to=reply_to_tg_id, message_thread_id=connector.tg_topic_id,
            max_msg_id=mid,
            connector_key=connector.key,
        )

    name = sender.get("name", "?")
    print(f"[MAX→TG] {name}: {text[:50]}")


async def handle_message_edited(update: dict) -> None:
    """Сообщение отредактировали в MAX → редактировать зеркало в TG."""

    message = update.get("message", {})
    body = message.get("body", {})
    sender = message.get("sender", {})
    recipient = message.get("recipient", {})

    chat_id = recipient.get("chat_id")
    connector = get_connector_for_max(chat_id)
    if not connector:
        return

    if sender.get("is_bot"):
        return

    mid = body.get("mid", "")
    text = body.get("text")
    if not text:
        return

    tg_msg_id = await get_tg_id(connector.key, mid)
    if not tg_msg_id:
        print(f"[MAX→TG] Edit: пара не найдена для mid={mid}, игнор")
        return

    formatted = format_max_to_tg(sender, text)

    await enqueue_message(
        chat_id=connector.tg_group_id,
        text=formatted,
        action="edit",
        tg_msg_id=tg_msg_id,
        connector_key=connector.key,
    )

    name = sender.get("name", "?")
    print(f"[MAX→TG] Edit: {name}: {text[:50]}")
