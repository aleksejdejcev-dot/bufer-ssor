-- ==============================================================================
-- Миграция: 004_deletions_log.sql
-- Проект: «Буфер Ссор»
-- Назначение:
--   Таблица deletions_log для аудита фактов удаления данных (GDPR / право на забвение)
--   без сохранения персональных данных (строго хэшированные идентификаторы).
-- ==============================================================================

CREATE TABLE IF NOT EXISTS deletions_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    couple_id_hash text NOT NULL,
    initiated_by_hash text NOT NULL,
    entity_type text NOT NULL, -- 'couple' | 'history'
    deleted_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE deletions_log IS 'Журнал аудита фактов удаления данных пользователей (псевдонимизирован)';

CREATE INDEX IF NOT EXISTS idx_deletions_log_couple_id_hash ON deletions_log (couple_id_hash);
CREATE INDEX IF NOT EXISTS idx_deletions_log_deleted_at ON deletions_log (deleted_at);

GRANT SELECT, INSERT ON deletions_log TO app_user;
