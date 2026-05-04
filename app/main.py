# main.py — точка входа: запускает мост в обе стороны
#
# Работают параллельно:
#   1. aiogram polling  — слушает Telegram
#   2. MAX (long polling GET /updates или HTTPS webhook)
#   3. TG sender worker — отправляет в TG с rate limit

import asyncio
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from config import (
    TG_BOT_TOKEN,
    MAX_USE_WEBHOOK,
    MAX_WEBHOOK_PUBLIC_URL,
    WEBHOOK_SECRET,
    max_api_webhook_secret_ok,
)
from connectors import CONNECTORS
from tg_handler import router as tg_router
from commands import router as cmd_router
from tg_sender import sender_worker
from max_handler import poll_max, run_max_webhook_server, shutdown_max_subscriptions
from max_sender import close_client


async def main():
    """Запуск бота."""

    if MAX_USE_WEBHOOK:
        if not MAX_WEBHOOK_PUBLIC_URL.startswith("https://"):
            raise SystemExit(
                "MAX_USE_WEBHOOK=1: задайте MAX_WEBHOOK_PUBLIC_URL с префиксом https:// "
                "(требование MAX API)."
            )
        if not urlparse(MAX_WEBHOOK_PUBLIC_URL).netloc:
            raise SystemExit("MAX_USE_WEBHOOK=1: некорректный MAX_WEBHOOK_PUBLIC_URL.")
        if WEBHOOK_SECRET and not max_api_webhook_secret_ok(WEBHOOK_SECRET):
            raise SystemExit(
                "WEBHOOK_SECRET: пусто или 5–256 символов [a-zA-Z0-9_-] (формат MAX API)."
            )

    bot = Bot(token=TG_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(cmd_router)    # команды ПЕРВЫМИ — чтобы /status не ушёл в tg_handler
    dp.include_router(tg_router)

    # Запускаем фоновые задачи
    worker_task = asyncio.create_task(sender_worker(bot))
    if MAX_USE_WEBHOOK:
        max_recv_task = asyncio.create_task(run_max_webhook_server())
    else:
        max_recv_task = asyncio.create_task(poll_max())

    print("=" * 50)
    print("🚀 Мост TG ↔ MAX запущен")
    print("📡 TG polling: слушаю Telegram")
    if MAX_USE_WEBHOOK:
        print(f"📡 MAX webhook: {MAX_WEBHOOK_PUBLIC_URL}")
    else:
        print("📡 MAX long polling: GET /updates")
    print(f"🔌 Коннекторов: {len(CONNECTORS)}")
    print("📤 TG sender: воркер с rate limit (3.5 сек)")
    print("🔄 Режим: восстановление пропущенных сообщений включено")
    print("🛑 Для остановки нажмите Ctrl+C")
    print("=" * 50)

    try:
        await dp.start_polling(bot, skip_updates=False, allowed_updates=["message", "edited_message"])
    finally:
        worker_task.cancel()
        max_recv_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        try:
            await max_recv_task
        except asyncio.CancelledError:
            pass
        if MAX_USE_WEBHOOK:
            try:
                await shutdown_max_subscriptions()
            except Exception as e:
                print(f"Не удалось снять подписку MAX: {e}")
        await close_client()
        await bot.session.close()
        print("\n👋 Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
