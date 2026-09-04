# Сертификаты НУЦ Минцифры России
#
# Нужны для TLS к https://platform-api2.max.ru (корневой + промежуточный).
# Источник: https://gu-st.ru/ (официальный портал Госуслуг / НУЦ).
#
# В Docker-образе они ставятся автоматически (см. Dockerfile).
# На хосте CentOS 7 вручную:
#   sudo cp russian_trusted_*.crt /etc/pki/ca-trust/source/anchors/
#   sudo update-ca-trust
#
# Проверка:
#   curl -I https://platform-api2.max.ru
