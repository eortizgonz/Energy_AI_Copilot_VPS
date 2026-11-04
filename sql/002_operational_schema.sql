CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.products (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) NOT NULL UNIQUE,
    name VARCHAR(140) NOT NULL,
    product_type VARCHAR(80) NOT NULL,
    presentation VARCHAR(120) NOT NULL,
    unit_of_measure VARCHAR(20) NOT NULL DEFAULT 'ton',
    standard_batch_size INTEGER NOT NULL CHECK (standard_batch_size > 0),
    shelf_life_days INTEGER CHECK (shelf_life_days IS NULL OR shelf_life_days > 0),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS public.work_shifts (
    id SERIAL PRIMARY KEY,
    code VARCHAR(20) NOT NULL UNIQUE,
    name VARCHAR(60) NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    planned_minutes INTEGER NOT NULL CHECK (planned_minutes > 0),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS public.sop_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_hash VARCHAR(64) NOT NULL,
    document_name VARCHAR(255) NOT NULL,
    page INTEGER NOT NULL CHECK (page >= 1),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    content TEXT NOT NULL,
    embedding public.vector NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_hash, page, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_sop_chunks_document_hash
    ON public.sop_chunks(document_hash);

CREATE TABLE IF NOT EXISTS public.machine_readings (
    id BIGSERIAL PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    usage_hours DOUBLE PRECISION NOT NULL CHECK (usage_hours >= 0),
    vibration DOUBLE PRECISION NOT NULL CHECK (vibration >= 0),
    temperature DOUBLE PRECISION NOT NULL,
    current_amps DOUBLE PRECISION NOT NULL CHECK (current_amps >= 0),
    rpm DOUBLE PRECISION NOT NULL CHECK (rpm >= 0),
    pressure DOUBLE PRECISION NOT NULL CHECK (pressure >= 0),
    failure_probability DOUBLE PRECISION NOT NULL CHECK (failure_probability BETWEEN 0 AND 100),
    health_status VARCHAR(20) NOT NULL CHECK (health_status IN ('healthy', 'warning', 'critical')),
    explanation VARCHAR(500) NOT NULL,
    UNIQUE(machine_id, recorded_at)
);

CREATE INDEX IF NOT EXISTS ix_machine_readings_health_status
    ON public.machine_readings(health_status);
CREATE INDEX IF NOT EXISTS ix_machine_readings_machine_time
    ON public.machine_readings(machine_id, recorded_at DESC);

CREATE TABLE IF NOT EXISTS public.product_routings (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES public.products(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    operation_code VARCHAR(40) NOT NULL,
    operation_name VARCHAR(120) NOT NULL,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id),
    ideal_cycle_time_seconds DOUBLE PRECISION NOT NULL CHECK (ideal_cycle_time_seconds > 0),
    setup_minutes INTEGER NOT NULL CHECK (setup_minutes >= 0),
    UNIQUE(product_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_product_routings_machine_id
    ON public.product_routings(machine_id);

CREATE TABLE IF NOT EXISTS public.production_orders (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(40) NOT NULL UNIQUE,
    product_id INTEGER NOT NULL REFERENCES public.products(id),
    planned_quantity INTEGER NOT NULL CHECK (planned_quantity > 0),
    planned_start TIMESTAMPTZ NOT NULL,
    planned_end TIMESTAMPTZ NOT NULL,
    status VARCHAR(30) NOT NULL CHECK (status IN ('planned', 'released', 'in_progress', 'completed', 'cancelled')),
    priority VARCHAR(20) NOT NULL CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (planned_end > planned_start)
);

CREATE INDEX IF NOT EXISTS ix_production_orders_status
    ON public.production_orders(status);

CREATE TABLE IF NOT EXISTS public.production_batches (
    id SERIAL PRIMARY KEY,
    batch_number VARCHAR(50) NOT NULL UNIQUE,
    production_order_id INTEGER NOT NULL REFERENCES public.production_orders(id) ON DELETE CASCADE,
    planned_quantity INTEGER NOT NULL CHECK (planned_quantity > 0),
    actual_quantity INTEGER NOT NULL DEFAULT 0 CHECK (actual_quantity >= 0),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status VARCHAR(30) NOT NULL CHECK (status IN ('planned', 'in_progress', 'quality_hold', 'released', 'completed', 'rejected')),
    expiry_date DATE
);

CREATE INDEX IF NOT EXISTS ix_production_batches_order
    ON public.production_batches(production_order_id);
CREATE INDEX IF NOT EXISTS ix_production_batches_status
    ON public.production_batches(status);

CREATE TABLE IF NOT EXISTS public.production_runs (
    id SERIAL PRIMARY KEY,
    production_order_id INTEGER NOT NULL REFERENCES public.production_orders(id),
    batch_id INTEGER NOT NULL REFERENCES public.production_batches(id),
    product_id INTEGER NOT NULL REFERENCES public.products(id),
    machine_id INTEGER NOT NULL REFERENCES public.machines(id),
    shift_id INTEGER NOT NULL REFERENCES public.work_shifts(id),
    operation_sequence INTEGER NOT NULL CHECK (operation_sequence > 0),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    planned_minutes INTEGER NOT NULL CHECK (planned_minutes > 0),
    ideal_cycle_time_seconds DOUBLE PRECISION NOT NULL CHECK (ideal_cycle_time_seconds > 0),
    status VARCHAR(30) NOT NULL CHECK (status IN ('planned', 'running', 'paused', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS ix_production_runs_machine_time
    ON public.production_runs(machine_id, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_production_runs_order
    ON public.production_runs(production_order_id);

CREATE TABLE IF NOT EXISTS public.machine_downtime_events (
    id BIGSERIAL PRIMARY KEY,
    production_run_id INTEGER NOT NULL REFERENCES public.production_runs(id) ON DELETE CASCADE,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_minutes DOUBLE PRECISION NOT NULL CHECK (duration_minutes >= 0),
    reason_code VARCHAR(40) NOT NULL,
    reason_description VARCHAR(180) NOT NULL,
    category VARCHAR(60) NOT NULL,
    is_planned BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_downtime_machine_time
    ON public.machine_downtime_events(machine_id, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_downtime_reason
    ON public.machine_downtime_events(reason_code);

CREATE TABLE IF NOT EXISTS public.oee_results (
    id BIGSERIAL PRIMARY KEY,
    production_run_id INTEGER NOT NULL UNIQUE REFERENCES public.production_runs(id) ON DELETE CASCADE,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    availability DOUBLE PRECISION NOT NULL CHECK (availability BETWEEN 0 AND 100),
    performance DOUBLE PRECISION NOT NULL CHECK (performance BETWEEN 0 AND 100),
    quality DOUBLE PRECISION NOT NULL CHECK (quality BETWEEN 0 AND 100),
    oee DOUBLE PRECISION NOT NULL CHECK (oee BETWEEN 0 AND 100),
    operating_minutes DOUBLE PRECISION NOT NULL CHECK (operating_minutes >= 0),
    downtime_minutes DOUBLE PRECISION NOT NULL CHECK (downtime_minutes >= 0),
    total_units INTEGER NOT NULL CHECK (total_units >= 0),
    good_units INTEGER NOT NULL CHECK (good_units >= 0)
);

CREATE TABLE IF NOT EXISTS public.production_counters (
    id BIGSERIAL PRIMARY KEY,
    production_run_id INTEGER NOT NULL REFERENCES public.production_runs(id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_units INTEGER NOT NULL CHECK (total_units >= 0),
    good_units INTEGER NOT NULL CHECK (good_units >= 0),
    rejected_units INTEGER NOT NULL CHECK (rejected_units >= 0),
    rework_units INTEGER NOT NULL CHECK (rework_units >= 0),
    CHECK (good_units + rejected_units <= total_units)
);

CREATE INDEX IF NOT EXISTS ix_production_counters_run_time
    ON public.production_counters(production_run_id, recorded_at DESC);
