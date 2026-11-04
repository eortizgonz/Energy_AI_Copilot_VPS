import argparse
from datetime import datetime, timezone
import os
import random
import time

from app import get_db
from telemetry_config import MACHINES


POWER_BY_CODE = {code: max(float(power), 5.0) for code, _name, _family, _area, power in MACHINES}
BASE_EFFICIENCY = {
    "boiler": 0.89,
    "turbine": 0.43,
    "generator": 0.97,
    "pump": 0.82,
    "fan": 0.80,
    "condenser": 0.86,
}
AUXILIARY_SHARE = {
    "boiler": 0.055,
    "turbine": 0.025,
    "generator": 0.018,
    "pump": 0.065,
    "fan": 0.070,
    "condenser": 0.045,
}


def collect_once(interval_seconds):
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    rng = random.Random(int(timestamp.timestamp()) + 701)
    planned_minutes = interval_seconds / 60
    with get_db() as db:
        run_id = db.execute("INSERT INTO public.energy_collection_runs DEFAULT VALUES RETURNING id").fetchone()["id"]
        db.commit()
        try:
            machines = db.execute(
                """SELECT m.id,m.code,m.machine_type,COALESCE(h.risk_score,0) risk_score
                FROM public.machines m
                LEFT JOIN LATERAL (
                    SELECT risk_score FROM public.machine_health_snapshots
                    WHERE machine_id=m.id ORDER BY recorded_at DESC LIMIT 1
                ) h ON TRUE
                WHERE m.active ORDER BY m.id"""
            ).fetchall()
            inserted = 0
            for machine in machines:
                risk = float(machine["risk_score"])
                family = machine["machine_type"]
                rated_power = POWER_BY_CODE.get(machine["code"], 5.0)
                availability = max(70.0, min(99.8, 99.2 - risk * 0.12 + rng.gauss(0, 0.35)))
                operating_minutes = planned_minutes * availability / 100
                downtime_minutes = max(0.0, planned_minutes - operating_minutes)
                performance = max(55.0, min(99.5, 95.0 - risk * 0.18 + rng.gauss(0, 1.0)))
                conformity = max(75.0, min(99.9, 99.1 - risk * 0.07 + rng.gauss(0, 0.25)))
                thermal_efficiency = max(20.0, min(99.0, 100 * BASE_EFFICIENCY.get(family, 0.85) - risk * 0.05 + rng.gauss(0, 0.4)))
                gross = rated_power * operating_minutes / 60 * performance / 100
                auxiliary = gross * AUXILIARY_SHARE.get(family, 0.05)
                net = max(0.0, gross - auxiliary)
                compliant = net * conformity / 100
                fuel_input = gross / max(thermal_efficiency / 100, 0.01)
                heat_rate = 3.6 / max(thermal_efficiency / 100, 0.01)
                operational = availability * performance * conformity / 10000
                result = db.execute(
                    """INSERT INTO public.energy_generation_readings
                    (machine_id,recorded_at,interval_seconds,rated_power_mw,planned_minutes,
                    operating_minutes,downtime_minutes,gross_generation_mwh,auxiliary_consumption_mwh,
                    net_generation_mwh,compliant_generation_mwh,fuel_energy_input_mwh,heat_rate_mj_kwh,
                    thermal_efficiency,availability,performance,conformity,operational_efficiency,source)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'simulator')
                    ON CONFLICT(machine_id,recorded_at) DO NOTHING RETURNING id""",
                    (machine["id"], timestamp, interval_seconds, rated_power, planned_minutes,
                     operating_minutes, downtime_minutes, gross, auxiliary, net, compliant, fuel_input,
                     heat_rate, thermal_efficiency, availability, performance, conformity, operational),
                ).fetchone()
                inserted += int(result is not None)
            db.execute(
                """UPDATE public.energy_collection_runs SET finished_at=CURRENT_TIMESTAMP,status='completed',
                readings_inserted=%s,machines_processed=%s WHERE id=%s""",
                (inserted, len(machines), run_id),
            )
            print(f"{timestamp.isoformat()} | máquinas={len(machines)} | lecturas energéticas={inserted}")
        except Exception as error:
            db.rollback()
            db.execute(
                """UPDATE public.energy_collection_runs SET finished_at=CURRENT_TIMESTAMP,status='failed',
                error_message=%s WHERE id=%s""",
                (str(error)[:600], run_id),
            )
            db.commit()
            raise


def main():
    parser = argparse.ArgumentParser(description="Collector simulado de eficiencia energética")
    configured_interval = int(os.environ.get("ENERGY_COLLECTOR_INTERVAL_SECONDS", "60"))
    parser.add_argument("--interval", type=int, default=configured_interval)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("El intervalo debe ser mayor o igual a 1 segundo")
    while True:
        collect_once(args.interval)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
