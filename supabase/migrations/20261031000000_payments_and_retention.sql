-- ==============================================================================
-- Миграция: 20261031000000_payments_and_retention.sql
-- Проект: «Буфер Ссор»
-- Назначение:
--   1. Таблица payments для фиксации платежей с требованием бухучета (ON DELETE SET NULL).
--   2. Политика retention: функция purge_expired_data для очистки старых сессий и сырых данных.
--   3. Обновленная функция delete_couple_data с каскадным удалением профилей пользователей.
-- ==============================================================================

-- ==============================================================================
-- 1. Таблица: payments (Финансовые транзакции)
-- Платежи хранятся независимо от удаления пары для выполнения требований бухучета.
-- Персональный идентификатор заменяется на payer_hash.
-- ==============================================================================
CREATE TABLE IF NOT EXISTS payments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    product text NOT NULL,
    amount integer NOT NULL CHECK (amount > 0),
    currency text NOT NULL DEFAULT 'RUB',
    provider_charge_id text NOT NULL UNIQUE,
    payer_hash text NOT NULL,
    couple_id uuid NULL REFERENCES couples(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE payments IS 'Транзакции оплат пользователей (анонимизированы через payer_hash, отвязываются при удалении пары)';
COMMENT ON COLUMN payments.provider_charge_id IS 'Уникальный ID платежа со стороны платежного шлюза (YooKassa / Telegram Stars)';
COMMENT ON COLUMN payments.payer_hash IS 'SHA-256 хэш telegram_id плательщика с секретной солью PAYMENT_HASH_KEY';
COMMENT ON COLUMN payments.couple_id IS 'ID пары на момент оплаты (при удалении пары выставляется в NULL)';

CREATE INDEX IF NOT EXISTS idx_payments_couple_id ON payments (couple_id);
CREATE INDEX IF NOT EXISTS idx_payments_payer_hash ON payments (payer_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_charge_id ON payments (provider_charge_id);

-- RLS для payments: доступ ТОЛЬКО через service_role
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access on payments" ON payments;
CREATE POLICY "Service role full access on payments" ON payments
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON payments FROM anon, authenticated;
GRANT ALL ON payments TO service_role;


-- ==============================================================================
-- 2. Хранимая функция: purge_expired_data(days_retention INT, hours_raw_ttl INT)
-- Очистка завершенных сессий старше days_retention (30 дней)
-- и удаление зависших сырых данных старше hours_raw_ttl (48 часов).
-- ==============================================================================
CREATE OR REPLACE FUNCTION purge_expired_data(
    days_retention integer DEFAULT 30,
    hours_raw_ttl integer DEFAULT 48
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    purged_sessions_count integer := 0;
    purged_inputs_count integer := 0;
    sessions_cutoff timestamptz;
    inputs_cutoff timestamptz;
BEGIN
    sessions_cutoff := now() - (days_retention || ' days')::interval;
    inputs_cutoff := now() - (hours_raw_ttl || ' hours')::interval;

    -- 1. Очистка результатов completed-сессий старше days_retention
    UPDATE conflict_sessions
    SET
        ai_advice_p1 = NULL,
        ai_advice_p2 = NULL,
        shared_summary = NULL,
        status = 'purged_by_retention'
    WHERE status = 'completed'
      AND completed_at IS NOT NULL
      AND completed_at <= sessions_cutoff;

    GET DIAGNOSTICS purged_sessions_count = ROW_COUNT;

    -- 2. Удаление зависших сырых данных pending_inputs
    DELETE FROM pending_inputs
    WHERE created_at <= inputs_cutoff
       OR expires_at <= now();

    GET DIAGNOSTICS purged_inputs_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'purged_sessions', purged_sessions_count,
        'purged_inputs', purged_inputs_count
    );
END;
$$;

COMMENT ON FUNCTION purge_expired_data(integer, integer) IS 'Очистка данных по политике retention (обнуление сессий и удаление pending_inputs)';


-- ==============================================================================
-- 3. Обновленная хранимая функция: delete_couple_data(target_couple_id uuid)
-- Удаляет:
-- - историю сессий и исходников;
-- - саму пару;
-- - ОБА пользовательских профиля в users;
-- Платежи отвязываются (couple_id = NULL).
-- ==============================================================================
CREATE OR REPLACE FUNCTION delete_couple_data(target_couple_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    p1_id bigint;
    p2_id bigint;
BEGIN
    -- Находим идентификаторы партнеров перед удалением пары
    SELECT partner_1_id, partner_2_id INTO p1_id, p2_id
    FROM couples
    WHERE id = target_couple_id;

    -- 1. Отвязываем платежи
    UPDATE payments
    SET couple_id = NULL
    WHERE couple_id = target_couple_id;

    -- 2. Сбрасываем couple_id у пользователей перед каскадным удалением
    UPDATE users
    SET couple_id = NULL
    WHERE couple_id = target_couple_id;

    -- 3. Удаляем пару (каскадно удаляет conflict_sessions и pending_inputs)
    DELETE FROM couples
    WHERE id = target_couple_id;

    -- 4. Удаляем профили обоих партнеров
    IF p1_id IS NOT NULL THEN
        DELETE FROM users WHERE telegram_id = p1_id;
    END IF;

    IF p2_id IS NOT NULL THEN
        DELETE FROM users WHERE telegram_id = p2_id;
    END IF;
END;
$$;

COMMENT ON FUNCTION delete_couple_data(uuid) IS 'Полное удаление пары, истории и обоих профилей пользователей с отвязкой платежей';
