from pathlib import Path

from app import get_db
from telemetry_config import MACHINES, USAGE_HOURS_BY_MACHINE, VARIABLES


def setup():
    with get_db() as db:
        migration_dir = Path(__file__).with_name("sql")
        for migration_path in sorted(migration_dir.glob("*.sql")):
            db.execute(migration_path.read_text(encoding="utf-8"))
            print(f"Migración aplicada: {migration_path.name}")
        for code, name, family, area, power in MACHINES:
            machine = db.execute(
                """INSERT INTO public.machines
                (code,name,machine_type,area,max_usage_hours,max_vibration,max_temperature,rated_current,nominal_rpm,max_pressure)
                VALUES(%s,%s,%s,%s,50000,12,600,%s,%s,%s)
                ON CONFLICT(code) DO UPDATE SET name=EXCLUDED.name,machine_type=EXCLUDED.machine_type,area=EXCLUDED.area,active=TRUE
                RETURNING id""",
                (code, name, family, area, max(power, 1) * 1.2, 1500 if family in {"turbine", "fan"} else 3600 if family in {"generator", "pump"} else 0, 180 if family != "condenser" else 15),
            ).fetchone()
            for spec in VARIABLES[family]:
                spec = list(spec)
                if spec[0] == "usage_hours":
                    spec[4] = USAGE_HOURS_BY_MACHINE[code]
                db.execute(
                    """INSERT INTO public.machine_variables
                    (machine_id,code,name,unit,category,nominal_value,simulation_sigma,lower_warning,lower_critical,upper_warning,upper_critical)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(machine_id,code) DO UPDATE SET name=EXCLUDED.name,unit=EXCLUDED.unit,category=EXCLUDED.category,
                    nominal_value=EXCLUDED.nominal_value,simulation_sigma=EXCLUDED.simulation_sigma,
                    lower_warning=EXCLUDED.lower_warning,lower_critical=EXCLUDED.lower_critical,
                    upper_warning=EXCLUDED.upper_warning,upper_critical=EXCLUDED.upper_critical,enabled=TRUE""",
                    (machine["id"], *spec),
                )
    print("Esquema predictivo y catálogo de variables configurados.")


if __name__ == "__main__":
    setup()
