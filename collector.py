import argparse
from datetime import datetime, timezone
import math
import os
import random
import time

from app import get_db
from telemetry_config import FAILURE_MODES


FAULT_BIAS = {
    ("BBA-01", "vibration"): 3.3,
    ("BBA-01", "bearing_temp"): 17.0,
    ("TUR-01", "vibration_radial"): 3.2,
    ("TUR-01", "bearing_temp"): 16.0,
    ("VEN-01", "vibration_radial"): 2.2,
    ("VEN-01", "bearing_temp"): 16.0,
    ("CAL-02", "tube_metal_temp"): 35.0,
    ("CAL-02", "flue_co"): 85.0,
}


def threshold_score(value, row):
    scores = []
    if row["lower_warning"] is not None and value < row["lower_warning"]:
        critical = row["lower_critical"] if row["lower_critical"] is not None else row["lower_warning"]
        span = max(abs(row["lower_warning"] - critical), 1e-9)
        scores.append(min(1.0, 0.55 + 0.45 * (row["lower_warning"] - value) / span))
    if row["upper_warning"] is not None and value > row["upper_warning"]:
        critical = row["upper_critical"] if row["upper_critical"] is not None else row["upper_warning"]
        span = max(abs(critical - row["upper_warning"]), 1e-9)
        scores.append(min(1.0, 0.55 + 0.45 * (value - row["upper_warning"]) / span))
    return max(scores, default=0.0)


def collect_once():
    timestamp = datetime.now(timezone.utc).replace(microsecond=0)
    rng = random.Random(int(timestamp.timestamp()))
    with get_db() as db:
        run_id = db.execute("INSERT INTO public.telemetry_collection_runs DEFAULT VALUES RETURNING id").fetchone()["id"]
        db.commit()
        try:
            machines = db.execute("SELECT id,code FROM public.machines WHERE active ORDER BY id").fetchall()
            total = 0
            for machine in machines:
                variables = db.execute("SELECT * FROM public.machine_variables WHERE machine_id=%s AND enabled ORDER BY id", (machine["id"],)).fetchall()
                risk_components = []
                top_variable = None
                top_score = 0.0
                for variable in variables:
                    drift = FAULT_BIAS.get((machine["code"], variable["code"]), 0.0)
                    if variable["code"] == "usage_hours":
                        previous = db.execute(
                            "SELECT value,recorded_at FROM public.telemetry_readings WHERE variable_id=%s ORDER BY recorded_at DESC LIMIT 1",
                            (variable["id"],),
                        ).fetchone()
                        if previous:
                            elapsed_hours = max(0, (timestamp - previous["recorded_at"]).total_seconds() / 3600)
                            value = previous["value"] + elapsed_hours
                        else:
                            value = variable["nominal_value"]
                    else:
                        value = variable["nominal_value"] + rng.gauss(0, variable["simulation_sigma"]) + drift
                    score = threshold_score(value, variable)
                    if score > top_score:
                        top_score, top_variable = score, variable
                    risk_components.append(score)
                    db.execute(
                        """INSERT INTO public.telemetry_readings(variable_id,recorded_at,value,quality,is_anomaly,source)
                        VALUES(%s,%s,%s,'good',%s,'simulator') ON CONFLICT(variable_id,recorded_at) DO NOTHING""",
                        (variable["id"], timestamp, round(value, 4), score > 0),
                    )
                    total += 1
                risk = round(100 * (1 - math.prod(1 - min(.35, score * .35) for score in risk_components)), 1)
                status = "critical" if risk >= 65 else "warning" if risk >= 32 else "healthy"
                mode = FAILURE_MODES.get(top_variable["code"] if top_variable else "", "Sin modo de falla dominante")
                explanation = f"Mayor contribución: {top_variable['name']}" if top_variable else "Variables dentro de la línea base"
                db.execute(
                    """INSERT INTO public.machine_health_snapshots
                    (machine_id,recorded_at,risk_score,health_status,predicted_failure_mode,remaining_useful_life_days,explanation)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(machine_id,recorded_at) DO NOTHING""",
                    (machine["id"], timestamp, risk, status, mode, max(2, round((100-risk)*1.8)), explanation),
                )
            db.execute(
                """UPDATE public.telemetry_collection_runs SET finished_at=CURRENT_TIMESTAMP,status='completed',
                readings_inserted=%s,machines_processed=%s WHERE id=%s""",
                (total, len(machines), run_id),
            )
            print(f"{timestamp.isoformat()} | máquinas={len(machines)} | lecturas={total}")
        except Exception as error:
            db.rollback()
            db.execute("UPDATE public.telemetry_collection_runs SET finished_at=CURRENT_TIMESTAMP,status='failed',error_message=%s WHERE id=%s", (str(error)[:600], run_id))
            db.commit()
            raise


def main():
    parser = argparse.ArgumentParser(description="Collector simulado de telemetría térmica")
    configured_interval = int(os.environ.get("COLLECTOR_INTERVAL_SECONDS", "60"))
    parser.add_argument("--interval", type=int, default=configured_interval, help="Segundos entre ciclos; reemplaza COLLECTOR_INTERVAL_SECONDS")
    parser.add_argument("--once", action="store_true", help="Ejecutar un solo ciclo")
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("El intervalo debe ser mayor o igual a 1 segundo")
    while True:
        collect_once()
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
