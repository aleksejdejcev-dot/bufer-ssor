-- Track which partners received a result so it can be removed immediately afterward.
ALTER TABLE conflict_sessions
    ADD COLUMN IF NOT EXISTS result_seen_by_p1 boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS result_seen_by_p2 boolean NOT NULL DEFAULT false;
