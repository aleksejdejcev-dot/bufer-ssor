-- ==============================================================================
-- Миграция: 001_init_schema.sql
-- Проект: «Буфер Ссор»
-- СУБД: PostgreSQL (15+)
-- ==============================================================================

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
    mood_updated_at_p1 timestamptz NULL,
    mood_updated_at_p2 timestamptz NULL,
    invite_created_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_different_partners CHECK (partner_2_id IS NULL OR partner_1_id <> partner_2_id)
);

COMMENT ON TABLE couples IS 'Связки двух партнеров, лимиты сессий и текущие показатели настроения';
COMMENT ON COLUMN couples.invite_code IS 'Уникальный код для приглашения второго партнера';
COMMENT ON COLUMN couples.free_sessions_left IS 'Количество оставшихся бесплатных сессий медиации';

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
    status text NOT NULL CHECK (status IN ('waiting_partner_2', 'processing', 'analyzing', 'completed', 'expired', 'failed', 'purged_by_retention')),
    risk_level text NULL CHECK (risk_level IN ('none', 'elevated', 'high')),
    ai_advice_p1 jsonb NULL,
    ai_advice_p2 jsonb NULL,
    shared_summary jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz NULL
);

COMMENT ON TABLE conflict_sessions IS 'Сессии разбора конфликта с персональными рекомендациями и общим итогом';

-- ==============================================================================
-- 4. Таблица: pending_inputs (Временные зашифрованные исходники)
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

-- ==============================================================================
-- 5. Таблица: rate_limits (Хранилище ограничений запросов)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS rate_limits (
    key text PRIMARY KEY,
    requests integer NOT NULL DEFAULT 1,
    window_start timestamptz NOT NULL DEFAULT now()
);

-- ==============================================================================
-- 6. Индексы
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
-- 7. Хранимые функции
-- ==============================================================================
CREATE OR REPLACE FUNCTION delete_couple_data(target_couple_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    UPDATE users
    SET couple_id = NULL
    WHERE couple_id = target_couple_id;

    DELETE FROM couples
    WHERE id = target_couple_id;
END;
$$;

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
