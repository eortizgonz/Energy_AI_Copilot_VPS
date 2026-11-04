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

El collector energético simula MW/MWh, consumo auxiliar, entrada térmica de
combustible, disponibilidad, rendimiento, conformidad e índice operacional:

```bash
python energy_collector.py --once
python energy_collector.py
```

```env
ENERGY_COLLECTOR_INTERVAL_SECONDS=60
```

En Docker se ejecuta continuamente como el servicio `energy_collector`.

Las capturas energéticas se asignan automáticamente a tres turnos de 8 horas
usando `APP_TIMEZONE=America/Bogota`: T1 (00:00–08:00), T2 (08:00–16:00) y
T3 (16:00–00:00). La vista **Turno** compara energía neta, disponibilidad,
rendimiento, conformidad, eficiencia térmica y tiempo de parada.

## Documentación RAG de activos

El proyecto genera un manual específico para cada una de las 10 máquinas con
fallas probables, causas asociadas a variables dominantes, acciones recomendadas,
seguridad y respuestas diferenciadas por rango de riesgo. Para indexarlos:

```bash
python ingest_energy_manuals.py
```

La recuperación semántica y el chat utilizan Ollama con `nomic-embed-text` y
`llama3.1:8b`. En Docker, el servicio de una sola ejecución `rag_init` indexa los
manuales cuando la base documental está vacía.

## Recuperación de contraseña con Gmail

Configurar en `.env` una cuenta de Gmail con verificación en dos pasos y una
contraseña de aplicación (no la contraseña normal de la cuenta):

```env
APP_BASE_URL=http://127.0.0.1:5000
PASSWORD_RESET_MINUTES=30
MAIL_HOST=smtp.gmail.com
MAIL_PORT=465
MAIL_USE_SSL=true
MAIL_USERNAME=tu_cuenta@gmail.com
MAIL_APP_PASSWORD=tu_password_de_aplicacion
MAIL_FROM_NAME=ZYMA 360 Energy
```

El enlace se guarda como hash en `password_reset_tokens`, vence según
`PASSWORD_RESET_MINUTES` y solo puede utilizarse una vez. En producción,
`APP_BASE_URL` debe contener la URL HTTPS pública de la aplicación.

El collector usa la conexión PostgreSQL configurada en `.env` y almacena datos en
`machine_variables`, `telemetry_readings`, `machine_health_snapshots` y
`telemetry_collection_runs`.

## Despliegue en VPS con Docker

El archivo `compose.prod.yaml` despliega tres servicios aislados:

- `app`: aplicación Flask servida con Gunicorn en el puerto público `5080`.
- `collector`: simulador de telemetría con el intervalo configurado.
- `db`: PostgreSQL con pgvector, accesible únicamente por la red interna de Docker.

En el directorio del proyecto dentro de la VPS:

```bash
cp .env.production.example .env.production
nano .env.production
```

Cambiar como mínimo `PGPASSWORD`, `SECRET_KEY`, `APP_BASE_URL` y las credenciales
de Gmail. Luego validar e iniciar:

```bash
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml up -d --build
docker compose --env-file .env.production -f compose.prod.yaml ps
```

Consultar el arranque y verificar el acceso local:

```bash
docker compose --env-file .env.production -f compose.prod.yaml logs -f app collector
curl http://127.0.0.1:5080/login
```

La base de datos, sus tablas y el catálogo inicial de las 10 máquinas se crean
automáticamente antes de iniciar Gunicorn. El archivo `.env.production` está
excluido de Git y no debe subirse al repositorio.

El despliegue inicializa 18 tablas mediante migraciones idempotentes: seguridad,
activos y telemetría predictiva, además del modelo operativo para productos,
rutas, órdenes, lotes, turnos, ejecuciones, contadores, paradas, OEE y documentos
SOP con embeddings de pgvector.
