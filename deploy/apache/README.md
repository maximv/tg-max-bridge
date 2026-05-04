# Apache + SSL для MAX webhook

С 11.05.2026 для MAX API нужен webhook на HTTPS. Здесь — конфигурация Apache,
проксирующая `https://connector.into.spb.ru/max/webhook` на контейнер бота
(`127.0.0.1:8080`), без вмешательства в существующий Nextcloud на 80 порту.

## TL;DR

```bash
# 0. Проверьте что DNS уже указывает на сервер
dig +short connector.into.spb.ru

# 1. Скопируйте vhost (CentOS 7 / Apache 2.4)
sudo cp deploy/apache/connector.into.spb.ru.conf /etc/httpd/conf.d/
sudo httpd -t                  # проверка синтаксиса
sudo systemctl reload httpd

# 2. Включите модули (если ещё не включены)
sudo yum install -y mod_ssl
# модули proxy/proxy_http/rewrite в CentOS 7 включены штатно через
# /etc/httpd/conf.modules.d/00-proxy.conf и 00-base.conf — проверьте:
httpd -M 2>&1 | grep -E 'proxy_module|proxy_http_module|rewrite_module|ssl_module'

# 3. Установите certbot и выпустите сертификат
sudo yum install -y epel-release
sudo yum install -y certbot python2-certbot-apache
sudo certbot --apache -d connector.into.spb.ru \
     --agree-tos -m you@example.com --redirect --non-interactive

# 4. Раскомментируйте :443 блок в vhost
#    (или оставьте конфиг от certbot — см. ниже)
sudo httpd -t && sudo systemctl reload httpd

# 5. Откройте 443 порт в firewall, если он закрыт
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# 6. Проверьте что webhook доступен снаружи
curl -i https://connector.into.spb.ru/max/webhook -X POST \
     -H 'Content-Type: application/json' -d '{}'
# Ожидаем: 200 OK или 400 bad json — главное что не 502/SSL ошибка.
```

## Что не сломает Nextcloud

В каждом `<VirtualHost>` блоке **жёстко прописан `ServerName`**:

```
ServerName connector.into.spb.ru
```

Apache 2.4 направляет запрос в vhost по `Host`-заголовку. Если у Nextcloud
свой `ServerName` (например `cloud.into.spb.ru`) — он продолжит работать как
работал. Новый vhost забирает только запросы для нового домена.

Если Nextcloud сейчас обрабатывает **дефолтный** vhost (без `ServerName`),
тогда всё запросы без явной привязки уйдут к нему, а наш блок — только при
явном Host: connector.into.spb.ru. Это безопасный сценарий.

## Про два варианта SSL-конфигурации

certbot с флагом `--apache` делает один из двух вариантов:

1. **Дописывает SSL-директивы прямо в `connector.into.spb.ru.conf`** — тогда
   раскомментируйте :443 блок вручную не нужно, certbot сам всё сделает.
2. **Создаёт `connector.into.spb.ru-le-ssl.conf`** — отдельный файл со своей
   копией :443 блока.

Оба варианта рабочие. После certbot достаточно `httpd -t && systemctl reload httpd`.

## Если certbot не справился

Можно получить сертификат вручную через webroot и подключить файлами:

```bash
sudo certbot certonly --webroot \
     -w /var/www/html \
     -d connector.into.spb.ru \
     --agree-tos -m you@example.com --non-interactive

# Затем раскомментируйте :443 блок в connector.into.spb.ru.conf и:
sudo httpd -t && sudo systemctl reload httpd
```

## Автообновление сертификата

certbot ставит cron / systemd-timer для `certbot renew` автоматически.
Проверка:

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

После обновления Apache сам перечитает сертификат на `systemctl reload httpd`
(certbot прописывает renew_hook).

## Включение webhook в боте

После того как `https://connector.into.spb.ru/max/webhook` отвечает 2xx/4xx
(а не SSL-ошибкой) — переводите бота на webhook:

```env
# .env
MAX_USE_WEBHOOK=1
MAX_WEBHOOK_PUBLIC_URL=https://connector.into.spb.ru/max/webhook
MAX_WEBHOOK_LISTEN_HOST=0.0.0.0
MAX_WEBHOOK_LISTEN_PORT=8080
# Секрет 5–256 символов [a-zA-Z0-9_-]; рекомендуется задать.
WEBHOOK_SECRET=сгенерируйте_длинную_случайную_строку
```

```bash
docker compose down
docker compose up -d --build
docker compose logs -f bot
# Ожидаем: [MAX WEBHOOK] HTTP слушает http://0.0.0.0:8080/max/webhook
#          [MAX WEBHOOK] Подписка зарегистрирована: https://connector.into.spb.ru/max/webhook
```

При запуске бот сам:
- удалит все старые подписки (`DELETE /subscriptions`),
- зарегистрирует новую (`POST /subscriptions`),
- начнёт принимать события на `/max/webhook`.

При штатной остановке (`docker compose down`) бот снимает свою подписку,
чтобы MAX не слал события в простаивающий сервер.

## Откат на long polling

Если что-то пошло не так — поставьте в `.env`:

```env
MAX_USE_WEBHOOK=0
```

И перезапустите бота. До 11.05.2026 long polling работает как раньше,
после — с лимитами 2 RPS / 30 c / 100 событий / TTL 24 ч.
