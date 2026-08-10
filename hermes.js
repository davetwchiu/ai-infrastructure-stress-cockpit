(() => {
  "use strict";

  const escapeHtml = (value) => String(value ?? "--").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const titleCase = (value = "") => String(value).split(/[_\s-]+/).map((part) => part ? part[0].toUpperCase() + part.slice(1) : "").join(" ");
  const pct = (value) => Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : "--";
  const statusClass = (value = "") => String(value).toLowerCase().replace(/\s+/g, "-");
  const date = (value) => value ? new Date(value).toLocaleString() : "--";
  const safeUrl = (value) => /^https?:\/\//i.test(String(value)) ? String(value) : "";
  const fetchJson = async (path) => {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) throw new Error(`${response.status} ${path}`);
    return response.json();
  };

  function evidenceList(thesis, evidence, sources) {
    const rows = (thesis.evidence_ids || []).map((id) => evidence[id]).filter(Boolean);
    return rows.length ? `<ul class="hermes-evidence">${rows.map((item) => {
      const source = sources[item.source_id] || {};
      const url = safeUrl(source.url);
      const link = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(source.publisher)}</a>` : escapeHtml(source.publisher);
      return `<li><b>[${escapeHtml(item.classification)}]</b> Tier ${escapeHtml(source.tier)} · ${escapeHtml(item.published_at)} · ${link}<br>${escapeHtml(item.summary)}</li>`;
    }).join("")}</ul>` : "<p class=\"hermes-muted\">No linked evidence.</p>";
  }

  function renderUnavailable(target, report) {
    const status = report?.status === "fail" ? "Validation failed — last valid research is retained when available." : "No validated Hermes research is available.";
    target.innerHTML = `<div class="hermes-head"><div><h2>Hermes AI Infrastructure Research</h2><p>${status} The official market score continues normally.</p></div><span class="pill failed">${escapeHtml(report?.status || "unavailable")}</span></div>`;
  }

  function render(target, data, report) {
    const sources = Object.fromEntries((data.sources || []).map((item) => [item.id, item]));
    const evidence = Object.fromEntries((data.evidence || []).map((item) => [item.id, item]));
    const stale = report?.status === "fail" || data.validation?.stale;
    const changes = (data.changes || []).filter((item) => item.material);
    const theses = data.theses || [];
    const constraints = data.constraints?.items || [];
    const metrics = data.metrics || [];
    const warning = stale ? `<p class="hermes-stale">Validation failed after this run. Showing last valid research from ${escapeHtml(date(data.validation?.validated_at))}.</p>` : "";
    const pillarCards = theses.map((item) => `<details class="hermes-thesis"><summary><span>${escapeHtml(item.pillar)}</span><b class="pill ${statusClass(item.validated_status)}">${escapeHtml(item.validated_status)}</b><strong>${pct(item.validated_confidence)}</strong></summary><div><p>${escapeHtml(item.claim)}</p><p class="hermes-muted">Previous: ${escapeHtml(item.prior_status)} · Direction: ${escapeHtml(item.direction)}</p><dl><dt>Watch</dt><dd>${escapeHtml(item.watch_trigger)}</dd><dt>Confirm</dt><dd>${escapeHtml(item.confirmation_trigger)}</dd><dt>Invalidate</dt><dd>${escapeHtml(item.invalidation_trigger)}</dd></dl>${evidenceList(item, evidence, sources)}</div></details>`).join("");
    const metricRows = metrics.length ? metrics.map((item) => `<tr><td>${escapeHtml(item.entity)}</td><td>${escapeHtml(item.metric)}</td><td>${escapeHtml(item.value ?? item.range)}</td><td>${escapeHtml(item.unit)}</td><td>${escapeHtml(item.period)}</td><td>${escapeHtml(item.basis)} / ${escapeHtml(item.comparability)}</td></tr>`).join("") : "<tr><td colspan=\"6\">No normalized metrics.</td></tr>";
    target.innerHTML = `<div class="hermes-head"><div><h2>Hermes AI Infrastructure Research</h2><p>Diagnostic research only — validated independently and never included in the official market score.</p></div><div class="hermes-meta"><span class="pill ${statusClass(report?.status || data.validation?.status)}">${escapeHtml(report?.status || data.validation?.status)}</span><small>Last validated ${escapeHtml(date(data.validation?.validated_at))}</small></div></div>${warning}
      <section class="hermes-synthesis"><div><span>Market × Research</span><strong>${escapeHtml(data.market_research_synthesis?.state || "INSUFFICIENT_DATA")}</strong></div><p>${escapeHtml(data.market_research_synthesis?.interpretation)}</p><small>Official credit: ${escapeHtml(data.market_research_synthesis?.official_market_credit?.status)} ${escapeHtml(data.market_research_synthesis?.official_market_credit?.score)} · Hermes research view: ${escapeHtml(data.cycle_assessment?.state)}</small></section>
      <div class="hermes-grid"><article><h3>What Changed?</h3>${changes.length ? `<ul>${changes.map((item) => `<li>${escapeHtml(item.summary || `${titleCase(item.type)}: ${item.thesis_id || item.metric_id || ""}`)}</li>`).join("")}</ul>` : "<p class=\"hermes-muted\">No material thesis change.</p>"}</article><article><h3>AI Infrastructure Constraint Map</h3><div class="hermes-constraints">${constraints.length ? constraints.map((item) => `<span class="${statusClass(item.state)}">${escapeHtml(item.title)} <b>${escapeHtml(item.state)}</b></span>`).join("") : "<p class=\"hermes-muted\">No validated constraints.</p>"}</div></article></div>
      <section><h3>Seven-Pillar Thesis Monitor</h3><div class="hermes-pillars">${pillarCards || "<p class=\"hermes-muted\">No validated theses.</p>"}</div></section>
      <section class="hermes-cash"><h3>CAPEX → Monetisation → Cash Flow</h3><p>Normalized issuer research metrics; values stay separate when definitions are not comparable.</p><div class="table-wrap"><table><thead><tr><th>Entity</th><th>Metric</th><th>Value</th><th>Unit</th><th>Period</th><th>Basis / comparability</th></tr></thead><tbody>${metricRows}</tbody></table></div></section>`;
  }

  async function boot() {
    const target = document.getElementById("hermes-intelligence");
    if (!target) return;
    let report;
    try { report = await fetchJson("data/hermes/validation.json"); } catch (_) { report = null; }
    try { render(target, await fetchJson("data/hermes/latest.json"), report); } catch (_) { renderUnavailable(target, report); }
  }

  boot();
})();
