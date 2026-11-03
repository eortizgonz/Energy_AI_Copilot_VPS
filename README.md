# Energy AI Copilot Dashboard Interactivo

Versión mejorada e interactiva para energía.

## Incluye
- Dashboard vertical con scroll.
- Botones funcionales por perfil.
- Tarjetas pequeñas para KPIs.
- Barras dinámicas de operación energética.
- Gráfico tipo donut de impacto.
- Generación, capacidad, contratos, downtime y costo por MWh.
- Preguntas dinámicas por perfil: Operacional, Mantenimiento, Financiero, Ejecutivo y Comercial.
- Respuestas automáticas.
- Acciones sugeridas.
- Simuladores SAP ERP, MII, ME, CAP y BTP.
- Backend Python Flask.
- Archivos nube: Dockerfile, Procfile, render.yaml.

## Ejecutar
```bash
cd Energy_AI_Copilot_Dashboard_Interactivo
pip install -r requirements.txt
python app.py
```

Abrir `http://127.0.0.1:5000`

## Telemetría predictiva

Inicializar las 10 máquinas, el catálogo de variables y las tablas históricas:

```bash
python setup_predictive_db.py
```

Insertar un ciclo simulado:

```bash
python collector.py --once
```

Ejecutar el collector continuamente usando el intervalo configurado en `.env`:

```bash
python collector.py
```

```env
COLLECTOR_INTERVAL_SECONDS=60
```

El argumento `--interval` puede reemplazar temporalmente este valor.

El collector usa la conexión PostgreSQL configurada en `.env` y almacena datos en
`machine_variables`, `telemetry_readings`, `machine_health_snapshots` y
`telemetry_collection_runs`.
