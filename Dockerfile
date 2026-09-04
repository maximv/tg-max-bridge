# Dockerfile — инструкция для Docker: как собрать контейнер с ботом
#
# Docker читает этот файл сверху вниз и выполняет каждую команду.
# Результат — готовый «образ» (image), из которого запускается контейнер.

# Шаг 1: Берём готовый образ Python 3.11 (slim — лёгкая версия без лишнего)
FROM python:3.11-slim

# Шаг 2: Создаём рабочую папку внутри контейнера
WORKDIR /bridge

# Шаг 3: Сертификаты НУЦ Минцифры для platform-api2.max.ru.
# Кладём в /bridge/certs — httpx к MAX берёт их через app/ca_bundle.py.
# НЕ дописываем в certifi: aiogram грузит certifi.where() как есть,
# битый бандл роняет Bot() с ssl.SSLError: [X509] PEM lib.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY certs/ /bridge/certs/
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY certs/russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates

# Шаг 4: Копируем файл со списком библиотек и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Шаг 5: Копируем папку с кодом бота внутрь контейнера
COPY app/ app/

# Шаг 6: Команда запуска — что делать когда контейнер стартует
CMD ["python", "app/main.py"]
