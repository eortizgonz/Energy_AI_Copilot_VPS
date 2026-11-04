const state = {data: null, energy: null, shifts: null, filter: "all", selectedId: null, refreshTimer: null, view: "predictive"};
const labels = {healthy: "Saludable", warning: "Alerta", critical: "Crítica"};
const nf = new Intl.NumberFormat("es-CO", {maximumFractionDigits: 1});
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

async function getDashboard() {
  const response = await fetch("/api/dashboard");
  if (!response.ok) throw new Error("No fue posible consultar la telemetría");
  return response.json();
}

async function getThermalEfficiency() {
  const response = await fetch("/api/thermal-efficiency");
  return response.ok ? response.json() : null;
}

async function getShiftsDashboard() {
  const response = await fetch("/api/shifts-dashboard");
  if (!response.ok) throw new Error("No fue posible consultar los turnos");
  return response.json();
}

async function loadRagDocuments() {
  const response = await fetch("/api/rag/documents");
  if (!response.ok) throw new Error("No fue posible consultar los documentos RAG");
  const documents = await response.json();
  document.getElementById("ragDocumentList").innerHTML = documents.length ? documents.map(document => `<div class="rag-document"><strong>${esc(document.document_name)}</strong><span>${document.chunks} fragmentos</span><small>${new Date(document.indexed_at).toLocaleString("es-CO")}</small></div>`).join("") : '<p class="rag-empty">No hay manuales indexados. Ejecuta <code>python ingest_energy_manuals.py</code>.</p>';
}

async function askRag(event) {
  event.preventDefault();
  const question = document.getElementById("ragQuestion").value.trim();
  const button = document.getElementById("ragSubmit");
  button.disabled = true;
  button.textContent = "Consultando…";
  document.getElementById("ragAnswer").innerHTML = "<p>Recuperando evidencia y elaborando la respuesta…</p>";
  document.getElementById("ragSources").innerHTML = "";
  try {
    const response = await fetch("/api/rag/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No fue posible consultar el conocimiento");
    document.getElementById("ragAnswer").innerHTML = `<p>${esc(data.answer).replace(/\n/g, "<br>")}</p>`;
    document.getElementById("ragSources").innerHTML = data.sources.map(source => `<span>${esc(source)}</span>`).join("");
  } catch (error) {
    document.getElementById("ragAnswer").innerHTML = `<p class="machine-error">${esc(error.message)}</p>`;
  } finally {
    button.disabled = false;
    button.textContent = "Consultar RAG";
  }
}

function txt(id, value) { document.getElementById(id).textContent = value; }
function esc(value) { return String(value ?? "").replace(/[&<>'"]/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"}[character])); }
function risk(value) { return `<div class="risk-cell"><div class="risk-track"><i style="width:${value}%"></i></div><strong>${value}%</strong></div>`; }
function signal(item) { return item && item.value !== null ? `${nf.format(item.value)} ${item.unit}` : "—"; }
function average(values) { return values.reduce((total, value) => total + value, 0) / Math.max(1, values.length); }
function indicatorClass(value) { return value >= 85 ? "excellent" : value >= 75 ? "good" : value >= 60 ? "watch" : "poor"; }

function renderSummary() {
  const {summary, priority, updated_at: updatedAt} = state.data;
  txt("healthyCount", summary.healthy);
  txt("warningCount", summary.warning);
  txt("criticalCount", summary.critical);
  txt("averageRisk", `${summary.average_risk}%`);
  txt("generation", `${summary.generation} MW`);
  txt("updatedAt", `Última lectura: ${new Date(updatedAt).toLocaleString("es-CO")}`);
  txt("priorityTitle", `${priority.id} · ${priority.name} concentra el mayor riesgo (${priority.risk}%).`);
  txt("priorityText", `${priority.diagnosis} Vida útil estimada: ${priority.rul_days} días.`);
  document.getElementById("priorityDetail").onclick = () => selectMachine(priority.id);
}

function renderTable() {
  const body = document.getElementById("machineRows");
  const machines = state.data.machines.filter(machine => state.filter === "all" || machine.status === state.filter);
  body.innerHTML = machines.map(machine => `<tr class="${state.selectedId === machine.id ? "selected" : ""}"><td><strong>${machine.id}</strong><small>${machine.name} · ${machine.area}</small></td><td>${nf.format(machine.hours)} h</td><td>${signal(machine.signals.condition)}</td><td>${signal(machine.signals.temperature)}</td><td>${signal(machine.signals.process)}</td><td>${signal(machine.signals.performance)}</td><td>${risk(machine.risk)}</td><td><span class="status-pill ${machine.status}">${labels[machine.status]}</span></td><td><button class="detail-button" data-machine="${machine.id}">Ver detalle</button></td></tr>`).join("");
  document.getElementById("emptyState").hidden = machines.length > 0;
  body.querySelectorAll(".detail-button").forEach(button => button.addEventListener("click", () => selectMachine(button.dataset.machine)));
}

async function selectMachine(id) {
  const dialog = document.getElementById("machineDialog");
  state.selectedId = id;
  renderTable();
  txt("machineDialogTitle", id);
  document.getElementById("machineDialogBody").innerHTML = '<p class="machine-loading">Consultando telemetría del activo…</p>';
  if (!dialog.open) dialog.showModal();
  try {
    const response = await fetch(`/api/machines/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("No fue posible consultar el detalle de la máquina");
    const machine = await response.json();
    txt("machineDialogTitle", `${machine.id} · ${machine.name}`);
    const energy = machine.energy;
    const energyCards = energy ? `<div class="machine-energy-grid"><div><span>Turno</span><strong>${esc(energy.shift)}</strong></div><div><span>Energía neta</span><strong>${nf.format(energy.net_generation_mwh)} MWh</strong></div><div><span>Índice operacional</span><strong>${nf.format(energy.operational_efficiency)}%</strong></div><div><span>Eficiencia térmica</span><strong>${nf.format(energy.thermal_efficiency)}%</strong></div><div><span>Disponibilidad</span><strong>${nf.format(energy.availability)}%</strong></div><div><span>Conformidad</span><strong>${nf.format(energy.conformity)}%</strong></div></div>` : '<p class="machine-empty">Aún no hay una lectura energética asociada.</p>';
    const factorLines = machine.factors.map(factor => `<div class="machine-factor"><span>${esc(factor.name)}</span><i><b style="width:${Math.min(100, factor.contribution * 3.2)}%"></b></i><strong>${nf.format(factor.contribution)} pt</strong></div>`).join("");
    const telemetryRows = machine.telemetry.map(item => `<tr><td><strong>${esc(item.name)}</strong><small>${esc(item.code)} · ${esc(item.category)}</small></td><td>${item.value === null ? "—" : nf.format(item.value)} ${esc(item.unit)}</td><td>${nf.format(item.nominal)} ${esc(item.unit)}</td><td>${item.deviation_percent === null ? "—" : nf.format(item.deviation_percent) + "%"}</td><td><span class="telemetry-status ${item.status}">${item.status === "normal" ? "Normal" : item.status === "warning" ? "Alerta" : "Crítica"}</span></td><td>${item.recorded_at ? new Date(item.recorded_at).toLocaleString("es-CO") : "Sin lectura"}</td></tr>`).join("");
    const manual = machine.manual;
    const manualHtml = `<section class="machine-manual"><div class="machine-manual-head"><div><span class="eyebrow dark">CONOCIMIENTO RAG DEL ACTIVO</span><h3>${esc(manual.risk_range)} · causas y acciones según variables dominantes</h3></div><span>${esc(manual.source)}</span></div><p>${esc(manual.finding)}</p><div><article><h4>Fallas y causas probables</h4><ul>${manual.causes.map(item => `<li>${esc(item)}</li>`).join("")}</ul></article><article><h4>Acciones recomendadas</h4><ul>${manual.actions.map(item => `<li>${esc(item)}</li>`).join("")}</ul></article></div></section>`;
    document.getElementById("machineDialogBody").innerHTML = `<section class="machine-summary"><div><span class="eyebrow dark">ESTADO DEL ACTIVO</span><h3>${esc(machine.type)} · ${esc(machine.area)} · ${nf.format(machine.power_mw)} MW</h3><p>${esc(machine.failure_mode)}. ${esc(machine.explanation)}.</p></div><div class="machine-risk"><span class="status-pill ${machine.status}">${labels[machine.status] || machine.status}</span><strong>${nf.format(machine.risk)}%</strong><small>Riesgo · ${machine.rul_days ?? "—"} días estimados</small></div></section><div class="machine-dialog-columns"><section class="machine-dialog-panel"><span class="eyebrow dark">DESEMPEÑO ENERGÉTICO</span><h3>Última captura del collector</h3>${energyCards}</section><section class="machine-dialog-panel"><span class="eyebrow dark">CONTRIBUCIÓN AL RIESGO</span><h3>Factores principales</h3><div class="machine-factors">${factorLines || '<p>Sin factores disponibles.</p>'}</div></section></div>${manualHtml}<section class="machine-telemetry"><div><span class="eyebrow dark">TELEMETRÍA ASOCIADA</span><h3>${machine.telemetry.length} variables monitoreadas</h3></div><div class="machine-table-wrap"><table><thead><tr><th>VARIABLE</th><th>VALOR ACTUAL</th><th>NOMINAL</th><th>DESVIACIÓN</th><th>ESTADO</th><th>ÚLTIMA LECTURA</th></tr></thead><tbody>${telemetryRows}</tbody></table></div></section><p class="machine-disclaimer">Datos simulados para analítica. Validar señales, límites y diagnóstico con instrumentación calibrada y procedimientos del fabricante antes de intervenir.</p>`;
  } catch (error) {
    document.getElementById("machineDialogBody").innerHTML = `<p class="machine-error">${esc(error.message)}</p>`;
  }
}

function thermalMetric(machine) {
  const performanceSignal = machine.signals.performance || {};
  let performance = Number(performanceSignal.value || 0);
  if (performanceSignal.unit === "ratio") performance *= 100;
  performance = clamp(performance || 82, 55, 99.5);
  const availability = clamp(99.4 - machine.risk * 0.14, 82, 99.5);
  const reliability = clamp(99.1 - machine.risk * 0.11, 84, 99.4);
  const index = availability * performance * reliability / 10000;
  const lossMw = machine.power * (1 - index / 100);
  return {...machine, availability, performance, reliability, index, lossMw};
}

function renderThermal() {
  if (!state.data) return;
  const persisted = state.energy;
  const metrics = persisted ? persisted.machines.map(item => ({
    ...item,
    index: item.operational_efficiency,
    reliability: item.conformity,
    lossMw: item.rated_power_mw * (1 - item.operational_efficiency / 100),
  })) : state.data.machines.map(thermalMetric);
  const global = persisted ? persisted.summary.operational_efficiency : average(metrics.map(item => item.index));
  const availability = persisted ? persisted.summary.availability : average(metrics.map(item => item.availability));
  const performance = persisted ? persisted.summary.performance : average(metrics.map(item => item.performance));
  const reliability = persisted ? persisted.summary.conformity : average(metrics.map(item => item.reliability));
  const thermalEfficiency = persisted ? persisted.summary.thermal_efficiency : average(metrics.map(item => item.performance));
  txt("thermalGlobal", `${nf.format(global)}%`);
  txt("thermalAvailability", `${nf.format(availability)}%`);
  txt("thermalPerformance", `${nf.format(performance)}%`);
  txt("thermalReliability", `${nf.format(reliability)}%`);
  txt("thermalEfficiency", `${nf.format(thermalEfficiency)}%`);

  document.getElementById("thermalRows").innerHTML = metrics.map(item => `<tr><td><strong>${item.id}</strong><small>${item.name} · ${item.area}</small></td><td><div class="thermal-score ${indicatorClass(item.index)}"><span><i style="width:${item.index}%"></i></span><strong>${nf.format(item.index)}%</strong></div></td><td>${nf.format(item.availability)}%</td><td>${nf.format(item.performance)}%</td><td>${nf.format(item.reliability)}%</td><td>${nf.format(item.thermal_efficiency || item.performance)}%</td><td>${nf.format(item.lossMw)} MW</td></tr>`).join("");

  const downtimeMinutes = persisted ? persisted.losses.downtime_minutes_7d : Math.round((100 - availability) / 100 * 7 * 24 * 60 * metrics.length);
  const generationGap = persisted ? persisted.losses.generation_gap_mwh_7d : metrics.reduce((total, item) => total + item.power * (1 - item.performance / 100) * 24 * 7, 0);
  const degradationLoss = persisted ? persisted.losses.degradation_loss_mwh_7d : metrics.reduce((total, item) => total + item.power * (1 - item.reliability / 100) * 24 * 7, 0);
  txt("lossDowntime", `${nf.format(downtimeMinutes)} min`);
  txt("lossGeneration", `${nf.format(generationGap)} MWh`);
  txt("lossDegradation", `${nf.format(degradationLoss)} MWh`);
  document.getElementById("lossDowntimeBar").style.width = `${clamp(100 - availability, 8, 100)}%`;
  document.getElementById("lossGenerationBar").style.width = `${clamp(100 - performance, 8, 100)}%`;
  document.getElementById("lossDegradationBar").style.width = `${clamp(100 - reliability, 8, 100)}%`;
}

function metric(value, suffix = "%") {
  return value === null || value === undefined ? "—" : `${nf.format(value)}${suffix}`;
}

function renderShifts() {
  if (!state.shifts) return;
  const data = state.shifts;
  const active = data.active_shift;
  txt("shiftUpdated", `Actualizado ${new Date(data.generated_at).toLocaleTimeString("es-CO", {hour: "2-digit", minute: "2-digit"})}`);
  txt("shiftTimezone", data.timezone);
  txt("shiftActive", active ? `${active.code} · ${active.name}` : "Sin turno activo");
  txt("shiftSchedule", active ? `${active.start_time}–${active.end_time}` : "—");
  txt("shiftEnergy", active ? metric(active.net_generation_mwh, " MWh") : "—");
  txt("shiftOperational", active ? metric(active.operational_efficiency) : "—");
  txt("shiftThermal", active ? metric(active.thermal_efficiency) : "—");
  txt("shiftDowntime", active ? metric(active.downtime_minutes, " min") : "—");

  document.getElementById("shiftCards").innerHTML = data.shifts.map(shift => `<article class="shift-card ${shift.active ? "active" : ""}"><header><strong>${shift.code} · ${shift.name}</strong><span>${shift.start_time}–${shift.end_time}</span></header><span class="shift-badge">${shift.active ? "TURNO ACTIVO" : shift.readings ? "CON DATOS" : "SIN LECTURAS"}</span><dl><div><dt>Energía neta</dt><dd>${metric(shift.net_generation_mwh, " MWh")}</dd></div><div><dt>Índice</dt><dd>${metric(shift.operational_efficiency)}</dd></div><div><dt>Disponibilidad</dt><dd>${metric(shift.availability)}</dd></div><div><dt>Eficiencia térmica</dt><dd>${metric(shift.thermal_efficiency)}</dd></div></dl></article>`).join("");

  txt("shiftEfficiencyTitle", active ? `${active.code} · ${metric(active.operational_efficiency)}` : "Esperando lecturas");
  document.getElementById("shiftEfficiencyMetrics").innerHTML = active ? [
    ["Disponibilidad", active.availability],
    ["Rendimiento", active.performance],
    ["Conformidad", active.conformity],
    ["Eficiencia térmica", active.thermal_efficiency],
  ].map(item => `<div><span>${item[0]}</span><strong>${metric(item[1])}</strong></div>`).join("") : '<div class="shift-empty">No hay un turno activo.</div>';
  document.getElementById("shiftEfficiencyBar").style.width = `${active?.operational_efficiency || 0}%`;
  txt("shiftNote", active?.readings ? `${active.readings} lecturas de ${active.machines} activos durante las últimas 24 horas.` : "El collector asignará las nuevas capturas a este turno según la hora de Bogotá.");
}

function showView(view, scrollToAssets = false) {
  state.view = view;
  const thermal = view === "performance";
  const shifts = view === "shifts";
  const rag = view === "rag";
  const dashboard = !thermal && !shifts && !rag;
  document.querySelectorAll(".dashboard-view").forEach(section => section.hidden = !dashboard);
  document.getElementById("performanceView").hidden = !thermal;
  document.getElementById("shiftView").hidden = !shifts;
  document.getElementById("ragView").hidden = !rag;
  txt("headerPath", thermal ? "OPERACIÓN / EFICIENCIA TÉRMICA" : shifts ? "OPERACIÓN / TURNO" : rag ? "CONOCIMIENTO / DOCUMENTOS RAG" : "OPERACIÓN / ANALÍTICA PREDICTIVA");
  txt("headerTitle", thermal ? "Desempeño de generación térmica" : shifts ? "Seguimiento del turno energético" : rag ? "Copiloto documental Energy" : "Salud de generación térmica");
  if (thermal) {
    renderThermal();
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (shifts) {
    renderShifts();
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (rag) {
    loadRagDocuments().catch(error => document.getElementById("ragDocumentList").innerHTML = `<p class="machine-error">${esc(error.message)}</p>`);
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (scrollToAssets) {
    document.getElementById("assets").scrollIntoView({behavior: "smooth", block: "start"});
  } else {
    window.scrollTo({top: 0, behavior: "smooth"});
  }
}

async function refresh(shouldScroll = false) {
  const button = document.getElementById("refreshButton");
  button.disabled = true;
  button.textContent = "Consultando…";
  try {
    [state.data, state.energy, state.shifts] = await Promise.all([getDashboard(), getThermalEfficiency(), getShiftsDashboard()]);
    renderSummary();
    renderTable();
    renderThermal();
    renderShifts();
    if (!state.refreshTimer) state.refreshTimer = setInterval(() => refresh(false), Math.max(5, state.data.collector_interval_seconds) * 1000);
  } catch (error) {
    txt("updatedAt", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Consultar base de datos";
  }
}

async function refreshThermal() {
  const button = document.getElementById("thermalRefresh");
  button.disabled = true;
  button.textContent = "Actualizando…";
  await refresh(false);
  button.disabled = false;
  button.textContent = "Actualizar indicadores";
}

async function refreshShifts() {
  const button = document.getElementById("shiftRefresh");
  button.disabled = true;
  button.textContent = "Actualizando…";
  state.shifts = await getShiftsDashboard();
  renderShifts();
  button.disabled = false;
  button.textContent = "Actualizar turno";
}

document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(item => item.classList.toggle("active", item === button));
  renderTable();
}));
document.getElementById("refreshButton").addEventListener("click", () => refresh(true));
document.getElementById("thermalRefresh").addEventListener("click", refreshThermal);
document.getElementById("shiftRefresh").addEventListener("click", refreshShifts);
document.getElementById("ragRefresh").addEventListener("click", () => loadRagDocuments().catch(error => alert(error.message)));
document.getElementById("ragForm").addEventListener("submit", askRag);
document.getElementById("machineDialogClose").addEventListener("click", () => document.getElementById("machineDialog").close());
document.getElementById("machineDialog").addEventListener("click", event => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
document.getElementById("menuToggle").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item === button));
  document.querySelector(".sidebar").classList.remove("open");
  const section = button.dataset.section;
  showView(section === "performance" ? "performance" : section === "shifts" ? "shifts" : section === "rag" ? "rag" : "predictive", section === "assets");
}));

refresh(false);
