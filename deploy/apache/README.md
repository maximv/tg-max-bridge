# Apache + SSL для MAX webhook

С 11.05.2026 у MAX API на long polling жёсткие лимиты, поэтому нужен webhook
по HTTPS. Здесь — конфигурация Apache на CentOS 7, проксирующая
`https://connector.into.spb.ru/max/webhook` на контейнер бота
(`127.0.0.1:8080`), без вмешательства в существующий Nextcloud на 80 порту.

Конфиг разнесён на два файла:

- `connector.into.spb.ru.conf` — `VirtualHost *:80`. Принимает ACME-челлендж
  и редиректит остальное на HTTPS. Подключается **до** получения сертификата.
- `connector.into.spb.ru-ssl.conf` — `VirtualHost *:443`. Терминирует TLS и
  проксирует `/max/webhook` на бота. Подключается **после** того, как
  certbot выпустил сертификат.

Такое разделение нужно потому, что Apache не запустится с включённым :443
блоком, если файлов сертификата ещё нет.

## Шаги

```bash
# 0. Проверьте, что DNS уже указывает на сервер
dig +short connector.into.spb.ru

# 1. HTTP-vhost (для ACME-челленджа и редиректа)
sudo cp deploy/apache/connector.into.spb.ru.conf /etc/httpd/conf.d/
sudo httpd -t && sudo systemctl reload httpd

# 2. Установите mod_ssl и certbot, если ещё нет
sudo yum install -y mod_ssl
sudo yum install -y epel-release
sudo yum install -y certbot

# Проверьте, что нужные модули включены
httpd -M 2>&1 | grep -E 'proxy_module|proxy_http_module|rewrite_module|ssl_module|headers_module'

# 3. Откройте 443 порт в firewall, если он закрыт
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# 4. Выпустите сертификат через webroot (без --apache, чтобы certbot
#    не лез в наши конфиги)
sudo certbot certonly --webroot -w /var/www/html \
     -d connector.into.spb.ru \
     --agree-tos -m you@example.com --non-interactive

# 5. HTTPS-vhost с reverse proxy
sudo cp deploy/apache/connector.into.spb.ru-ssl.conf /etc/httpd/conf.d/
sudo httpd -t && sudo systemctl reload httpd

# 6. Запустите бота с пробросом 127.0.0.1:8080 (см. docker-compose.yml)
#    и включите webhook в .env (см. ниже).

# 7. Проверьте, что webhook доступен снаружи
curl -i https://connector.into.spb.ru/max/webhook -X POST \
     -H 'Content-Type: application/json' -d '{}'
# Ожидаем: 200, 400 ("bad json") или 403 (если задан WEBHOOK_SECRET).
# 404 = vhost не подключён или ServerName/путь не совпадают.
# 502/503 = бот не слушает 8080 или порт не проброшен.
```

## Что не сломает Nextcloud

В каждом `<VirtualHost>` явно указан `ServerName connector.into.spb.ru`.
Apache 2.4 направляет запрос в vhost по `Host`-заголовку. Если у Nextcloud
свой `ServerName` (например `cloud.into.spb.ru`) — он продолжит работать
как раньше. Новый vhost забирает только запросы для нового домена.

Если Nextcloud сейчас обрабатывает дефолтный vhost (без `ServerName`),
тоже всё ок: запросы без явной привязки уходят туда, наш блок —
только при `Host: connector.into.spb.ru`.

## Включение webhook в боте

После того как `https://connector.into.spb.ru/max/webhook` отвечает 2xx/4xx
(но не SSL-ошибкой и не 502) — переводите бота на webhook.

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
# Ожидаем:
#   [MAX WEBHOOK] HTTP слушает http://0.0.0.0:8080/max/webhook
#   [MAX WEBHOOK] Подписка зарегистрирована: https://connector.into.spb.ru/max/webhook
```

При запуске бот сам:
- удалит все старые подписки (`DELETE /subscriptions`),
- зарегистрирует новую (`POST /subscriptions`),
- начнёт принимать события на `/max/webhook`.

При штатной остановке (`docker compose down`) бот снимает свою подписку,
чтобы MAX не слал события в простаивающий сервер.

## Автообновление сертификата

certbot ставит systemd-timer для `certbot renew` автоматически. Проверка:

```bash
sudo systemctl list-timers | grep certbot
sudo certbot renew --dry-run
```

После обновления сертификата нужно перечитать Apache. Самый надёжный способ
— добавить deploy-hook:

```bash
sudo tee /etc/letsencrypt/renewal-hooks/deploy/reload-httpd.sh <<'EOF'
#!/bin/bash
systemctl reload httpd
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-httpd.sh
```

## Откат на long polling

В `.env`:

```env
MAX_USE_WEBHOOK=0
```

И `docker compose restart bot` — снова long polling. До 11.05.2026 — без
изменений, после — с лимитами (2 RPS, 30 c, 100 событий, TTL 24 ч).

## Диагностика 404 на /max/webhook

Если `curl https://connector.into.spb.ru/max/webhook` возвращает 404:

```bash
# Какой vhost обрабатывает HTTPS-запрос для этого домена?
sudo httpd -S 2>&1 | grep -B1 -A3 connector

# Если в выводе port 443 namevhost не connector.into.spb.ru —
# значит наш :443 vhost не подключён, проверьте:
ls -la /etc/httpd/conf.d/connector*

# Слушает ли бот 8080 на хосте?
sudo ss -tlnp | grep 8080
# Должно быть: 127.0.0.1:8080 ... docker-proxy

# Перечитать Apache и контейнер
sudo httpd -t
sudo systemctl reload httpd
docker compose ps
```
