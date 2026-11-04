const state = {data: null, energy: null, filter: "all", selectedId: null, refreshTimer: null, view: "predictive"};
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

function txt(id, value) { document.getElementById(id).textContent = value; }
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

function selectMachine(id, shouldScroll = true) {
  const machine = state.data.machines.find(item => item.id === id);
  if (!machine) return;
  state.selectedId = id;
  txt("detailName", `${machine.id} · ${machine.name}`);
  txt("detailMeta", `${machine.type} · ${machine.area} · ${machine.power} MW instalados`);
  const status = document.getElementById("detailStatus");
  status.className = `status-pill ${machine.status}`;
  status.textContent = labels[machine.status];
  document.getElementById("detailMetrics").innerHTML = [machine.signals.condition, machine.signals.temperature, machine.signals.process, machine.signals.performance].map(item => `<div><span>${item.label}</span><strong>${signal(item)}</strong></div>`).join("");
  txt("detailDiagnosis", `${machine.diagnosis} ${machine.recommendation}`);
  txt("rulDays", `${machine.rul_days} días`);
  document.getElementById("factorBars").innerHTML = machine.factors.map(factor => `<div><label><span>${factor.name}</span><strong>${factor.impact} pt</strong></label><div><i style="width:${Math.min(100, factor.impact * 3.2)}%"></i></div></div>`).join("");
  renderTable();
  if (shouldScroll) document.getElementById("machineDetail").scrollIntoView({behavior: "smooth", block: "start"});
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

function showView(view, scrollToAssets = false) {
  state.view = view;
  const thermal = view === "performance";
  document.querySelectorAll(".dashboard-view").forEach(section => section.hidden = thermal);
  document.getElementById("performanceView").hidden = !thermal;
  txt("headerPath", thermal ? "OPERACIÓN / EFICIENCIA TÉRMICA" : "OPERACIÓN / ANALÍTICA PREDICTIVA");
  txt("headerTitle", thermal ? "Desempeño de generación térmica" : "Salud de generación térmica");
  if (thermal) {
    renderThermal();
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
    [state.data, state.energy] = await Promise.all([getDashboard(), getThermalEfficiency()]);
    renderSummary();
    renderTable();
    renderThermal();
    selectMachine(state.selectedId || state.data.priority.id, shouldScroll);
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

document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach(item => item.classList.toggle("active", item === button));
  renderTable();
}));
document.getElementById("refreshButton").addEventListener("click", () => refresh(true));
document.getElementById("thermalRefresh").addEventListener("click", refreshThermal);
document.getElementById("menuToggle").addEventListener("click", () => document.querySelector(".sidebar").classList.toggle("open"));
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item === button));
  document.querySelector(".sidebar").classList.remove("open");
  showView(button.dataset.section === "performance" ? "performance" : "predictive", button.dataset.section === "assets");
}));

refresh(false);
