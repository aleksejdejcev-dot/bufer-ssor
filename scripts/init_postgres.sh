#!/usr/bin/env bash
# ==============================================================================
# scripts/init_postgres.sh
# Инициализация тестовой БД и ролей при первом старте контейнера PostgreSQL.
# ==============================================================================
set -e

MIGRATOR_PASS="${MIGRATOR_PASSWORD:-migrator_dev_pass}"
APP_USER_PASS="${APP_USER_PASSWORD:-app_user_dev_pass}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE buffer_ssor_test;

    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migrator') THEN
            CREATE ROLE migrator WITH LOGIN SUPERUSER PASSWORD '$MIGRATOR_PASS';
        ELSE
            ALTER ROLE migrator WITH PASSWORD '$MIGRATOR_PASS';
        END IF;

        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
            CREATE ROLE app_user WITH LOGIN PASSWORD '$APP_USER_PASS';
        ELSE
            ALTER ROLE app_user WITH PASSWORD '$APP_USER_PASS';
        END IF;
    END
    \$\$;

    GRANT ALL PRIVILEGES ON DATABASE buffer_ssor TO migrator;
    GRANT ALL PRIVILEGES ON DATABASE buffer_ssor_test TO migrator;
    GRANT CONNECT ON DATABASE buffer_ssor TO app_user;
    GRANT CONNECT ON DATABASE buffer_ssor_test TO app_user;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "buffer_ssor_test" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";
    GRANT ALL PRIVILEGES ON SCHEMA public TO migrator;
    GRANT USAGE ON SCHEMA public TO app_user;
EOSQL
