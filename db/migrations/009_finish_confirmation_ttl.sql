-- Rename the temporary result-view markers to explicit mutual finish confirmations.
ALTER TABLE conflict_sessions RENAME COLUMN result_seen_by_p1 TO finish_confirmed_by_p1;
ALTER TABLE conflict_sessions RENAME COLUMN result_seen_by_p2 TO finish_confirmed_by_p2;

-- Completed conflict records are deleted after the configured TTL (48 hours by default).
CREATE OR REPLACE FUNCTION purge_expired_data(
    days_retention integer DEFAULT 2,
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
    sessions_cutoff := now() - (GREATEST(days_retention, 0) || ' days')::interval;
    inputs_cutoff := now() - (hours_raw_ttl || ' hours')::interval;

    DELETE FROM conflict_sessions
    WHERE status = 'completed'
      AND completed_at IS NOT NULL
      AND completed_at <= sessions_cutoff;
    GET DIAGNOSTICS purged_sessions_count = ROW_COUNT;

    DELETE FROM pending_inputs
    WHERE created_at <= inputs_cutoff OR expires_at <= now();
    GET DIAGNOSTICS purged_inputs_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'purged_sessions', purged_sessions_count,
        'purged_inputs', purged_inputs_count
    );
END;
$$;
