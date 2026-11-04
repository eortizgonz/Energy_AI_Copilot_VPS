from rag_service import connect, ingest_text


GUIDES = {
    "CAL-01": {
        "process": "generación de vapor base",
        "components": "domo, tubos de agua, sobrecalentador, quemadores, refractario y economizador",
        "failures": ["fuga o fisura incipiente en tubos", "incrustación y pérdida de transferencia térmica", "combustión deficiente por exceso o defecto de aire"],
        "actions": ["realizar inspección acústica y termográfica del banco de tubos", "verificar química del agua y tendencia de conductividad", "ajustar relación aire-combustible con analizador de gases calibrado"],
    },
    "CAL-02": {
        "process": "generación de vapor de respaldo y punta",
        "components": "tubos de pared, domo, atemperador, sopladores de hollín, hogar y tren de gases",
        "failures": ["sobretemperatura y fluencia de tubos", "ensuciamiento del paso de gases", "inestabilidad de llama y formación de CO"],
        "actions": ["comparar temperatura metálica por zonas y revisar atemperación", "evaluar diferencial de presión y ejecutar limpieza según procedimiento", "inspeccionar quemadores, detectores de llama y distribución de aire"],
    },
    "TUR-01": {
        "process": "expansión principal de vapor",
        "components": "rotor, cojinetes, álabes, sellos, sistema de lubricación y válvulas de admisión",
        "failures": ["desbalance o desalineación del rotor", "degradación de cojinete y película de aceite", "roce interno o expansión diferencial anormal"],
        "actions": ["analizar espectro y fase de vibración axial/radial", "muestrear aceite y verificar presión, temperatura y caudal", "contrastar expansión diferencial, excentricidad y posición axial"],
    },
    "TUR-02": {
        "process": "expansión secundaria y regulación de carga",
        "components": "etapas de presión, sellos laberínticos, rotor, cojinetes, gobernador y drenajes",
        "failures": ["pérdida de eficiencia por erosión o depósitos", "fuga interna en sellos", "inestabilidad de regulación o presión de admisión"],
        "actions": ["comparar eficiencia isentrópica y condiciones de vapor", "verificar sellos, drenajes y balance térmico", "probar respuesta del gobernador y válvulas de control"],
    },
    "GEN-01": {
        "process": "conversión electromecánica principal",
        "components": "estator, rotor, excitación, aislamiento, cojinetes y sistema de enfriamiento",
        "failures": ["sobretemperatura o deterioro del aislamiento del estator", "desbalance de corriente entre fases", "descargas parciales y contaminación del devanado"],
        "actions": ["comparar temperaturas RTD y carga por fase", "medir desbalance, armónicos y conexiones", "evaluar tendencia de descargas parciales y resistencia de aislamiento"],
    },
    "GEN-02": {
        "process": "conversión electromecánica de respaldo",
        "components": "sistema de excitación, rotor, estator, ventilación, cojinetes y protecciones",
        "failures": ["anomalía de excitación o factor de potencia", "vibración electromagnética", "restricción del circuito de enfriamiento"],
        "actions": ["verificar corriente de campo, tensión y factor de potencia", "correlacionar vibración con carga y frecuencia eléctrica", "inspeccionar filtros, ventiladores y temperatura del aire de salida"],
    },
    "BBA-01": {
        "process": "alimentación principal de agua a caldera",
        "components": "impulsor, sello mecánico, rodamientos, acople, motor y línea de succión",
        "failures": ["cavitación por margen NPSH insuficiente", "desgaste de impulsor o recirculación", "falla de sello o rodamiento"],
        "actions": ["verificar presión de succión, NPSH, nivel y temperatura", "comparar caudal, presión de descarga y eficiencia hidráulica", "inspeccionar fuga de sello, partículas de aceite y vibración"],
    },
    "BBA-02": {
        "process": "alimentación redundante y regulación de agua",
        "components": "impulsor, carcasa, válvula de descarga, motor, cojinetes y sistema de aceite",
        "failures": ["operación fuera del punto de mejor eficiencia", "restricción o válvula parcialmente cerrada", "sobrecarga del motor y desalineación"],
        "actions": ["ubicar el punto de operación sobre la curva de la bomba", "revisar válvulas, filtros y pérdidas de carga", "medir corriente, alineación y condición de cojinetes"],
    },
    "VEN-01": {
        "process": "extracción de gases y control de tiro",
        "components": "rodete, eje, cojinetes, motor, damper, carcasa y ductos",
        "failures": ["ensuciamiento o desbalance del rodete", "rodamiento degradado", "obstrucción de ductos o damper defectuoso"],
        "actions": ["inspeccionar depósitos, erosión y balance del rodete", "analizar vibración y temperatura de cojinetes", "verificar tiro del hogar, posición del damper y flujo de gases"],
    },
    "CON-01": {
        "process": "condensación y mantenimiento del vacío",
        "components": "haz tubular, cajas de agua, sistema de vacío, pozo caliente y bombas de circulación",
        "failures": ["ingreso de aire y pérdida de vacío", "ensuciamiento o incrustación de tubos", "bajo caudal de agua de enfriamiento"],
        "actions": ["ejecutar prueba de fugas y revisar sellos del sistema de vacío", "comparar diferencia terminal y presión diferencial del lado agua", "verificar caudal, temperaturas de entrada/salida y calidad del condensado"],
    },
}


VARIABLE_GUIDANCE = {
    "vibration": ("desbalance, desalineación, holgura, roce o degradación de rodamientos", "confirmar con analizador calibrado y revisar espectro, fase, fijaciones, alineación y lubricación"),
    "temperature": ("sobrecarga térmica, transferencia deficiente, fricción o refrigeración insuficiente", "validar la medición y revisar carga, flujo, limpieza, lubricación y enfriamiento"),
    "pressure": ("restricción, fuga, cavitación, regulación inestable o sensor desviado", "contrastar transmisor con patrón y revisar válvulas, filtros, fugas, succión y descarga"),
    "current": ("sobrecarga, desbalance eléctrico, bloqueo mecánico o deterioro de aislamiento", "medir por fase y revisar conexiones, protecciones, aislamiento y libertad mecánica"),
    "efficiency": ("ensuciamiento, desgaste, operación fuera de diseño o pérdidas internas", "construir balance energético y comparar carga, caudal, temperaturas y condición interna"),
    "conductivity": ("contaminación, ingreso de sales o control químico deficiente", "confirmar muestra de laboratorio y revisar dosificación, purga, fugas y tratamiento de agua"),
    "leak": ("pérdida de estanqueidad, fisura, sello degradado o conexión floja", "localizar la fuga de forma segura y programar reparación con aislamiento y LOTO"),
    "oxygen": ("ingreso de aire, desaireación deficiente o desviación química", "verificar estanqueidad, desaireador, tratamiento químico y calibración del analizador"),
    "flow": ("obstrucción, recirculación, desgaste o posición incorrecta de válvulas", "validar caudal y revisar filtros, válvulas, curvas de operación y pérdidas de carga"),
    "default": ("desviación del proceso, degradación del componente o instrumentación inestable", "confirmar la señal, revisar tendencia y contrastar con el procedimiento específico del activo"),
}


RISK_BANDS = [
    (25, "Estable", "Continuar operación y mantener la ronda preventiva definida."),
    (45, "Atención", "Aumentar vigilancia y confirmar las variables dominantes durante el turno."),
    (65, "Degradado", "Crear orden de inspección para la siguiente ventana operativa segura."),
    (80, "Alto", "Priorizar diagnóstico especializado y evaluar reducción controlada de carga."),
    (101, "Crítico", "Evaluar parada controlada; aplicar LOTO y escalar a Operaciones, Mantenimiento y HSE."),
]


def risk_band(risk):
    return next(((label, strategy) for ceiling, label, strategy in RISK_BANDS if risk < ceiling), RISK_BANDS[-1][1:])


def variable_guidance(code):
    normalized = code.casefold()
    key = next((item for item in VARIABLE_GUIDANCE if item != "default" and item in normalized), "default")
    return VARIABLE_GUIDANCE[key]


def diagnostic_for(machine, telemetry, risk):
    code = machine.get("code", machine.get("id"))
    guide = GUIDES[code]
    level, strategy = risk_band(risk)
    dominant = sorted(telemetry, key=lambda item: item.get("contribution", 0), reverse=True)[:3]
    causes = [f"Escenario probable en {guide['process']}: {failure}." for failure in guide["failures"]]
    actions = [strategy] + guide["actions"]
    for variable in dominant:
        cause, action = variable_guidance(variable["code"])
        causes.append(f"{variable['name']} ({variable['contribution']} pt): posible {cause}.")
        actions.append(f"Para {variable['name']}: {action}.")
    return {
        "risk_range": level,
        "finding": f"Riesgo {risk:.1f}% en {guide['process']}; componentes prioritarios: {guide['components']}.",
        "strategy": strategy,
        "probable_failures": guide["failures"],
        "causes": causes,
        "actions": actions,
        "source": manual_name(code),
    }


def manual_name(code):
    return f"MAN-ENE-{code}_operacion_mantenimiento.md"


def manual_text(machine):
    guide = GUIDES[machine["code"]]
    bands = "\n".join(
        f"- {'Desde 80' if ceiling == 101 else 'Menor de ' + str(ceiling)}%: {label}. {strategy}"
        for ceiling, label, strategy in RISK_BANDS
    )
    failures = "\n".join(f"- {item}." for item in guide["failures"])
    actions = "\n".join(f"- {item}." for item in guide["actions"])
    return f"""# Manual técnico Energy {machine['code']} — {machine['name']}
Área: {machine['area']}. Proceso: {guide['process']}. Tipo: {machine['machine_type']}.
Componentes críticos: {guide['components']}.

## Seguridad y control de energías
Solo personal competente y autorizado puede operar o intervenir el activo. Coordinar con sala de control, identificar todas las fuentes eléctricas, térmicas, hidráulicas, neumáticas, químicas y mecánicas, reducir presión y temperatura de forma controlada, aplicar bloqueo y etiquetado LOTO, verificar energía cero y utilizar los elementos de protección definidos. Nunca abrir equipos presurizados, retirar guardas, puentear protecciones ni intervenir circuitos energizados. Los límites de esta guía son demostrativos y deben validarse contra el fabricante y la ingeniería de la central.

## Fallas probables específicas
{failures}

## Respuesta por rango de índice de falla
{bands}

## Acciones recomendadas específicas
{actions}

## Interpretación de variables dominantes
Vibración: revisar desbalance, alineación, holgura, roce y rodamientos. Temperatura: revisar transferencia térmica, carga, fricción y refrigeración. Presión y caudal: buscar restricciones, fugas, cavitación y desviación de válvulas. Corriente: verificar carga, fases, conexiones y aislamiento. Eficiencia: construir balance energético y buscar ensuciamiento, desgaste y pérdidas internas. Química: confirmar con laboratorio antes de modificar dosificación o purga.

## Retorno a servicio
Cerrar la orden, retirar herramientas, reinstalar protecciones, liberar bloqueos según procedimiento y ejecutar prueba controlada. Confirmar estabilidad de alarmas, vibración, temperatura, presión, flujo, energía y eficiencia antes de autorizar carga normal.
"""


def ingest_machine_manuals():
    with connect() as db:
        machines = db.execute("SELECT code,name,machine_type,area FROM public.machines WHERE active ORDER BY code").fetchall()
    chunks = sum(ingest_text(manual_name(machine["code"]), manual_text(machine)) for machine in machines)
    return len(machines), chunks
