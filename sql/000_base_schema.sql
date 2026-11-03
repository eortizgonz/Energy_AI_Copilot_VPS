CREATE TABLE IF NOT EXISTS public.users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(80) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(40) NOT NULL DEFAULT 'Operador',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_users_email_lower
    ON public.users (lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username_lower
    ON public.users (lower(username));

CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user
    ON public.password_reset_tokens(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_active
    ON public.password_reset_tokens(expires_at) WHERE used_at IS NULL;

CREATE TABLE IF NOT EXISTS public.machines (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(140) NOT NULL,
    machine_type VARCHAR(100) NOT NULL,
    area VARCHAR(100) NOT NULL,
    max_usage_hours DOUBLE PRECISION NOT NULL DEFAULT 50000,
    max_vibration DOUBLE PRECISION NOT NULL DEFAULT 12,
    max_temperature DOUBLE PRECISION NOT NULL DEFAULT 600,
    rated_current DOUBLE PRECISION NOT NULL DEFAULT 0,
    nominal_rpm DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_pressure DOUBLE PRECISION NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (max_usage_hours > 0),
    CHECK (max_vibration >= 0),
    CHECK (max_temperature >= 0),
    CHECK (rated_current >= 0),
    CHECK (nominal_rpm >= 0),
    CHECK (max_pressure >= 0)
);
