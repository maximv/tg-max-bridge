# Dockerfile — инструкция для Docker: как собрать контейнер с ботом
#
# Docker читает этот файл сверху вниз и выполняет каждую команду.
# Результат — готовый «образ» (image), из которого запускается контейнер.

# Шаг 1: Берём готовый образ Python 3.11 (slim — лёгкая версия без лишнего)
FROM python:3.11-slim

# Шаг 2: Создаём рабочую папку внутри контейнера
WORKDIR /bridge

# Шаг 3: Сертификаты НУЦ Минцифры (нужны для HTTPS к platform-api2.max.ru).
# Кладём и в системный trust store, и в /bridge/certs (для явного бандла в httpx).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY certs/ /bridge/certs/
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY certs/russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates

# OpenSSL/часть клиентов смотрят на эти переменные, а не на certifi.
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Шаг 4: Копируем файл со списком библиотек и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "\
from pathlib import Path; \
import certifi; \
b = Path(certifi.where()); \
extra = ''.join(p.read_text() for p in sorted(Path('/bridge/certs').glob('russian_trusted_*.crt'))); \
text = b.read_text(); \
b.write_text(text + ('\\n' + extra if extra.strip() not in text else ''))"

# Шаг 5: Копируем папку с кодом бота внутрь контейнера
COPY app/ app/

# Шаг 6: Команда запуска — что делать когда контейнер стартует
CMD ["python", "app/main.py"]
