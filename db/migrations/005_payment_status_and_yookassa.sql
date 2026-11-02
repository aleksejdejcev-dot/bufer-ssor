-- ==============================================================================
-- Миграция: 005_payment_status_and_yookassa.sql
-- Проект: «Буфер Ссор»
-- Назначение:
--   Поддержка статусов платежей (pending, succeeded, canceled) и даты оплаты для ЮKassa.
-- ==============================================================================

ALTER TABLE payments ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_at timestamptz NULL;
ALTER TABLE payments ALTER COLUMN amount TYPE numeric USING amount::numeric;

CREATE INDEX IF NOT EXISTS idx_payments_status ON payments (status);

GRANT SELECT, INSERT, UPDATE, DELETE ON payments TO app_user;
