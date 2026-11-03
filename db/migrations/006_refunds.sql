-- ==============================================================================
-- Миграция: 006_refunds.sql
-- Проект: «Буфер Ссор»
-- Назначение:
--   Поддержка фиксации возвратов (refund_id, refunded_at) в таблице платежей.
-- ==============================================================================

ALTER TABLE payments ADD COLUMN IF NOT EXISTS refund_id text NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS refunded_at timestamptz NULL;

CREATE INDEX IF NOT EXISTS idx_payments_refund_id ON payments (refund_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON payments TO app_user;
