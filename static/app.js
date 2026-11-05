const state = {data: null, energy: null, shifts: null, filter: "all", selectedId: null, refreshTimer: null, view: "predictive"};
const labels = {healthy: "Saludable", warning: "Alerta", critical: "Crítica"};
const nf = new Intl.NumberFormat("es-CO", {maximumFractionDigits: 1});
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
let downtimeOptionsLoaded = false;

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

async function getShifts() {
  const response = await fetch("/api/shifts");
  if (!response.ok) throw new Error("No fue posible consultar la configuración de turnos");
  return response.json();
}

function showShiftMessage(message, error = false) {
  const element = document.getElementById("shiftFormMessage");
  element.hidden = !message;
  element.textContent = message || "";
  element.classList.toggle("error", error);
}

function resetShiftForm(shift = null) {
  document.getElementById("shiftForm").hidden = false;
  document.getElementById("shiftId").value = shift?.id || "";
  document.getElementById("shiftCode").value = shift?.code || "";
  document.getElementById("shiftName").value = shift?.name || "";
  document.getElementById("shiftStart").value = shift?.start_time || "";
  document.getElementById("shiftEnd").value = shift?.end_time || "";
  document.getElementById("shiftEnabled").checked = shift?.active ?? true;
  txt("shiftFormTitle", shift ? `Editar ${shift.code}` : "Crear turno");
  showShiftMessage("");
  document.getElementById("shiftCode").focus();
}

async function loadShiftManager() {
  const shifts = await getShifts();
  const list = document.getElementById("shiftManagerList");
  list.innerHTML = shifts.length ? shifts.map(shift => `<article class="shift-manager-row ${shift.active ? "" : "inactive"}"><div><strong>${esc(shift.code)} · ${esc(shift.name)}</strong><span>${esc(shift.start_time)}–${esc(shift.end_time)} · ${nf.format(shift.planned_minutes)} min</span></div><span class="shift-manager-status">${shift.active ? "Activo" : "Inactivo"}</span><div class="shift-manager-actions"><button type="button" data-shift-edit="${shift.id}">Editar</button><button type="button" class="danger" data-shift-delete="${shift.id}">Eliminar</button></div></article>`).join("") : '<p class="shift-empty">No hay turnos configurados.</p>';
  list.querySelectorAll("[data-shift-edit]").forEach(button => button.addEventListener("click", () => resetShiftForm(shifts.find(shift => shift.id === Number(button.dataset.shiftEdit)))));
  list.querySelectorAll("[data-shift-delete]").forEach(button => button.addEventListener("click", () => deleteShift(Number(button.dataset.shiftDelete), shifts.find(shift => shift.id === Number(button.dataset.shiftDelete)))));
}

async function openShiftManager() {
  const dialog = document.getElementById("shiftDialog");
  document.getElementById("shiftForm").hidden = true;
  showShiftMessage("");
  dialog.showModal();
  try { await loadShiftManager(); } catch (error) { showShiftMessage(error.message, true); }
}

async function saveShift(event) {
  event.preventDefault();
  const id = document.getElementById("shiftId").value;
  const button = document.getElementById("shiftSave");
  const payload = {
    code: document.getElementById("shiftCode").value,
    name: document.getElementById("shiftName").value,
    start_time: document.getElementById("shiftStart").value,
    end_time: document.getElementById("shiftEnd").value,
    active: document.getElementById("shiftEnabled").checked,
  };
  button.disabled = true;
  button.textContent = "Guardando…";
  try {
    const response = await fetch(id ? `/api/shifts/${id}` : "/api/shifts", {method: id ? "PUT" : "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No fue posible guardar el turno");
    document.getElementById("shiftForm").hidden = true;
    await loadShiftManager();
    await refreshShifts();
    showShiftMessage(id ? "Turno actualizado correctamente." : "Turno creado correctamente.");
  } catch (error) {
    showShiftMessage(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Guardar turno";
  }
}

async function deleteShift(id, shift) {
  if (!confirm(`¿Deseas eliminar el turno ${shift.code}? Si tiene historial será desactivado.`)) return;
  try {
    const response = await fetch(`/api/shifts/${id}`, {method: "DELETE"});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "No fue posible eliminar el turno");
    document.getElementById("shiftForm").hidden = true;
    await loadShiftManager();
    await refreshShifts();
    showShiftMessage(data.message || "Turno eliminado correctamente.");
  } catch (error) {
    showShiftMessage(error.message, true);
  }
}

async function loadRagDocuments() {
  const response = await fetch("/api/rag/documents");
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "No fue posible consultar los documentos RAG");
  const documents = result;
  const list = document.getElementById("ragDocumentList");
  list.innerHTML = documents.length ? `<table class="rag-document-table"><thead><tr><th>Documento</th><th>Fragmentos</th><th>Indexación</th><th></th></tr></thead><tbody>${documents.map(document => `<tr><td><strong>${esc(document.document_name)}</strong></td><td>${document.chunks}</td><td>${new Date(document.indexed_at).toLocaleString("es-CO")}</td><td><button class="rag-delete" data-name="${esc(document.document_name)}">Eliminar</button></td></tr>`).join("")}</tbody></table>` : '<p class="rag-empty">No hay documentos indexados. Carga documentación o ejecuta <code>python ingest_energy_manuals.py</code>.</p>';
  list.querySelectorAll(".rag-delete").forEach(button => button.addEventListener("click", () => removeRagDocument(button.dataset.name)));
}

async function uploadRagDocuments(event) {
  event.preventDefault();
  const input = document.getElementById("ragFiles");
  const button = document.getElementById("ragUploadButton");
  const status = document.getElementById("ragUploadStatus");
  const files = [...input.files];
  if (!files.length) return;
  const body = new FormData();
  files.forEach(file => body.append("files", file));
  button.disabled = true;
  status.classList.remove("error");
  status.textContent = "Extrayendo, fragmentando, vectorizando e indexando…";
  try {
    const response = await fetch("/api/rag/documents", {method: "POST", body});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No fue posible indexar los documentos");
    status.textContent = `${result.total} documento(s) indexado(s) correctamente.`;
    input.value = "";
    await loadRagDocuments();
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function removeRagDocument(name) {
  if (!confirm(`¿Eliminar ${name} de la base vectorial?`)) return;
  const status = document.getElementById("ragUploadStatus");
  try {
    const response = await fetch(`/api/rag/documents/${encodeURIComponent(name)}`, {method: "DELETE"});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No fue posible eliminar el documento");
    status.classList.remove("error");
    status.textContent = `${name} eliminado (${result.deleted_chunks} fragmentos).`;
    await loadRagDocuments();
  } catch (error) {
    status.classList.add("error");
    status.textContent = error.message;
  }
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

function localDateTime(value) {
  return value ? new Date(value).toLocaleString("es-CO", {dateStyle: "short", timeStyle: "short"}) : "Abierta";
}

function localInputDate(value = new Date()) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

async function loadDowntime() {
  const query = new URLSearchParams();
  [["date_from", "downtimeFrom"], ["date_to", "downtimeTo"], ["machine", "downtimeMachine"], ["category", "downtimeCategory"], ["status", "downtimeStatus"]].forEach(([key, id]) => {
    const value = document.getElementById(id).value;
    if (value) query.set(key, value);
  });
  const response = await fetch(`/api/downtime?${query}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "No fue posible consultar las paradas");
  if (!downtimeOptionsLoaded) {
    const machines = data.options.machines.map(machine => `<option value="${esc(machine.code)}">${esc(machine.code)} · ${esc(machine.name)}</option>`).join("");
    document.getElementById("downtimeMachine").insertAdjacentHTML("beforeend", machines);
    document.getElementById("downtimeFormMachine").innerHTML = machines;
    const categories = data.options.categories.map(category => `<option value="${esc(category)}">${esc(category)}</option>`).join("");
    document.getElementById("downtimeCategory").insertAdjacentHTML("beforeend", categories);
    document.getElementById("downtimeCategoryOptions").innerHTML = categories;
    downtimeOptionsLoaded = true;
  }
  document.getElementById("downtimeFrom").value = data.filters.date_from;
  document.getElementById("downtimeTo").value = data.filters.date_to;
  txt("downtimeTotal", `${nf.format(data.summary.total_minutes)} min`);
  txt("downtimeEvents", data.summary.events);
  txt("downtimeAverage", `${nf.format(data.summary.average_minutes)} min`);
  txt("downtimeOpen", data.summary.open_events);
  txt("downtimeTopMachine", `Mayor impacto: ${data.summary.top_machine}`);
  txt("downtimePeriod", `${data.filters.date_from} → ${data.filters.date_to}`);
  document.getElementById("downtimeRows").innerHTML = data.events.length ? data.events.map(event => `<tr><td><strong>${localDateTime(event.started_at)}</strong><small>${localDateTime(event.ended_at)}</small></td><td><strong>${esc(event.machine_code)}</strong><small>${esc(event.machine_name)} · ${esc(event.area)}</small></td><td>${esc(event.shift_code || "—")}</td><td><strong>${esc(event.category)}</strong><small>${esc(event.cause)}</small></td><td>${nf.format(event.duration_minutes)} min</td><td>${event.planned ? "Planificada" : "No planificada"}<small>${esc(event.source)}</small></td><td><span class="downtime-status ${event.status}">${event.status === "open" ? "Abierta" : "Cerrada"}</span></td><td>${event.status === "open" ? `<button class="downtime-close" data-id="${event.id}">Cerrar</button>` : ""}</td></tr>`).join("") : '<tr><td colspan="8" class="empty-state">No hay paradas para los filtros seleccionados.</td></tr>';
  const maxMinutes = Math.max(...data.by_category.map(item => item.minutes), 1);
  document.getElementById("downtimeCategories").innerHTML = data.by_category.length ? data.by_category.map(item => `<div class="downtime-category"><label><strong>${esc(item.category)}</strong><span>${item.events} eventos · ${nf.format(item.minutes)} min</span></label><i><b style="width:${item.minutes / maxMinutes * 100}%"></b></i></div>`).join("") : "<p>Sin pérdidas en el periodo.</p>";
  document.querySelectorAll(".downtime-close").forEach(button => button.addEventListener("click", () => closeDowntime(button.dataset.id)));
}

async function closeDowntime(id) {
  if (!confirm("¿Cerrar esta parada con la fecha y hora actual?")) return;
  const response = await fetch(`/api/downtime/${id}/close`, {method: "PATCH"});
  const data = await response.json();
  if (!response.ok) return alert(data.error || "No fue posible cerrar la parada");
  await loadDowntime();
}

async function saveDowntime(event) {
  event.preventDefault();
  const payload = {
    machine: document.getElementById("downtimeFormMachine").value,
    category: document.getElementById("downtimeFormCategory").value,
    started_at: document.getElementById("downtimeStarted").value,
    ended_at: document.getElementById("downtimeEnded").value,
    cause: document.getElementById("downtimeCause").value,
    notes: document.getElementById("downtimeNotes").value,
    planned: document.getElementById("downtimePlanned").checked,
  };
  const response = await fetch("/api/downtime", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) return alert(data.error || "No fue posible guardar la parada");
  document.getElementById("downtimeDialog").close();
  document.getElementById("downtimeForm").reset();
  await loadDowntime();
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
  const downtime = view === "downtime";
  const dashboard = !thermal && !shifts && !rag && !downtime;
  document.querySelectorAll(".dashboard-view").forEach(section => section.hidden = !dashboard);
  document.getElementById("performanceView").hidden = !thermal;
  document.getElementById("shiftView").hidden = !shifts;
  document.getElementById("ragView").hidden = !rag;
  document.getElementById("downtimeView").hidden = !downtime;
  txt("headerPath", thermal ? "OPERACIÓN / EFICIENCIA TÉRMICA" : shifts ? "OPERACIÓN / TURNO" : downtime ? "OPERACIÓN / PARADAS" : rag ? "CONOCIMIENTO / DOCUMENTOS RAG" : "OPERACIÓN / ANALÍTICA PREDICTIVA");
  txt("headerTitle", thermal ? "Desempeño de generación térmica" : shifts ? "Seguimiento del turno energético" : downtime ? "Pérdidas por paradas" : rag ? "Copiloto documental Energy" : "Salud de generación térmica");
  if (thermal) {
    renderThermal();
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (shifts) {
    renderShifts();
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (rag) {
    loadRagDocuments().catch(error => document.getElementById("ragDocumentList").innerHTML = `<p class="machine-error">${esc(error.message)}</p>`);
    window.scrollTo({top: 0, behavior: "smooth"});
  } else if (downtime) {
    loadDowntime().catch(error => alert(error.message));
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
  button.textContent = "Actualizar indicadores";
}

document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(item => item.classList.toggle("active", item === button));
  renderTable();
}));
document.getElementById("refreshButton").addEventListener("click", () => refresh(true));
document.getElementById("thermalRefresh").addEventListener("click", refreshThermal);
document.getElementById("shiftRefresh").addEventListener("click", refreshShifts);
document.getElementById("shiftManage").addEventListener("click", openShiftManager);
document.getElementById("shiftDialogClose").addEventListener("click", () => document.getElementById("shiftDialog").close());
document.getElementById("shiftDialog").addEventListener("click", event => { if (event.target === event.currentTarget) event.currentTarget.close(); });
document.getElementById("shiftNew").addEventListener("click", () => resetShiftForm());
document.getElementById("shiftCancel").addEventListener("click", () => { document.getElementById("shiftForm").hidden = true; showShiftMessage(""); });
document.getElementById("shiftForm").addEventListener("submit", saveShift);
document.getElementById("ragRefresh").addEventListener("click", () => loadRagDocuments().catch(error => alert(error.message)));
document.getElementById("ragUploadForm").addEventListener("submit", uploadRagDocuments);
document.getElementById("downtimeApply").addEventListener("click", () => loadDowntime().catch(error => alert(error.message)));
document.getElementById("downtimeRegister").addEventListener("click", () => {
  document.getElementById("downtimeStarted").value = localInputDate();
  document.getElementById("downtimeDialog").showModal();
});
document.getElementById("downtimeDialogClose").addEventListener("click", () => document.getElementById("downtimeDialog").close());
document.getElementById("downtimeForm").addEventListener("submit", saveDowntime);
document.getElementById("machineDialogClose").addEventListener("click", () => document.getElementById("machineDialog").close());
document.getElementById("machineDialog").addEventListener("click", event => {
  if (event.target === event.currentTarget) event.currentTarget.close();
});
function setSidebar(open) {
  document.querySelector(".sidebar").classList.toggle("open", open);
  document.getElementById("menuToggle").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("menu-open", open);
}

document.getElementById("menuToggle").addEventListener("click", () => setSidebar(!document.querySelector(".sidebar").classList.contains("open")));
document.getElementById("sidebarScrim").addEventListener("click", () => setSidebar(false));
document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    setSidebar(false);
    document.getElementById("aiChat").classList.remove("open");
  }
});
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item === button));
  setSidebar(false);
  const section = button.dataset.section;
  showView(section === "performance" ? "performance" : section === "shifts" ? "shifts" : section === "downtime" ? "downtime" : section === "rag" ? "rag" : "predictive", false);
}));

function addAiMessage(text, type, sources = [], mode = "") {
  const box = document.getElementById("aiMessages");
  const message = document.createElement("div");
  message.className = `ai-message ${type}`;
  message.textContent = text;
  if (sources.length) {
    const detail = document.createElement("small");
    detail.textContent = `${mode ? `Modo: ${mode} · ` : ""}Fuentes: ${sources.join(" · ")}`;
    message.appendChild(detail);
  }
  box.appendChild(message);
  box.scrollTop = box.scrollHeight;
}

document.getElementById("aiLauncher").addEventListener("click", () => {
  document.getElementById("aiChat").classList.toggle("open");
  if (document.getElementById("aiChat").classList.contains("open")) document.getElementById("aiQuestion").focus();
});
document.getElementById("aiClose").addEventListener("click", () => document.getElementById("aiChat").classList.remove("open"));
document.getElementById("aiForm").addEventListener("submit", async event => {
  event.preventDefault();
  const input = document.getElementById("aiQuestion");
  const button = document.getElementById("aiSend");
  const question = input.value.trim();
  if (question.length < 5) return;
  addAiMessage(question, "user");
  input.value = "";
  button.disabled = true;
  button.textContent = "Analizando datos…";
  try {
    const response = await fetch("/api/copilot/chat", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "No fue posible consultar el copiloto");
    addAiMessage(result.answer, "assistant", result.sources || [], result.mode || "");
  } catch (error) {
    addAiMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Consultar con IA";
  }
});

refresh(false);
