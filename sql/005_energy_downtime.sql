CREATE TABLE IF NOT EXISTS public.energy_downtime_events (
    id BIGSERIAL PRIMARY KEY,
    event_key VARCHAR(80) UNIQUE,
    machine_id INTEGER NOT NULL REFERENCES public.machines(id),
    shift_id INTEGER REFERENCES public.work_shifts(id),
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_minutes DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (duration_minutes >= 0),
    category VARCHAR(60) NOT NULL,
    cause VARCHAR(180) NOT NULL,
    planned BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    source VARCHAR(30) NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'simulator')),
    notes VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((status = 'open' AND ended_at IS NULL) OR (status = 'closed' AND ended_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS ix_energy_downtime_machine_time
    ON public.energy_downtime_events(machine_id, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_energy_downtime_status_time
    ON public.energy_downtime_events(status, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_energy_downtime_shift
    ON public.energy_downtime_events(shift_id, started_at DESC);

INSERT INTO public.energy_downtime_events
    (event_key,machine_id,shift_id,started_at,ended_at,duration_minutes,category,cause,planned,status,source,notes)
SELECT seed.event_key,m.id,s.id,CURRENT_TIMESTAMP-seed.start_ago,
       CURRENT_TIMESTAMP-seed.end_ago,seed.duration,seed.category,seed.cause,
       seed.planned,'closed','simulator','Evento inicial simulado para análisis de paradas.'
FROM (VALUES
    ('SIM-INIT-CAL02','CAL-02','T1',INTERVAL '22 hours',INTERVAL '21 hours 18 minutes',42.0,'Proceso térmico','Sobretemperatura de tubos y ajuste de combustión',FALSE),
    ('SIM-INIT-TUR01','TUR-01','T2',INTERVAL '18 hours',INTERVAL '17 hours 32 minutes',28.0,'Condición mecánica','Vibración radial por encima del patrón esperado',FALSE),
    ('SIM-INIT-BBA01','BBA-01','T3',INTERVAL '12 hours',INTERVAL '11 hours 25 minutes',35.0,'Sistema hidráulico','Margen NPSH bajo e indicios de cavitación',FALSE),
    ('SIM-INIT-VEN01','VEN-01','T1',INTERVAL '7 hours',INTERVAL '6 hours 40 minutes',20.0,'Gases de combustión','Inspección de rodete por desbalance y depósitos',TRUE),
    ('SIM-INIT-GEN01','GEN-01','T2',INTERVAL '3 hours',INTERVAL '2 hours 45 minutes',15.0,'Sistema eléctrico','Verificación de temperatura y desbalance de fases',TRUE)
) AS seed(event_key,machine_code,shift_code,start_ago,end_ago,duration,category,cause,planned)
JOIN public.machines m ON m.code=seed.machine_code
JOIN public.work_shifts s ON s.code=seed.shift_code
ON CONFLICT(event_key) DO NOTHING;
