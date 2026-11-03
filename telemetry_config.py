MACHINES = [
    ("CAL-01", "Caldera principal 1", "boiler", "Generación de vapor", 125),
    ("CAL-02", "Caldera principal 2", "boiler", "Generación de vapor", 125),
    ("TUR-01", "Turbina de vapor 1", "turbine", "Casa de máquinas", 95),
    ("TUR-02", "Turbina de vapor 2", "turbine", "Casa de máquinas", 95),
    ("GEN-01", "Generador síncrono 1", "generator", "Generación eléctrica", 110),
    ("GEN-02", "Generador síncrono 2", "generator", "Generación eléctrica", 110),
    ("BBA-01", "Bomba de alimentación 1", "pump", "Agua de alimentación", 8),
    ("BBA-02", "Bomba de alimentación 2", "pump", "Agua de alimentación", 8),
    ("VEN-01", "Ventilador de tiro inducido", "fan", "Gases de combustión", 5),
    ("CON-01", "Condensador principal", "condenser", "Ciclo térmico", 0),
]

USAGE_HOURS_BY_MACHINE = {
    "CAL-01": 18420.0,
    "CAL-02": 17680.0,
    "TUR-01": 22150.0,
    "TUR-02": 19840.0,
    "GEN-01": 21420.0,
    "GEN-02": 18760.0,
    "BBA-01": 24310.0,
    "BBA-02": 16990.0,
    "VEN-01": 20970.0,
    "CON-01": 22680.0,
}


def var(code, name, unit, category, nominal, sigma, low_warn=None, low_crit=None, high_warn=None, high_crit=None):
    return (code, name, unit, category, nominal, sigma, low_warn, low_crit, high_warn, high_crit)


COMMON = [
    var("load_pct", "Carga operativa", "%", "operation", 88, 3, 55, 35, 101, 110),
    var("usage_hours", "Horas acumuladas", "h", "lifecycle", 18000, 0.02),
]

VARIABLES = {
    "boiler": COMMON + [
        var("drum_pressure", "Presión del domo", "bar", "process", 142, 1.2, 132, 125, 151, 157),
        var("drum_level", "Nivel del domo", "%", "process", 50, 2.2, 35, 25, 65, 75),
        var("superheated_steam_temp", "Temperatura vapor sobrecalentado", "°C", "thermal", 490, 4, 465, 450, 515, 530),
        var("tube_metal_temp", "Temperatura metálica de tubos", "°C", "thermal", 525, 5, None, None, 555, 580),
        var("flue_o2", "Oxígeno en gases", "%", "combustion", 3.2, .25, 2.1, 1.5, 4.8, 6),
        var("flue_co", "Monóxido de carbono", "ppm", "combustion", 55, 10, None, None, 120, 200),
        var("furnace_pressure", "Presión del hogar", "Pa", "process", -45, 4, -60, -75, -25, -10),
        var("gas_path_dp", "Diferencial circuito de gases", "kPa", "performance", 2.8, .15, None, None, 3.8, 4.5),
        var("water_conductivity", "Conductividad del agua", "µS/cm", "chemistry", 18, 2, None, None, 30, 45),
        var("acoustic_leak", "Índice acústico de fuga", "dB", "condition", 38, 2, None, None, 50, 60),
        var("boiler_efficiency", "Eficiencia de caldera", "%", "performance", 91, .5, 87, 83),
    ],
    "turbine": COMMON + [
        var("vibration_radial", "Vibración radial RMS", "mm/s", "condition", 4.2, .35, None, None, 7.1, 9.5),
        var("vibration_axial", "Vibración axial RMS", "mm/s", "condition", 3.4, .3, None, None, 6.3, 8.5),
        var("axial_displacement", "Desplazamiento axial", "mm", "condition", .18, .03, -.35, -.5, .35, .5),
        var("shaft_eccentricity", "Excentricidad del eje", "µm", "condition", 42, 4, None, None, 70, 90),
        var("bearing_temp", "Temperatura de cojinete", "°C", "thermal", 78, 2, None, None, 92, 105),
        var("lube_oil_pressure", "Presión de aceite", "bar", "lubrication", 2.4, .08, 1.8, 1.4),
        var("lube_oil_temp", "Temperatura de aceite", "°C", "lubrication", 52, 1.3, 40, 35, 62, 70),
        var("steam_inlet_pressure", "Presión de vapor de entrada", "bar", "process", 116, 1.5, 105, 98, 125, 132),
        var("steam_inlet_temp", "Temperatura de vapor de entrada", "°C", "process", 475, 3, 455, 440, 500, 515),
        var("differential_expansion", "Expansión diferencial", "mm", "condition", 1.8, .15, .8, .3, 3.1, 3.8),
        var("turbine_efficiency", "Eficiencia isentrópica", "%", "performance", 87, .6, 82, 78),
    ],
    "generator": COMMON + [
        var("stator_winding_temp", "Temperatura devanado estator", "°C", "thermal", 82, 2, None, None, 105, 120),
        var("bearing_temp", "Temperatura de cojinete", "°C", "thermal", 74, 2, None, None, 90, 102),
        var("phase_current", "Corriente de fase", "A", "electrical", 106, 3, 65, 45, 122, 135),
        var("current_imbalance", "Desbalance de corriente", "%", "electrical", 1.2, .2, None, None, 3, 5),
        var("power_factor", "Factor de potencia", "ratio", "electrical", .96, .008, .9, .85, 1.01, 1.03),
        var("field_current", "Corriente de excitación", "A", "electrical", 420, 10, 360, 330, 490, 530),
        var("partial_discharge", "Descargas parciales", "pC", "insulation", 120, 18, None, None, 260, 400),
        var("vibration", "Vibración global", "mm/s", "condition", 3.7, .3, None, None, 6.5, 8.5),
        var("cooling_outlet_temp", "Temperatura salida refrigeración", "°C", "cooling", 46, 1.2, None, None, 58, 65),
        var("active_power", "Potencia activa", "MW", "performance", 96, 3, 60, 40, 112, 120),
    ],
    "pump": COMMON + [
        var("vibration", "Vibración RMS", "mm/s", "condition", 4.3, .4, None, None, 7.1, 9),
        var("bearing_temp", "Temperatura de cojinete", "°C", "thermal", 76, 2, None, None, 90, 102),
        var("suction_pressure", "Presión de succión", "bar", "process", 5.2, .15, 4.2, 3.5),
        var("discharge_pressure", "Presión de descarga", "bar", "process", 148, 1.5, 135, 125, 158, 165),
        var("flow", "Caudal de alimentación", "m³/h", "process", 410, 8, 360, 320, 460, 490),
        var("motor_current", "Corriente del motor", "A", "electrical", 78, 2.5, 55, 40, 92, 105),
        var("seal_leakage", "Fuga del sello", "ml/min", "condition", 8, 2, None, None, 20, 35),
        var("oil_particles", "Partículas en aceite", "ppm", "lubrication", 55, 8, None, None, 110, 180),
        var("hydraulic_efficiency", "Eficiencia hidráulica", "%", "performance", 84, 1, 76, 70),
        var("npsh_margin", "Margen NPSH", "m", "process", 3.8, .2, 2.2, 1.3),
    ],
    "fan": COMMON + [
        var("vibration_radial", "Vibración radial", "mm/s", "condition", 5.4, .45, None, None, 7.1, 9.5),
        var("vibration_axial", "Vibración axial", "mm/s", "condition", 4.1, .35, None, None, 6.3, 8.5),
        var("bearing_temp", "Temperatura de cojinete", "°C", "thermal", 79, 2, None, None, 92, 105),
        var("motor_current", "Corriente del motor", "A", "electrical", 84, 3, 60, 45, 98, 112),
        var("fan_speed", "Velocidad del ventilador", "rpm", "operation", 1480, 15, 1350, 1250, 1580, 1650),
        var("damper_position", "Posición del damper", "%", "operation", 72, 3, 35, 20, 96, 100),
        var("furnace_draft", "Tiro del hogar", "Pa", "process", -48, 4, -65, -80, -25, -12),
        var("gas_flow", "Caudal de gases", "km³/h", "process", 390, 9, 340, 310, 445, 480),
        var("gas_temperature", "Temperatura de gases", "°C", "thermal", 135, 3, 110, 95, 165, 185),
        var("fan_efficiency", "Eficiencia del ventilador", "%", "performance", 82, 1, 74, 68),
    ],
    "condenser": COMMON + [
        var("vacuum", "Vacío del condensador", "bar", "process", -.88, .008, -.93, -.96, -.82, -.76),
        var("backpressure", "Contrapresión de turbina", "kPa", "process", 8.2, .25, 6.8, 5.8, 10.5, 12),
        var("cooling_water_in_temp", "Temperatura entrada agua", "°C", "thermal", 26, .8, 18, 14, 34, 38),
        var("cooling_water_out_temp", "Temperatura salida agua", "°C", "thermal", 35, .9, 26, 22, 44, 49),
        var("cooling_water_flow", "Caudal agua enfriamiento", "m³/h", "process", 8200, 120, 7000, 6200, 9300, 10000),
        var("water_side_dp", "Diferencial lado agua", "kPa", "performance", 68, 3, 48, 38, 90, 105),
        var("terminal_temp_difference", "Diferencia terminal de temperatura", "°C", "performance", 5.5, .35, None, None, 8, 11),
        var("hotwell_level", "Nivel del hotwell", "%", "process", 52, 2, 38, 28, 68, 78),
        var("condensate_conductivity", "Conductividad condensado", "µS/cm", "chemistry", .25, .04, None, None, .5, .8),
        var("dissolved_oxygen", "Oxígeno disuelto", "ppb", "chemistry", 8, 1.5, None, None, 15, 25),
        var("air_ingress", "Entrada de aire", "kg/h", "condition", 4, .7, None, None, 8, 13),
    ],
}

FAILURE_MODES = {
    "vibration": "Degradación de rodamientos o desalineación",
    "vibration_radial": "Desbalance, desalineación o daño de rodamiento",
    "vibration_axial": "Desalineación o empuje axial anormal",
    "tube_metal_temp": "Sobrecalentamiento o incrustación en tubos",
    "acoustic_leak": "Posible fuga de tubos de caldera",
    "partial_discharge": "Degradación del aislamiento eléctrico",
    "seal_leakage": "Desgaste del sello mecánico",
    "oil_particles": "Desgaste interno o contaminación del lubricante",
    "vacuum": "Pérdida de vacío del condensador",
    "air_ingress": "Ingreso de aire al condensador",
    "terminal_temp_difference": "Ensuciamiento del condensador",
}
