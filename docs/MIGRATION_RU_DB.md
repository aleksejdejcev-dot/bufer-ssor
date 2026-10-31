# План миграции базы данных на российский хостинг (Yandex Cloud / Selectel)

> **Цель**: Обеспечить размещение первичных баз данных пользователей на территории РФ (в соответствии с требованиями ч. 5 ст. 18 152-ФЗ) без изменения бизнес-логики приложения и сигнатур репозитория.

---

## 1. Архитектурная изоляция репозитория

В ходе рефакторинга Этапа 3.6 слой базы данных изолирован за абстрактным интерфейсом `Repository` (`backend/repo/base.py`).

В приложении реализованы два класса:
1. `InMemoryRepo` — автономное in-memory хранилище для тестов и локальной разработки.
2. `SupabaseRepo` — реализация поверх Supabase PostgREST клиента.

Для миграции на Managed PostgreSQL в РФ создается третья реализация: `PostgresRepo` (`backend/repo/postgres_repo.py`), реализующая тот же протокол `Repository` с использованием асинхронного драйвера `asyncpg` или `psycopg3` (пул соединений `asyncpg.Pool`). Ни `main.py`, ни `bot.py`, ни `ai_service.py` не потребуют изменений.

---

## 2. Выбор целевой инфраструктуры

| Критерий | Yandex Cloud Managed Service for PostgreSQL | Selectel Managed Databases |
| :--- | :--- | :--- |
| **Локализация в РФ** | Дата-центры в Москве, Владимире, Рязани | Дата-центры в Москве и Санкт-Петербурге |
| **Отказоустойчивость** | Multi-AZ (HA-кластер из 2-3 хостов) | Master-Replica кластер |
| **Резервное копирование** | Автоматические ежедневные бэкапы + WAL | Автоматические ежедневные бэкапы |
| **Безопасность** | Соответствие 152-ФЗ до УЗ-1 включительно | Аттестат соответствия 152-ФЗ до УЗ-1 |
| **Расширения** | `pgcrypto`, `uuid-ossp`, `pg_stat_statements` | `pgcrypto`, `uuid-ossp`, `pg_stat_statements` |

---

## 3. Пошаговый план миграции

### Шаг 1. Подготовка кластера в РФ
1. Развернуть кластер Managed PostgreSQL (версия 15 или 16).
2. Создать базу данных `buffer_ssor` и пользователя `buffer_app`.
3. Включить расширение `pgcrypto`:
   ```sql
   CREATE EXTENSION IF NOT EXISTS "pgcrypto";
   ```
4. Выполнить последовательно все миграции из папки `supabase/migrations/`:
   - `20261029000000_init_buffer_ssor.sql`
   - `20261031000000_payments_and_retention.sql`

### Шаг 2. Перенос существующих данных (Data Migration)
1. Выполнить экспорт структуры и данных из текущей БД Supabase:
   ```bash
   pg_dump "postgresql://postgres:[PASSWORD]@db.[REF].supabase.co:5432/postgres" \
     --data-only \
     --exclude-table-data="pending_inputs" \
     --no-owner \
     --no-privileges \
     > dump_data.sql
   ```
   > **Примечание**: Таблица `pending_inputs` исключается из переноса, так как содержит только временные данные активных сессий (не дольше 48ч).

2. Загрузить данные в российский кластер:
   ```bash
   psql "postgresql://buffer_app:[PASSWORD]@[RU_HOST]:6432/buffer_ssor?sslmode=verify-full&sslrootcert=certs/CA.pem" \
     < dump_data.sql
   ```

### Шаг 3. Реализация адаптера PostgresRepo
1. Установить зависимости:
   ```bash
   pip install asyncpg
   ```
2. Создать `backend/repo/postgres_repo.py`, реализующий методы интерфейса `Repository`:
   - Пул соединений: `asyncpg.create_pool(...)`
   - Вызовы стандартных SQL-запросов и хранимых функций `purge_expired_data`, `delete_couple_data`.
3. В `backend/repo/__init__.py` добавить выбор репозитория:
   - Если задан `DATABASE_URL=postgresql://...` — использовать `PostgresRepo`.
   - Если заданы `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` — `SupabaseRepo`.
   - Иначе — `InMemoryRepo`.

### Шаг 4. Переключение трафика (Switchover)
1. Активировать технологическое окно (maintenance window):
   - Бот переводится в режим ожидания («Идут технические работы, сервис возобновит работу через 10 минут»).
2. Зафиксировать финальную дельту данных.
3. Обновить переменные окружения на сервере приложения:
   ```env
   REPO_TYPE=postgres
   DATABASE_URL=postgresql://buffer_app:...@[RU_HOST]:6432/buffer_ssor?sslmode=verify-full
   ```
4. Перезапустить бэкенд и бота.
5. Прогнать e2e-тесты (`pytest backend/tests/test_e2e_pipeline.py`).
6. Открыть доступ пользователям.

---

## 4. Контрольные проверки после миграции

1. [ ] Подключение к БД работает исключительно по зашифрованному каналу TLS с валидацией сертификата удостоверяющего центра.
2. [ ] Все сессии и пары сохранены, пользователи не потеряли привязки.
3. [ ] Автоматическая задача retention (`purge_expired_data`) выполняется по расписанию.
4. [ ] Доступ к БД разрешен только с IP-адресов серверов приложения (Security Groups).
