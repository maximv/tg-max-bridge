# Dockerfile — инструкция для Docker: как собрать контейнер с ботом
#
# Docker читает этот файл сверху вниз и выполняет каждую команду.
# Результат — готовый «образ» (image), из которого запускается контейнер.

# Шаг 1: Берём готовый образ Python 3.11 (slim — лёгкая версия без лишнего)
FROM python:3.11-slim

# Шаг 2: Создаём рабочую папку внутри контейнера
WORKDIR /bridge

# Шаг 3: Сертификаты НУЦ Минцифры (нужны для HTTPS к platform-api2.max.ru).
# Без них httpx/ssl падает с CERTIFICATE_VERIFY_FAILED.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY certs/russian_trusted_root_ca.crt /usr/local/share/ca-certificates/russian_trusted_root_ca.crt
COPY certs/russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/russian_trusted_sub_ca.crt
RUN update-ca-certificates

# Шаг 4: Копируем файл со списком библиотек и устанавливаем их
# (делаем это ДО копирования кода — так Docker кэширует этот шаг
#  и не переустанавливает библиотеки при каждом изменении кода)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Шаг 5: Копируем папку с кодом бота внутрь контейнера
COPY app/ app/

# Шаг 6: Команда запуска — что делать когда контейнер стартует
CMD ["python", "app/main.py"]
