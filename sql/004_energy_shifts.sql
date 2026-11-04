INSERT INTO public.work_shifts(code,name,start_time,end_time,planned_minutes,active)
VALUES
    ('T1','Turno 1','00:00','08:00',480,TRUE),
    ('T2','Turno 2','08:00','16:00',480,TRUE),
    ('T3','Turno 3','16:00','00:00',480,TRUE)
ON CONFLICT(code) DO UPDATE SET
    name=EXCLUDED.name,
    start_time=EXCLUDED.start_time,
    end_time=EXCLUDED.end_time,
    planned_minutes=EXCLUDED.planned_minutes,
    active=TRUE;

ALTER TABLE public.energy_generation_readings
    ADD COLUMN IF NOT EXISTS shift_id INTEGER REFERENCES public.work_shifts(id);

CREATE INDEX IF NOT EXISTS ix_energy_generation_shift_time
    ON public.energy_generation_readings(shift_id, recorded_at DESC);
