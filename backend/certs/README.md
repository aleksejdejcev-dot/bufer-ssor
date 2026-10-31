# Сертификаты Минцифры РФ (Russian Trusted Root CA)

## Назначение
Файл `russian_trusted_root_ca.pem` содержит доверенные корневой и выпускающий сертификаты Национального удостоверяющего центра Минцифры России.
Используется для защищенного TLS-взаимодействия с API Сбер GigaChat (`https://ngw.devices.sberbank.ru:9443`) без отключения проверки сертификатов (`GIGACHAT_INSECURE=0`).

---

## Контрольная сумма и источник

- **Имя файла**: `russian_trusted_root_ca.pem`
- **Официальный источник**: [Единый портал государственных услуг (Госуслуги)](https://www.gosuslugi.ru/crt)
- **Прямая ссылка**: `https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.pem`
- **Алгоритм хеширования**: SHA-256
- **Хеш-сумма (SHA-256)**:
  ```
  6b0878aec15ce67eac22dee8eb2755eee019cb60d20a99d8fa970e79a75874c7
  ```

---

## Проверка целостности

Для проверки подлинности файла выполните команду в терминале:

```bash
# macOS
shasum -a 256 backend/certs/russian_trusted_root_ca.pem

# Linux
sha256sum backend/certs/russian_trusted_root_ca.pem
```

Вывод должен в точности совпадать с эталонным хешем:
`6b0878aec15ce67eac22dee8eb2755eee019cb60d20a99d8fa970e79a75874c7`.

---

## Обновление сертификата

Если файл отсутствует или истёк срок действия сертификата:
```bash
curl -k -o backend/certs/russian_trusted_root_ca.pem https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.pem
shasum -a 256 backend/certs/russian_trusted_root_ca.pem
```
