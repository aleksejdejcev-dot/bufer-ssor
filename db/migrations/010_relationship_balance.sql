CREATE TABLE IF NOT EXISTS relationship_balance_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    couple_id uuid NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    status text NOT NULL CHECK (status IN ('collecting', 'analyzing', 'completed')) DEFAULT 'collecting',
    answers_p1 bytea NULL,
    answers_p2 bytea NULL,
    result jsonb NULL,
    finish_confirmed_by_p1 boolean NOT NULL DEFAULT false,
    finish_confirmed_by_p2 boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz NULL
);

CREATE INDEX IF NOT EXISTS idx_relationship_balance_couple_created
    ON relationship_balance_sessions (couple_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_balance_one_collecting_per_couple
    ON relationship_balance_sessions (couple_id) WHERE status IN ('collecting', 'analyzing');

GRANT SELECT, INSERT, UPDATE, DELETE ON relationship_balance_sessions TO app_user;
