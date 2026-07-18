const fields = document.querySelectorAll("[data-field]");
let latestData = null;

const statusClass = (status = "") => status.toLowerCase().replace(/\s+/g, "-");
const fmt = (n, digits = 0) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : "--";
const pct = (n) => Number.isFinite(Number(n)) ? `${Number(n) >= 0 ? "+" : ""}${Number(n).toFixed(2)}%` : "--";
const localTime = (value) => value ? new Date(value).toLocaleString() : "--";
const presentNumber = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
const titleCase = (value = "") => value.split(/[_\s-]+/).map((part) => part ? part[0].toUpperCase() + part.slice(1) : "").join(" ");
const scoreStatus = (score) => Number(score) >= 71 ? "CREDIT STRESS CONFIRMED" : Number(score) >= 51 ? "STRESS" : Number(score) >= 26 ? "WATCH" : "NORMAL";

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
    updated_at: localTime(data.updated_at),
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

function overlayFreshness(overlay = {}) {
  if (!overlay.available) return ["REGULAR", "CLOSED"].includes(overlay.market_state) ? "Inactive" : "Unavailable";
  return overlay.is_stale ? "Stale" : "Fresh";
}

function renderFreshness(data) {
  const overlay = data.extended_hours || {};
  const rows = [
    ["Dashboard generated", localTime(data.updated_at)],
    ["Official close data through", data.updated_label || "--"],
    ["Extended overlay generated", localTime(overlay.generated_at)],
    ["Extended quote as of", localTime(overlay.as_of)],
    ["Market state", overlay.market_state || "UNKNOWN"],
    ["Overlay freshness", overlayFreshness(overlay)],
    ["Quote age", presentNumber(overlay.quote_age_minutes) ? `${overlay.quote_age_minutes} min` : "--"],
    ["Next expected automatic refresh", overlay.is_active_session ? "Scheduled about every 10 minutes; GitHub Actions can run late." : "During pre-market or after-hours on the next scheduled GitHub Actions run."],
  ];
  document.getElementById("freshness").innerHTML = rows
    .map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
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
  const cls = statusClass(overlay.status);
  const rows = [
    ["Status", overlayFreshness(overlay)],
    ["Quote age", presentNumber(overlay.quote_age_minutes) ? `${overlay.quote_age_minutes} min` : "--"],
    ["Market state", overlay.market_state],
    ["SOXX extended-hours change", pct(overlay.soxx?.extended_change_percent)],
    ["QQQ extended-hours change", pct(overlay.qqq?.extended_change_percent)],
    ["NVDA extended-hours change", pct(overlay.nvda?.extended_change_percent)],
    ["SOXX vs QQQ", pct(overlay.soxx_vs_qqq_change)],
    ["NVDA vs SOXX", pct(overlay.nvda_vs_soxx_change)],
    ["SOXX quote time", localTime(overlay.soxx?.quote_time_label)],
    ["QQQ quote time", localTime(overlay.qqq?.quote_time_label)],
    ["NVDA quote time", localTime(overlay.nvda?.quote_time_label)],
  ];
  target.innerHTML = `<div class="overlay-grid">
    ${rows.map(([label, value]) => `<div><span>${label}</span><strong>${value}</strong></div>`).join("")}
    <div><span>Overlay status</span><strong><span class="pill ${cls}">${overlay.status}</span></strong></div>
  </div>
  ${overlay.stale_reason ? `<p class="unavailable">${overlay.stale_reason}</p>` : ""}
  <p>${overlay.interpretation}</p>
  <p>This overlay is provisional and does not change the official close-based stress score.</p>`;
}

function renderNarrativeHealth(data) {
  const target = document.getElementById("narrative-health");
  const equity = data.drivers?.find((driver) => driver.key === "equity") || {};
  const relative = data.hard_data?.find((metric) => metric.key === "soxx_qqq_rel") || {};
  const overlay = data.extended_hours || {};
  const compute = data.compute_stress || {};
  const financing = compute.components?.financing_event_score || {};
  const balance = compute.components?.balance_sheet_pressure_score || {};
  const financingEvents = compute.details?.financing_events || [];
  const neocloudScore = presentNumber(financing.score) && presentNumber(balance.score)
    ? Math.round(Number(financing.score) * .65 + Number(balance.score) * .35)
    : presentNumber(compute.score) ? Number(compute.score) : null;
  const neocloudStatus = presentNumber(neocloudScore) ? scoreStatus(neocloudScore) : "UNMONITORED";
  const leverageScore = presentNumber(equity.score) ? Number(equity.score) : null;
  const leverageStatus = presentNumber(leverageScore) ? equity.status || scoreStatus(leverageScore) : "UNMONITORED";
  const leverageInterpretation = Number(leverageScore) >= 51
    ? "Price action is consistent with forced de-risking or crowded-position unwinds, but this is not direct evidence of Korean margin liquidation."
    : Number(leverageScore) >= 26
    ? "Positioning stress is visible, but broad credit confirmation remains limited."
    : "Current equity-relative data does not show material liquidation stress.";
  const neocloudInterpretation = Number(neocloudScore) >= 71
    ? "Neocloud financing pressure is elevated across recent SEC filing activity and balance-sheet indicators."
    : Number(neocloudScore) >= 51
    ? "Neocloud financing pressure is building and warrants closer review of funding events and cash burn."
    : "Neocloud financing indicators are not showing broad stress.";
  const lane = ({ title, score, status, interpretation, evidence, source }) => `<article class="narrative-lane">
    <div class="narrative-lane-head">
      <h3>${title}</h3>
      <div>
        <div class="narrative-lane-score ${presentNumber(score) ? "" : "unmonitored"}">${presentNumber(score) ? fmt(score) : "N/A"}</div>
        <span class="pill ${statusClass(status)}">${status}</span>
      </div>
    </div>
    <p>${interpretation}</p>
    <ul>${evidence.map((item) => `<li>${item}</li>`).join("")}</ul>
    <small class="narrative-source">${source}</small>
  </article>`;

  target.innerHTML = `<div class="narrative-head">
    <div>
      <h2>AI Narrative Health Decomposition</h2>
      <p>Separates market plumbing, hyperscaler cash economics, and borrower financing. A strong CAPEX number is not treated as proof of healthy returns.</p>
    </div>
    <div class="narrative-coverage">
      <strong>2 / 3 live</strong>
      <span class="pill partial">Coverage</span>
    </div>
  </div>
  <div class="narrative-grid">
    ${lane({
      title: "Korea / Leverage Liquidation",
      score: leverageScore,
      status: leverageStatus,
      interpretation: leverageInterpretation,
      evidence: [
        `SOXX / QQQ relative: ${relative.change_5d_label || "--"} over 5d; ${relative.change_20d_label || "--"} over 20d.`,
        `Extended-hours overlay: ${overlay.status || "unavailable"} (${overlayFreshness(overlay)}).`,
        "Direct KOSPI margin balances and single-stock leveraged ETF flows are not yet ingested.",
      ],
      source: "Live proxy from existing equity-confirmation data; not a direct Korea flow feed.",
    })}
    ${lane({
      title: "Hyperscaler CAPEX Return",
      score: null,
      status: "UNMONITORED",
      interpretation: "The cockpit does not yet ingest hyperscaler CAPEX, depreciation, operating cash flow, free cash flow, or AI/cloud revenue. It therefore cannot claim that rising CAPEX proves a healthy AI return cycle.",
      evidence: [
        "Required: CAPEX growth versus cloud and AI revenue growth.",
        "Required: depreciation, operating cash flow, and free-cash-flow trend.",
        "Until these are added, narrative confidence should remain capped.",
      ],
      source: "Coverage gap shown explicitly rather than filled with a false score.",
    })}
    ${lane({
      title: "Neocloud Financing",
      score: neocloudScore,
      status: neocloudStatus,
      interpretation: neocloudInterpretation,
      evidence: [
        `${financingEvents.length} recent financing-related SEC signals in the current data window.`,
        `Financing-event score ${fmt(financing.score)}; balance-sheet pressure ${fmt(balance.score)}.`,
        `Detailed Compute Financing Stress status: ${titleCase(compute.status || "fallback")}.`,
      ],
      source: "Live SEC filing and XBRL components already in data/latest.json.",
    })}
  </div>
  <p class="narrative-note">This decomposition is diagnostic only and does not change the official close-based stress score.</p>`;
}

function renderComputeStress(data) {
  const target = document.getElementById("compute-stress");
  const fallbackDriver = data.drivers?.find((driver) => driver.key === "compute") || {};
  const compute = data.compute_stress || {
    score: fallbackDriver.score,
    status: "fallback",
    components: {},
    details: { financing_events: [], caveats: ["Detailed compute stress data unavailable."] },
  };
  const componentLabels = {
    financing_event_score: "Financing events",
    balance_sheet_pressure_score: "Balance-sheet pressure",
    compute_equity_confirmation_score: "Equity confirmation",
    infrastructure_spillover_score: "Infrastructure spillover",
  };
  const components = Object.entries(componentLabels).map(([key, label]) => {
    const item = compute.components?.[key] || {};
    return `<div class="compute-component">
      <span>${label}</span>
      <strong>${fmt(item.score)}</strong>
      <small>${fmt(Number(item.contribution), 1)} pts @ ${fmt(Number(item.weight) * 100)}%</small>
      <b class="pill ${statusClass(item.status || "fallback")}">${titleCase(item.status || "fallback")}</b>
    </div>`;
  }).join("");
  const events = compute.details?.financing_events || [];
  const eventRows = events.length ? events.slice(0, 8).map((event) => `<tr>
    <td>${event.ticker || "--"}</td>
    <td>${event.form || "--"}</td>
    <td>${event.filing_date || "--"}</td>
    <td>${titleCase(event.signal_type || "")}</td>
    <td>${fmt(event.points, 1)}</td>
    <td>${event.reason || "--"}</td>
  </tr>`).join("") : `<tr><td colspan="6">No recent financing filing signal detected.</td></tr>`;
  const caveats = compute.details?.caveats || [];
  const componentStatuses = Object.values(compute.components || {}).map((item) => item.status);
  const weakParts = Object.entries(componentLabels)
    .filter(([key]) => Number(compute.components?.[key]?.score) >= 50)
    .map(([, label]) => label.toLowerCase());
  const interpretation = weakParts.length
    ? `Compute stress is elevated mainly because ${weakParts.slice(0, 2).join(" and ")} are pressuring the score.`
    : `Compute stress is not elevated; SEC and market confirmation signals are limited.`;
  const partialNote = componentStatuses.some((item) => item && item !== "ok") ? " Some source data is partial or fallback." : "";

  target.innerHTML = `<div class="compute-head">
    <div>
      <h2>Compute Financing Stress Score</h2>
      <p>${interpretation}${partialNote}</p>
    </div>
    <div class="compute-score">
      <strong>${fmt(compute.score)}</strong>
      <span>/ 100</span>
      <b class="pill ${statusClass(compute.status)}">${titleCase(compute.status || "fallback")}</b>
    </div>
  </div>
  <div class="compute-components">${components}</div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Ticker</th><th>Form</th><th>Filing date</th><th>Signal</th><th>Points</th><th>Reason</th></tr></thead>
      <tbody>${eventRows}</tbody>
    </table>
  </div>
  <ul class="caveats">${caveats.map((item) => `<li>${item}</li>`).join("")}</ul>`;
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
    renderFreshness(latestData);
    renderCards(latestData, history);
    renderTriggers(latestData);
    renderNarrativeHealth(latestData);
    renderComputeStress(latestData);
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
