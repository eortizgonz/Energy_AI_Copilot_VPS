from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import os
import re
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from mailer import send_password_reset
from energy_machine_manuals import diagnostic_for
from rag_service import ALLOWED_DOCUMENT_EXTENSIONS, answer_copilot, answer_rag, delete_document, ingest_document, list_documents


def load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-this-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


def get_db():
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        dbname=os.environ.get("PGDATABASE", "energy_ia"),
        row_factory=dict_row,
    )


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view

MACHINES = [
    {"id": "CAL-01", "name": "Caldera principal 1", "area": "Generación de vapor", "type": "Caldera acuotubular", "power": 125, "hours": 18420, "base": [4.1, 487, 141, 91.8, 7.4]},
    {"id": "CAL-02", "name": "Caldera principal 2", "area": "Generación de vapor", "type": "Caldera acuotubular", "power": 125, "hours": 17680, "base": [5.8, 512, 145, 88.6, 9.8]},
    {"id": "TUR-01", "name": "Turbina de vapor 1", "area": "Casa de máquinas", "type": "Turbogenerador", "power": 95, "hours": 22150, "base": [7.6, 468, 118, 84.2, 13.8]},
    {"id": "TUR-02", "name": "Turbina de vapor 2", "area": "Casa de máquinas", "type": "Turbogenerador", "power": 95, "hours": 19840, "base": [4.7, 452, 116, 89.4, 8.4]},
    {"id": "GEN-01", "name": "Generador síncrono 1", "area": "Generación eléctrica", "type": "Generador", "power": 110, "hours": 21420, "base": [6.4, 86, 108, 90.1, 10.6]},
    {"id": "GEN-02", "name": "Generador síncrono 2", "area": "Generación eléctrica", "type": "Generador", "power": 110, "hours": 18760, "base": [3.8, 79, 105, 93.2, 6.1]},
    {"id": "BBA-01", "name": "Bomba de alimentación 1", "area": "Agua de alimentación", "type": "Bomba centrífuga", "power": 8, "hours": 24310, "base": [8.5, 92, 152, 78.8, 18.4]},
    {"id": "BBA-02", "name": "Bomba de alimentación 2", "area": "Agua de alimentación", "type": "Bomba centrífuga", "power": 8, "hours": 16990, "base": [4.3, 78, 148, 92.6, 7.2]},
    {"id": "VEN-01", "name": "Ventilador de tiro inducido", "area": "Gases de combustión", "type": "Ventilador industrial", "power": 5, "hours": 20970, "base": [6.9, 104, 2.1, 82.7, 15.2]},
    {"id": "CON-01", "name": "Condensador principal", "area": "Ciclo térmico", "type": "Condensador de superficie", "power": 0, "hours": 22680, "base": [2.1, 43, -0.88, 86.5, 11.9]},
]

SIGNAL_MAP = {
    "boiler": ("acoustic_leak", "tube_metal_temp", "drum_pressure", "boiler_efficiency"),
    "turbine": ("vibration_radial", "bearing_temp", "steam_inlet_pressure", "turbine_efficiency"),
    "generator": ("vibration", "stator_winding_temp", "phase_current", "power_factor"),
    "pump": ("vibration", "bearing_temp", "discharge_pressure", "hydraulic_efficiency"),
    "fan": ("vibration_radial", "bearing_temp", "furnace_draft", "fan_efficiency"),
    "condenser": ("air_ingress", "cooling_water_out_temp", "vacuum", "terminal_temp_difference"),
}


def variable_contribution(variable):
    value = variable["value"]
    score = 0.0
    if variable["lower_warning"] is not None and value < variable["lower_warning"]:
        critical = variable["lower_critical"] or variable["lower_warning"]
        score = max(score, min(1, .55 + .45 * (variable["lower_warning"] - value) / max(abs(variable["lower_warning"] - critical), 1e-9)))
    if variable["upper_warning"] is not None and value > variable["upper_warning"]:
        critical = variable["upper_critical"] or variable["upper_warning"]
        score = max(score, min(1, .55 + .45 * (value - variable["upper_warning"]) / max(abs(critical - variable["upper_warning"]), 1e-9)))
    z_score = abs(value - variable["nominal_value"]) / max(variable["simulation_sigma"], 1e-9)
    return round(min(30, score * 24 + min(6, z_score * 1.5)), 1)


def dashboard_payload():
    power_by_code = {machine["id"]: machine["power"] for machine in MACHINES}
    with get_db() as db:
        rows = db.execute("""SELECT m.id machine_pk,m.code,m.name,m.machine_type,m.area,
            v.code variable_code,v.name variable_name,v.unit,v.nominal_value,v.simulation_sigma,
            v.lower_warning,v.lower_critical,v.upper_warning,v.upper_critical,r.value,r.recorded_at
            FROM public.machines m
            JOIN public.machine_variables v ON v.machine_id=m.id AND v.enabled
            JOIN LATERAL (SELECT value,recorded_at FROM public.telemetry_readings
                WHERE variable_id=v.id ORDER BY recorded_at DESC LIMIT 1) r ON TRUE
            WHERE m.active ORDER BY m.id,v.id""").fetchall()
        snapshots = db.execute("""SELECT DISTINCT ON(machine_id) machine_id,recorded_at,risk_score,
            health_status,predicted_failure_mode,remaining_useful_life_days,explanation
            FROM public.machine_health_snapshots ORDER BY machine_id,recorded_at DESC""").fetchall()

    snapshot_by_machine = {row["machine_id"]: row for row in snapshots}
    grouped = {}
    for row in rows:
        grouped.setdefault(row["machine_pk"], {"meta": row, "variables": {}})["variables"][row["variable_code"]] = row

    machines = []
    latest_time = None
    signal_keys = ("condition", "temperature", "process", "performance")
    for machine_pk, group in grouped.items():
        meta, variables = group["meta"], group["variables"]
        snapshot = snapshot_by_machine.get(machine_pk)
        if not snapshot:
            continue
        selected_codes = SIGNAL_MAP.get(meta["machine_type"], SIGNAL_MAP["pump"])
        signals = {}
        for key, code in zip(signal_keys, selected_codes):
            variable = variables.get(code)
            signals[key] = {"label": variable["variable_name"], "value": round(variable["value"], 2), "unit": variable["unit"]} if variable else {"label": key.title(), "value": None, "unit": ""}
        factors = sorted(
            ({"name": variable["variable_name"], "impact": variable_contribution(variable)} for variable in variables.values()),
            key=lambda factor: factor["impact"], reverse=True,
        )[:5]
        diagnosis = f"{snapshot['predicted_failure_mode']}. {snapshot['explanation']}."
        machines.append({
            "id": meta["code"], "name": meta["name"], "area": meta["area"], "type": meta["machine_type"],
            "power": power_by_code.get(meta["code"], 0), "hours": round(variables.get("usage_hours", {}).get("value", 0), 1),
            "risk": round(snapshot["risk_score"], 1), "status": snapshot["health_status"],
            "rul_days": snapshot["remaining_useful_life_days"], "signals": signals, "factors": factors,
            "diagnosis": diagnosis,
            "recommendation": "Validar las señales con instrumentación de campo y ejecutar análisis de causa raíz antes de intervenir.",
        })
        latest_time = max(latest_time, snapshot["recorded_at"]) if latest_time else snapshot["recorded_at"]

    if not machines:
        raise RuntimeError("No hay telemetría disponible. Ejecuta collector.py --once.")
    priority = max(machines, key=lambda machine: machine["risk"])
    active_power = [group["variables"]["active_power"]["value"] for group in grouped.values() if "active_power" in group["variables"]]
    summary = {
        "healthy": sum(machine["status"] == "healthy" for machine in machines),
        "warning": sum(machine["status"] == "warning" for machine in machines),
        "critical": sum(machine["status"] == "critical" for machine in machines),
        "average_risk": round(sum(machine["risk"] for machine in machines) / len(machines), 1),
        "generation": round(sum(active_power), 1),
        "availability": round(100 * sum(machine["status"] != "critical" for machine in machines) / len(machines), 1),
    }
    return {
        "updated_at": latest_time.isoformat(timespec="seconds"),
        "collector_interval_seconds": int(os.environ.get("COLLECTOR_INTERVAL_SECONDS", "60")),
        "summary": summary, "priority": priority, "machines": machines,
    }


def energy_efficiency_payload():
    with get_db() as db:
        rows = db.execute(
            """SELECT DISTINCT ON (r.machine_id)
                m.code,m.name,m.area,m.machine_type,r.recorded_at,r.rated_power_mw,
                r.availability,r.performance,r.conformity,r.operational_efficiency,
                r.thermal_efficiency,r.heat_rate_mj_kwh,r.net_generation_mwh
            FROM public.energy_generation_readings r
            JOIN public.machines m ON m.id=r.machine_id
            WHERE m.active
            ORDER BY r.machine_id,r.recorded_at DESC"""
        ).fetchall()
    if not rows:
        raise RuntimeError("No hay lecturas energéticas disponibles. Ejecuta energy_collector.py --once.")
    machines = [{
        "id": row["code"], "name": row["name"], "area": row["area"], "type": row["machine_type"],
        "rated_power_mw": round(row["rated_power_mw"], 2),
        "availability": round(row["availability"], 2),
        "performance": round(row["performance"], 2),
        "conformity": round(row["conformity"], 2),
        "operational_efficiency": round(row["operational_efficiency"], 2),
        "thermal_efficiency": round(row["thermal_efficiency"], 2),
        "heat_rate_mj_kwh": round(row["heat_rate_mj_kwh"], 3),
        "net_generation_mwh": round(row["net_generation_mwh"], 4),
    } for row in rows]
    count = len(rows)
    avg = lambda field: round(sum(float(row[field]) for row in rows) / count, 2)
    availability = avg("availability")
    performance = avg("performance")
    conformity = avg("conformity")
    losses = {
        "downtime_minutes_7d": round(sum((100 - float(row["availability"])) / 100 * 7 * 24 * 60 for row in rows)),
        "generation_gap_mwh_7d": round(sum(float(row["rated_power_mw"]) * (100 - float(row["performance"])) / 100 * 7 * 24 for row in rows), 1),
        "degradation_loss_mwh_7d": round(sum(float(row["rated_power_mw"]) * (100 - float(row["conformity"])) / 100 * 7 * 24 for row in rows), 1),
    }
    return {
        "updated_at": max(row["recorded_at"] for row in rows).isoformat(timespec="seconds"),
        "collector_interval_seconds": int(os.environ.get("ENERGY_COLLECTOR_INTERVAL_SECONDS", "60")),
        "summary": {
            "operational_efficiency": avg("operational_efficiency"),
            "availability": availability,
            "performance": performance,
            "conformity": conformity,
            "thermal_efficiency": avg("thermal_efficiency"),
        },
        "losses": losses,
        "machines": machines,
    }


def shift_dashboard_payload():
    app_timezone = ZoneInfo(os.environ.get("APP_TIMEZONE", "America/Bogota"))
    local_now = datetime.now(timezone.utc).astimezone(app_timezone)
    current_time = local_now.time().replace(tzinfo=None)
    with get_db() as db:
        shifts = db.execute(
            "SELECT id,code,name,start_time,end_time,planned_minutes FROM public.work_shifts WHERE active ORDER BY start_time"
        ).fetchall()
        metrics = db.execute(
            """SELECT shift_id,COUNT(*) readings,COUNT(DISTINCT machine_id) machines,
                AVG(availability) availability,AVG(performance) performance,AVG(conformity) conformity,
                AVG(operational_efficiency) operational_efficiency,AVG(thermal_efficiency) thermal_efficiency,
                SUM(net_generation_mwh) net_generation_mwh,SUM(downtime_minutes) downtime_minutes,
                MAX(recorded_at) updated_at
            FROM public.energy_generation_readings
            WHERE shift_id IS NOT NULL AND recorded_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
            GROUP BY shift_id"""
        ).fetchall()
    metrics_by_shift = {row["shift_id"]: row for row in metrics}
    active_id = None
    result = []
    for shift in shifts:
        start, end = shift["start_time"], shift["end_time"]
        active = (start < end and start <= current_time < end) or (start > end and (current_time >= start or current_time < end))
        if active:
            active_id = shift["id"]
        row = metrics_by_shift.get(shift["id"])
        result.append({
            "id": shift["id"], "code": shift["code"], "name": shift["name"],
            "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M"),
            "planned_minutes": shift["planned_minutes"], "active": active,
            "readings": row["readings"] if row else 0,
            "machines": row["machines"] if row else 0,
            "availability": round(row["availability"], 1) if row else None,
            "performance": round(row["performance"], 1) if row else None,
            "conformity": round(row["conformity"], 1) if row else None,
            "operational_efficiency": round(row["operational_efficiency"], 1) if row else None,
            "thermal_efficiency": round(row["thermal_efficiency"], 1) if row else None,
            "net_generation_mwh": round(row["net_generation_mwh"], 2) if row else 0,
            "downtime_minutes": round(row["downtime_minutes"], 1) if row else 0,
            "updated_at": row["updated_at"].isoformat(timespec="seconds") if row else None,
        })
    active_shift = next((shift for shift in result if shift["id"] == active_id), None)
    return {
        "generated_at": local_now.isoformat(timespec="seconds"),
        "timezone": str(app_timezone),
        "active_shift": active_shift,
        "shifts": result,
    }


def shift_minutes(value):
    return value.hour * 60 + value.minute


def shift_duration(start, end):
    duration = (shift_minutes(end) - shift_minutes(start)) % 1440
    return duration or 1440


def shift_segments(start, end):
    start_minute, duration = shift_minutes(start), shift_duration(start, end)
    if duration == 1440:
        return [(0, 1440)]
    finish = start_minute + duration
    return [(start_minute, finish)] if finish <= 1440 else [(start_minute, 1440), (0, finish - 1440)]


def parse_shift_body(body):
    code = str(body.get("code", "")).strip().upper()
    name = str(body.get("name", "")).strip()
    if not re.fullmatch(r"[A-Z0-9_-]{1,20}", code):
        raise ValueError("El código debe tener entre 1 y 20 caracteres: letras, números, guion o guion bajo.")
    if not name or len(name) > 60:
        raise ValueError("El nombre es obligatorio y admite máximo 60 caracteres.")
    try:
        start = datetime.strptime(str(body.get("start_time", "")), "%H:%M").time()
        end = datetime.strptime(str(body.get("end_time", "")), "%H:%M").time()
    except ValueError as error:
        raise ValueError("Los horarios deben tener el formato HH:MM.") from error
    return code, name, start, end, bool(body.get("active", True)), shift_duration(start, end)


def validate_shift_overlap(db, start, end, exclude_id=None):
    if exclude_id is None:
        rows = db.execute("SELECT id,code,start_time,end_time FROM public.work_shifts WHERE active").fetchall()
    else:
        rows = db.execute(
            "SELECT id,code,start_time,end_time FROM public.work_shifts WHERE active AND id<>%s",
            (exclude_id,),
        ).fetchall()
    candidate = shift_segments(start, end)
    for row in rows:
        if any(max(a, c) < min(b, d) for a, b in candidate for c, d in shift_segments(row["start_time"], row["end_time"])):
            raise ValueError(f"El horario se solapa con el turno {row['code']}.")


def machine_detail_payload(machine_code):
    with get_db() as db:
        machine = db.execute(
            "SELECT id,code,name,machine_type,area FROM public.machines WHERE upper(code)=upper(%s) AND active",
            (machine_code,),
        ).fetchone()
        if not machine:
            return None
        variables = db.execute(
            """SELECT v.code,v.name,v.unit,v.category,v.nominal_value,v.simulation_sigma,
                v.lower_warning,v.lower_critical,v.upper_warning,v.upper_critical,
                r.value,r.recorded_at,r.quality,r.is_anomaly
            FROM public.machine_variables v
            LEFT JOIN LATERAL (
                SELECT value,recorded_at,quality,is_anomaly FROM public.telemetry_readings
                WHERE variable_id=v.id ORDER BY recorded_at DESC LIMIT 1
            ) r ON TRUE
            WHERE v.machine_id=%s AND v.enabled ORDER BY v.category,v.name""",
            (machine["id"],),
        ).fetchall()
        snapshot = db.execute(
            """SELECT recorded_at,risk_score,health_status,predicted_failure_mode,
                remaining_useful_life_days,explanation
            FROM public.machine_health_snapshots WHERE machine_id=%s
            ORDER BY recorded_at DESC LIMIT 1""",
            (machine["id"],),
        ).fetchone()
        energy = db.execute(
            """SELECT e.recorded_at,e.net_generation_mwh,e.thermal_efficiency,e.availability,
                e.performance,e.conformity,e.operational_efficiency,s.code shift_code,s.name shift_name
            FROM public.energy_generation_readings e
            LEFT JOIN public.work_shifts s ON s.id=e.shift_id
            WHERE e.machine_id=%s ORDER BY e.recorded_at DESC LIMIT 1""",
            (machine["id"],),
        ).fetchone()

    telemetry = []
    for row in variables:
        value = row["value"]
        status = "normal"
        if value is not None:
            if ((row["lower_critical"] is not None and value <= row["lower_critical"]) or
                    (row["upper_critical"] is not None and value >= row["upper_critical"])):
                status = "critical"
            elif ((row["lower_warning"] is not None and value <= row["lower_warning"]) or
                  (row["upper_warning"] is not None and value >= row["upper_warning"])):
                status = "warning"
        nominal = float(row["nominal_value"])
        deviation = abs(float(value) - nominal) / max(abs(nominal), 1e-9) * 100 if value is not None else None
        telemetry.append({
            "code": row["code"], "name": row["name"], "unit": row["unit"], "category": row["category"],
            "value": round(value, 3) if value is not None else None, "nominal": round(nominal, 3),
            "deviation_percent": round(deviation, 1) if deviation is not None else None,
            "status": status, "quality": row["quality"], "is_anomaly": row["is_anomaly"],
            "recorded_at": row["recorded_at"].isoformat(timespec="seconds") if row["recorded_at"] else None,
            "lower_warning": row["lower_warning"], "lower_critical": row["lower_critical"],
            "upper_warning": row["upper_warning"], "upper_critical": row["upper_critical"],
            "contribution": variable_contribution(row) if value is not None else 0,
        })
    factors = sorted(telemetry, key=lambda item: item["contribution"], reverse=True)[:5]
    risk = round(snapshot["risk_score"], 1) if snapshot else 0
    manual = diagnostic_for(machine, telemetry, risk)
    return {
        "id": machine["code"], "name": machine["name"], "type": machine["machine_type"], "area": machine["area"],
        "power_mw": next((item["power"] for item in MACHINES if item["id"] == machine["code"]), 0),
        "risk": risk,
        "status": snapshot["health_status"] if snapshot else "healthy",
        "failure_mode": snapshot["predicted_failure_mode"] if snapshot else "Sin diagnóstico disponible",
        "rul_days": snapshot["remaining_useful_life_days"] if snapshot else None,
        "explanation": snapshot["explanation"] if snapshot else "Sin lectura predictiva disponible",
        "snapshot_at": snapshot["recorded_at"].isoformat(timespec="seconds") if snapshot else None,
        "factors": factors, "telemetry": telemetry, "manual": manual,
        "energy": ({
            "recorded_at": energy["recorded_at"].isoformat(timespec="seconds"),
            "net_generation_mwh": round(energy["net_generation_mwh"], 3),
            "thermal_efficiency": round(energy["thermal_efficiency"], 1),
            "availability": round(energy["availability"], 1), "performance": round(energy["performance"], 1),
            "conformity": round(energy["conformity"], 1),
            "operational_efficiency": round(energy["operational_efficiency"], 1),
            "shift": f"{energy['shift_code']} · {energy['shift_name']}" if energy["shift_code"] else "Sin turno",
        } if energy else None),
    }


def downtime_dashboard_payload():
    local_today = datetime.now(ZoneInfo(os.environ.get("APP_TIMEZONE", "America/Bogota"))).date()
    date_from = request.args.get("date_from") or (local_today - timedelta(days=30)).isoformat()
    date_to = request.args.get("date_to") or local_today.isoformat()
    try:
        start_date = datetime.strptime(date_from, "%Y-%m-%d").date()
        end_date = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Las fechas deben usar el formato AAAA-MM-DD.") from error
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ValueError("El rango de fechas no es válido o supera 366 días.")
    conditions = ["e.started_at >= %s::date", "e.started_at < (%s::date + INTERVAL '1 day')"]
    parameters = [date_from, date_to]
    for argument, column in (("machine", "m.code"), ("category", "e.category"), ("status", "e.status")):
        value = request.args.get(argument, "").strip()
        if value:
            conditions.append(f"{column}=%s")
            parameters.append(value)
    where = " AND ".join(conditions)
    with get_db() as db:
        events = db.execute(
            f"""SELECT e.id,e.started_at,e.ended_at,
                CASE WHEN e.status='open' THEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-e.started_at))/60 ELSE e.duration_minutes END duration_minutes,
                e.category,e.cause,e.planned,e.status,e.source,e.notes,
                m.code machine_code,m.name machine_name,m.area,s.code shift_code,s.name shift_name
            FROM public.energy_downtime_events e
            JOIN public.machines m ON m.id=e.machine_id
            LEFT JOIN public.work_shifts s ON s.id=e.shift_id
            WHERE {where} ORDER BY e.started_at DESC""",
            parameters,
        ).fetchall()
        machines = db.execute("SELECT code,name FROM public.machines WHERE active ORDER BY code").fetchall()
        categories = db.execute("SELECT DISTINCT category FROM public.energy_downtime_events ORDER BY category").fetchall()
    result = [{
        **{key: row[key] for key in ("id", "category", "cause", "planned", "status", "source", "notes", "machine_code", "machine_name", "area", "shift_code", "shift_name")},
        "started_at": row["started_at"].isoformat(timespec="seconds"),
        "ended_at": row["ended_at"].isoformat(timespec="seconds") if row["ended_at"] else None,
        "duration_minutes": round(float(row["duration_minutes"]), 1),
    } for row in events]
    total = round(sum(item["duration_minutes"] for item in result), 1)
    by_category = {}
    for item in result:
        current = by_category.setdefault(item["category"], {"category": item["category"], "events": 0, "minutes": 0.0})
        current["events"] += 1
        current["minutes"] += item["duration_minutes"]
    categories_result = sorted(by_category.values(), key=lambda item: item["minutes"], reverse=True)
    for item in categories_result:
        item["minutes"] = round(item["minutes"], 1)
    machine_totals = {}
    for item in result:
        machine_totals[item["machine_code"]] = machine_totals.get(item["machine_code"], 0) + item["duration_minutes"]
    top_machine = max(machine_totals, key=machine_totals.get) if machine_totals else "—"
    return {
        "filters": {"date_from": date_from, "date_to": date_to},
        "summary": {"total_minutes": total, "events": len(result), "average_minutes": round(total / len(result), 1) if result else 0, "open_events": sum(item["status"] == "open" for item in result), "top_machine": top_machine},
        "events": result, "by_category": categories_result,
        "options": {"machines": machines, "categories": [row["category"] for row in categories]},
    }


def copilot_operational_context(question):
    predictive = dashboard_payload()
    efficiency = energy_efficiency_payload()
    shifts = shift_dashboard_payload()
    downtime = downtime_dashboard_payload()
    normalized = question.casefold()
    selected_machines = [machine for machine in predictive["machines"] if machine["id"].casefold() in normalized or machine["name"].casefold() in normalized]
    selected_machines = selected_machines or sorted(predictive["machines"], key=lambda machine: machine["risk"], reverse=True)[:5]
    efficiency_by_machine = {machine["id"]: machine for machine in efficiency["machines"]}
    lines = [
        "[PostgreSQL · análisis predictivo] "
        f"Lectura {predictive['updated_at']}; {len(predictive['machines'])} activos; "
        f"saludables {predictive['summary']['healthy']}, alertas {predictive['summary']['warning']}, "
        f"críticos {predictive['summary']['critical']}, riesgo promedio {predictive['summary']['average_risk']}%, "
        f"generación estimada {predictive['summary']['generation']} MW.",
        "[PostgreSQL · KPI de eficiencia] "
        f"Lectura {efficiency['updated_at']}; índice operacional {efficiency['summary']['operational_efficiency']}%, "
        f"disponibilidad {efficiency['summary']['availability']}%, rendimiento {efficiency['summary']['performance']}%, "
        f"conformidad {efficiency['summary']['conformity']}%, eficiencia térmica {efficiency['summary']['thermal_efficiency']}%. "
        f"Pérdidas estimadas 7 días: {efficiency['losses']['downtime_minutes_7d']} min de indisponibilidad, "
        f"brecha de generación {efficiency['losses']['generation_gap_mwh_7d']} MWh y degradación {efficiency['losses']['degradation_loss_mwh_7d']} MWh.",
    ]
    for machine in selected_machines:
        energy = efficiency_by_machine.get(machine["id"])
        signals = "; ".join(f"{item['label']} {item['value']} {item['unit']}" for item in machine["signals"].values())
        factors = "; ".join(f"{item['name']} {item['impact']} puntos" for item in machine["factors"][:3])
        line = (f"[PostgreSQL · activo {machine['id']}] {machine['name']} ({machine['area']}): riesgo {machine['risk']}%, "
                f"estado {machine['status']}, uso {machine['hours']} h, vida útil estimada {machine['rul_days']} días; "
                f"señales: {signals}; factores dominantes: {factors}; diagnóstico: {machine['diagnosis']}")
        if energy:
            line += (f"; índice operacional {energy['operational_efficiency']}%, disponibilidad {energy['availability']}%, "
                     f"rendimiento {energy['performance']}%, conformidad {energy['conformity']}%, eficiencia térmica {energy['thermal_efficiency']}%")
        lines.append(line + ".")
    active = shifts["active_shift"]
    active_text = (f"Turno activo {active['code']} {active['name']} ({active['start_time']}–{active['end_time']}), "
        f"energía {active['net_generation_mwh']} MWh, índice operacional {active['operational_efficiency']}%, "
        f"eficiencia térmica {active['thermal_efficiency']}% y paradas {active['downtime_minutes']} min. " if active else "No hay turno activo. ")
    lines.append("[PostgreSQL · turnos] " + active_text + "Comparativo: " + "; ".join(
        f"{shift['code']} {shift['name']}: {shift['start_time']}–{shift['end_time']}, energía {shift['net_generation_mwh']} MWh, índice {shift['operational_efficiency']}%" for shift in shifts["shifts"]))
    summary = downtime["summary"]
    lines.append(f"[PostgreSQL · paradas] Periodo {downtime['filters']['date_from']} a {downtime['filters']['date_to']}: "
                 f"{summary['events']} eventos, {summary['total_minutes']} min, promedio {summary['average_minutes']} min, "
                 f"{summary['open_events']} abiertos, mayor impacto {summary['top_machine']}. Categorías: " +
                 "; ".join(f"{row['category']} {row['events']} eventos/{row['minutes']} min" for row in downtime["by_category"][:8]))
    for event in downtime["events"][:10]:
        lines.append(f"[PostgreSQL · parada {event['id']}] {event['machine_code']}, {event['category']}, causa {event['cause']}, "
                     f"{event['duration_minutes']} min, estado {event['status']}, turno {event['shift_code'] or 'sin turno'}, origen {event['source']}.")
    return "\n".join(lines), [
        "PostgreSQL · telemetría y análisis predictivo", "PostgreSQL · energy_generation_readings",
        "PostgreSQL · energy_downtime_events", "PostgreSQL · work_shifts",
    ]


def parse_local_datetime(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Fecha y hora inválida.") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(os.environ.get("APP_TIMEZONE", "America/Bogota")))
    return parsed.astimezone(timezone.utc)


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM public.users WHERE lower(username) = %s", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], user_name=user["name"], user_role=user["role"])
            return redirect(url_for("index"))
        flash("Correo o contraseña incorrectos.", "error")
    return render_template("auth.html", mode="login")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if len(name) < 3 or "@" not in email:
            flash("Ingresa un nombre y correo válidos.", "error")
        elif not re.fullmatch(r"[a-z0-9_.-]{3,50}", username):
            flash("El usuario debe tener entre 3 y 50 caracteres: letras, números, punto, guion o guion bajo.", "error")
        elif len(password) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
        elif password != confirmation:
            flash("Las contraseñas no coinciden.", "error")
        else:
            try:
                with get_db() as db:
                    db.execute(
                        "INSERT INTO public.users(name,email,username,password_hash) VALUES(%s,%s,%s,%s)",
                        (name, email, username, generate_password_hash(password)),
                    )
                flash(f"Cuenta creada. Ya puedes iniciar sesión con el usuario {username}.", "success")
                return redirect(url_for("login"))
            except psycopg.IntegrityError:
                flash("Ya existe una cuenta con ese correo.", "error")
    return render_template("auth.html", mode="register")


@app.route("/recover", methods=["GET", "POST"])
def recover():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            flash("Ingresa un correo válido.", "error")
            return render_template("auth.html", mode="recover")
        try:
            with get_db() as db:
                user = db.execute("SELECT id,email FROM public.users WHERE lower(email)=%s LIMIT 1", (email,)).fetchone()
                if user:
                    token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                    minutes = max(5, min(1440, int(os.environ.get("PASSWORD_RESET_MINUTES", "30"))))
                    db.execute("UPDATE public.password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE user_id=%s AND used_at IS NULL", (user["id"],))
                    db.execute(
                        "INSERT INTO public.password_reset_tokens(user_id,token_hash,expires_at) VALUES(%s,%s,%s)",
                        (user["id"], token_hash, datetime.now(timezone.utc) + timedelta(minutes=minutes)),
                    )
                    base_url = os.environ.get("APP_BASE_URL", request.host_url.rstrip("/")).rstrip("/")
                    reset_url = f"{base_url}/reset-password/{token}"
                else:
                    reset_url = None
            if user:
                send_password_reset(user["email"], reset_url)
        except Exception:
            app.logger.exception("No fue posible procesar la recuperación de contraseña")
        flash("Si el correo está registrado, recibirás instrucciones para restablecer tu contraseña.", "success")
        return redirect(url_for("login"))
    return render_template("auth.html", mode="recover")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if len(token) <= 200 else ""
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")
        if len(password) < 10:
            flash("La contraseña debe tener al menos 10 caracteres.", "error")
        elif password != confirmation:
            flash("Las contraseñas no coinciden.", "error")
        else:
            with get_db() as db:
                reset_token = db.execute(
                    """SELECT id,user_id FROM public.password_reset_tokens
                    WHERE token_hash=%s AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP FOR UPDATE""",
                    (token_hash,),
                ).fetchone()
                if reset_token:
                    db.execute("UPDATE public.users SET password_hash=%s WHERE id=%s", (generate_password_hash(password), reset_token["user_id"]))
                    db.execute("UPDATE public.password_reset_tokens SET used_at=CURRENT_TIMESTAMP WHERE id=%s", (reset_token["id"],))
                    session.clear()
                    flash("Contraseña actualizada correctamente. Ya puedes iniciar sesión.", "success")
                    return redirect(url_for("login"))
            flash("El enlace es inválido, expiró o ya fue utilizado.", "error")

    with get_db() as db:
        valid = db.execute(
            "SELECT 1 FROM public.password_reset_tokens WHERE token_hash=%s AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP",
            (token_hash,),
        ).fetchone() is not None
    return render_template("auth.html", mode="reset", token=token, valid=valid)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
@login_required
def api_dashboard():
    return jsonify(dashboard_payload())


@app.get("/api/thermal-efficiency")
@login_required
def api_thermal_efficiency():
    try:
        return jsonify(energy_efficiency_payload())
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 404


@app.get("/api/shifts-dashboard")
@login_required
def api_shifts_dashboard():
    return jsonify(shift_dashboard_payload())


@app.get("/api/shifts")
@login_required
def api_shifts():
    with get_db() as db:
        rows = db.execute(
            "SELECT id,code,name,start_time,end_time,planned_minutes,active FROM public.work_shifts ORDER BY start_time,code"
        ).fetchall()
    return jsonify([{
        **{key: row[key] for key in ("id", "code", "name", "planned_minutes", "active")},
        "start_time": row["start_time"].strftime("%H:%M"),
        "end_time": row["end_time"].strftime("%H:%M"),
    } for row in rows])


@app.post("/api/shifts")
@login_required
def api_shift_create():
    try:
        code, name, start, end, active, planned = parse_shift_body(request.get_json(silent=True) or {})
        with get_db() as db:
            if db.execute("SELECT 1 FROM public.work_shifts WHERE code=%s", (code,)).fetchone():
                return jsonify({"error": "Ya existe un turno con ese código."}), 409
            if active:
                validate_shift_overlap(db, start, end)
            row = db.execute(
                "INSERT INTO public.work_shifts(code,name,start_time,end_time,planned_minutes,active) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                (code, name, start, end, planned, active),
            ).fetchone()
        return jsonify({"id": row["id"], "created": True}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.put("/api/shifts/<int:shift_id>")
@login_required
def api_shift_update(shift_id):
    try:
        code, name, start, end, active, planned = parse_shift_body(request.get_json(silent=True) or {})
        with get_db() as db:
            if db.execute("SELECT 1 FROM public.work_shifts WHERE code=%s AND id<>%s", (code, shift_id)).fetchone():
                return jsonify({"error": "Ya existe un turno con ese código."}), 409
            if active:
                validate_shift_overlap(db, start, end, shift_id)
            row = db.execute(
                "UPDATE public.work_shifts SET code=%s,name=%s,start_time=%s,end_time=%s,planned_minutes=%s,active=%s WHERE id=%s RETURNING id",
                (code, name, start, end, planned, active, shift_id),
            ).fetchone()
        if not row:
            return jsonify({"error": "Turno no encontrado."}), 404
        return jsonify({"id": row["id"], "updated": True})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.delete("/api/shifts/<int:shift_id>")
@login_required
def api_shift_delete(shift_id):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM public.work_shifts WHERE id=%s", (shift_id,)).fetchone():
            return jsonify({"error": "Turno no encontrado."}), 404
        references = db.execute(
            """SELECT
                (SELECT COUNT(*) FROM public.energy_generation_readings WHERE shift_id=%s) +
                (SELECT COUNT(*) FROM public.energy_downtime_events WHERE shift_id=%s) +
                (SELECT COUNT(*) FROM public.production_runs WHERE shift_id=%s) AS total""",
            (shift_id, shift_id, shift_id),
        ).fetchone()["total"]
        if references:
            db.execute("UPDATE public.work_shifts SET active=FALSE WHERE id=%s", (shift_id,))
            return jsonify({"deleted": False, "deactivated": True, "message": "El turno tiene historial y fue desactivado para conservar la trazabilidad."})
        db.execute("DELETE FROM public.work_shifts WHERE id=%s", (shift_id,))
    return jsonify({"deleted": True, "deactivated": False})


@app.get("/api/rag/documents")
@login_required
def api_rag_documents():
    try:
        return jsonify(list_documents())
    except Exception:
        app.logger.exception("Error listando documentos RAG")
        return jsonify({"error": "No fue posible consultar los documentos indexados."}), 503


@app.post("/api/rag/documents")
@login_required
def api_rag_documents_upload():
    files = [item for item in request.files.getlist("files") if item and item.filename]
    if not files or len(files) > 20:
        return jsonify({"error": "Selecciona entre 1 y 20 documentos."}), 400
    results = []
    try:
        for uploaded in files:
            filename = secure_filename(uploaded.filename)
            if not filename or Path(filename).suffix.lower() not in ALLOWED_DOCUMENT_EXTENSIONS:
                raise ValueError(f"Archivo no compatible: {uploaded.filename}")
            raw = uploaded.read()
            if not raw or len(raw) > 25 * 1024 * 1024:
                raise ValueError(f"El archivo {filename} está vacío o supera 25 MB.")
            results.append({"document_name": filename, "chunks": ingest_document(filename, raw)})
        return jsonify({"documents": results, "total": len(results)}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503
    except Exception:
        app.logger.exception("Error indexando documentos RAG")
        return jsonify({"error": "No fue posible procesar los documentos."}), 500


@app.delete("/api/rag/documents/<path:document_name>")
@login_required
def api_rag_document_delete(document_name):
    filename = secure_filename(document_name)
    if not filename or filename != document_name:
        return jsonify({"error": "Nombre de documento inválido."}), 400
    try:
        deleted = delete_document(filename)
        if not deleted:
            return jsonify({"error": "Documento no encontrado."}), 404
        return jsonify({"deleted_chunks": deleted})
    except Exception:
        app.logger.exception("Error eliminando documento RAG")
        return jsonify({"error": "No fue posible eliminar el documento."}), 503


@app.post("/api/rag/chat")
@login_required
def api_rag_chat():
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip() if isinstance(body.get("question"), str) else ""
    if len(question) < 5 or len(question) > 2000:
        return jsonify({"error": "La pregunta debe tener entre 5 y 2000 caracteres."}), 400
    try:
        answer, sources = answer_rag(question)
        return jsonify({"answer": answer, "sources": sources})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503


@app.post("/api/copilot/chat")
@login_required
def api_copilot_chat():
    body = request.get_json(silent=True) or {}
    question = body.get("question", "").strip() if isinstance(body.get("question"), str) else ""
    if len(question) < 5 or len(question) > 2000:
        return jsonify({"error": "La pregunta debe tener entre 5 y 2000 caracteres."}), 400
    try:
        context, operational_sources = copilot_operational_context(question)
        answer, sources = answer_copilot(question, context, operational_sources)
        return jsonify({"answer": answer, "sources": sources, "mode": "operacional integrado"})
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 503
    except Exception:
        app.logger.exception("Error consultando el copiloto operacional")
        return jsonify({"error": "No fue posible consultar el copiloto operacional."}), 503


@app.get("/api/downtime")
@login_required
def api_downtime():
    try:
        return jsonify(downtime_dashboard_payload())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/downtime")
@login_required
def api_downtime_create():
    body = request.get_json(silent=True) or {}
    machine_code = str(body.get("machine", "")).strip().upper()
    category = str(body.get("category", "")).strip()
    cause = str(body.get("cause", "")).strip()
    notes = str(body.get("notes", "")).strip()
    if not machine_code or not category or not cause or len(category) > 60 or len(cause) > 180 or len(notes) > 500:
        return jsonify({"error": "Máquina, categoría y causa son obligatorias y deben respetar las longitudes permitidas."}), 400
    try:
        started_at = parse_local_datetime(body.get("started_at"))
        ended_at = parse_local_datetime(body["ended_at"]) if body.get("ended_at") else None
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if ended_at and ended_at <= started_at:
        return jsonify({"error": "La fecha de fin debe ser posterior al inicio."}), 400
    local_started = started_at.astimezone(ZoneInfo(os.environ.get("APP_TIMEZONE", "America/Bogota")))
    local_time = local_started.time().replace(tzinfo=None)
    with get_db() as db:
        machine = db.execute("SELECT id FROM public.machines WHERE code=%s AND active", (machine_code,)).fetchone()
        if not machine:
            return jsonify({"error": "Máquina no encontrada."}), 404
        shifts = db.execute("SELECT id,start_time,end_time FROM public.work_shifts WHERE active ORDER BY start_time").fetchall()
        shift = next((item for item in shifts if (item["start_time"] < item["end_time"] and item["start_time"] <= local_time < item["end_time"]) or (item["start_time"] > item["end_time"] and (local_time >= item["start_time"] or local_time < item["end_time"]))), None)
        duration = (ended_at - started_at).total_seconds() / 60 if ended_at else 0
        event = db.execute(
            """INSERT INTO public.energy_downtime_events
            (machine_id,shift_id,started_at,ended_at,duration_minutes,category,cause,planned,status,source,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual',%s) RETURNING id""",
            (machine["id"], shift["id"] if shift else None, started_at, ended_at, duration, category, cause, bool(body.get("planned")), "closed" if ended_at else "open", notes or None),
        ).fetchone()
    return jsonify({"id": event["id"], "created": True}), 201


@app.patch("/api/downtime/<int:event_id>/close")
@login_required
def api_downtime_close(event_id):
    with get_db() as db:
        event = db.execute(
            """UPDATE public.energy_downtime_events SET ended_at=CURRENT_TIMESTAMP,
            duration_minutes=EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_at))/60,status='closed'
            WHERE id=%s AND status='open' RETURNING id,duration_minutes""",
            (event_id,),
        ).fetchone()
    if not event:
        return jsonify({"error": "La parada no existe o ya está cerrada."}), 404
    return jsonify({"id": event["id"], "duration_minutes": round(float(event["duration_minutes"]), 1)})


@app.get("/api/machines/<machine_id>")
@login_required
def api_machine(machine_id):
    machine = machine_detail_payload(machine_id)
    if machine is None:
        return jsonify({"error": "Máquina no encontrada"}), 404
    return jsonify(machine)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
