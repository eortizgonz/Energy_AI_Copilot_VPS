CREATE TABLE IF NOT EXISTS public.energy_generation_readings (
    id BIGSERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
    rated_power_mw DOUBLE PRECISION NOT NULL CHECK (rated_power_mw >= 0),
    planned_minutes DOUBLE PRECISION NOT NULL CHECK (planned_minutes > 0),
    operating_minutes DOUBLE PRECISION NOT NULL CHECK (operating_minutes >= 0),
    downtime_minutes DOUBLE PRECISION NOT NULL CHECK (downtime_minutes >= 0),
    gross_generation_mwh DOUBLE PRECISION NOT NULL CHECK (gross_generation_mwh >= 0),
    auxiliary_consumption_mwh DOUBLE PRECISION NOT NULL CHECK (auxiliary_consumption_mwh >= 0),
    net_generation_mwh DOUBLE PRECISION NOT NULL CHECK (net_generation_mwh >= 0),
    compliant_generation_mwh DOUBLE PRECISION NOT NULL CHECK (compliant_generation_mwh >= 0),
    fuel_energy_input_mwh DOUBLE PRECISION NOT NULL CHECK (fuel_energy_input_mwh >= 0),
    heat_rate_mj_kwh DOUBLE PRECISION NOT NULL CHECK (heat_rate_mj_kwh >= 0),
    thermal_efficiency DOUBLE PRECISION NOT NULL CHECK (thermal_efficiency BETWEEN 0 AND 100),
    availability DOUBLE PRECISION NOT NULL CHECK (availability BETWEEN 0 AND 100),
    performance DOUBLE PRECISION NOT NULL CHECK (performance BETWEEN 0 AND 100),
    conformity DOUBLE PRECISION NOT NULL CHECK (conformity BETWEEN 0 AND 100),
    operational_efficiency DOUBLE PRECISION NOT NULL CHECK (operational_efficiency BETWEEN 0 AND 100),
    source VARCHAR(40) NOT NULL DEFAULT 'simulator',
    UNIQUE(machine_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS ix_energy_generation_machine_time
    ON public.energy_generation_readings(machine_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS ix_energy_generation_time
    ON public.energy_generation_readings(recorded_at DESC);

CREATE TABLE IF NOT EXISTS public.energy_collection_runs (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    readings_inserted INTEGER NOT NULL DEFAULT 0,
    machines_processed INTEGER NOT NULL DEFAULT 0,
    error_message VARCHAR(600)
);
