from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import os
import re
import secrets

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash

from mailer import send_password_reset


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


@app.get("/api/machines/<machine_id>")
@login_required
def api_machine(machine_id):
    machine = next((item for item in dashboard_payload()["machines"] if item["id"] == machine_id.upper()), None)
    if machine is None:
        return jsonify({"error": "Máquina no encontrada"}), 404
    return jsonify(machine)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
