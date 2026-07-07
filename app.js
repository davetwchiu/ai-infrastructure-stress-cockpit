const fields = document.querySelectorAll("[data-field]");
let latestData = null;

const statusClass = (status = "") => status.toLowerCase().replace(/\s+/g, "-");
const fmt = (n, digits = 0) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : "--";
const pct = (n) => Number.isFinite(Number(n)) ? `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%` : "--";

function parseCsv(text) {
  const [head, ...rows] = text.trim().split(/\r?\n/).map((line) => line.split(","));
  return rows.map((row) => Object.fromEntries(head.map((key, i) => [key, row[i]])));
}

function sparkline(values, color = "var(--gold)") {
  const nums = values.map(Number).filter(Number.isFinite);
  if (nums.length < 2) return "";
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const span = max - min || 1;
  const points = nums.map((v, i) => {
    const x = (i / (nums.length - 1)) * 120;
    const y = 48 - ((v - min) / span) * 42;
    return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" viewBox="0 0 120 54" aria-hidden="true" style="color:${color}"><path d="${points}"></path></svg>`;
}

function setGauge(score) {
  const clamped = Math.max(0, Math.min(100, Number(score) || 0));
  const angle = -90 + clamped * 1.8;
  document.getElementById("needle").style.transform = `rotate(${angle}deg)`;
  document.getElementById("needle-dot").style.transform = `rotate(${angle}deg)`;
  document.getElementById("needle-dot").style.transformOrigin = "180px 165px";
}

function setFields(data) {
  const map = {
    updated_at: data.updated_label,
    stress_score: fmt(data.stress.score),
    stress_status: data.stress.status,
    regime: data.stress.regime,
    confidence: data.stress.confidence,
    judgment: data.stress.judgment,
    action_status: data.action.status,
    meaning: data.action.meaning,
  };
  fields.forEach((field) => { field.textContent = map[field.dataset.field] ?? "--"; });
  setGauge(data.stress.score);
}

function renderCards(data, history) {
  const colors = { rates: "var(--gold)", credit: "var(--green)", equity: "var(--gold)", compute: "var(--gold)" };
  document.getElementById("scorecards").innerHTML = data.drivers.map((driver, i) => {
    const series = history.slice(-40).map((row) => row[`${driver.key}_score`]);
    const cls = statusClass(driver.status);
    return `<article class="panel score-card ${cls}">
      <div class="card-head"><span class="rank">${i + 1}</span><h2>${driver.title}</h2></div>
      <div class="card-body">
        <div>
          <div class="driver-score">${fmt(driver.score)}</div>
          <ul>${driver.bullets.map((item) => `<li>${item}</li>`).join("")}</ul>
        </div>
        <div>
          <span class="pill ${cls}">${driver.status}</span>
          ${sparkline(series, colors[driver.key])}
        </div>
      </div>
    </article>`;
  }).join("");
}

function renderTriggers(data) {
  const groups = [
    ["positive", "Positive"],
    ["warning", "Warning"],
    ["negative", "Negative"],
  ];
  document.getElementById("triggers").innerHTML = groups.map(([key, title]) => `<section class="trigger ${key}">
    <h3>${title}</h3>
    <ul>${data.triggers[key].map((item) => `<li>${item}</li>`).join("")}</ul>
  </section>`).join("");
}

function renderHardData(data, history) {
  document.getElementById("hard-data").innerHTML = data.hard_data.map((metric) => {
    const values = history.slice(-40).map((row) => row[metric.key]);
    const cls5 = Number(metric.change_5d) > 0 ? "up" : Number(metric.change_5d) < 0 ? "down" : "";
    const cls20 = Number(metric.change_20d) > 0 ? "up" : Number(metric.change_20d) < 0 ? "down" : "";
    return `<article class="metric">
      <h3>${metric.label}</h3>
      <div class="value">${metric.value_label}</div>
      ${sparkline(values, "var(--blue)")}
      <div class="change"><span>5d</span><strong class="${cls5}">${metric.change_5d_label}</strong></div>
      <div class="change"><span>20d</span><strong class="${cls20}">${metric.change_20d_label}</strong></div>
    </article>`;
  }).join("");
}

function renderExtendedHours(data) {
  const overlay = data.extended_hours || {};
  const target = document.getElementById("extended-hours");
  if (!overlay.available) {
    target.innerHTML = `<p class="unavailable">Extended-hours data unavailable</p>`;
    return;
  }
  const cls = statusClass(overlay.status);
  const rows = [
    ["Market state", overlay.market_state],
    ["SOXX extended-hours change", pct(overlay.soxx?.extended_change_percent)],
    ["QQQ extended-hours change", pct(overlay.qqq?.extended_change_percent)],
    ["NVDA extended-hours change", pct(overlay.nvda?.extended_change_percent)],
    ["SOXX vs QQQ", pct(overlay.soxx_vs_qqq_change)],
    ["NVDA vs SOXX", pct(overlay.nvda_vs_soxx_change)],
  ];
  target.innerHTML = `<div class="overlay-grid">
    ${rows.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}
    <div><span>Overlay status</span><strong><span class="pill ${cls}">${overlay.status}</span></strong></div>
  </div>
  <p>${overlay.interpretation}</p>`;
}

function renderPortfolio(data) {
  document.getElementById("portfolio").innerHTML = data.action.portfolio_read_through
    .map((item) => `<li>${item}</li>`)
    .join("");
}

async function init() {
  try {
    const [latestRes, historyRes] = await Promise.all([fetch("data/latest.json"), fetch("data/history.csv")]);
    latestData = await latestRes.json();
    const history = parseCsv(await historyRes.text());
    setFields(latestData);
    renderCards(latestData, history);
    renderTriggers(latestData);
    renderExtendedHours(latestData);
    renderHardData(latestData, history);
    renderPortfolio(latestData);
  } catch (err) {
    document.body.insertAdjacentHTML("afterbegin", `<p class="error">Unable to load dashboard data: ${err.message}</p>`);
  }
}

document.getElementById("refresh").addEventListener("click", () => location.reload());
document.getElementById("export").addEventListener("click", () => {
  if (!latestData) return;
  const blob = new Blob([JSON.stringify(latestData, null, 2)], { type: "application/json" });
  const link = Object.assign(document.createElement("a"), {
    href: URL.createObjectURL(blob),
    download: "ai-infrastructure-stress-latest.json",
  });
  link.click();
  URL.revokeObjectURL(link.href);
});

init();
