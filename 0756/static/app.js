const COLORS = {
  power: "#d7682d",
  energy: "#207a84",
  main: "#1d4f73",
  mainCmd: "#78a6c8",
  incline: "#5f6b2f",
  inclineCmd: "#b6c676",
  panel101: "#7e5a9b",
  panel101Cmd: "#b698d1",
  flowA: "#d7682d",
  flowB: "#385d7a",
  flowC: "#8d4f39",
  queue: "#b1452f",
  fill: "#207a84",
  profile: "#385d7a"
};

let latestState = null;
let applyTimer = null;

function $(id) {
  return document.getElementById(id);
}

function deviceCanvas(canvas) {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 240;
  if (canvas.width !== Math.floor(width * ratio) || canvas.height !== Math.floor(height * ratio)) {
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { ctx, width, height };
}

function formatNumber(value, digits = 2) {
  return Number(value || 0).toFixed(digits);
}

function drawAxes(ctx, width, height, yMin, yMax) {
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fffdf8";
  ctx.fillRect(0, 0, width, height);
  const left = 42;
  const right = width - 10;
  const top = 14;
  const bottom = height - 26;
  ctx.strokeStyle = "rgba(20, 35, 45, 0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 4; i += 1) {
    const y = top + ((bottom - top) * i) / 4;
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
  }
  ctx.stroke();
  ctx.fillStyle = "#5f6d74";
  ctx.font = "12px Microsoft YaHei";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i += 1) {
    const yValue = yMax - ((yMax - yMin) * i) / 4;
    const y = top + ((bottom - top) * i) / 4;
    ctx.fillText(formatNumber(yValue, yMax > 10 ? 0 : 2), left - 6, y);
  }
  return { left, right, top, bottom };
}

function drawLegend(ctx, series, width) {
  let x = 48;
  const y = 12;
  ctx.font = "12px Microsoft YaHei";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  series.forEach((item) => {
    ctx.fillStyle = item.color;
    ctx.fillRect(x, y - 5, 10, 10);
    ctx.fillStyle = "#31444f";
    ctx.fillText(item.name, x + 16, y);
    x += ctx.measureText(item.name).width + 34;
    if (x > width - 80) {
      x = 48;
    }
  });
}

function drawLineChart(canvas, xValues, series, options = {}) {
  const { ctx, width, height } = deviceCanvas(canvas);
  const validSeries = series.filter((item) => item.values && item.values.length > 1);
  const allValues = validSeries.flatMap((item) => item.values);
  const hasData = xValues && xValues.length > 1 && allValues.length > 0;
  const yMin = options.yMin ?? 0;
  let yMax = options.yMax ?? (hasData ? Math.max(...allValues) : 1);
  if (yMax <= yMin + 1e-6) {
    yMax = yMin + 1;
  }
  yMax *= 1.08;
  const frame = drawAxes(ctx, width, height, yMin, yMax);

  if (!hasData) {
    ctx.fillStyle = "#7c8a90";
    ctx.font = "14px Microsoft YaHei";
    ctx.textAlign = "center";
    ctx.fillText("等待数据...", width / 2, height / 2);
    return;
  }

  drawLegend(ctx, validSeries, width);
  const xMin = Math.min(...xValues);
  const xMax = Math.max(...xValues);
  const xSpan = Math.max(xMax - xMin, 1e-6);

  validSeries.forEach((item) => {
    ctx.beginPath();
    item.values.forEach((value, index) => {
      const x = frame.left + ((xValues[index] - xMin) / xSpan) * (frame.right - frame.left);
      const y = frame.bottom - ((value - yMin) / (yMax - yMin)) * (frame.bottom - frame.top);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = item.color;
    ctx.lineWidth = item.lineWidth || 2.4;
    if (item.dashed) {
      ctx.setLineDash([6, 4]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
  });
}

function drawProfileChart(canvas, belt) {
  const { ctx, width, height } = deviceCanvas(canvas);
  const profile = belt?.profile;
  if (!profile || !profile.x_m || profile.x_m.length < 2) {
    ctx.clearRect(0, 0, width, height);
    return;
  }
  const yMax = Math.max(1, Math.max(...profile.fill_ratio) * 1.08);
  const frame = drawAxes(ctx, width, height, 0, yMax);
  const xMin = profile.x_m[0];
  const xMax = profile.x_m[profile.x_m.length - 1];
  const xSpan = Math.max(xMax - xMin, 1e-6);
  ctx.beginPath();
  profile.fill_ratio.forEach((value, index) => {
    const x = frame.left + ((profile.x_m[index] - xMin) / xSpan) * (frame.right - frame.left);
    const y = frame.bottom - (value / yMax) * (frame.bottom - frame.top);
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.lineWidth = 2.4;
  ctx.strokeStyle = COLORS.profile;
  ctx.stroke();
  ctx.lineTo(frame.right, frame.bottom);
  ctx.lineTo(frame.left, frame.bottom);
  ctx.closePath();
  ctx.fillStyle = "rgba(56, 93, 122, 0.18)";
  ctx.fill();
}

function renderBeltCards(belts) {
  const host = $("beltCards");
  host.innerHTML = belts.map((belt) => `
    <article class="belt-card">
      <h3>${belt.name}</h3>
      <p>${belt.controllable ? "可控皮带" : "固定速度皮带"}</p>
      <div class="belt-stats">
        <div><span>当前速度</span><strong>${formatNumber(belt.speed_mps, 2)} m/s</strong></div>
        <div><span>目标速度</span><strong>${formatNumber(belt.command_speed_mps, 2)} m/s</strong></div>
        <div><span>当前功率</span><strong>${formatNumber(belt.power_kw, 1)} kW</strong></div>
        <div><span>当前流量</span><strong>${formatNumber(belt.outflow_tph, 1)} t/h</strong></div>
        <div><span>带上存煤</span><strong>${formatNumber(belt.inventory_t, 2)} t</strong></div>
        <div><span>满载率</span><strong>${formatNumber(belt.fill_ratio * 100, 1)} %</strong></div>
      </div>
    </article>
  `).join("");
}

function renderSummary(state) {
  $("totalPowerValue").textContent = formatNumber(state.summary.total_power_kw, 1);
  $("totalEnergyValue").textContent = formatNumber(state.summary.total_energy_kwh, 2);
  $("queueValue").textContent = formatNumber(state.summary.queue_total_t, 2);
  $("wearValue").textContent = formatNumber(state.summary.total_wear, 2);
  $("simTimeValue").textContent = `${formatNumber(state.time_s, 0)} s`;
  $("strategyValue").textContent = state.strategy || "-";
  $("transferQueueValue").textContent = `${formatNumber(state.transfer_queues.T_B2_B3 || 0, 2)} t`;
  $("toggleRunBtn").textContent = state.running ? "暂停" : "继续";
}

function renderCharts(state) {
  const h = state.history;
  const t = h.time_s || [];
  drawLineChart(
    $("powerChart"),
    t,
    [
      { name: "总功率", color: COLORS.power, values: h.total_power_kw },
      { name: "累计电耗", color: COLORS.energy, values: h.total_energy_kwh }
    ]
  );
  drawLineChart(
    $("speedChart"),
    t,
    [
      { name: "主运实速", color: COLORS.main, values: h.main_speed_mps },
      { name: "主运目标", color: COLORS.mainCmd, values: h.main_cmd_mps, dashed: true },
      { name: "斜井实速", color: COLORS.incline, values: h.incline_speed_mps },
      { name: "斜井目标", color: COLORS.inclineCmd, values: h.incline_cmd_mps, dashed: true },
      { name: "101实速", color: COLORS.panel101, values: h.panel101_speed_mps },
      { name: "101目标", color: COLORS.panel101Cmd, values: h.panel101_cmd_mps, dashed: true }
    ]
  );
  drawLineChart(
    $("flowChart"),
    t,
    [
      { name: "A", color: COLORS.flowA, values: h.A_tph },
      { name: "B", color: COLORS.flowB, values: h.B_tph },
      { name: "C", color: COLORS.flowC, values: h.C_tph }
    ]
  );
  drawLineChart(
    $("queueChart"),
    t,
    [
      { name: "总队列", color: COLORS.queue, values: h.queue_total_t },
      { name: "主运满载率", color: COLORS.main, values: (h.main_fill_ratio || []).map((v) => v * 100) },
      { name: "斜井满载率", color: COLORS.fill, values: (h.incline_fill_ratio || []).map((v) => v * 100) }
    ]
  );

  const beltMap = Object.fromEntries(state.belts.map((belt) => [belt.id, belt]));
  drawProfileChart($("profileMain"), beltMap.main);
  drawProfileChart($("profileIncline"), beltMap.incline);
  drawProfileChart($("profile101"), beltMap.panel101);
}

function renderState(state) {
  latestState = state;
  renderSummary(state);
  renderBeltCards(state.belts);
  renderCharts(state);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  return response.json();
}

function currentSettingsPayload(includeRunning = true) {
  return {
    mode: $("modeSelect").value,
    scenario: $("scenarioSelect").value,
    running: includeRunning ? Boolean(latestState?.running ?? true) : true,
    manual_rates_tph: {
      A: Number($("rateA").value),
      B: Number($("rateB").value),
      C: Number($("rateC").value)
    },
    weights: {
      power: Number($("weightPower").value),
      wear: Number($("weightWear").value),
      queue: Number($("weightQueue").value),
      fill: Number($("weightFill").value),
      ramp: Number($("weightRamp").value)
    }
  };
}

function syncLabels() {
  $("rateALabel").textContent = $("rateA").value;
  $("rateBLabel").textContent = $("rateB").value;
  $("rateCLabel").textContent = $("rateC").value;
}

function scheduleApply() {
  if (applyTimer) {
    window.clearTimeout(applyTimer);
  }
  applyTimer = window.setTimeout(async () => {
    const state = await requestJson("/api/control", {
      method: "POST",
      body: JSON.stringify(currentSettingsPayload())
    });
    renderState(state);
  }, 240);
}

async function fetchStateLoop() {
  const state = await requestJson("/api/state");
  renderState(state);
}

async function handleToggleRun() {
  const state = await requestJson("/api/control", {
    method: "POST",
    body: JSON.stringify({
      running: !latestState.running,
      mode: $("modeSelect").value,
      scenario: $("scenarioSelect").value,
      manual_rates_tph: currentSettingsPayload().manual_rates_tph,
      weights: currentSettingsPayload().weights
    })
  });
  renderState(state);
}

async function handleReset() {
  const state = await requestJson("/api/reset", {
    method: "POST",
    body: JSON.stringify(currentSettingsPayload(false))
  });
  renderState(state);
}

async function handleBenchmark() {
  $("benchmarkResult").textContent = "对比运行中...";
  const report = await requestJson("/api/benchmark");
  const baseline = report.baseline;
  const optimized = report.optimized;
  const delta = report.delta;
  $("benchmarkResult").textContent =
    `基线电耗: ${formatNumber(baseline.energy_kwh, 3)} kWh\n` +
    `优化电耗: ${formatNumber(optimized.energy_kwh, 3)} kWh\n` +
    `电耗变化: ${formatNumber(delta.energy_pct, 3)} %\n` +
    `峰值功率变化: ${formatNumber(delta.peak_power_pct, 3)} %\n` +
    `磨损变化: ${formatNumber(delta.wear_pct, 3)} %`;
}

function bindControls() {
  ["rateA", "rateB", "rateC"].forEach((id) => {
    $(id).addEventListener("input", () => {
      syncLabels();
      if ($("scenarioSelect").value === "manual") {
        scheduleApply();
      }
    });
  });
  ["modeSelect", "scenarioSelect", "weightPower", "weightWear", "weightQueue", "weightFill", "weightRamp"]
    .forEach((id) => $(id).addEventListener("change", scheduleApply));
  $("applySettingsBtn").addEventListener("click", async () => {
    const state = await requestJson("/api/control", {
      method: "POST",
      body: JSON.stringify(currentSettingsPayload())
    });
    renderState(state);
  });
  $("toggleRunBtn").addEventListener("click", handleToggleRun);
  $("resetBtn").addEventListener("click", handleReset);
  $("benchmarkBtn").addEventListener("click", handleBenchmark);
}

async function init() {
  syncLabels();
  bindControls();
  await fetchStateLoop();
  window.setInterval(fetchStateLoop, 900);
  window.addEventListener("resize", () => {
    if (latestState) {
      renderCharts(latestState);
    }
  });
}

init();
