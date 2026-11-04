-- Подписка принадлежит плательщику и сохраняется при удалении/смене пары.
CREATE TABLE IF NOT EXISTS user_subscriptions (
    payer_hash text PRIMARY KEY,
    subscription_until timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

UPDATE couples SET free_sessions_left = LEAST(free_sessions_left, 2)
WHERE free_sessions_left > 2;

GRANT SELECT, INSERT, UPDATE, DELETE ON user_subscriptions TO app_user;

-- Переносим известные успешные покупки, включая платежи, отвязанные от
-- удалённых пар. Для существующей пары сохраняем её текущий срок, если он позже.
WITH RECURSIVE paid_rows AS (
    SELECT payer_hash,
           COALESCE(paid_at, created_at) AS paid_at,
           30 AS period_days,
           ROW_NUMBER() OVER (PARTITION BY payer_hash ORDER BY COALESCE(paid_at, created_at), id) AS rn
    FROM payments
    WHERE status = 'succeeded' AND paid_at IS NOT NULL
), timeline AS (
    SELECT payer_hash, rn, paid_at + make_interval(days => period_days) AS subscription_until
    FROM paid_rows WHERE rn = 1
    UNION ALL
    SELECT p.payer_hash, p.rn,
           GREATEST(t.subscription_until, p.paid_at) + make_interval(days => p.period_days)
    FROM timeline t
    JOIN paid_rows p ON p.payer_hash = t.payer_hash AND p.rn = t.rn + 1
), computed AS (
    SELECT payer_hash, MAX(subscription_until) AS subscription_until
    FROM timeline
    GROUP BY payer_hash
), legacy AS (
    SELECT p.payer_hash, MAX(c.subscription_until) AS subscription_until
    FROM payments p
    JOIN couples c ON c.id = p.couple_id
    WHERE p.status = 'succeeded'
    GROUP BY p.payer_hash
)
INSERT INTO user_subscriptions (payer_hash, subscription_until)
SELECT c.payer_hash, GREATEST(c.subscription_until, l.subscription_until)
FROM computed c
LEFT JOIN legacy l USING (payer_hash)
WHERE GREATEST(c.subscription_until, l.subscription_until) > now()
ON CONFLICT (payer_hash) DO UPDATE
SET subscription_until = GREATEST(user_subscriptions.subscription_until, EXCLUDED.subscription_until),
    updated_at = now();
