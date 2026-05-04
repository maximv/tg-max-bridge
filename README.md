# 🌉 Мост Telegram ↔ MAX

Двусторонний бот-мост для синхронизации сообщений между супергруппой **Telegram** и группой **MAX** (VK Teams / Мессенджер MAX).

Сообщения из одного мессенджера автоматически появляются в другом — с указанием имени автора.

## Чем форк отличается от оригинала

- Поддержка нескольких связок TG↔MAX через `state/connectors.json` (а не одна пара ID в `.env`).
- Автопривязка групп командами `/connect <секрет>` и `/disconnect [секрет]`.
- Команды привязки/отвязки доступны только администраторам групп.
- Бот стартует даже без заранее созданного `connectors.json` — файл создаётся автоматически при первом `/connect`.
- Защита от дублей и незавершённых повторных связок для одной и той же TG/MAX группы.

## Что умеет

- **Текст** — пересылка в обе стороны с атрибуцией (`👤 Иван Иванов (TG): текст`)
- **Reply** — если оригинал свежий (< 2ч), нативный ответ; иначе цитата в тексте
- **Edit** — редактирование зеркалируется (пока связка жива в Redis, 2ч)
- **Фото и документы** — до 20 МБ пересылаются, больше — текстовая заглушка + уведомление админу
- **Топики TG** — метка `[📌 тема]` перед текстом
- **Rate limiting** — очередь в Redis, 1 сообщение в 3.5 сек в сторону TG (защита от бана)
- **Восстановление после перезапуска** — маркер MAX и пропущенные сообщения TG подхватываются

## Что не поддерживается (осознанные компромиссы)

- Форматирование (Markdown/HTML) — всё идёт plain text
- Голосовые сообщения и видео-кружки — игнорируются
- Видео — пересылается как файл (без плеера)
- Edit/delete старше 2 часов — игнор (связка протухла в Redis)

## Стек

- Python 3.11+, [aiogram 3.x](https://docs.aiogram.dev/) (Telegram)
- [httpx](https://www.python-httpx.org/) (MAX API)
- Redis — маппинг ID сообщений + очередь rate limit
- Docker Compose (бот + Redis)

## Структура проекта

```
bridge/
├── .env.example          ← шаблон настроек (заполните свой .env)
├── state/connectors.json ← связи TG group+topic ↔ MAX group (создаётся автоматически)
├── docker-compose.yml    ← запуск бота + Redis
├── Dockerfile            ← сборка контейнера
├── requirements.txt      ← Python-зависимости
└── app/
    ├── main.py           ← точка входа, запуск polling
    ├── config.py         ← чтение .env
    ├── tg_handler.py     ← обработка событий из Telegram
    ├── max_handler.py    ← обработка событий из MAX
    ├── tg_sender.py      ← отправка в TG (воркер + очередь)
    ├── max_sender.py     ← отправка в MAX
    ├── formatter.py      ← атрибуция, очистка разметки, цитаты
    ├── media.py          ← работа с файлами (скачивание, загрузка)
    ├── mapping.py        ← Redis: связки ID, кэш топиков, маркер
    ├── commands.py       ← команды бота (/status)
    └── reset.py          ← сброс очередей перед первым запуском
```

## Быстрый старт

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/ВАШ_ЮЗЕРНЕЙМ/tg-max-bridge.git
cd tg-max-bridge
```

### 2. Создайте файл .env

```bash
cp .env.example .env
nano .env   # заполните токены ботов
```

Заполните токены ботов. Маршрутизация чатов хранится в `state/connectors.json`.
Файл создаётся автоматически при первом `/connect`, но можно подготовить заранее.

### 3. (Опционально) Создайте стартовый файл connectors.json

```bash
mkdir -p state
cp connectors.json.example state/connectors.json
nano state/connectors.json
```

Пример одного коннектора:

```json
{
  "connectors": [
    {
      "name": "support-main",
      "enabled": true,
      "tg_group_id": -1001111111111,
      "tg_topic_id": 0,
      "max_group_id": -73533154791452,
      "comment": "Основной поток"
    }
  ]
}
```

Правила:
- `tg_topic_id = 0` означает сообщения из всей TG-группы (без фильтра по топику).
- Один `max_group_id` может принадлежать только одному коннектору.
- Пара `tg_group_id + tg_topic_id` должна быть уникальной.

### 4. Запустите через Docker Compose

```bash
docker compose up -d --build
```

Проверьте что всё работает:

```bash
docker compose ps          # статус контейнеров
docker compose logs bot    # логи бота
```

### 5. Тест

Напишите сообщение в TG-группу → оно должно появиться в MAX, и наоборот.

## Деплой на VPS

Подробная инструкция для новичков — в файле [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md).

### События MAX: webhook вместо long polling

С **11.05.2026** у [GET /updates (long polling)](https://dev.max.ru/docs-api/methods/GET/updates) появляются жёсткие лимиты (в т.ч. **2 RPS**, таймаут **30 с**, до **100** событий в ответе, **TTL** событий **24 ч**). Для продакшена MAX рекомендует [POST /subscriptions (webhook)](https://dev.max.ru/docs-api/methods/POST/subscriptions).

В боте включите в `.env`: `MAX_USE_WEBHOOK=1`, полный HTTPS URL `MAX_WEBHOOK_PUBLIC_URL` (как в подписке; снаружи обычно порт **443**, до контейнера — прокси на `MAX_WEBHOOK_LISTEN_PORT`), по желанию `WEBHOOK_SECRET` (формат в `.env.example`). До включения webhook у вас по умолчанию используется long polling, как раньше.

Готовый Apache vhost + пошаговая инструкция по SSL (Let's Encrypt) лежат в [`deploy/apache/`](deploy/apache/README.md) — конфиг написан так, чтобы не мешать другим сайтам на 80 порту (например, Nextcloud).

### Важно: выбор сервера

- **Telegram API** заблокирован в России — сервер с российским IP не подойдёт
- **MAX API** работает с любого зарубежного сервера без ограничений

**Для россиян**: Hetzner, DigitalOcean и другие зарубежные хостинги с 2022–2024 закрыли регистрацию для клиентов из РФ. Рабочий вариант — **Timeweb Cloud** (timeweb.cloud): российский хостинг, оплата рублями, но есть серверы в **Казахстане** и **США** — оттуда Telegram работает.

> ⚠️ Если вы купили VPS в России и Telegram API не отвечает — это блокировка. Нужен сервер за рубежом. Подробнее — в [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md).

## Полезные команды

```bash
# Статус
docker compose ps

# Логи в реальном времени
docker compose logs -f bot

# Перезапуск
docker compose restart bot

# Полная остановка
docker compose down

# Обновление кода
docker compose up -d --build

# Проверка Redis
docker exec -it tg-max-redis redis-cli ping
```

## Команды бота

| Команда | Описание | Где работает |
|---------|----------|-------------|
| `/status` | Uptime и размер очереди | Личка с ботом |
| `/connect <секрет>` | Автопривязка TG↔MAX по секрету (только админы) | Группы TG и MAX |
| `/disconnect [секрет]` | Разрыв связи текущей группы (секрет опционален, только админы) | Группы TG и MAX |

## Лицензия

MIT — используйте как хотите.

## Полезно

- Инструкция по получению ID и автопривязке: [docs/ids-and-pairing.md](docs/ids-and-pairing.md)
