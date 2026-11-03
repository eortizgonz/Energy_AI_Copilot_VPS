CREATE TABLE IF NOT EXISTS public.machine_variables (
    id BIGSERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    code VARCHAR(80) NOT NULL,
    name VARCHAR(160) NOT NULL,
    unit VARCHAR(30) NOT NULL,
    category VARCHAR(40) NOT NULL,
    nominal_value DOUBLE PRECISION NOT NULL,
    simulation_sigma DOUBLE PRECISION NOT NULL DEFAULT 0,
    lower_warning DOUBLE PRECISION,
    lower_critical DOUBLE PRECISION,
    upper_warning DOUBLE PRECISION,
    upper_critical DOUBLE PRECISION,
    sampling_interval_seconds INTEGER NOT NULL DEFAULT 60 CHECK (sampling_interval_seconds > 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(machine_id, code),
    CHECK (simulation_sigma >= 0)
);

CREATE TABLE IF NOT EXISTS public.telemetry_readings (
    id BIGSERIAL PRIMARY KEY,
    variable_id BIGINT NOT NULL REFERENCES public.machine_variables(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    value DOUBLE PRECISION NOT NULL,
    quality VARCHAR(20) NOT NULL DEFAULT 'good' CHECK (quality IN ('good', 'uncertain', 'bad')),
    is_anomaly BOOLEAN NOT NULL DEFAULT FALSE,
    source VARCHAR(40) NOT NULL DEFAULT 'simulator',
    UNIQUE(variable_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS ix_telemetry_variable_time
    ON public.telemetry_readings(variable_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_telemetry_anomalies
    ON public.telemetry_readings(recorded_at DESC) WHERE is_anomaly;

CREATE TABLE IF NOT EXISTS public.machine_health_snapshots (
    id BIGSERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    risk_score DOUBLE PRECISION NOT NULL CHECK (risk_score BETWEEN 0 AND 100),
    health_status VARCHAR(20) NOT NULL CHECK (health_status IN ('healthy', 'warning', 'critical')),
    predicted_failure_mode VARCHAR(180) NOT NULL,
    remaining_useful_life_days INTEGER CHECK (remaining_useful_life_days >= 0),
    explanation VARCHAR(600) NOT NULL,
    UNIQUE(machine_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS ix_health_machine_time
    ON public.machine_health_snapshots(machine_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_health_status_time
    ON public.machine_health_snapshots(health_status, recorded_at DESC);

CREATE TABLE IF NOT EXISTS public.telemetry_collection_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    readings_inserted INTEGER NOT NULL DEFAULT 0,
    machines_processed INTEGER NOT NULL DEFAULT 0,
    error_message VARCHAR(600)
);
