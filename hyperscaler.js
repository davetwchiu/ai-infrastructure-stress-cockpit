(() => {
  "use strict";

  const COMPONENT_LABELS = {
    bond_issuance: "New bond issuance",
    credit_spreads: "Credit spreads",
    rating_changes: "Rating changes",
    capex_to_ocf: "CapEx / OCF",
    fcf_revisions: "FCF forecast revisions",
  };

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const presentNumber = (value) => value !== null && value !== undefined && Number.isFinite(Number(value));
  const number = (value, digits = 0) => presentNumber(value) ? Number(value).toFixed(digits) : "--";
  const percent = (value, digits = 0) => presentNumber(value) ? `${(Number(value) * 100).toFixed(digits)}%` : "--";
  const money = (value) => presentNumber(value) ? `$${(Number(value) / 1e9).toFixed(1)}bn` : "--";
  const titleCase = (value = "") => String(value).split(/[_\s-]+/).map((part) => part ? part[0].toUpperCase() + part.slice(1) : "").join(" ");
  const statusClass = (value = "") => String(value).toLowerCase().replace(/\s+/g, "-");
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function injectStyles() {
    if (document.getElementById("hyperscaler-credit-styles")) return;
    const style = document.createElement("style");
    style.id = "hyperscaler-credit-styles";
    style.textContent = `
      .hyperscaler-credit { margin-top: 12px; padding: 14px 20px; }
      .hyperscaler-credit-head { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; }
      .hyperscaler-credit-head h2 { margin-bottom:7px; font-size:20px; }
      .hyperscaler-credit-head p, .hyperscaler-credit .caveats { color:var(--muted); font-size:15px; line-height:1.35; }
      .hyperscaler-credit-score { min-width:150px; text-align:right; }
      .hyperscaler-credit-score strong { display:block; color:var(--gold); font-size:38px; line-height:1; }
      .hyperscaler-components { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin-top:12px; }
      .hyperscaler-component { min-height:118px; padding:10px; border:1px solid var(--line); border-radius:8px; background:rgba(5,14,25,.68); }
      .hyperscaler-component span, .hyperscaler-component small { display:block; color:var(--muted); font-size:13px; }
      .hyperscaler-component strong { display:block; margin-top:6px; color:var(--blue); font-size:27px; }
      .hyperscaler-credit h3 { margin-top:14px; color:var(--blue); font-size:17px; }
      .hyperscaler-credit table { min-width:780px; }
      .hyperscaler-credit .table-wrap { max-height:280px; }
      .hyperscaler-credit .caveats { margin-top:10px; padding-left:20px; }
      @media (max-width:1050px) { .hyperscaler-components { grid-template-columns:repeat(2,minmax(0,1fr)); } }
      @media (max-width:680px) {
        .hyperscaler-credit-head { flex-direction:column; }
        .hyperscaler-credit-score { text-align:left; }
        .hyperscaler-components { grid-template-columns:1fr; }
      }
    `;
    document.head.appendChild(style);
  }

  function summarizeCapex(issuers) {
    const usable = issuers.filter((row) => presentNumber(row.capex_to_ocf));
    if (!usable.length) return { text: "CapEx / OCF unavailable from current SEC facts.", median: null, max: null };
    const sorted = usable.map((row) => Number(row.capex_to_ocf)).sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
    const max = usable.reduce((best, row) => Number(row.capex_to_ocf) > Number(best.capex_to_ocf) ? row : best, usable[0]);
    return {
      text: `${usable.length} issuers matched; median CapEx / OCF ${percent(median)}, highest ${escapeHtml(max.ticker)} ${percent(max.capex_to_ocf)}.`,
      median,
      max,
    };
  }

  function componentEvidence(data) {
    const components = data.components || {};
    const bond = components.bond_issuance || {};
    const spread = components.credit_spreads || {};
    const rating = components.rating_changes || {};
    const fcf = components.fcf_revisions || {};
    const capexSummary = summarizeCapex(data.issuers || []);
    const spreadText = spread.status === "broad_proxy"
      ? `Issuer spreads not supplied; broad IG OAS fallback changed ${number(spread.broad_ig_change_bps, 1)} bps over 20d.`
      : spread.evidence_count
      ? `${spread.evidence_count} dated issuer-spread observations; component score ${number(spread.score)}.`
      : "No current issuer-spread observation.";
    return [
      `${bond.evidence_count || 0} recent debt-related SEC or manual events; issuance is treated as a watch signal, not automatic distress.`,
      spreadText,
      rating.evidence_count ? `${rating.evidence_count} dated rating actions; component score ${number(rating.score)}.` : "No dated rating-change input; component remains unmonitored.",
      capexSummary.text,
      fcf.evidence_count ? `${fcf.evidence_count} dated FCF estimate revisions; component score ${number(fcf.score)}.` : "No dated analyst FCF-revision input; component remains unmonitored.",
    ];
  }

  function patchNarrativeLane(data) {
    const grid = document.querySelector("#narrative-health .narrative-grid");
    if (!grid || grid.children.length < 3) return false;
    const lane = grid.children[1];
    const evidence = componentEvidence(data);
    lane.innerHTML = `
      <div class="narrative-lane-head">
        <h3>Hyperscaler Funding & Cash Stress</h3>
        <div>
          <div class="narrative-lane-score">${number(data.score)}</div>
          <span class="pill ${statusClass(data.status)}">${escapeHtml(data.status || "UNMONITORED")}</span>
        </div>
      </div>
      <p>${data.score >= 51
        ? "Funding and cash-flow pressure is material enough to challenge the assumption that rising AI CapEx is self-financing."
        : "Current covered signals do not confirm broad hyperscaler credit stress, but missing issuer-spread, rating, or FCF-revision data limits confidence."}</p>
      <ul>${evidence.map((item) => `<li>${item}</li>`).join("")}</ul>
      <small class="narrative-source">${escapeHtml(data.source_summary || "SEC and dated manual observations.")} Coverage ${percent(data.coverage_ratio)}; data status ${escapeHtml(titleCase(data.data_status || "partial"))}.</small>`;

    const coverage = document.querySelector("#narrative-health .narrative-coverage");
    if (coverage) {
      coverage.innerHTML = `<strong>3 / 3 live</strong><span class="pill ${data.data_status === "ok" ? "ok" : "partial"}">${escapeHtml(titleCase(data.data_status || "partial"))}</span>`;
    }
    return true;
  }

  function renderDetail(data) {
    document.getElementById("hyperscaler-credit")?.remove();
    const panel = document.createElement("section");
    panel.id = "hyperscaler-credit";
    panel.className = "panel hyperscaler-credit";

    const componentCards = Object.entries(COMPONENT_LABELS).map(([key, label]) => {
      const component = data.components?.[key] || {};
      return `<div class="hyperscaler-component">
        <span>${escapeHtml(label)}</span>
        <strong>${number(component.score)}</strong>
        <small>Weight ${number(Number(component.weight || 0) * 100)}% · ${escapeHtml(titleCase(component.status || "unmonitored"))}</small>
        <b class="pill ${statusClass(component.status || "unmonitored")}">${escapeHtml(titleCase(component.status || "unmonitored"))}</b>
      </div>`;
    }).join("");

    const issuerRows = (data.issuers || []).map((row) => `<tr>
      <td>${escapeHtml(row.ticker)}</td>
      <td>${escapeHtml(row.period_end || "--")}</td>
      <td>${escapeHtml(row.form || "--")}</td>
      <td>${money(row.operating_cash_flow)}</td>
      <td>${money(row.capex)}</td>
      <td>${percent(row.capex_to_ocf)}</td>
      <td>${money(row.fcf_proxy)}</td>
      <td>${number(row.score)}</td>
      <td>${escapeHtml(titleCase(row.data_status || "unavailable"))}</td>
    </tr>`).join("") || `<tr><td colspan="9">No matched hyperscaler SEC cash-flow periods.</td></tr>`;

    const eventRows = (data.events || []).slice(0, 10).map((row) => `<tr>
      <td>${escapeHtml(row.date || row.as_of || "--")}</td>
      <td>${escapeHtml(row.ticker || row.issuer || "--")}</td>
      <td>${escapeHtml(titleCase(row.event_type || row.category || row.action || "event"))}</td>
      <td>${escapeHtml(row.form || "--")}</td>
      <td>${escapeHtml(row.summary || row.source || "--")}</td>
    </tr>`).join("") || `<tr><td colspan="5">No current debt or rating event in the configured window.</td></tr>`;

    panel.innerHTML = `
      <div class="hyperscaler-credit-head">
        <div>
          <h2>Hyperscaler Funding & Cash Stress</h2>
          <p>Tracks new debt, credit-spread widening, rating actions, CapEx relative to operating cash flow, and analyst FCF revisions. It remains diagnostic and does not alter the official close-based score.</p>
        </div>
        <div class="hyperscaler-credit-score">
          <strong>${number(data.score)} / 100</strong>
          <span class="pill ${statusClass(data.status)}">${escapeHtml(data.status || "UNMONITORED")}</span>
          <small>Coverage ${percent(data.coverage_ratio)}</small>
        </div>
      </div>
      <div class="hyperscaler-components">${componentCards}</div>
      <h3>SEC cash-flow coverage</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Issuer</th><th>Period end</th><th>Form</th><th>OCF</th><th>CapEx</th><th>CapEx / OCF</th><th>FCF proxy</th><th>Score</th><th>Data</th></tr></thead>
        <tbody>${issuerRows}</tbody>
      </table></div>
      <h3>Recent financing and rating events</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>Issuer</th><th>Event</th><th>Form</th><th>Summary</th></tr></thead>
        <tbody>${eventRows}</tbody>
      </table></div>
      <ul class="caveats">${(data.caveats || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;

    const anchor = document.getElementById("narrative-health");
    anchor?.insertAdjacentElement("afterend", panel);
  }

  async function boot() {
    injectStyles();
    let latest;
    try {
      const response = await fetch("data/latest.json", { cache: "no-store" });
      latest = await response.json();
    } catch (error) {
      console.error("Unable to load hyperscaler credit data", error);
      return;
    }
    const data = latest.hyperscaler_credit;
    if (!data) return;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (patchNarrativeLane(data)) {
        renderDetail(data);
        return;
      }
      await delay(50);
    }
  }

  boot();
})();
