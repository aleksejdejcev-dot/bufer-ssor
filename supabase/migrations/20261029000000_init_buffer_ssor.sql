-- ==============================================================================
-- Миграция: 20261029000000_init_buffer_ssor.sql
-- Проект: «Буфер Ссор» (Telegram Mini App + Бот ИИ-медиатор)
-- СУБД: Supabase PostgreSQL
-- ==============================================================================

-- Включаем расширение для генерации UUID, если оно еще не подключено
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ==============================================================================
-- 1. Таблица: users (Пользователи Telegram)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS users (
    telegram_id bigint PRIMARY KEY,
    first_name text NOT NULL,
    accepted_legal_at timestamptz NULL,
    couple_id uuid NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS 'Пользователи бота/мини-аппа, привязанные к их Telegram ID';
COMMENT ON COLUMN users.accepted_legal_at IS 'Отметка согласия с условиями использования и подтверждение 18+';
COMMENT ON COLUMN users.couple_id IS 'ID текущей активной пары пользователя';

-- ==============================================================================
-- 2. Таблица: couples (Пары и статус связки)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS couples (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invite_code text NOT NULL UNIQUE,
    partner_1_id bigint NOT NULL REFERENCES users(telegram_id),
    partner_2_id bigint NULL REFERENCES users(telegram_id),
    free_sessions_left integer NOT NULL DEFAULT 2 CHECK (free_sessions_left >= 0),
    subscription_until timestamptz NULL,
    auto_renew boolean NOT NULL DEFAULT false,
    mood_p1 integer NULL CHECK (mood_p1 BETWEEN 1 AND 10),
    mood_p2 integer NULL CHECK (mood_p2 BETWEEN 1 AND 10),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_partners CHECK (partner_2_id IS NULL OR partner_1_id <> partner_2_id)
);

COMMENT ON TABLE couples IS 'Связки двух партнеров, лимиты сессий и текущие показатели настроения';
COMMENT ON COLUMN couples.invite_code IS 'Уникальный код для приглашения второго партнера';
COMMENT ON COLUMN couples.free_sessions_left IS 'Количество оставшихся бесплатных сессий медиации (по умолчанию 2)';
COMMENT ON COLUMN couples.mood_p1 IS 'Субъективное самочувствие партнера 1 (шкала 1-10)';
COMMENT ON COLUMN couples.mood_p2 IS 'Субъективное самочувствие партнера 2 (шкала 1-10)';

-- Внешний ключ из users в couples (с ON DELETE SET NULL, чтобы при удалении пары не ломался профиль)
ALTER TABLE users
    DROP CONSTRAINT IF EXISTS fk_users_couple,
    ADD CONSTRAINT fk_users_couple
    FOREIGN KEY (couple_id)
    REFERENCES couples(id)
    ON DELETE SET NULL;

-- ==============================================================================
-- 3. Таблица: conflict_sessions (Сессии медиации конфликта)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS conflict_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    couple_id uuid NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    initiator_id bigint NOT NULL REFERENCES users(telegram_id),
    status text NOT NULL CHECK (status IN ('waiting_partner_2', 'analyzing', 'completed', 'expired', 'failed')),
    risk_level text NULL CHECK (risk_level IN ('none', 'elevated', 'high')),
    ai_advice_p1 jsonb NULL,
    ai_advice_p2 jsonb NULL,
    shared_summary jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz NULL
);

COMMENT ON TABLE conflict_sessions IS 'Сессии разбора конфликта с персональными рекомендациями и общим итогом';
COMMENT ON COLUMN conflict_sessions.shared_summary IS 'Общий итог для пары (хранится один раз, одинаковый для обоих, без раскрытия личных версий)';
COMMENT ON COLUMN conflict_sessions.risk_level IS 'Оценка риска деструктивного поведения/насилия (none, elevated, high)';

-- ==============================================================================
-- 4. Таблица: pending_inputs (Временные зашифрованные исходники)
-- ВНИМАНИЕ: сырые тексты/аудио хранятся ТОЛЬКО здесь в зашифрованном виде (Fernet bytea),
-- удаляются сразу после завершения анализа или по истечении 48 часов.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS pending_inputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES conflict_sessions(id) ON DELETE CASCADE,
    author_telegram_id bigint NOT NULL REFERENCES users(telegram_id),
    kind text NOT NULL CHECK (kind IN ('text', 'audio')),
    payload_encrypted bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '48 hours')
);

COMMENT ON TABLE pending_inputs IS 'Временный зашифрованный буфер исходных жалоб партнеров (text/audio)';
COMMENT ON COLUMN pending_inputs.payload_encrypted IS 'Зашифрованные симметричным ключом Fernet байты текста или аудиофайла';

-- ==============================================================================
-- 5. Индексы
-- ==============================================================================
CREATE UNIQUE INDEX IF NOT EXISTS idx_couples_invite_code ON couples (invite_code);
CREATE INDEX IF NOT EXISTS idx_users_couple_id ON users (couple_id);
CREATE INDEX IF NOT EXISTS idx_couples_partner_1_id ON couples (partner_1_id);
CREATE INDEX IF NOT EXISTS idx_couples_partner_2_id ON couples (partner_2_id);
CREATE INDEX IF NOT EXISTS idx_conflict_sessions_couple_id ON conflict_sessions (couple_id);
CREATE INDEX IF NOT EXISTS idx_conflict_sessions_status ON conflict_sessions (status);
CREATE INDEX IF NOT EXISTS idx_pending_inputs_session_id ON pending_inputs (session_id);
CREATE INDEX IF NOT EXISTS idx_pending_inputs_expires_at ON pending_inputs (expires_at);

-- ==============================================================================
-- 6. Хранимая функция: delete_couple_data(target_couple_id uuid)
-- Полное удаление пары, всех сессий, зашифрованных исходников и сброс users.couple_id.
-- ==============================================================================
CREATE OR REPLACE FUNCTION delete_couple_data(target_couple_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- 1. Сбрасываем couple_id у пользователей данной пары
    UPDATE users
    SET couple_id = NULL
    WHERE couple_id = target_couple_id;

    -- 2. Удаляем саму пару.
    -- За счет внешних ключей с ON DELETE CASCADE автоматически удаляются:
    -- - все записи conflict_sessions данной пары;
    -- - все временные записи pending_inputs для удаленных сессий.
    DELETE FROM couples
    WHERE id = target_couple_id;
END;
$$;

COMMENT ON FUNCTION delete_couple_data(uuid) IS 'Полное и безвозвратное удаление всех данных пары (сессии, исходники, связь)';

-- ==============================================================================
-- 7. Хранимая функция: cleanup_expired_pending_inputs()
-- Автоматическая очистка просроченных (>48ч) зашифрованных исходников.
-- ==============================================================================
CREATE OR REPLACE FUNCTION cleanup_expired_pending_inputs()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    deleted_rows integer;
BEGIN
    DELETE FROM pending_inputs
    WHERE expires_at <= now();

    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$$;

COMMENT ON FUNCTION cleanup_expired_pending_inputs() IS 'Очистка просроченных зашифрованных исходников по TTL expires_at';

-- ==============================================================================
-- 8. Row Level Security (RLS)
-- Включаем RLS на всех таблицах.
-- Доступ разрешен ТОЛЬКО через service_role с бэкенда.
-- Любые прямые запросы через anon / authenticated ключи с фронтенда заблокированы.
-- ==============================================================================
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE couples ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflict_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_inputs ENABLE ROW LEVEL SECURITY;

-- Явные политики для роли service_role
DROP POLICY IF EXISTS "Service role full access on users" ON users;
CREATE POLICY "Service role full access on users" ON users
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access on couples" ON couples;
CREATE POLICY "Service role full access on couples" ON couples
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access on conflict_sessions" ON conflict_sessions;
CREATE POLICY "Service role full access on conflict_sessions" ON conflict_sessions
    FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access on pending_inputs" ON pending_inputs;
CREATE POLICY "Service role full access on pending_inputs" ON pending_inputs
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Запрещаем публичный доступ (anon / authenticated не имеют прав SELECT/INSERT/UPDATE/DELETE)
REVOKE ALL ON users FROM anon, authenticated;
REVOKE ALL ON couples FROM anon, authenticated;
REVOKE ALL ON conflict_sessions FROM anon, authenticated;
REVOKE ALL ON pending_inputs FROM anon, authenticated;

-- Предоставляем полные права служебной роли Supabase (service_role)
GRANT ALL ON users TO service_role;
GRANT ALL ON couples TO service_role;
GRANT ALL ON conflict_sessions TO service_role;
GRANT ALL ON pending_inputs TO service_role;
